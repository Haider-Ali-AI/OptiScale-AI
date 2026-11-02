"""Local registry: catalog IDs only, atomic publication, one active training worker."""

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone

import psutil

from ads_optimizer.domain import DomainError
from ads_optimizer.ml.contracts import TERMINAL


def now():
    return datetime.now(timezone.utc).isoformat()


class ModelStore:
    def __init__(self, data_root):
        self.root = data_root / "ml"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, "
                "active INTEGER NOT NULL, snapshot TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active ON jobs(active) WHERE active=1"
            )

    def connect(self):
        return sqlite3.connect(self.root / "registry.sqlite", timeout=30)

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise DomainError("This model run is no longer available.", 404)
        return json.loads(row[0])

    def update(self, job_id, only_if_active=False, **changes):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise DomainError("This model run is no longer available.", 404)
            previous = json.loads(row[0])
            if only_if_active and previous["status"] in TERMINAL:
                return previous
            job = {**previous, **changes, "updated_at": now()}
            conn.execute(
                "UPDATE jobs SET active=?,snapshot=? WHERE id=?",
                (int(job["status"] not in TERMINAL), json.dumps(job), job_id),
            )
        return job

    def jobs(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT snapshot FROM jobs ORDER BY rowid DESC LIMIT 100"
            ).fetchall()
        jobs = [json.loads(row[0]) for row in rows]
        for i, job in enumerate(jobs):
            if job["status"] in TERMINAL:
                continue
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"])
            ).total_seconds()
            if not job.get("worker_pid") and age < 15:
                continue
            try:
                process = psutil.Process(job["worker_pid"] or -1)
                alive = (
                    "ads_optimizer.ml.worker" in process.cmdline()
                    and job["id"] in process.cmdline()
                    and process.status() != psutil.STATUS_ZOMBIE
                )
            except psutil.AccessDenied:
                alive = True
            except (psutil.Error, OSError):
                alive = False
            if not alive:
                jobs[i] = self.update(
                    job["id"],
                    only_if_active=True,
                    status="interrupted",
                    stage="interrupted",
                    message="The worker stopped. Start a new training run.",
                )
                self.cleanup_partial(job["id"])
        return jobs

    def cleanup_partial(self, job_id):
        job = self.get(job_id)
        if job["status"] in TERMINAL and job["status"] != "succeeded":
            for name in [
                "input.parquet",
                "model.ubj",
                "model.joblib",
                "preprocessing.json",
                "holdout.parquet",
            ]:
                (self.root / job["id"] / name).unlink(missing_ok=True)

    def delete_for_dataset(self, dataset_id):
        self.jobs()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            jobs = [json.loads(row[0]) for row in conn.execute("SELECT snapshot FROM jobs")]
            matching = [j for j in jobs if j["config"]["dataset_id"] == dataset_id]
            if any(j["status"] not in TERMINAL for j in matching):
                raise DomainError(
                    "Cancel or finish this dataset's training before deleting it.", 409
                )
            for job in matching:
                conn.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
        for job in matching:
            shutil.rmtree(self.root / job["id"], ignore_errors=True)

    def create(self, config, manifest):
        self.jobs()
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": now(),
            "updated_at": now(),
            "completed_at": None,
            "config": config.model_dump(mode="json"),
            "dataset": manifest.model_dump(mode="json"),
            "result": None,
            "message": "Waiting for the local training worker.",
            "worker_pid": None,
            "cancel_requested": False,
        }
        try:
            with self.connect() as conn:
                conn.execute("INSERT INTO jobs VALUES (?,1,?)", (job_id, json.dumps(job)))
        except sqlite3.IntegrityError as error:
            raise DomainError(
                "A model is already training. Wait or cancel it first.", 409
            ) from error
        (self.root / job_id).mkdir()
        return job

    def published(self, model_id):
        job = self.get(model_id)
        if job["status"] != "succeeded" or not job["result"]:
            raise DomainError("This run has no completed model. Train again.", 409)
        return job

    def complete(self, job_id, result):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = json.loads(
                conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
            )
            cancelled = job["cancel_requested"]
            job.update(
                status="cancelled" if cancelled else "succeeded",
                stage="cancelled" if cancelled else "complete",
                completed_at=now(),
                updated_at=now(),
                result=None if cancelled else result,
                message="Training cancelled. No model was published."
                if cancelled
                else "Training and holdout evaluation completed.",
            )
            conn.execute(
                "UPDATE jobs SET active=0,snapshot=? WHERE id=?", (json.dumps(job), job_id)
            )
        return job


def public_job(job):
    return {k: v for k, v in job.items() if k != "worker_pid"}
