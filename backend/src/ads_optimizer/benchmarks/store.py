"""Atomic SQLite job snapshots. Experiment data never enters the small campaign catalog."""

import json
import os
import signal
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil

from ads_optimizer.benchmarks.contracts import TERMINAL, ExperimentConfig
from ads_optimizer.domain import DomainError


def now():
    return datetime.now(timezone.utc).isoformat()


class LabStore:
    def __init__(self, data_root: Path):
        self.root = data_root / "benchmarks"
        self.root.mkdir(exist_ok=True, parents=True)
        (self.root / "datasets").mkdir(exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, "
                "active INTEGER NOT NULL, snapshot TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(active) WHERE active=1"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, "
                "config_key TEXT UNIQUE NOT NULL, manifest TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.root / "lab.sqlite", timeout=30)

    def get_job(self, job_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise DomainError("That experiment is no longer available.", 404)
        return json.loads(row[0])

    def update_job(self, job_id: str, only_if_active=False, **changes):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise DomainError("That experiment is no longer available.", 404)
            previous = json.loads(row[0])
            if only_if_active and previous["status"] in TERMINAL:
                return previous
            snapshot = {**previous, **changes, "updated_at": now()}
            conn.execute(
                "UPDATE jobs SET active=?, snapshot=? WHERE id=?",
                (int(snapshot["status"] not in TERMINAL), json.dumps(snapshot), job_id),
            )
        return snapshot

    def jobs(self, limit=30):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT snapshot FROM jobs ORDER BY rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        jobs = [json.loads(row[0]) for row in rows]
        for job in jobs:
            if job["status"] not in TERMINAL and (
                job.get("worker_pid")
                or (
                    datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"])
                ).total_seconds()
                > 15
            ):
                if not self.worker_alive(job):
                    job.update(
                        self.update_job(
                            job["id"],
                            only_if_active=True,
                            status="interrupted",
                            message="The experiment worker stopped. Start a new run; saved "
                            "datasets and completed measurements are retained.",
                        )
                    )
                    if job["status"] == "interrupted":
                        self.cleanup_interrupted(job)
        return jobs

    def cleanup_interrupted(self, job):
        import shutil

        pid = job.get("engine_pid")
        if pid:
            try:
                process = psutil.Process(pid)
                command = process.cmdline()
                if (
                    "ads_optimizer.benchmarks.engine_runner" in command
                    and any(job["id"] in arg for arg in command)
                    and os.name == "posix"
                    and os.getpgid(pid) == pid
                ):
                    descendants = process.children(recursive=True)
                    os.killpg(pid, signal.SIGTERM)
                    psutil.wait_procs([process, *descendants], timeout=2)
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            except (OSError, psutil.Error):
                pass
        # Only one job can generate. These are internal incomplete-data folders.
        for path in (self.root / "datasets").glob(f".partial-{job['id']}-*"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def worker_alive(job):
        try:
            process = psutil.Process(job["worker_pid"])
            command = process.cmdline()
            return (
                "ads_optimizer.benchmarks.worker" in command
                and job["id"] in command
                and process.status() != psutil.STATUS_ZOMBIE
            )
        except (psutil.AccessDenied, PermissionError):
            # Unknown process visibility is not proof that a worker died.
            return True
        except (KeyError, TypeError, OSError, psutil.Error):
            return False

    def create_job(self, config: ExperimentConfig):
        self.jobs()
        job_id = uuid.uuid4().hex
        snapshot = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": now(),
            "updated_at": now(),
            "config": config.model_dump(mode="json"),
            "message": "Waiting for the local worker.",
            "generated_rows": 0,
            "cancel_requested": False,
            "worker_pid": None,
            "dataset": None,
            "environment": None,
            "results": [],
            "completed_at": None,
        }
        try:
            with self.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if (
                    config.dataset_id
                    and not conn.execute(
                        "SELECT 1 FROM datasets WHERE id=?", (config.dataset_id,)
                    ).fetchone()
                ):
                    raise DomainError("The selected lab dataset was deleted. Choose another.", 404)
                conn.execute("INSERT INTO jobs VALUES (?, 1, ?)", (job_id, json.dumps(snapshot)))
        except sqlite3.IntegrityError as error:
            raise DomainError(
                "Another local experiment is running. Wait or cancel it first.", 409
            ) from error
        (self.root / "jobs" / job_id).mkdir()
        return snapshot

    def datasets(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT manifest FROM datasets ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_dataset(self, dataset_id):
        with self.connect() as conn:
            row = conn.execute("SELECT manifest FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            raise DomainError("That lab dataset is no longer available. Generate another.", 404)
        return json.loads(row[0])

    def by_config(self, key):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT manifest FROM datasets WHERE config_key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_dataset(self, manifest):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO datasets VALUES (?, ?, ?)",
                (manifest["id"], manifest["config_key"], json.dumps(manifest)),
            )

    def dataset_path(self, dataset_id):
        manifest = self.get_dataset(dataset_id)
        return self.root / "datasets" / manifest["id"]

    def cancel(self, job_id):
        job = self.get_job(job_id)
        if job["status"] in TERMINAL:
            return job
        return self.update_job(
            job_id, cancel_requested=True, message="Cancellation requested; stopping local work."
        )

    def delete_dataset(self, dataset_id):
        import shutil

        self.get_dataset(dataset_id)
        self.jobs()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM jobs WHERE active=1").fetchone():
                raise DomainError(
                    "Wait for the running experiment before deleting lab datasets.", 409
                )
            conn.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
        shutil.rmtree(self.root / "datasets" / dataset_id, ignore_errors=True)


def worker_environment():
    source = str(Path(__file__).resolve().parents[2])
    return {
        **os.environ,
        "PYTHONPATH": source,
        "PYTHONUNBUFFERED": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
    }
