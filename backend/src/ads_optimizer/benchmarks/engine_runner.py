"""One disposable process per engine session. Setup is separated from repeated reads."""

import argparse
import json
import time
import traceback
from pathlib import Path

from ads_optimizer.benchmarks.contracts import ExperimentConfig


def atomic_result(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    # OptiScale patch (2026-11-02, see docs/08-backend-change-log.md): on Windows,
    # replace() fails while the polling worker briefly holds the target open.
    # Retry for a bounded time; POSIX never raises here, so behaviour is unchanged.
    for attempt in range(100):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.05)


def run_engine(engine_id, config, folder, destination):
    setup_start = time.perf_counter()
    import pyarrow as pa

    from ads_optimizer.benchmarks.aggregation import finalize, parity
    from ads_optimizer.benchmarks.engines import MapReduceEngine, PandasEngine, SparkEngine

    pa.set_cpu_count(config.workers)
    pa.set_io_thread_count(config.workers)
    expected = json.loads((folder / "manifest.json").read_text())["reference_units"]
    engine = None
    snapshot = {"status": "starting", "runs": []}
    try:
        engine = {"pandas": PandasEngine, "mapreduce": MapReduceEngine, "spark": SparkEngine}[
            engine_id
        ](config)
        snapshot.update(
            mode=engine.mode, setup_seconds=time.perf_counter() - setup_start, status="running"
        )
        atomic_result(destination, snapshot)
        for repeat in range(config.repeats):
            start = time.perf_counter()
            states = engine.run(folder)
            aggregate = finalize(states)
            elapsed = time.perf_counter() - start
            correct = parity(states, expected)
            snapshot["runs"].append(
                {
                    "repeat": repeat + 1,
                    "elapsed_seconds": elapsed,
                    "rows_per_second": config.rows / elapsed,
                    "correct": correct,
                }
            )
            snapshot.update(aggregate=aggregate)
            atomic_result(destination, snapshot)
            if not correct:
                raise ValueError("Engine totals did not match the trusted reference.")
        snapshot["status"] = "completed"
    except Exception:
        snapshot.update(
            status="failed",
            message="The engine could not finish or its totals "
            "failed validation. Review the local worker log and retry.",
        )
        traceback.print_exc()
    finally:
        if engine:
            try:
                engine.close()
            except Exception:
                snapshot.update(status="failed", message="The engine did not shut down cleanly.")
                traceback.print_exc()
        atomic_result(destination, snapshot)
    return snapshot["status"] == "completed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, choices=["pandas", "mapreduce", "spark"])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = ExperimentConfig.model_validate_json(args.config.read_text())
    success = run_engine(args.engine, config, args.dataset, args.output)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
