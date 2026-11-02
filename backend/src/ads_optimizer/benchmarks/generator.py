"""Bounded deterministic 10K logical simulation blocks -> configurable Parquet parts."""

import hashlib
import json
import shutil
import uuid

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ads_optimizer.benchmarks.aggregation import finalize, reference_add
from ads_optimizer.benchmarks.contracts import GENERATOR_VERSION, ExperimentConfig
from ads_optimizer.benchmarks.store import LabStore, now
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import GenerateConfig


def config_key(config: ExperimentConfig):
    return hashlib.sha256(
        json.dumps(
            {**config.generation_config(), "generator": GENERATOR_VERSION}, sort_keys=True
        ).encode()
    ).hexdigest()


def iter_frames(config: ExperimentConfig):
    # Fixed logical block boundaries mean output is independent of physical chunk_rows.
    blocks = []
    size = 0
    for offset in range(0, config.rows, 10_000):
        block = offset // 10_000
        seed = int(np.random.SeedSequence([config.seed, block]).generate_state(1)[0])
        small = GenerateConfig(
            rows=min(10_000, config.rows - offset),
            seed=seed,
            start_date=config.start_date,
            end_date=config.end_date,
            platforms=config.platforms,
        )
        frame, _ = generate_frame(small)
        frame["campaign"] = f"Batch {block + 1:04d} · " + frame.campaign
        frame["campaign_id"] = f"batch-{block + 1:04d}-" + frame.campaign_id
        if not (
            (frame.impressions >= frame.clicks).all()
            and (frame.clicks >= frame.conversions).all()
            and (frame.revenue[frame.conversions == 0] == 0).all()
            and (frame[["spend", "revenue", "conversions", "clicks", "impressions"]] >= 0)
            .all()
            .all()
        ):
            raise ValueError("Synthetic funnel validation failed.")
        blocks.append(frame)
        size += len(frame)
        if size >= config.chunk_rows or offset + len(frame) == config.rows:
            yield pd.concat(blocks, ignore_index=True)
            blocks.clear()
            size = 0


def generate_dataset(store: LabStore, config: ExperimentConfig, checkpoint, job_id=None):
    dataset_id = uuid.uuid4().hex
    staging = store.root / "datasets" / f".partial-{job_id or dataset_id}-{dataset_id}"
    destination = store.root / "datasets" / dataset_id
    staging.mkdir()
    accumulated = {}
    checksums = []
    byte_count = rows = 0
    try:
        for index, frame in enumerate(iter_frames(config)):
            checkpoint(rows)
            path = staging / f"part-{index:05d}.parquet"
            pq.write_table(
                pa.Table.from_pandas(frame, preserve_index=False),
                path,
                compression="snappy",
                row_group_size=min(10_000, len(frame)),
            )
            reference_add(accumulated, frame)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            checksums.append(
                {
                    "file": path.name,
                    "sha256": digest,
                    "rows": len(frame),
                    "bytes": path.stat().st_size,
                }
            )
            byte_count += path.stat().st_size
            rows += len(frame)
            checkpoint(rows)
        manifest = {
            "id": dataset_id,
            "config_key": config_key(config),
            "created_at": now(),
            "is_synthetic": True,
            "currency": "PKR",
            "source": "synthetic_benchmark",
            "rows": rows,
            "bytes": byte_count,
            "parts": len(checksums),
            "config": config.generation_config(),
            "generator_version": GENERATOR_VERSION,
            "sha256": hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest(),
            "files": checksums,
            "reference_units": accumulated,
            "reference": finalize(accumulated),
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (staging / "simulation_truth.evaluation-only.json").write_text(
            json.dumps(
                {
                    "generator": GENERATOR_VERSION,
                    "logical_block_rows": 10_000,
                    "block_seed": "numpy.SeedSequence([seed, block_index])",
                    "simulation": {
                        "delivery_saturation": 18000,
                        "click_saturation": 10000,
                        "season_period_days": 30,
                        "fatigue_decay_days": 450,
                    },
                    "notice": "Simulation evaluation only; never training or inference features.",
                },
                indent=2,
            )
        )
        staging.rename(destination)
        store.save_dataset(manifest)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(destination, ignore_errors=True)
        raise
