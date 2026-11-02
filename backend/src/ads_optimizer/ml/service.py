import hashlib
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

from ads_optimizer.benchmarks.store import worker_environment
from ads_optimizer.data.provenance import provenance_review
from ads_optimizer.data.reporting import known, manifest_setup
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.contracts import TERMINAL
from ads_optimizer.ml.features import chronological_split
from ads_optimizer.ml.store import ModelStore, public_job


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(repo, config, input_frame=None, *, historical=False):
    manifest = repo.get(config.dataset_id)
    review = provenance_review(manifest)
    if review:
        raise DomainError(review[0])
    if manifest.rows > 100_000:
        raise DomainError("Training is bounded to 100,000 campaign rows; lab inputs stay separate.")
    missing = [field for field in ["spend", "revenue"] if manifest.coverage.get(field, 0) < 1]
    if missing:
        raise DomainError(
            "Training needs complete values for: "
            + ", ".join(missing)
            + ". Review these column mappings and missing rows in Data Studio."
        )
    if not known(manifest.attribution_window) or not known(manifest.conversion_definition):
        raise DomainError(
            "Financial columns are complete, but the conversion definition or attribution "
            "window is unspecified. Supply the report's actual definitions before training."
        )
    if not manifest.data_ready_for_revenue:
        raise DomainError(
            "This import has not passed revenue-readiness validation. "
            "Review its validation warnings in Data Studio."
        )
    frame = (
        (repo.read(manifest.id) if input_frame is None else input_frame)
        .sort_values("date", kind="stable")
        .reset_index(drop=True)
    )
    lag = 0 if manifest.is_synthetic else config.label_lag_days
    cutoff = (config.as_of_date - timedelta(days=lag)).isoformat()
    period_days = 7 if manifest.date_granularity == "weekly" else 1
    period_cutoff = (config.as_of_date - timedelta(days=lag + period_days - 1)).isoformat()
    mature = frame[frame.date <= period_cutoff].copy()
    valid = (
        np.isfinite(mature.spend)
        & np.isfinite(mature.revenue)
        & (mature.spend >= 0)
        & (mature.revenue >= 0)
    )
    mature = mature[valid].reset_index(drop=True)
    if historical:
        if (
            len(mature) < 20
            or mature.date.nunique() < 4
            or mature.spend.nunique() < 3
            or mature.spend.sum() <= 0
            or mature.revenue.sum() <= 0
        ):
            raise DomainError(
                "Historical planning needs 20 mature rows across 4 reporting periods, "
                "3 distinct spends and positive spend/revenue. Analytics remain available."
            )
    elif len(mature) < 300 or mature.spend.nunique() < 10 or mature.revenue.sum() <= 0:
        raise DomainError(
            "Need 300 mature rows, 10 distinct spends and positive attributed revenue."
        )
    parts = [mature] if historical else chronological_split(mature)
    if not historical and (parts[0].spend.nunique() < 10 or parts[0].revenue.sum() <= 0):
        raise DomainError("The training period needs 10 distinct spends and positive revenue.")
    for key in ["attribution_window", "conversion_definition"]:
        if key in mature and mature[key].nunique() > 1:
            raise DomainError(
                "This report mixes attribution/conversion definitions. Import separately."
            )
    return (
        manifest,
        mature,
        parts,
        {
            "input_rows": len(frame),
            "eligible_rows": len(mature),
            "excluded_rows": len(frame) - len(mature),
            "maturity_cutoff": cutoff,
            "period_days": period_days,
            "label_lag_days": lag,
        },
    )


def readiness(repo, config):
    setup = None
    try:
        source = repo.get(config.dataset_id)
        from ads_optimizer.hosting.workspace import serverless

        if serverless() and source.rows > 10000:
            raise DomainError(
                "Hosted training supports up to 10,000 rows. Train larger reports locally."
            )
        setup = manifest_setup(
            source,
            repo.read(source.id)
            if "mixed" in {source.conversion_definition, source.attribution_window}
            else None,
        )
        manifest, _, parts, coverage = prepare(repo, config)
        return {
            "ready": True,
            "reasons": [],
            "coverage": coverage,
            "splits": split_summary(parts),
            "is_synthetic": manifest.is_synthetic,
            "reporting_setup": setup,
        }
    except DomainError as error:
        return {"ready": False, "reasons": [error.message], "reporting_setup": setup}


def split_summary(parts):
    return {
        name: {"rows": len(part), "start": part.date.min(), "end": part.date.max()}
        for name, part in zip(["train", "validation", "test"], parts, strict=True)
    }


def dependency_versions():
    result = {}
    for name in ["xgboost", "scikit-learn", "numpy", "pandas"]:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            try:
                result[name] = version("xgboost-cpu") if name == "xgboost" else None
            except PackageNotFoundError:
                result[name] = None
    return result


def start_training(repo, config):
    if not repo.selected() or repo.selected().id != config.dataset_id:
        raise DomainError("Select this dataset before training; reports cannot be pooled.", 409)
    from ads_optimizer.hosting.workspace import serverless

    manifest, _, _, _ = prepare(repo, config)
    if serverless() and manifest.rows > 10000:
        raise DomainError(
            "Hosted training supports up to 10,000 rows. Train larger reports locally."
        )
    store = ModelStore(repo.root)
    # Serialize source deletion and model creation using the campaign catalog lock.
    with repo.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        repo.get(manifest.id)
        if not repo.selected() or repo.selected().id != manifest.id:
            raise DomainError("The selected dataset changed. Review it before training.", 409)
        job = store.create(config, manifest)
    folder = store.root / job["id"]
    try:
        source = repo.root / "datasets" / manifest.id / "campaigns.parquet"
        shutil.copyfile(source, folder / "input.parquet")
        store.update(job["id"], input_sha256=sha256(folder / "input.parquet"))
        if serverless():
            from ads_optimizer.ml.worker import run

            run(repo.root, job["id"])
            return public_job(store.get(job["id"]))
        with (folder / "worker.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ads_optimizer.ml.worker",
                    "--data-root",
                    str(repo.root),
                    "--job",
                    job["id"],
                ],
                env=training_environment(),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return public_job(store.update(job["id"], worker_pid=process.pid))
    except (OSError, DomainError) as error:
        store.update(
            job["id"], status="failed", message="Could not snapshot/start training. Retry."
        )
        (folder / "input.parquet").unlink(missing_ok=True)
        raise DomainError(
            "Could not start local training. Retry or restart the service.", 503
        ) from error


def cancel_training(store, job_id):
    job = store.get(job_id)
    if job["status"] in TERMINAL:
        return public_job(job)
    return public_job(
        store.update(
            job_id,
            only_if_active=True,
            cancel_requested=True,
            message="Cancellation requested; stopping at the next fit step.",
        )
    )


def training_environment():
    environment = worker_environment()
    if sys.platform == "darwin":
        library = (
            Path(sys.prefix)
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages/sklearn/.dylibs/libomp.dylib"
        )
        if library.is_file():
            environment["DYLD_LIBRARY_PATH"] = os.pathsep.join(
                filter(None, [str(library.parent), os.environ.get("DYLD_LIBRARY_PATH")])
            )
    return environment
