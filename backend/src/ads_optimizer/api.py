"""Single-owner versioned HTTP boundary; all calculations are Python services."""

import base64
import csv
import hmac
import io
import os
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ads_optimizer.ai import nvidia
from ads_optimizer.ai.service import ExplanationInput, KeyInput, explain, preview
from ads_optimizer.analytics.metrics import analytics_result, filter_frame, safe_csv_cell
from ads_optimizer.benchmarks.contracts import ExperimentConfig
from ads_optimizer.benchmarks.environment import environment
from ads_optimizer.benchmarks.service import (
    METHODOLOGY,
    dataset_summary,
    export_csv,
    export_json,
    public_job,
    start_job,
)
from ads_optimizer.benchmarks.store import LabStore
from ads_optimizer.commerce.api import router as commerce_router
from ads_optimizer.data.csv_importer import commit_import, records, stage_csv, validate_import
from ads_optimizer.data.reporting import ReportingAnswers, clarify_report
from ads_optimizer.data.repository import Repository, get_repository
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import MAX_UPLOAD_BYTES, DomainError, GenerateConfig, ImportOptions
from ads_optimizer.hosting.workspace import persisted_response, serverless
from ads_optimizer.ml.contracts import Prediction, TrainingConfig
from ads_optimizer.ml.infer import predict, reevaluate
from ads_optimizer.ml.service import cancel_training, dependency_versions, readiness, start_training
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.ml.store import public_job as public_model_job
from ads_optimizer.optimization.contracts import PlanConfig
from ads_optimizer.optimization.service import create_plan, export_plan, get_plan, optimizer_state
from ads_optimizer.schemas import WorkspaceState
from ads_optimizer.services.application_service import get_workspace_state

app = FastAPI(title="Advertising Budget Optimizer", version="0.4.0")
app.include_router(commerce_router)
Repo = Annotated[Repository, Depends(get_repository)]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/v1/ai/"):
        return JSONResponse(
            status_code=422, content={"detail": "Review the AI request fields and retry."}
        )
    return await request_validation_exception_handler(request, error)


@app.get("/api/v1/ai/status")
def ai_status(repo: Repo):
    return nvidia.status(repo)


@app.put("/api/v1/ai/key")
def ai_key(request: KeyInput, repo: Repo):
    return nvidia.save_key(repo, request.api_key.get_secret_value())


@app.delete("/api/v1/ai/key")
def ai_remove_key(repo: Repo):
    return nvidia.remove_key(repo)


@app.post("/api/v1/ai/test")
def ai_test(repo: Repo):
    nvidia.complete(
        repo,
        "Reply with one short acknowledgement only.",
        "Connection check. No report data is included.",
    )
    return nvidia.status(repo)


@app.get("/api/v1/ai/summary")
def ai_summary(repo: Repo, kind: Literal["performance", "model", "budget"] = "performance"):
    return preview(repo, kind)


@app.post("/api/v1/ai/explain")
def ai_explain(request: ExplanationInput, repo: Repo):
    return explain(repo, request)


@app.exception_handler(DomainError)
async def domain_error(_request: Request, error: DomainError):
    return JSONResponse(status_code=error.status, content={"detail": error.message})


@app.middleware("http")
async def local_write_guard(request: Request, call_next):
    hosted = (
        os.environ.get("ADS_HOSTED") == "1" or os.environ.get("RENDER") == "true" or serverless()
    )
    password = os.environ.get("ADS_ACCESS_PASSWORD", "")
    if hosted or password:
        if request.url.path != "/api/v1/health":
            if len(password) < 32:
                return JSONResponse(
                    status_code=503, content={"detail": "Hosted access is not configured."}
                )
            expected = "Basic " + base64.b64encode(("owner:" + password).encode()).decode()
            if not hmac.compare_digest(
                request.headers.get("authorization", "").encode(), expected.encode()
            ):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required."},
                    headers={
                        "WWW-Authenticate": 'Basic realm="Adwise", charset="UTF-8"',
                        "Cache-Control": "no-store",
                    },
                )
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        allowed_origins = {
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        }
        allowed_origins.update(
            value.strip()
            for value in os.environ.get("ADS_ALLOWED_ORIGINS", "").split(",")
            if value.strip()
        )
        if origin and origin not in allowed_origins:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Workspace writes must come from an allowed application origin."
                },
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                status_code=403, content={"detail": "Cross-site workspace writes are not allowed."}
            )
        length = request.headers.get("content-length", "0")
        upload_limit = 4 * 1024 * 1024 if serverless() else MAX_UPLOAD_BYTES
        if not length.isdigit() or int(length) > upload_limit:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": "The request exceeds the upload limit (4 MiB hosted; 10 MiB local)."
                },
            )
    if serverless() and request.url.path not in {
        "/api/v1/health",
        "/openapi.json",
        "/docs",
        "/redoc",
    }:
        response = await persisted_response(request, call_next)
    else:
        response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ads-optimizer", "version": "0.4.0"}


@app.get("/api/v1/workspace", response_model=WorkspaceState)
def workspace(repo: Repo) -> WorkspaceState:
    return get_workspace_state(repo)


class Selection(BaseModel):
    dataset_id: str | None


@app.put("/api/v1/workspace/dataset", response_model=WorkspaceState)
def select_dataset(selection: Selection, repo: Repo):
    repo.select(selection.dataset_id)
    return get_workspace_state(repo)


@app.post("/api/v1/datasets/generate", status_code=201)
def generate_dataset(config: GenerateConfig, repo: Repo):
    frame, truth = generate_frame(config)
    return repo.save(
        frame,
        {
            "name": config.name.strip(),
            "source": "synthetic_generator",
            "is_synthetic": True,
            "revenue_source": "synthetic",
            "seed": config.seed,
            "conversion_definition": "click-attributed purchases",
            "attribution_window": "synthetic same-day click",
            "data_ready_for_revenue": True,
            "warnings": [
                "Synthetic demo: simulated results do not demonstrate real business performance."
            ],
        },
        truth,
    )


@app.get("/api/v1/datasets/{dataset_id}/preview")
def dataset_preview(
    dataset_id: str,
    repo: Repo,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    frame = repo.read(dataset_id)
    start = (page - 1) * page_size
    return {
        "columns": frame.columns.tolist(),
        "rows": records(frame.iloc[start : start + page_size], page_size),
        "total": len(frame),
        "page": page,
        "page_size": page_size,
    }


@app.delete("/api/v1/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, repo: Repo):
    repo.delete(dataset_id)
    return {"deleted": dataset_id}


FILTER_FIELDS = [
    "start_date",
    "end_date",
    "platform",
    "campaign",
    "city",
    "age",
    "gender",
    "device",
]


def request_filters(request: Request):
    return {
        key: request.query_params[key] for key in FILTER_FIELDS if request.query_params.get(key)
    }


@app.get("/api/v1/datasets/{dataset_id}/analytics")
def analytics(
    dataset_id: str,
    request: Request,
    repo: Repo,
    group_by: str = "campaign",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    sort: str = "revenue",
    direction: str = "desc",
):
    manifest = repo.get(dataset_id)
    return {
        "dataset": manifest,
        **analytics_result(
            repo.read(dataset_id),
            request_filters(request),
            group_by,
            page,
            page_size,
            sort,
            direction,
        ),
    }


def csv_stream(frame):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(frame.columns)
    yield buffer.getvalue()
    for row in frame.itertuples(index=False, name=None):
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow([safe_csv_cell(value) for value in row])
        yield buffer.getvalue()


@app.get("/api/v1/datasets/{dataset_id}/export")
def export_dataset(dataset_id: str, request: Request, repo: Repo):
    manifest = repo.get(dataset_id)
    frame = filter_frame(repo.read(dataset_id), request_filters(request)).copy()
    frame["dataset_id"] = manifest.id
    frame["source"] = manifest.source
    frame["revenue_source"] = manifest.revenue_source
    return StreamingResponse(
        csv_stream(frame),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{manifest.source}-{manifest.id[:8]}.csv"'
        },
    )


@app.post("/api/v1/imports/preview")
async def upload_preview(
    request: Request, repo: Repo, filename: str = Query(max_length=250), profile: str = "generic"
):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_UPLOAD_BYTES:
            raise DomainError("The CSV exceeds the 10 MiB upload limit.", 413)
        chunks.extend(chunk)
    return await run_in_threadpool(stage_csv, repo, bytes(chunks), filename, profile)


@app.post("/api/v1/imports/{token}/validate")
def validate_csv(token: str, options: ImportOptions, repo: Repo):
    _, report, _ = validate_import(repo, token, options)
    return report


@app.post("/api/v1/imports/{token}/commit", status_code=201)
def save_csv(token: str, options: ImportOptions, repo: Repo):
    return commit_import(repo, token, options)


@app.delete("/api/v1/imports/{token}")
def discard_preview(token: str, repo: Repo):
    from ads_optimizer.data.csv_importer import read_stage

    read_stage(repo, token)
    (repo.root / "staging" / f"{token}.json").unlink(missing_ok=True)
    return {"discarded": token}


@app.get("/api/v1/templates/campaign.csv")
def campaign_template():
    frame, _ = generate_frame(GenerateConfig(rows=100, seed=7))
    return StreamingResponse(
        csv_stream(frame),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="synthetic-campaign-fixture.csv"'},
    )


@app.get("/api/v1/lab")
def lab_state(repo: Repo):
    store = LabStore(repo.root)
    runtime = {**environment(repo.root), "hosted": serverless()}
    if serverless():
        for engine in runtime["engines"]:
            engine.update(available=False, reason="Run Big Data experiments in the local app.")
    return {
        "environment": runtime,
        "methodology": METHODOLOGY,
        "datasets": [dataset_summary(d) for d in store.datasets()],
        "jobs": [public_job(j) for j in store.jobs()],
    }


@app.post("/api/v1/lab/jobs", status_code=202)
def create_experiment(config: ExperimentConfig, repo: Repo):
    return start_job(LabStore(repo.root), config)


@app.get("/api/v1/lab/jobs/{job_id}")
def experiment(job_id: str, repo: Repo):
    store = LabStore(repo.root)
    store.jobs()
    return public_job(store.get_job(job_id))


@app.post("/api/v1/lab/jobs/{job_id}/cancel")
def cancel_experiment(job_id: str, repo: Repo):
    return public_job(LabStore(repo.root).cancel(job_id))


@app.get("/api/v1/lab/jobs/{job_id}/export")
def export_experiment(job_id: str, repo: Repo, format: str = "json"):
    job = LabStore(repo.root).get_job(job_id)
    if format not in {"json", "csv"}:
        raise DomainError("Choose JSON or CSV for the experiment export.")
    body = export_json(job) if format == "json" else export_csv(job)
    return Response(
        body,
        media_type="application/json" if format == "json" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="synthetic-benchmark-'
            f'{job["id"][:8]}.{format}"'
        },
    )


@app.get("/api/v1/lab/datasets/{dataset_id}/preview")
def lab_preview(dataset_id: str, repo: Repo):
    import pyarrow.parquet as pq

    store = LabStore(repo.root)
    dataset = store.get_dataset(dataset_id)
    path = store.dataset_path(dataset_id) / dataset["files"][0]["file"]
    batch = next(pq.ParquetFile(path).iter_batches(batch_size=20))
    return {"columns": batch.schema.names, "rows": batch.to_pylist(), "total": dataset["rows"]}


@app.delete("/api/v1/lab/datasets/{dataset_id}")
def delete_lab_dataset(dataset_id: str, repo: Repo):
    LabStore(repo.root).delete_dataset(dataset_id)
    return {"deleted": dataset_id}


@app.get("/api/v1/ml")
def ml_state(repo: Repo):
    selected = repo.selected()
    jobs = ModelStore(repo.root).jobs()
    return {
        "jobs": [
            public_model_job(j)
            for j in jobs
            if selected and j["config"]["dataset_id"] == selected.id
        ],
        "active_job": next(
            (
                public_model_job(j)
                for j in jobs
                if j["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}
            ),
            None,
        ),
        "versions": dependency_versions(),
    }


@app.post("/api/v1/ml/readiness")
def ml_readiness(config: TrainingConfig, repo: Repo):
    return readiness(repo, config)


@app.post("/api/v1/datasets/{dataset_id}/reporting-setup", status_code=201)
def reporting_setup(dataset_id: str, answers: ReportingAnswers, repo: Repo):
    return clarify_report(repo, dataset_id, answers)


@app.post("/api/v1/ml/jobs", status_code=202)
def ml_start(config: TrainingConfig, repo: Repo):
    return start_training(repo, config)


@app.get("/api/v1/ml/jobs/{job_id}")
def ml_job(job_id: str, repo: Repo):
    store = ModelStore(repo.root)
    store.jobs()
    return public_model_job(store.get(job_id))


@app.post("/api/v1/ml/jobs/{job_id}/cancel")
def ml_cancel(job_id: str, repo: Repo):
    return cancel_training(ModelStore(repo.root), job_id)


@app.post("/api/v1/ml/models/{model_id}/evaluate")
def ml_evaluate(model_id: str, repo: Repo):
    return reevaluate(repo, ModelStore(repo.root), model_id)


@app.post("/api/v1/ml/models/{model_id}/predict")
def ml_predict(model_id: str, request: Prediction, repo: Repo):
    return predict(repo, ModelStore(repo.root), model_id, request)


@app.get("/api/v1/ml/jobs/{job_id}/export")
def ml_export(job_id: str, repo: Repo):
    import json

    job = public_model_job(ModelStore(repo.root).get(job_id))
    return Response(
        json.dumps(job, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="model-evaluation-{job["id"][:8]}.json"'
        },
    )


@app.get("/api/v1/optimizer")
def budget_state(repo: Repo):
    return optimizer_state(repo)


@app.post("/api/v1/optimizer/plans", status_code=201)
def budget_plan(config: PlanConfig, repo: Repo):
    return create_plan(repo, config)


@app.get("/api/v1/optimizer/plans/{plan_id}")
def saved_budget_plan(plan_id: str, repo: Repo):
    return get_plan(repo, plan_id)


@app.get("/api/v1/optimizer/plans/{plan_id}/export")
def export_budget_plan(plan_id: str, repo: Repo, format: str = "json"):
    report = get_plan(repo, plan_id)
    body = export_plan(report, format)
    return Response(
        body,
        media_type="application/json" if format == "json" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="budget-plan-{report["id"][:8]}.{format}"'
        },
    )
