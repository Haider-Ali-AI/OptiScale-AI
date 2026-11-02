import asyncio
import json
import os
import signal
import statistics
import subprocess
import sys
import time

import pandas as pd
import psutil
import pyarrow.parquet as pq
import pytest
from ads_optimizer.api import app
from ads_optimizer.benchmarks.aggregation import finalize, parity, reference_add
from ads_optimizer.benchmarks.contracts import ExperimentConfig
from ads_optimizer.benchmarks.engine_runner import run_engine
from ads_optimizer.benchmarks.engines import MapReduceEngine, PandasEngine
from ads_optimizer.benchmarks.environment import environment
from ads_optimizer.benchmarks.generator import config_key, generate_dataset, iter_frames
from ads_optimizer.benchmarks.service import export_csv, start_job
from ads_optimizer.benchmarks.store import LabStore
from ads_optimizer.benchmarks.worker import Cancelled, execute_job, measure_engine, stop_tree
from ads_optimizer.domain import DomainError
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError


def request(method, path, data=None, headers=None):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=data, headers=headers)

    return asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"rows": 99999999},
        {"rows": 20000},
        {"repeats": 2},
        {"workers": 5},
        {"chunk_rows": 900000},
        {"memory_mib": 4097},
        {"seed": -1},
        {"engines": []},
        {"engines": ["pandas", "pandas"]},
        {"platforms": ["Google", "Google"]},
        {"end_date": "2025-01-01"},
        {"dataset_id": "../../catalog.sqlite"},
        {"untrusted_extra": True},
    ],
)
def test_config_resource_and_path_guards(changes):
    with pytest.raises(ValidationError):
        ExperimentConfig(**changes)


def test_deterministic_chunked_generation_and_physical_layout(tmp_path):
    config = ExperimentConfig(rows=100000, seed=123, chunk_rows=10000)
    small = list(iter_frames(config))
    large = list(iter_frames(config.model_copy(update={"chunk_rows": 50000})))
    assert max(len(frame) for frame in small) <= 10000
    assert max(len(frame) for frame in large) <= 50000
    pd.testing.assert_frame_equal(
        pd.concat(small, ignore_index=True), pd.concat(large, ignore_index=True)
    )
    frame = pd.concat(small, ignore_index=True)
    assert len(frame) == 100000
    assert frame.groupby(["date", "campaign_id"]).size().max() == 1
    assert frame.platform.nunique() == 5
    assert (frame.impressions >= frame.clicks).all()
    assert (frame.clicks >= frame.conversions).all()
    assert (frame.loc[frame.conversions == 0, "revenue"] == 0).all()
    store = LabStore(tmp_path)
    seen = []
    manifest = generate_dataset(store, config, seen.append)
    assert manifest["rows"] == 100000 and manifest["parts"] == 10
    assert seen[-1] == 100000
    assert store.by_config(config_key(config))["id"] == manifest["id"]
    path = store.dataset_path(manifest["id"])
    assert pq.ParquetFile(path / manifest["files"][0]["file"]).metadata.num_rows == 10000
    assert (path / "simulation_truth.evaluation-only.json").exists()
    assert "delivery_saturation" not in pq.read_schema(path / manifest["files"][0]["file"]).names
    assert sum(r["rows"] for r in manifest["reference"]) == 100000


def test_cancelled_generation_removes_partial_files(tmp_path):
    store = LabStore(tmp_path)

    def checkpoint(rows):
        if rows >= 10000:
            raise Cancelled()

    with pytest.raises(Cancelled):
        generate_dataset(store, ExperimentConfig(rows=100000, chunk_rows=10000), checkpoint)
    assert store.datasets() == []
    assert list((store.root / "datasets").iterdir()) == []


@pytest.fixture
def known_input(tmp_path):
    folder = tmp_path / "known"
    folder.mkdir()
    frame = pd.DataFrame(
        {
            "platform": ["Google", "Google", "TikTok", "TikTok"],
            "impressions": [100, 900, 0, 0],
            "clicks": [10, 90, 0, 0],
            "spend": [10.01, 89.99, 0.0, 0.0],
            "conversions": [0.5, 1.25, 0.0, 0.0],
            "revenue": [None, 100.0, None, None],
        }
    )
    # Independently calculated small trusted fixture, including missing/zero/fractional cases.
    reference = {
        "Google": {
            "rows": 2,
            "impressions": 1000,
            "clicks": 100,
            "spend": 10000,
            "conversions": 1750000,
            "revenue": 10000,
            "known_impressions": 2,
            "known_clicks": 2,
            "known_spend": 2,
            "known_conversions": 2,
            "known_revenue": 1,
        },
        "TikTok": {
            "rows": 2,
            "impressions": 0,
            "clicks": 0,
            "spend": 0,
            "conversions": 0,
            "revenue": 0,
            "known_impressions": 2,
            "known_clicks": 2,
            "known_spend": 2,
            "known_conversions": 2,
            "known_revenue": 0,
        },
    }
    frame.iloc[:2].to_parquet(folder / "part-00000.parquet", index=False)
    frame.iloc[2:].to_parquet(folder / "part-00001.parquet", index=False)
    (folder / "manifest.json").write_text(json.dumps({"reference_units": reference}))
    return folder, frame, reference


def test_manual_reference_propagates_missing_and_weighted_ratios(known_input):
    _, frame, reference = known_input
    measured = {}
    reference_add(measured, frame)
    assert parity(measured, reference)
    totals = finalize(reference)
    google, tiktok = totals
    assert google["spend"] == 100
    assert google["ctr"] == 10
    assert google["cpc"] == 1
    assert google["cpa"] == pytest.approx(100 / 1.75)
    assert google["cvr"] == pytest.approx(1.75)
    assert google["revenue"] is None and google["roas"] is None
    assert google["coverage"]["revenue"] == 0.5
    assert tiktok["cpc"] is None and tiktok["ctr"] is None
    assert tiktok["revenue"] is None
    changed = {key: dict(value) for key, value in reference.items()}
    changed["Google"]["spend"] += 1
    assert not parity(changed, reference)


def test_pandas_in_memory_chunked_and_map_shuffle_reduce_parity(known_input):
    folder, _, reference = known_input
    config = ExperimentConfig()
    for engine in [
        PandasEngine(config),
        PandasEngine(config.model_copy(update={"rows": 10000000})),
        MapReduceEngine(config),
    ]:
        try:
            assert parity(engine.run(folder), reference)
        finally:
            engine.close()
    assert PandasEngine(config.model_copy(update={"rows": 10000000})).chunked


def test_spark_real_local_parity_and_repeats(known_input, tmp_path, monkeypatch):
    env = environment(tmp_path)
    if not next(e for e in env["engines"] if e["id"] == "spark")["available"]:
        pytest.skip("Optional PySpark and compatible Java are not installed.")
    from ads_optimizer.benchmarks.environment import java_home

    home = java_home()
    if home:
        monkeypatch.setenv("JAVA_HOME", str(home))
    monkeypatch.setenv("SPARK_LOCAL_IP", "127.0.0.1")
    folder, _, _ = known_input
    output = tmp_path / "spark-result.json"
    config = ExperimentConfig()
    assert run_engine("spark", config, folder, output)
    result = json.loads(output.read_text())
    assert result["mode"] == "PySpark · local[2]"
    assert len(result["runs"]) == 3
    assert all(r["correct"] and r["elapsed_seconds"] > 0 for r in result["runs"])
    assert result["aggregate"][0]["revenue"] is None


def prepare_job(store, config):
    job = store.create_job(config)
    (store.root / "jobs" / job["id"] / "config.json").write_text(config.model_dump_json())
    return job


def test_durable_single_job_and_stale_worker_recovery(tmp_path):
    store = LabStore(tmp_path)
    job = store.create_job(ExperimentConfig())
    with pytest.raises(DomainError, match="Another local experiment"):
        store.create_job(ExperimentConfig())
    store.update_job(job["id"], worker_pid=999999999)
    recovered = LabStore(tmp_path).jobs()[0]
    assert recovered["status"] == "interrupted"
    assert recovered["results"] == []
    assert store.create_job(ExperimentConfig())["status"] == "queued"
    with pytest.raises(DomainError):
        store.get_dataset("../../outside")


def test_missing_spark_is_recorded_without_invented_times(tmp_path, monkeypatch):
    store = LabStore(tmp_path)
    config = ExperimentConfig(engines=["spark"])
    job = prepare_job(store, config)
    env = environment(tmp_path)
    env["ram_available_bytes"] = 10 * 1024**3
    env["engines"][2].update(available=False, reason="Optional Java is absent.")
    monkeypatch.setattr("ads_optimizer.benchmarks.worker.environment", lambda _root: env)
    final = execute_job(store, job["id"])
    result = final["results"][0]
    assert final["status"] == "completed"
    assert result["status"] == "unavailable"
    assert result["median_seconds"] is None and result["runs"] == []
    assert "Optional Java is absent" in export_csv(final)


def test_ram_gate_and_prestart_cancellation_are_honest(tmp_path, monkeypatch):
    store = LabStore(tmp_path)
    env = environment(tmp_path)
    env["ram_available_bytes"] = 1024**2
    monkeypatch.setattr("ads_optimizer.benchmarks.worker.environment", lambda _root: env)
    job = prepare_job(store, ExperimentConfig())
    final = execute_job(store, job["id"])
    assert final["status"] == "failed" and "available RAM" in final["message"]
    assert final["dataset"] is None and final["results"] == []
    job = prepare_job(store, ExperimentConfig())
    store.cancel(job["id"])
    final = execute_job(store, job["id"])
    assert final["status"] == "cancelled" and final["dataset"] is None


def test_actual_worker_repeats_persistence_exports_and_bounded_preview(isolated_repository):
    store = LabStore(isolated_repository.root)
    config = ExperimentConfig(engines=["pandas", "mapreduce"])
    job = start_job(store, config)
    deadline = time.monotonic() + 40
    try:
        while time.monotonic() < deadline:
            final = store.get_job(job["id"])
            if final["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.1)
        assert final["status"] == "completed", final
        assert len(final["results"]) == 2
        for result in final["results"]:
            assert result["status"] == "completed", result
            assert len(result["runs"]) == 3
            assert result["median_seconds"] == statistics.median(
                r["elapsed_seconds"] for r in result["runs"]
            )
            assert result["peak_tree_rss_bytes"] is None or result["peak_tree_rss_bytes"] > 0
        assert LabStore(isolated_repository.root).get_job(job["id"])["status"] == "completed"
        dataset_id = final["dataset"]["id"]
        preview = request("GET", f"/api/v1/lab/datasets/{dataset_id}/preview").json()
        assert len(preview["rows"]) == 20
        assert preview["total"] == 10000
        report = request("GET", f"/api/v1/lab/jobs/{job['id']}/export").json()
        assert report["methodology"]["timing"]
        assert report["dataset"]["sha256"] == final["dataset"]["sha256"]
        csv = request("GET", f"/api/v1/lab/jobs/{job['id']}/export?format=csv").text
        assert len(csv.splitlines()) == 7
        assert "synthetic_benchmark" in csv
        assert request("GET", f"/api/v1/lab/jobs/{job['id']}/export?format=bad").status_code == 422
        assert request("GET", "/api/v1/workspace").json()["dataset_count"] == 0
        assert request("DELETE", f"/api/v1/lab/datasets/{dataset_id}").status_code == 200
        assert request("GET", f"/api/v1/lab/jobs/{job['id']}").json()["results"]
        assert request("GET", f"/api/v1/lab/datasets/{dataset_id}/preview").status_code == 404
    finally:
        store.cancel(job["id"])


def test_lab_api_limits_local_origin_and_unknown_ids():
    assert request("POST", "/api/v1/lab/jobs", {"repeats": 1}).status_code == 422
    assert (
        request("POST", "/api/v1/lab/jobs", {}, {"origin": "https://untrusted.example"}).status_code
        == 403
    )
    assert request("GET", "/api/v1/lab/jobs/unknown").status_code == 404
    assert request("POST", "/api/v1/lab/jobs/unknown/cancel", {}).status_code == 404
    state = request("GET", "/api/v1/lab").json()
    assert state["datasets"] == [] and state["jobs"] == []
    assert state["environment"]["input_format"] == "partitioned Parquet / Snappy"


def test_bad_engine_result_never_gets_fabricated_timing(known_input, tmp_path):
    folder, _, _ = known_input
    reference = json.loads((folder / "manifest.json").read_text())
    reference["reference_units"]["Google"]["clicks"] += 1
    (folder / "manifest.json").write_text(json.dumps(reference))
    destination = tmp_path / "failed.json"
    assert not run_engine("pandas", ExperimentConfig(), folder, destination)
    result = json.loads(destination.read_text())
    assert result["status"] == "failed"
    assert result["runs"][0]["correct"] is False
    assert "median_seconds" not in result
    assert "Traceback" not in result["message"]


def test_live_memory_limit_stops_engine_without_a_median(tmp_path, monkeypatch):
    store = LabStore(tmp_path)
    config = ExperimentConfig(engines=["pandas"], memory_mib=512)
    dataset = generate_dataset(store, config, lambda _rows: None)
    job = prepare_job(store, config)
    monkeypatch.setattr("ads_optimizer.benchmarks.worker.tree_rss", lambda _pid: 513 * 1024**2)
    result = measure_engine(store, job["id"], config, dataset, "pandas", lambda: None)
    assert result["status"] == "skipped"
    assert "memory limit" in result["message"]
    assert result["median_seconds"] is None and result["median_rows_per_second"] is None
    assert store.get_job(job["id"])["engine_pid"] is None


def test_stale_recovery_cleans_partial_data_and_delete_guard(tmp_path):
    store = LabStore(tmp_path)
    config = ExperimentConfig()
    dataset = generate_dataset(store, config, lambda _rows: None)
    job = prepare_job(store, config)
    with pytest.raises(DomainError, match="running experiment"):
        store.delete_dataset(dataset["id"])
    partial = store.root / "datasets" / f".partial-{job['id']}-test-internal"
    partial.mkdir()
    (partial / "part-00000.parquet").write_bytes(b"partial")
    store.update_job(job["id"], worker_pid=999999999)
    assert store.jobs()[0]["status"] == "interrupted"
    assert not partial.exists()
    assert store.get_dataset(dataset["id"])["rows"] == 10000


def test_cancel_stops_real_spark_jvm_descendants(tmp_path):
    if not environment(tmp_path)["engines"][2]["available"]:
        pytest.skip("Optional PySpark and compatible Java are not installed.")
    store = LabStore(tmp_path)
    job = start_job(store, ExperimentConfig(engines=["spark"]))
    deadline = time.monotonic() + 20
    descendants = []
    try:
        while time.monotonic() < deadline:
            current = store.get_job(job["id"])
            pid = current.get("engine_pid")
            if pid:
                try:
                    descendants = psutil.Process(pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    pass
                if any("java" in child.name().lower() for child in descendants):
                    break
            time.sleep(0.03)
        assert any("java" in child.name().lower() for child in descendants)
        store.cancel(job["id"])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = store.get_job(job["id"])
            if current["status"] == "cancelled":
                break
            time.sleep(0.05)
        assert current["status"] == "cancelled"
        for child in descendants:
            assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
        assert current["results"][0]["median_seconds"] is None
    finally:
        store.cancel(job["id"])


def test_cleanup_kills_orphan_group_after_runner_exits(tmp_path):
    pidfile = tmp_path / "child.pid"
    sleeper = "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"
    parent_code = (
        "import subprocess,sys,pathlib,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{sleeper!r}]); "
        f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(0.2)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parent.wait(timeout=5)
    pid = int(pidfile.read_text())
    try:
        assert psutil.pid_exists(pid)
        stop_tree(parent)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and psutil.pid_exists(pid):
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                break
            time.sleep(0.03)
        assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
