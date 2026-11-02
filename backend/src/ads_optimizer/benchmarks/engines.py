"""Three processing paths with identical sums/counts and explicit execution modes."""

import itertools
import multiprocessing
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.types as arrow_types

from ads_optimizer.benchmarks.aggregation import COLUMNS, SUM_FIELDS, empty, units
from ads_optimizer.benchmarks.contracts import UNIT_SCALES


def input_files(folder):
    return sorted(Path(folder).glob("part-*.parquet"))


def pandas_part(frame):
    scaled = pd.DataFrame({"platform": frame.platform, "rows": 1})
    for key, scale in UNIT_SCALES.items():
        scaled[key] = np.rint(frame[key].fillna(0) * scale).astype("int64")
        scaled[f"known_{key}"] = frame[key].notna().astype("int64")
    grouped = scaled.groupby("platform", sort=True, observed=True)[SUM_FIELDS].sum()
    return {
        str(name): {key: int(value) for key, value in row.items()}
        for name, row in grouped.to_dict(orient="index").items()
    }


def merge(target, partial):
    for name, values in partial.items():
        state = target.setdefault(name, empty())
        for key in SUM_FIELDS:
            state[key] += values[key]
    return target


class PandasEngine:
    def __init__(self, config):
        # Conservative working-set estimate; process-tree sampler also enforces the live cap.
        self.chunked = config.rows * 200 > config.memory_mib * 1024**2 * 0.4
        self.chunk_rows = config.chunk_rows
        self.mode = "Pandas · chunked" if self.chunked else "Pandas · in memory"

    def run(self, folder):
        if not self.chunked:
            frame = pd.read_parquet(input_files(folder), columns=COLUMNS)
            return pandas_part(frame)
        result = {}
        for path in input_files(folder):
            for batch in pq.ParquetFile(path).iter_batches(
                batch_size=self.chunk_rows, columns=COLUMNS
            ):
                merge(result, pandas_part(batch.to_pandas()))
        return result

    def close(self):
        pass


def map_partition(arguments):
    """Map records to keyed sums/counts, combining inside each file partition."""
    path, chunk_rows = arguments
    result = {}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=chunk_rows, columns=COLUMNS):
        data = batch.to_pydict()
        for index, name in enumerate(data["platform"]):
            if name not in result:
                result[name] = empty()
            state = result[name]
            state["rows"] += 1
            for metric, scale in UNIT_SCALES.items():
                value = data[metric][index]
                if value is not None:
                    state[metric] += units(value, scale)
                    state[f"known_{metric}"] += 1
    return list(result.items())


def mapper_ready(queue):
    import os

    import pyarrow as pa

    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    queue.put(os.getpid())


class MapReduceEngine:
    def __init__(self, config):
        context = multiprocessing.get_context("spawn")
        self.ready = context.Queue()
        self.pool = context.Pool(config.workers, initializer=mapper_ready, initargs=(self.ready,))
        # Wait for each mapper's imports and initialization; no dataset is read as warm-up.
        try:
            for _ in range(config.workers):
                self.ready.get(timeout=30)
        except BaseException:
            self.pool.terminate()
            self.pool.join()
            raise
        self.chunk_rows = config.chunk_rows
        self.mode = f"Local MapReduce · {config.workers} mapper processes"

    def run(self, folder):
        mapped = self.pool.imap_unordered(
            map_partition, ((str(p), self.chunk_rows) for p in input_files(folder)), chunksize=1
        )
        # Only platform partials enter the shuffle, never all raw records.
        shuffled = sorted(itertools.chain.from_iterable(mapped), key=lambda item: item[0])
        result = {}
        for name, group in itertools.groupby(shuffled, key=lambda item: item[0]):
            state = empty()
            for _, partial in group:
                for key in SUM_FIELDS:
                    state[key] += partial[key]
            result[name] = state
        return result

    def close(self):
        self.pool.close()
        self.pool.join()
        self.ready.close()


class SparkEngine:
    def __init__(self, config):
        from pyspark.sql import SparkSession

        self.mode = f"PySpark · local[{config.workers}]"
        self.spark = (
            SparkSession.builder.appName("Adwise synthetic benchmark")
            .master(f"local[{config.workers}]")
            .config("spark.ui.enabled", "false")
            .config("spark.driver.host", "127.0.0.1")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.driver.memory", "512m")
            .config("spark.sql.shuffle.partitions", str(config.workers))
            .config("spark.sql.adaptive.enabled", "false")
            .config("spark.sql.parquet.enableVectorizedReader", "true")
            .getOrCreate()
        )
        self.spark.sparkContext.setLogLevel("ERROR")

    def run(self, folder):
        from pyspark.sql import functions as f
        from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType

        arrow_schema = pq.read_schema(input_files(folder)[0])
        schema = StructType(
            [
                StructField("platform", StringType()),
                *[
                    StructField(
                        key,
                        LongType()
                        if arrow_types.is_integer(arrow_schema.field(key).type)
                        else DoubleType(),
                    )
                    for key in UNIT_SCALES
                ],
            ]
        )
        frame = self.spark.read.schema(schema).parquet(*map(str, input_files(folder)))
        expressions = [f.count(f.lit(1)).alias("rows")]
        for key, scale in UNIT_SCALES.items():
            expressions.extend(
                [
                    f.sum(f.bround(f.col(key) * scale).cast("long")).alias(key),
                    f.count(key).alias(f"known_{key}"),
                ]
            )
        # collect materializes the same five aggregate rows, with file reads included.
        rows = frame.groupBy("platform").agg(*expressions).collect()
        return {row["platform"]: {key: int(row[key] or 0) for key in SUM_FIELDS} for row in rows}

    def close(self):
        self.spark.stop()
