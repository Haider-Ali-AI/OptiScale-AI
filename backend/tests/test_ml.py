import asyncio
import time
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from ads_optimizer.api import app
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import DomainError, GenerateConfig
from ads_optimizer.ml.contracts import Prediction, TrainingConfig
from ads_optimizer.ml.evaluate import baseline_predict, fit_baseline, metrics
from ads_optimizer.ml.features import FEATURES, context, encoder_for, transform
from ads_optimizer.ml.infer import load_model, predict, predict_frame, reevaluate
from ads_optimizer.ml.service import prepare, readiness, sha256, start_training
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.ml.train import Stopped, acceptance, fit_model, train
from ads_optimizer.ml.worker import run
from httpx import ASGITransport, AsyncClient


def save(repo, rows=1000, seed=42, real=False):
    frame, _ = generate_frame(GenerateConfig(rows=rows, seed=seed))
    manifest = repo.save(
        frame,
        {
            "name": "ML fixture",
            "source": "advertiser_csv" if real else "synthetic_generator",
            "is_synthetic": not real,
            "revenue_source": "ad_platform_reported" if real else "synthetic",
            "data_ready_for_revenue": True,
            "warnings": [],
            "conversion_definition": "purchases",
            "attribution_window": "7-day click",
        },
    )
    return manifest, frame


def config(manifest, **changes):
    return TrainingConfig(dataset_id=manifest.id, as_of_date=date(2026, 10, 28), **changes)


def build(repo):
    manifest, _ = save(repo, rows=1000)
    cfg = config(manifest)
    _, _, parts, coverage = prepare(repo, cfg)
    store = ModelStore(repo.root)
    job = store.create(cfg, manifest)
    folder = store.root / job["id"]
    result = train(parts, coverage, manifest, cfg, folder, lambda: None, lambda *_: None)
    parts[2].to_parquet(folder / "holdout.parquet", index=False)
    result["hashes"]["holdout.parquet"] = sha256(folder / "holdout.parquet")
    store.update(
        job["id"],
        status="succeeded",
        result=result,
        input_sha256=sha256(repo.root / "datasets" / manifest.id / "campaigns.parquet"),
    )
    return manifest, store, job["id"], parts, result


def test_features_never_read_same_period_outcomes_or_truth(isolated_repository):
    _, frame = save(isolated_repository)
    before = context(frame)
    for key in ["clicks", "conversions", "revenue", "impressions", "roas", "simulation_truth"]:
        frame[key] = 999999
    pd.testing.assert_frame_equal(before, context(frame))
    assert not set(FEATURES) & {"revenue", "clicks", "conversions", "campaign"}


def test_complete_dates_and_maturity_with_real_definitions(isolated_repository):
    manifest, _ = save(isolated_repository, real=True)
    _, _, parts, coverage = prepare(
        isolated_repository,
        TrainingConfig(dataset_id=manifest.id, as_of_date=date(2026, 3, 31), label_lag_days=14),
    )
    assert parts[0].date.max() < parts[1].date.min() < parts[2].date.min()
    assert parts[1].date.max() < parts[2].date.min()
    assert parts[2].date.max() <= "2026-03-17"
    assert coverage["excluded_rows"] > 0


def test_encoder_uses_train_only_categories():
    frame, _ = generate_frame(GenerateConfig(rows=1000))
    training = frame.iloc[:600]
    future = frame.iloc[600:].copy()
    future["city"] = "Future-only city"
    encoder = encoder_for(training)
    assert "Future-only city" not in encoder.categories_[3]
    assert np.isfinite(transform(future, encoder)).all()


def test_readiness_small_missing_or_constant_report(isolated_repository):
    manifest, _ = save(isolated_repository, rows=100)
    assert not readiness(isolated_repository, config(manifest))["ready"]
    manifest2, frame = save(isolated_repository, seed=43)
    frame["spend"] = 1
    with pytest.raises(DomainError, match="distinct spends"):
        prepare(isolated_repository, config(manifest2), input_frame=frame)
    frame["revenue"] = np.nan
    with pytest.raises(DomainError):
        prepare(isolated_repository, config(manifest2), input_frame=frame)


def test_hand_calculated_baseline_and_zero_error_denominator():
    frame = pd.DataFrame(
        {"platform": ["Google", "Google"], "spend": [10.0, 20.0], "revenue": [30.0, 60.0]}
    )
    baseline = fit_baseline(frame)
    assert baseline["global_rate"] == 3
    np.testing.assert_allclose(baseline_predict(frame, baseline), [30, 60])
    score = metrics([0, 0], [1, 1])
    assert score == {"rows": 2, "mae": 1.0, "rmse": 1.0, "wape": None, "r2": None}
    assert metrics([10, 20], [8, 24])["wape"] == 0.2


def test_native_model_round_trip_and_sealed_evaluation(isolated_repository):
    manifest, store, model_id, parts, result = build(isolated_repository)
    assert result["algorithm"] == "XGBoost"
    assert result["versions"]["xgboost"]
    assert result["splits"]["train"]["end"] < result["splits"]["test"]["start"]
    job, model, encoder = load_model(store, model_id)
    measured = metrics(parts[2].revenue, predict_frame(model, encoder, parts[2]))
    assert measured == result["test"]["model"]
    assert reevaluate(isolated_repository, store, model_id)["test"] == result["test"]
    # Inference eligibility is intentionally independent of successful fitting.
    assert job["status"] == "succeeded"
    assert not result["recommendations_enabled"]
    assert job["dataset"]["id"] == manifest.id


def test_test_labels_do_not_select_or_change_model(isolated_repository, tmp_path):
    manifest, _ = save(isolated_repository)
    cfg = config(manifest)
    _, _, parts, coverage = prepare(isolated_repository, cfg)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    a = train(parts, coverage, manifest, cfg, first, lambda: None, lambda *_: None)
    changed = [p.copy() for p in parts]
    changed[2]["revenue"] *= 100
    b = train(changed, coverage, manifest, cfg, second, lambda: None, lambda *_: None)
    assert sha256(first / "model.ubj") == sha256(second / "model.ubj")
    assert a["parameters"] == b["parameters"]
    assert a["test"]["model"] != b["test"]["model"]


def test_corrupt_artifact_is_rejected(isolated_repository):
    _, store, model_id, _, result = build(isolated_repository)
    (store.root / model_id / result["artifact"]).write_bytes(b"corrupted")
    with pytest.raises(DomainError, match="checksum"):
        load_model(store, model_id)


def test_prediction_gates_source_range_context_and_date(isolated_repository):
    manifest, store, model_id, _, result = build(isolated_repository)
    # Test the inference contract separately from the measured acceptance result.
    result["acceptance"] = {"eligible": True, "reasons": [], "policy": "test contract"}
    store.update(model_id, result=result)
    platform = next(iter(result["spend_ranges"]))
    bounds = result["spend_ranges"][platform]
    kwargs = {
        "date": date(2026, 10, 29),
        "platform": platform,
        "spend": (bounds["min"] + bounds["max"]) / 2,
        **{
            key: values[0]
            for key, values in zip(
                ["age", "gender", "city", "device"], result["categories"][1:], strict=True
            )
        },
    }
    request = Prediction(**kwargs)
    assert predict(isolated_repository, store, model_id, request)["predicted_revenue"] >= 0
    with pytest.raises(DomainError, match="outside"):
        predict(isolated_repository, store, model_id, request.model_copy(update={"spend": 1e9}))
    with pytest.raises(DomainError, match="after"):
        predict(
            isolated_repository,
            store,
            model_id,
            request.model_copy(update={"date": date(2026, 1, 1)}),
        )
    with pytest.raises(DomainError, match="city"):
        predict(isolated_repository, store, model_id, request.model_copy(update={"city": "unseen"}))
    save(isolated_repository, seed=43)
    with pytest.raises(DomainError, match="source dataset"):
        predict(isolated_repository, store, model_id, request)
    isolated_repository.select(manifest.id)
    result["acceptance"]["eligible"] = False
    store.update(model_id, result=result)
    with pytest.raises(DomainError, match="failed acceptance"):
        predict(isolated_repository, store, model_id, request)


def test_fallback_and_cancel_during_fit(isolated_repository, tmp_path):
    manifest, _ = save(isolated_repository)
    _, _, parts, _ = prepare(isolated_repository, config(manifest))
    with patch.dict("sys.modules", {"xgboost": None}):
        _, _, info = fit_model(parts[0], parts[1], tmp_path, 42, lambda: None)
        assert info["algorithm"] == "HistGradientBoostingRegressor"

    def stop():
        raise Stopped()

    with pytest.raises(Stopped):
        fit_model(parts[0], parts[1], tmp_path, 42, stop)


def test_acceptance_does_not_force_bad_model_or_zero_revenue(isolated_repository):
    manifest, _ = save(isolated_repository)
    _, _, parts, _ = prepare(isolated_repository, config(manifest))
    result = {
        "model": {"rmse": 100, "wape": None, "r2": None},
        "baseline": {"rmse": 10},
        "platforms": [
            {"platform": p, "model": {"rmse": 100}, "baseline": {"rmse": 10}}
            for p in parts[2].platform.unique()
        ],
    }
    assert not acceptance(result, result, parts)["eligible"]


def test_worker_cancel_and_persistent_one_job_guard(isolated_repository):
    manifest, frame = save(isolated_repository)
    store = ModelStore(isolated_repository.root)
    cfg = config(manifest)
    job = store.create(cfg, manifest)
    with pytest.raises(DomainError, match="already training"):
        store.create(cfg, manifest)
    folder = store.root / job["id"]
    frame.to_parquet(folder / "input.parquet")
    store.update(job["id"], input_sha256=sha256(folder / "input.parquet"), cancel_requested=True)
    run(isolated_repository.root, job["id"])
    assert ModelStore(isolated_repository.root).get(job["id"])["status"] == "cancelled"
    assert not (folder / "input.parquet").exists()
    assert not (folder / "model.ubj").exists()


def test_real_background_job_publishes_and_recovers(isolated_repository):
    manifest, _ = save(isolated_repository)
    job = start_training(isolated_repository, config(manifest))
    store = ModelStore(isolated_repository.root)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        final = store.get(job["id"])
        if final["status"] in {"succeeded", "failed", "interrupted"}:
            break
        time.sleep(0.1)
    assert final["status"] == "succeeded", final
    assert final["result"]["test"]["model"]["rows"] > 0
    assert not (store.root / job["id"] / "input.parquet").exists()
    cfg = config(manifest)
    stale = store.create(cfg, manifest)
    store.update(stale["id"], worker_pid=999999999)
    assert store.jobs()[0]["status"] == "interrupted"


def test_ml_api_readiness_selected_boundary_and_export(isolated_repository):
    manifest, _ = save(isolated_repository)

    async def journey():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ml/readiness", json=config(manifest).model_dump(mode="json")
            )
            assert response.status_code == 200
            assert response.json()["ready"]
            assert (await client.get("/api/v1/ml")).json()["jobs"] == []
            await client.put("/api/v1/workspace/dataset", json={"dataset_id": None})
            response = await client.post(
                "/api/v1/ml/jobs", json=config(manifest).model_dump(mode="json")
            )
            assert response.status_code == 409
            response = await client.get("/api/v1/ml/jobs/../../private/export")
            assert response.status_code == 404

    asyncio.run(journey())


def test_source_deletion_blocks_active_training_and_purges_completed_models(isolated_repository):
    manifest, store, model_id, _, _ = build(isolated_repository)
    pending = store.create(config(manifest), manifest)
    with pytest.raises(DomainError, match="training before deleting"):
        isolated_repository.delete(manifest.id)
    store.update(pending["id"], status="cancelled")
    isolated_repository.delete(manifest.id)
    assert not (store.root / model_id).exists()
    assert store.jobs() == []


def test_atomic_publication_honors_late_cancel(isolated_repository):
    manifest, _ = save(isolated_repository)
    store = ModelStore(isolated_repository.root)
    job = store.create(config(manifest), manifest)
    store.update(job["id"], cancel_requested=True)
    final = store.complete(job["id"], {"test": "should never publish"})
    assert final["status"] == "cancelled"
    assert final["result"] is None


def test_live_worker_cancel_never_publishes_partial_model(isolated_repository):
    from ads_optimizer.ml.service import cancel_training

    manifest, _ = save(isolated_repository, rows=10000)
    store = ModelStore(isolated_repository.root)
    job = start_training(isolated_repository, config(manifest))
    cancel_training(store, job["id"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        final = store.get(job["id"])
        if final["status"] in {"cancelled", "failed", "succeeded"}:
            break
        time.sleep(0.1)
    assert final["status"] == "cancelled", final
    assert final["result"] is None
    with pytest.raises(DomainError, match="no completed model"):
        store.published(job["id"])


def test_complete_financials_with_unknown_definitions_explain_actual_blocker(isolated_repository):
    frame, _ = generate_frame(GenerateConfig(rows=1000))
    manifest = isolated_repository.save(
        frame,
        {
            "name": "Unspecified reporting definitions",
            "source": "advertiser_csv",
            "is_synthetic": False,
            "revenue_source": "ad_platform_reported",
            "data_ready_for_revenue": False,
            "warnings": [],
            "conversion_definition": "unspecified",
            "attribution_window": "unspecified",
        },
    )
    result = readiness(isolated_repository, config(manifest))
    assert not result["ready"]
    assert "Financial columns are complete" in result["reasons"][0]
    assert "conversion definition or attribution window is unspecified" in result["reasons"][0]


def test_missing_financial_readiness_names_only_incomplete_columns(isolated_repository):
    frame, _ = generate_frame(GenerateConfig(rows=1000))
    frame["revenue"] = np.nan
    manifest = isolated_repository.save(
        frame,
        {
            "name": "Missing revenue",
            "source": "advertiser_csv",
            "is_synthetic": False,
            "revenue_source": "ad_platform_reported",
            "data_ready_for_revenue": False,
            "warnings": [],
            "conversion_definition": "purchases",
            "attribution_window": "7-day click",
        },
    )
    result = readiness(isolated_repository, config(manifest))
    assert not result["ready"]
    assert "complete values for: revenue." in result["reasons"][0]
    assert "spend" not in result["reasons"][0]
    assert "conversions" not in result["reasons"][0]
