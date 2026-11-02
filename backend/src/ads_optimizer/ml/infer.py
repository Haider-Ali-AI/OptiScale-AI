"""Load only registered, locally generated artifacts whose checksums still match."""

import json
from datetime import date

import joblib
import numpy as np
import pandas as pd

from ads_optimizer.data.provenance import provenance_review
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.evaluate import evaluate
from ads_optimizer.ml.features import FEATURES, encoder_for, transform
from ads_optimizer.ml.service import dependency_versions, sha256


def load_model(store, model_id):
    job = store.published(model_id)
    result = job["result"]
    if (
        result.get("feature_schema_version") != "campaign-context-v1"
        or result.get("features") != FEATURES
    ):
        raise DomainError("Model feature schema is incompatible. Retrain before inference.", 409)
    folder = store.root / job["id"]
    if result["artifact"] not in {"model.ubj", "model.joblib"}:
        raise DomainError("Unsupported local model artifact. Retrain.", 409)
    for name in [result["artifact"], "preprocessing.json", "holdout.parquet"]:
        path = folder / name
        if not path.is_file() or sha256(path) != result["hashes"].get(name):
            raise DomainError(
                "Model evidence checksum failed. Retrain from the selected dataset.", 409
            )
    versions = dependency_versions()
    if any(versions[key] != value for key, value in result["versions"].items()):
        raise DomainError("Model library versions changed. Retrain before inference.", 409)
    if result["algorithm"] == "XGBoost":
        from xgboost import XGBRegressor

        model = XGBRegressor(n_jobs=2)
        model.load_model(folder / "model.ubj")
    else:
        model = joblib.load(folder / "model.joblib")
    categories = json.loads((folder / "preprocessing.json").read_text())["categories"]
    example = pd.DataFrame(
        [
            {
                key: values[0]
                for key, values in zip(
                    ["platform", "age", "gender", "city", "device"], categories, strict=True
                )
            }
            | {"date": "2026-01-01", "spend": 1}
        ]
    )
    encoder = encoder_for(example, categories)
    return job, model, encoder


def predict_frame(model, encoder, frame):
    result = np.maximum(0, model.predict(transform(frame, encoder)))
    if not np.isfinite(result).all():
        raise DomainError("The model produced non-finite values. Retrain.", 409)
    return result


def predict(repo, store, model_id, request):
    job = store.published(model_id)
    dataset = repo.get(job["config"]["dataset_id"])
    if not repo.selected() or repo.selected().id != dataset.id:
        raise DomainError("Select the model's source dataset before predicting.", 409)
    if provenance_review(dataset):
        raise DomainError(provenance_review(dataset)[0], 409)
    result = job["result"]
    source = repo.root / "datasets" / dataset.id / "campaigns.parquet"
    if job.get("input_sha256") != sha256(source):
        raise DomainError("Model input checksum differs from this source. Retrain.", 409)
    if not result["acceptance"]["eligible"]:
        raise DomainError(
            "This model failed acceptance checks. View diagnostics or train again.", 409
        )
    decision_date = max(result["splits"]["test"]["end"], job["config"]["as_of_date"])
    if request.date.isoformat() <= decision_date:
        raise DomainError(
            "Choose a prediction date after the historical period and label as-of date."
        )
    if (
        dataset.date_granularity == "weekly"
        and request.date.weekday() != date.fromisoformat(dataset.date_start).weekday()
    ):
        raise DomainError("Choose the same week-start day as the historical weekly report.")
    bounds = result["spend_ranges"].get(request.platform)
    if not bounds or not bounds["min"] <= request.spend <= bounds["max"]:
        raise DomainError(
            "Planned campaign-period spend is outside this platform's training range."
        )
    for key, categories in zip(
        ["platform", "age", "gender", "city", "device"], result["categories"], strict=True
    ):
        if getattr(request, key) not in categories:
            raise DomainError(f"Choose a {key} value observed in the training period.")
    job, model, encoder = load_model(store, model_id)
    frame = pd.DataFrame([request.model_dump(mode="json")])
    return {
        "model_id": model_id,
        "dataset_id": dataset.id,
        "predicted_revenue": float(predict_frame(model, encoder, frame)[0]),
        "currency": "PKR",
        "is_synthetic": dataset.is_synthetic,
        "uncertainty": "Not quantified",
        "notice": "Simulated estimate — not a real-world revenue guarantee"
        if dataset.is_synthetic
        else "Model estimate; observational data does not prove causal uplift.",
        "grain": result["grain"],
    }


def reevaluate(repo, store, model_id):
    job = store.published(model_id)
    repo.get(job["config"]["dataset_id"])
    if not repo.selected() or repo.selected().id != job["config"]["dataset_id"]:
        raise DomainError("Select the source dataset before evaluating this model.", 409)
    job, model, encoder = load_model(store, model_id)
    frame = pd.read_parquet(store.root / job["id"] / "holdout.parquet")
    return {
        "model_id": model_id,
        "test": evaluate(frame, predict_frame(model, encoder, frame), job["result"]["baseline"]),
        "notice": "Re-evaluated the same sealed holdout; no fitting or parameter changes.",
    }
