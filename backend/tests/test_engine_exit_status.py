"""Regression F-1: an engine that dies mid-way must never leave a non-terminal status.

Before the fix, measure_engine kept the last published "running" snapshot when the
engine process exited early, so a completed job could report an engine as running.
"""

import subprocess
import sys

from ads_optimizer.benchmarks.contracts import ExperimentConfig
from ads_optimizer.benchmarks.generator import generate_dataset
from ads_optimizer.benchmarks.store import LabStore
from ads_optimizer.benchmarks.worker import measure_engine

PARTIAL_THEN_CRASH = """
import json, sys
run = {"repeat": 1, "elapsed_seconds": 0.01, "rows_per_second": 1e6, "correct": True}
json.dump({"status": "running", "runs": [run, {**run, "repeat": 2}]}, open(sys.argv[1], "w"))
sys.exit(1)
"""


def test_engine_exiting_mid_run_is_reported_failed_without_timing(tmp_path, monkeypatch):
    store = LabStore(tmp_path)
    config = ExperimentConfig(engines=["pandas"])
    dataset = generate_dataset(store, config, lambda _rows: None)
    job = store.create_job(config)
    (store.root / "jobs" / job["id"] / "config.json").write_text(config.model_dump_json())
    real_popen = subprocess.Popen

    def fake_engine(command, **kwargs):
        output = command[command.index("--output") + 1]
        return real_popen([sys.executable, "-c", PARTIAL_THEN_CRASH, output], **kwargs)

    monkeypatch.setattr("ads_optimizer.benchmarks.worker.subprocess.Popen", fake_engine)
    result = measure_engine(store, job["id"], config, dataset, "pandas", lambda: None)
    assert result["status"] == "failed"
    assert "before publishing all repeats" in result["message"]
    assert len(result["runs"]) == 2
    assert result["median_seconds"] is None and result["median_rows_per_second"] is None
