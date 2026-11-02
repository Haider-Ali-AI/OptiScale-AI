"""Uploaded, explicitly synthetic regression fixtures; no merchant-accuracy claims."""

import asyncio
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ads_optimizer.api import app
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.infer import load_model
from ads_optimizer.ml.service import sha256
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.optimization.allocate import allocate_cents, comparison_cents, concave_minorant
from ads_optimizer.optimization.contracts import PlanConfig
from ads_optimizer.optimization.service import create_plan
from httpx import ASGITransport, AsyncClient


def daily_csv():
    rng = np.random.default_rng(712)
    rows = []
    for day in pd.date_range("2026-01-01", periods=100):
        for i, platform in enumerate(
            ["Facebook", "Instagram", "Google Ads", "TikTok Ads", "YouTube"]
        ):
            spend = round(float(np.exp(rng.uniform(np.log(100), np.log(100000)))), 2)
            revenue = round((1 + 0.15 * i) * 200000 * spend / (20000 + spend), 2)
            rows.append(
                {
                    "Date Recorded": day.strftime("%Y-%m-%d"),
                    "Campaign Name": f"Synthetic {platform}",
                    "Ad Platform": platform,
                    "Amount Spent": f"PKR {spend:,.2f}",
                    "Sales Revenue": revenue,
                    "conversion_definition": "purchases",
                    "attribution_window": "7-day click",
                    "is_synthetic": "true",
                }
            )
    return pd.DataFrame(rows).to_csv(index=False)


def test_uploaded_csv_to_trained_model_and_changed_budgets(isolated_repository):
    repo = isolated_repository

    async def journey():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/imports/preview?filename=daily.csv&profile=generic",
                content=daily_csv(),
                headers={"Content-Type": "text/csv"},
            )
            assert response.status_code == 200, response.text
            preview = response.json()
            options = {
                "name": "Synthetic budget regression",
                "mapping": preview["suggested_mapping"],
                "confirmed": True,
            }
            valid = await client.post(f"/api/v1/imports/{preview['token']}/validate", json=options)
            assert valid.json()["can_import"], valid.text
            response = await client.post(f"/api/v1/imports/{preview['token']}/commit", json=options)
            assert response.status_code == 201, response.text
            dataset = response.json()
            assert dataset["rows"] == 500 and dataset["coverage"]["conversions"] == 0
            response = await client.post(
                "/api/v1/ml/jobs", json={"dataset_id": dataset["id"], "as_of_date": "2026-10-29"}
            )
            assert response.status_code == 202, response.text
            model_id = response.json()["id"]
            store = ModelStore(repo.root)
            for _ in range(300):
                job = store.get(model_id)
                if job["status"] in {"succeeded", "failed", "interrupted"}:
                    break
                await asyncio.sleep(0.1)
            assert job["status"] == "succeeded", job
            assert job["result"]["algorithm"] == "XGBoost"
            assert job["result"]["acceptance"]["eligible"], job["result"]["acceptance"]
            assert job["dataset"]["id"] == dataset["id"]
            artifact = store.root / model_id / job["result"]["artifact"]
            original_hash = sha256(artifact)
            revenues, ids, allocations = [], [], []
            for budget in [10_000, 50_000, 100_000, 1_000_000, 54_321.87]:
                cfg = {
                    "dataset_id": dataset["id"],
                    "model_id": model_id,
                    "budget": budget,
                    "start_date": "2026-10-30",
                }
                response = await client.post("/api/v1/optimizer/plans", json=cfg)
                assert response.status_code == 201, response.text
                report = response.json()
                assert report["config"]["budget"] == budget
                assert sum(Decimal(str(row["budget"])) for row in report["allocations"]) == Decimal(
                    str(budget)
                )
                assert report["prediction_rows"] > 0
                for row in report["allocations"]:
                    assert row["effective_min"] <= row["budget"] <= row["effective_max"]
                    assert row["budget"] >= budget * row["requested_min_percent"] / 100 - 1e-7
                    assert row["budget"] <= budget * row["requested_max_percent"] / 100 + 1e-7
                revenues.append(report["totals"]["estimated_revenue"])
                ids.append(report["id"])
                allocations.append([row["budget"] for row in report["allocations"]])
            assert len(set(revenues)) == 5 and len(set(ids)) == 5
            assert allocations[0] != allocations[1]
            assert sha256(artifact) == original_hash and len(store.jobs()) == 1
            # Same fitted artifact loads with the exact preprocessing schema.
            load_model(store, model_id)
            result = job["result"]
            result["features"] = ["revenue"]
            store.update(model_id, result=result)
            with pytest.raises(DomainError, match="feature schema"):
                load_model(store, model_id)

    asyncio.run(journey())


def test_cent_allocator_matches_exhaustive_nonuniform_grid():
    import itertools

    curves = {}
    for platform, raw in [("a", [2, 9, 12]), ("b", [1, 10, 14]), ("c", [3, 8, 16])]:
        points = np.array([1, 3, 8])
        curves[platform] = {
            "points": points,
            "lower_units": 1,
            "upper_units": 8,
            "adjusted": concave_minorant(raw, points),
        }
    for budget in range(3, 25):
        allocation = allocate_cents(curves, budget)

        def score(amounts):
            return sum(
                np.interp(amounts[p], curves[p]["points"], curves[p]["adjusted"]) for p in curves
            )

        best = max(
            score(dict(zip(curves, values, strict=True)))
            for values in itertools.product(range(1, 9), repeat=3)
            if sum(values) == budget
        )
        assert score(allocation) == pytest.approx(best)
        comparison = comparison_cents(curves, budget, {"a": 7, "b": 1, "c": 1})
        assert sum(comparison.values()) == budget
        assert all(1 <= v <= 8 for v in comparison.values())


def test_unsafe_budget_and_missing_budget_rejected():
    from pydantic import ValidationError

    cfg = {"dataset_id": "x", "method": "historical", "start_date": "2026-10-30"}
    for value in [None, 0, -1, 0.001, float("inf"), float("nan"), 100_000_001]:
        with pytest.raises(ValidationError):
            PlanConfig.model_validate({**cfg, "budget": value})
    with pytest.raises(ValidationError):
        PlanConfig.model_validate(cfg)
    assert PlanConfig.model_validate({**cfg, "budget": 0.01}).budget_cents == 1


def test_historical_missing_revenue_and_small_samples(isolated_repository):
    from test_ml import save
    from test_optimization import plan_config

    source, _ = save(isolated_repository, rows=100)
    # A small supported history can offer a disclosed heuristic, never an ML badge.
    report = create_plan(isolated_repository, plan_config(source, budget=50_000))
    assert report["model_id"] is None and report["prediction_rows"] == 0
    with isolated_repository.connect() as conn:
        missing = source.model_copy(update={"coverage": {**source.coverage, "revenue": 0}})
        conn.execute(
            "UPDATE datasets SET manifest=? WHERE id=?", (missing.model_dump_json(), source.id)
        )
    missing = create_plan(isolated_repository, plan_config(source, budget=50_000))
    assert missing["totals"]["estimated_revenue"] is None


if __name__ == "__main__":
    Path("backend/tests/fixtures/daily_budget_training.csv").write_text(daily_csv())
