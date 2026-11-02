"""Durable local orchestration; no long benchmark request occupies an HTTP connection."""

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

import psutil

from ads_optimizer.benchmarks.contracts import ExperimentConfig
from ads_optimizer.benchmarks.environment import environment, java_home
from ads_optimizer.benchmarks.store import LabStore, now, worker_environment


class Cancelled(Exception):
    pass


class ResourceLimit(Exception):
    pass


def tree_rss(pid):
    try:
        process = psutil.Process(pid)
        processes = [process, *process.children(recursive=True)]
    except (OSError, psutil.Error):
        return None
    sizes = []
    for process in processes:
        try:
            sizes.append(process.memory_info().rss)
        except (OSError, psutil.Error):
            pass
    return sum(sizes) if sizes else None


def stop_tree(process):
    # Engine sessions have their own process group, including JVM/mapper descendants.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except (OSError, psutil.Error):
        descendants = []
    for child in reversed(descendants):
        try:
            child.terminate()
        except (OSError, psutil.Error):
            pass
    process.terminate()
    _, alive = psutil.wait_procs(descendants, timeout=2)
    for child in alive:
        try:
            child.kill()
        except (OSError, psutil.Error):
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    if os.name == "posix":
        # The runner can already have exited while an orphan descendant kept its group alive.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def read_snapshot(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def measure_engine(store, job_id, config, dataset, engine_id, checkpoint):
    folder = store.root / "jobs" / job_id
    output = folder / f"{engine_id}.json"
    command = [
        sys.executable,
        "-m",
        "ads_optimizer.benchmarks.engine_runner",
        "--engine",
        engine_id,
        "--config",
        str(folder / "config.json"),
        "--dataset",
        str(store.dataset_path(dataset["id"])),
        "--output",
        str(output),
    ]
    env = worker_environment()
    env.update(SPARK_LOCAL_IP="127.0.0.1", PYSPARK_PYTHON=sys.executable)
    home = java_home()
    if home:
        env["JAVA_HOME"] = str(home)
    snapshot = {
        "engine": engine_id,
        "status": "running",
        "runs": [],
        "peak_tree_rss_bytes": None,
        "setup_seconds": None,
        "median_seconds": None,
        "median_rows_per_second": None,
        "message": "Starting engine.",
    }
    peak = 0
    start = time.monotonic()
    child = None
    results_before = store.get_job(job_id)["results"]
    try:
        with (folder / f"{engine_id}.log").open("w") as log:
            child = subprocess.Popen(
                command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            store.update_job(job_id, engine_pid=child.pid)
            last_progress = -1
            while child.poll() is None:
                checkpoint()
                sample = tree_rss(child.pid)
                if sample is not None:
                    peak = max(peak, sample)
                if sample and sample > config.memory_mib * 1024**2:
                    raise ResourceLimit(
                        f"Stopped at the {config.memory_mib:,} MiB process-tree "
                        "memory limit. Try a larger allowance or fewer workers."
                    )
                if time.monotonic() - start > 600:
                    raise ResourceLimit("Stopped at the 10-minute engine time limit.")
                current = read_snapshot(output)
                if current:
                    snapshot.update(current)
                progress = len(snapshot["runs"])
                if progress != last_progress:
                    last_progress = progress
                    store.update_job(
                        job_id,
                        message=f"{engine_id}: {progress} of {config.repeats} repeats measured.",
                        results=[
                            *results_before,
                            {**snapshot, "peak_tree_rss_bytes": peak or None},
                        ],
                    )
                time.sleep(0.15)
            snapshot.update(
                read_snapshot(output)
                or {
                    "status": "failed",
                    "message": "Engine exited before producing a result. Review its local log.",
                }
            )
            if child.returncode != 0 and snapshot["status"] == "completed":
                snapshot.update(status="failed", message="The engine process exited abnormally.")
    except ResourceLimit as error:
        snapshot.update(status="skipped", message=str(error))
    except Cancelled:
        snapshot.update(status="cancelled", message="Cancelled by the user.")
    finally:
        if child:
            stop_tree(child)
        snapshot["peak_tree_rss_bytes"] = peak or None
        store.update_job(job_id, engine_pid=None)
    if (
        snapshot["status"] == "completed"
        and len(snapshot["runs"]) == config.repeats
        and all(run["correct"] for run in snapshot["runs"])
    ):
        snapshot["median_seconds"] = statistics.median(
            r["elapsed_seconds"] for r in snapshot["runs"]
        )
        snapshot["median_rows_per_second"] = config.rows / snapshot["median_seconds"]
        snapshot["message"] = "All repeated results match the reference."
    elif snapshot["status"] == "completed":
        snapshot.update(status="failed", message="The repeated correctness gate did not pass.")
    return snapshot


def execute_job(store: LabStore, job_id):
    config = ExperimentConfig.model_validate(store.get_job(job_id)["config"])
    started = time.monotonic()
    signalled = False

    def terminate(_signal, _frame):
        nonlocal signalled
        signalled = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    def checkpoint(rows=None):
        job = store.get_job(job_id)
        if signalled or job["cancel_requested"]:
            raise Cancelled()
        if time.monotonic() - started > 1800:
            raise ResourceLimit("The experiment reached the 30-minute job limit.")
        if rows is not None:
            rss = tree_rss(os.getpid())
            if rss and rss > config.memory_mib * 1024**2:
                raise ResourceLimit(
                    "Generation reached the selected memory limit. "
                    "Use smaller chunks or a larger allowance."
                )
            store.update_job(
                job_id,
                generated_rows=rows,
                message=f"Generated {rows:,} of {config.rows:,} synthetic rows.",
            )

    store.update_job(job_id, worker_pid=os.getpid(), status="running", stage="preflight")
    try:
        checkpoint()
        env = environment(store.root)
        store.update_job(job_id, environment=env)
        if (
            env["ram_available_bytes"] is not None
            and config.memory_mib * 1024**2 > env["ram_available_bytes"] * 0.7
        ):
            raise ResourceLimit(
                "The requested memory allowance exceeds 70% of currently "
                "available RAM. Close other apps or choose a smaller allowance."
            )
        from ads_optimizer.benchmarks.generator import config_key, generate_dataset

        dataset = (
            store.get_dataset(config.dataset_id)
            if config.dataset_id
            else store.by_config(config_key(config))
        )
        if dataset:
            if dataset["config"] != config.generation_config():
                raise ValueError("The selected dataset and experiment configuration differ.")
            for part in dataset["files"]:
                path = store.dataset_path(dataset["id"]) / part["file"]
                import hashlib

                with path.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != part["sha256"]:
                    raise ValueError("Saved dataset checksum verification failed.")
                checkpoint()
            generation_seconds = None
        else:
            # Conservative disk estimate, not an advertised measured dataset size.
            if shutil.disk_usage(store.root).free < config.rows * 1024 + 1024**3:
                raise ResourceLimit(
                    "Not enough free disk for safe generation plus a 1 GiB reserve."
                )
            store.update_job(job_id, stage="generating")
            generation_start = time.perf_counter()
            dataset = generate_dataset(store, config, checkpoint, job_id=job_id)
            generation_seconds = time.perf_counter() - generation_start
        store.update_job(
            job_id,
            dataset=dataset,
            generated_rows=dataset["rows"],
            generation_seconds=generation_seconds,
            message="Dataset verified and ready.",
        )
        results = []
        if config.kind == "benchmark":
            for engine_id in config.engines:
                checkpoint()
                store.update_job(job_id, stage=engine_id)
                capability = next(e for e in env["engines"] if e["id"] == engine_id)
                if not capability["available"]:
                    result = {
                        "engine": engine_id,
                        "status": "unavailable",
                        "runs": [],
                        "message": capability["reason"],
                        "median_seconds": None,
                        "median_rows_per_second": None,
                        "peak_tree_rss_bytes": None,
                        "setup_seconds": None,
                    }
                else:
                    result = measure_engine(store, job_id, config, dataset, engine_id, checkpoint)
                results.append(result)
                store.update_job(job_id, results=results)
                checkpoint()
        store.update_job(
            job_id,
            status="completed",
            stage="done",
            completed_at=now(),
            message="Experiment finished. Review measured results and any engine failures or skips."
            if config.kind == "benchmark"
            else "Synthetic lab dataset saved. Ready for a measured experiment.",
        )
    except Cancelled:
        store.update_job(
            job_id,
            status="cancelled",
            completed_at=now(),
            message="Experiment cancelled. Saved datasets and completed measurements "
            "are retained; incomplete generation is removed.",
        )
    except ResourceLimit as error:
        store.update_job(job_id, status="failed", completed_at=now(), message=str(error))
    except Exception:
        traceback.print_exc()
        store.update_job(
            job_id,
            status="failed",
            completed_at=now(),
            message="The experiment could not finish. Check its local worker log "
            "for diagnostics, then retry. Existing campaign datasets are unchanged.",
        )
    final = store.get_job(job_id)
    (store.root / "jobs" / job_id / "report.json").write_text(json.dumps(final, indent=2))
    return final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    store = LabStore(args.data_root)
    execute_job(store, args.job)


if __name__ == "__main__":
    main()
