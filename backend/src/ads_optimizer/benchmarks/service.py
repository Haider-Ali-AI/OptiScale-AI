import csv
import io
import json
import subprocess
import sys

from ads_optimizer.benchmarks.contracts import ExperimentConfig
from ads_optimizer.benchmarks.store import LabStore, worker_environment
from ads_optimizer.domain import DomainError

METHODOLOGY = {
    "workload": "platform_totals_v1",
    "source": "Seeded synthetic campaigns only; PKR; configured dates and platforms.",
    "timing": "Each repeat includes projected Parquet reads, aggregation, weighted rates and "
    "materialization of platform totals. Generation, checksums and engine setup are "
    "excluded and reported separately. No application cache or unreported warm-up.",
    "setup": "Imports/session initialization (including JVM startup and mapper readiness) "
    "measured separately. No input is read as an unreported warm-up.",
    "cache": "Sequential engine runs on one machine. OS/JVM caches are not flushed. Later "
    "repeats may benefit from warm caches; timings are not cluster benchmarks.",
    "correctness": "Every repeat must match independent vector-mask reference sums recorded "
    "during generation. Row/non-null counts and scaled-integer sums match exactly; "
    "weighted float rates use absolute and relative tolerance 1e-9.",
    "precision": "Money is summed as integer paisa; conversions as integer millionths. "
    "Incomplete metrics propagate null totals; zero denominators yield null rates.",
    "memory": "Sampled sum of RSS for the engine process and its descendants (including Spark "
    "JVM and mapper processes), every 150 ms. Shared pages may be counted more than "
    "once and short peaks may be missed. This is not whole-system memory. Generation "
    "checks its own worker tree at chunk boundaries. Unmeasurable memory stays null.",
    "resources": "One local job; 1–4 workers; 512–4096 MiB sampled memory ceiling; 10-minute "
    "engine / 30-minute job limits. Exceeding a limit stops the affected work. "
    "Pandas switches to bounded chunks when rows × 200 bytes exceed 40% of the "
    "chosen allowance. Native-library threads are bounded where supported.",
    "cancellation": "Cooperative cancellation between generation chunks and during engine "
    "monitoring. Child processes are terminated; incomplete data is removed. "
    "Saved data and completed repeats remain. Jobs survive web-server reloads.",
}


def dataset_summary(dataset):
    return {key: value for key, value in dataset.items() if key not in {"files", "reference_units"}}


def public_job(job):
    return {
        **{key: value for key, value in job.items() if key not in {"worker_pid", "engine_pid"}},
        "dataset": dataset_summary(job["dataset"]) if job["dataset"] else None,
    }


def start_job(store: LabStore, config: ExperimentConfig):
    from ads_optimizer.hosting.workspace import serverless

    if serverless():
        raise DomainError(
            "Big Data experiments require the local app. Vercel does not run detached lab workers.",
            409,
        )
    if config.dataset_id:
        dataset = store.get_dataset(config.dataset_id)
        if dataset["config"] != config.generation_config():
            raise DomainError(
                "The selected dataset has different generation settings. "
                "Use its saved configuration or generate a new input."
            )
    job = store.create_job(config)
    store.update_job(job["id"], methodology=METHODOLOGY, benchmark_version="2.0")
    folder = store.root / "jobs" / job["id"]
    (folder / "config.json").write_text(config.model_dump_json())
    try:
        with (folder / "worker.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ads_optimizer.benchmarks.worker",
                    "--data-root",
                    str(store.root.parent),
                    "--job",
                    job["id"],
                ],
                env=worker_environment(),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return public_job(store.update_job(job["id"], worker_pid=process.pid))
    except OSError as error:
        store.update_job(job["id"], status="failed", message="Could not start a local worker.")
        raise DomainError(
            "Could not start the experiment worker. Restart the service.", 503
        ) from error


def export_csv(job):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "job_id",
            "status",
            "source",
            "dataset_id",
            "dataset_sha256",
            "rows",
            "seed",
            "start_date",
            "end_date",
            "currency",
            "engine",
            "mode",
            "engine_status",
            "repeat",
            "elapsed_seconds",
            "rows_per_second",
            "correct",
            "setup_seconds",
            "peak_tree_rss_bytes",
            "median_seconds",
            "message",
        ]
    )
    config, dataset = job["config"], job["dataset"] or {}
    results = job["results"] or [{"engine": "generation", "status": job["status"]}]
    for result in results:
        for run in result.get("runs") or [{}]:
            writer.writerow(
                [
                    job["id"],
                    job["status"],
                    "synthetic_benchmark",
                    dataset.get("id"),
                    dataset.get("sha256"),
                    config["rows"],
                    config["seed"],
                    config["start_date"],
                    config["end_date"],
                    "PKR",
                    result["engine"],
                    result.get("mode"),
                    result["status"],
                    run.get("repeat"),
                    run.get("elapsed_seconds"),
                    run.get("rows_per_second"),
                    run.get("correct"),
                    result.get("setup_seconds"),
                    result.get("peak_tree_rss_bytes"),
                    result.get("median_seconds"),
                    result.get("message", job["message"]),
                ]
            )
    return output.getvalue()


def export_json(job):
    return json.dumps({"methodology": METHODOLOGY, **job}, indent=2)
