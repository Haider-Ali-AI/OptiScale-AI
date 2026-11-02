import asyncio
import itertools
from datetime import date

import numpy as np
import pytest
from ads_optimizer.api import app
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.service import prepare, sha256
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.ml.train import train
from ads_optimizer.optimization.allocate import (
    comparison_allocation,
    concave_minorant,
    greedy,
)
from ads_optimizer.optimization.contracts import PlanConfig, PlatformLimit
from ads_optimizer.optimization.service import (
    create_plan,
    effective_limits,
    export_plan,
    get_plan,
    representative_contexts,
    score_allocation,
)
from ads_optimizer.optimization.store import PlanStore
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from test_ml import config, save


def saved_model(repo):
    source, _ = save(repo, rows=10_000)
    cfg = config(source)
    _, _, parts, coverage = prepare(repo, cfg)
    store = ModelStore(repo.root)
    job = store.create(cfg, source)
    folder = store.root / job["id"]
    result = train(parts, coverage, source, cfg, folder, lambda: None, lambda *_: None)
    parts[2].to_parquet(folder / "holdout.parquet", index=False)
    result["hashes"]["holdout.parquet"] = sha256(folder / "holdout.parquet")
    store.update(
        job["id"],
        status="succeeded",
        result=result,
        input_sha256=sha256(repo.root / "datasets" / source.id / "campaigns.parquet"),
    )
    assert result["acceptance"]["eligible"], result["acceptance"]
    return source, store, job["id"]


def plan_config(source, model_id=None, **changes):
    changes.setdefault("budget", 1_000_000)
    return PlanConfig(
        dataset_id=source.id,
        method="model" if model_id else "historical",
        model_id=model_id,
        start_date=date(2026, 10, 29),
        as_of_date=date(2026, 10, 28),
        **changes,
    )


@pytest.mark.parametrize("raw", [[30], [0, 1, 4, 9], [30, 20, 40, 60], [0, 0, 0], [5, 20, 21, 50]])
def test_shape_policy_is_finite_conservative_monotone_and_concave(raw):
    shaped = concave_minorant(raw)
    assert np.isfinite(shaped).all()
    assert (shaped >= 0).all()
    assert (shaped <= np.array(raw) + 1e-7).all()
    assert (np.diff(shaped) >= -1e-7).all()
    assert (np.diff(shaped, n=2) <= 1e-7).all()


def test_greedy_matches_exhaustive_search_on_small_concave_grids():
    rng = np.random.default_rng(82)
    for _ in range(30):
        curves = {
            p: {
                "lower_units": 1,
                "upper_units": 5,
                "adjusted": np.r_[rng.uniform(1, 5), 0, 0, 0, 0],
            }
            for p in ["a", "b", "c"]
        }
        for c in curves.values():
            c["adjusted"][1:] = c["adjusted"][0] + np.cumsum(np.sort(rng.uniform(0, 20, 4))[::-1])
        score = lambda a: sum(curves[p]["adjusted"][a[p] - 1] for p in curves)  # noqa: E731
        got = greedy(curves, 9)
        best = max(
            score(dict(zip(curves, choice, strict=True)))
            for choice in itertools.product(range(1, 6), repeat=3)
            if sum(choice) == 9
        )
        assert sum(got.values()) == 9
        assert score(got) == pytest.approx(best)
        for weights in [{"a": 1, "b": 1, "c": 1}, {"a": 8, "b": 1, "c": 1}]:
            other = comparison_allocation(curves, 9, weights)
            assert sum(other.values()) == 9
            assert all(1 <= n <= 5 for n in other.values())
            assert score(got) >= score(other) - 1e-8


@pytest.mark.parametrize(
    "changes",
    [
        {"budget": 0},
        {"budget": -1},
        {"budget": 1.005},
        {"platforms": [PlatformLimit(platform="Google", max_percent=40)]},
        {"platforms": [PlatformLimit(platform="Google", max_percent=100)] * 2},
        {"method": "model", "model_id": None},
        {"horizon_days": 31},
    ],
)
def test_invalid_constraints_are_rejected_before_computation(changes):
    with pytest.raises(ValidationError):
        PlanConfig.model_validate(
            {
                "dataset_id": "test",
                "budget": 50_000,
                "method": "historical",
                "start_date": "2026-10-29",
                **changes,
            }
        )


def test_percentage_rounding_and_supported_grid_gates():
    cfg = PlanConfig(
        dataset_id="test",
        method="historical",
        start_date=date(2026, 10, 29),
        budget=110_000,
        step=10_000,
        platforms=[
            PlatformLimit(platform=p, min_percent=5, max_percent=60) for p in ["Google", "Facebook"]
        ],
    )
    contexts = {
        p: {"supported_min": 13_001, "supported_max": 69_999} for p in ["Google", "Facebook"]
    }
    limits = effective_limits(cfg, contexts)
    assert all(
        c["lower_units"] == 550_000 and c["upper_units"] == 6_600_000 for c in limits.values()
    )
    contexts["Google"]["supported_min"] = 90_000
    assert effective_limits(cfg, contexts) == limits  # historical support is not feasibility


def test_displayed_percentages_total_100_with_indivisible_shares():
    cfg = PlanConfig(
        dataset_id="fixture",
        method="historical",
        start_date=date(2026, 10, 29),
        budget=700,
        step=100,
    )
    curves = {
        p: {
            "lower_units": 0,
            "upper_units": 70_000,
            "points": np.arange(8) * 10_000,
            "requested_min_percent": 0,
            "requested_max_percent": 100,
            "raw": np.arange(8),
            "adjusted": np.arange(8),
        }
        for p in ["Facebook", "Google", "TikTok"]
    }
    report = score_allocation({"Facebook": 20_000, "Google": 20_000, "TikTok": 30_000}, curves, cfg)
    assert sum(round(a["share_percent"] * 100) for a in report["allocations"]) == 10_000
    assert report["budget"] == 700
    assert sorted(a["share_percent"] for a in report["allocations"]) == [28.57, 28.57, 42.86]


def test_context_policy_is_train_only_and_repeats_exact_spending_weights(isolated_repository):
    source, _ = save(isolated_repository, rows=10_000)
    _, _, parts, _ = prepare(isolated_repository, config(source))
    training = parts[0]
    a = representative_contexts(training, ["Google"], 7)["Google"]
    training["revenue"] = 999999999
    b = representative_contexts(training, ["Google"], 7)["Google"]
    assert a["date"] == b["date"] <= parts[0].date.max() < parts[1].date.min()
    np.testing.assert_array_equal(a["weights"], b["weights"])
    assert a["weights"].sum() == pytest.approx(1)
    for budget in [a["supported_min"], a["supported_max"]]:
        spends = a["weights"] * budget / 7
        assert spends.min() >= a["row_spend_min"] - 1e-8
        assert spends.max() <= a["row_spend_max"] + 1e-8
        assert spends.sum() * 7 == pytest.approx(budget)


def test_actual_model_plan_default_exact_total_and_persisted_evidence(isolated_repository):
    source, store, model_id = saved_model(isolated_repository)
    cfg = plan_config(source, model_id)
    original_model_result = store.get(model_id)["result"]
    report = create_plan(isolated_repository, cfg)
    assert report["totals"]["budget"] == 1_000_000
    assert report["model_id"] == model_id
    assert report["prediction_rows"] > 0
    assert report["training_controls"]["label_lag_days"] == 0
    assert report["is_synthetic"] and "Simulated" in report["notice"]
    assert sum(r["share_percent"] for r in report["allocations"]) == pytest.approx(100)
    for row in report["allocations"]:
        assert row["effective_min"] <= row["budget"] <= row["effective_max"]
        assert round(row["budget"] * 100) == pytest.approx(row["budget"] * 100)
        assert row["estimated_revenue"] <= row["raw_estimated_revenue"] + 1e-6
    for other in report["comparisons"]:
        assert other["budget"] == 1_000_000
        assert other["estimated_difference"] >= -1e-6
    assert get_plan(isolated_repository, report["id"]) == report
    assert PlanStore(isolated_repository.root).list(source.id)[0]["id"] == report["id"]
    assert "source_sha256" in export_plan(report, "json")
    assert "is_synthetic" in export_plan(report, "csv")
    assert "Simulated" in export_plan(report, "csv")
    assert store.get(model_id)["result"] == original_model_result
    # Source removal cascades to both plans and model artifacts.
    isolated_repository.delete(source.id)
    with pytest.raises(DomainError):
        PlanStore(isolated_repository.root).get(report["id"])
    assert not (store.root / model_id).exists()


def test_explicit_historical_rule_never_claims_ml_and_is_repeatable(isolated_repository):
    source, _ = save(isolated_repository, rows=10_000)
    first = create_plan(isolated_repository, plan_config(source))
    second = create_plan(isolated_repository, plan_config(source))
    assert first["allocations"] == second["allocations"]
    assert first["totals"] == second["totals"]
    assert first["model_id"] is None and first["model_evidence"] is None
    assert first["prediction_rows"] == 0
    assert "no ML" in first["method_label"]


def test_failed_model_corrupt_evidence_mismatched_source_and_date_stay_blocked(isolated_repository):
    repo = isolated_repository
    source, store, model_id = saved_model(repo)
    cfg = plan_config(source, model_id)
    with pytest.raises(DomainError, match="after"):
        create_plan(repo, cfg.model_copy(update={"start_date": date(2026, 10, 28)}))
    distant = create_plan(repo, cfg.model_copy(update={"start_date": date(2027, 5, 1)}))
    assert distant["forecast_status"] == "unavailable"
    result = store.get(model_id)["result"]
    result["acceptance"]["eligible"] = False
    store.update(model_id, result=result)
    with pytest.raises(DomainError, match="failed acceptance"):
        create_plan(repo, cfg)
    result["acceptance"]["eligible"] = True
    store.update(model_id, result=result)
    other, _ = save(repo, rows=10_000, seed=43)
    with pytest.raises(DomainError, match="source dataset"):
        create_plan(repo, cfg)
    with pytest.raises(DomainError, match="selected dataset"):
        create_plan(repo, cfg.model_copy(update={"dataset_id": other.id}))
    repo.select(source.id)
    store.update(model_id, input_sha256="bad-hash")
    with pytest.raises(DomainError, match="input checksum"):
        create_plan(repo, cfg)
    store.update(
        model_id, input_sha256=sha256(repo.root / "datasets" / source.id / "campaigns.parquet")
    )
    (store.root / model_id / "model.ubj").write_bytes(b"corrupt")
    with pytest.raises(DomainError, match="evidence checksum"):
        create_plan(repo, cfg)
    assert all(
        p["totals"]["estimated_revenue"] is None for p in PlanStore(repo.root).list(source.id)
    )


def test_missing_definitions_and_insufficient_history_do_not_enable_heuristic(isolated_repository):
    source, _ = save(isolated_repository, rows=100)
    small = create_plan(isolated_repository, plan_config(source, budget=50_000))
    assert small["model_id"] is None and "no ML" in small["method_label"]
    source, _ = save(isolated_repository, rows=10_000, seed=43)
    with isolated_repository.connect() as conn:
        manifest = source.model_copy(update={"attribution_window": "unspecified"})
        conn.execute(
            "UPDATE datasets SET manifest=? WHERE id=?", (manifest.model_dump_json(), source.id)
        )
    plan = create_plan(isolated_repository, plan_config(source))
    assert plan["forecast_status"] == "unavailable"
    assert any("unspecified" in reason for reason in plan["forecast_reasons"])


def test_huge_context_and_infeasible_spend_support_fail_without_saving(isolated_repository):
    source, _ = save(isolated_repository, rows=10_000)
    cfg = plan_config(source, budget=100_000_000, step=1_000_000)
    plan = create_plan(isolated_repository, cfg)
    assert plan["totals"]["budget"] == cfg.budget
    assert plan["totals"]["estimated_revenue"] is None


def test_prediction_work_limit_blocks_before_model_loading_or_publication(
    isolated_repository, monkeypatch
):
    source, _, model_id = saved_model(isolated_repository)
    monkeypatch.setattr("ads_optimizer.optimization.service.MAX_PREDICTION_ROWS", 1)
    with pytest.raises(DomainError, match="200,000"):
        create_plan(isolated_repository, plan_config(source, model_id))


def test_optimizer_http_history_source_boundary_and_exports(isolated_repository):
    source, _ = save(isolated_repository, rows=10_000)

    async def journey():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cfg = plan_config(source).model_dump(mode="json")
            response = await client.post("/api/v1/optimizer/plans", json=cfg)
            assert response.status_code == 201, response.text
            report = response.json()
            saved = (await client.get("/api/v1/optimizer")).json()
            assert saved["plans"][0]["id"] == report["id"]
            for fmt in ["csv", "json"]:
                export = await client.get(
                    f"/api/v1/optimizer/plans/{report['id']}/export?format={fmt}"
                )
                assert export.status_code == 200
                assert "attachment" in export.headers["content-disposition"]
                assert export.headers["cache-control"] == "no-store"
            assert (
                await client.post("/api/v1/optimizer/plans", json={**cfg, "budget": 0})
            ).status_code == 422
            isolated_repository.select(None)
            assert (await client.get(f"/api/v1/optimizer/plans/{report['id']}")).status_code == 409
            assert (await client.get("/api/v1/optimizer")).json()["plans"] == []

    asyncio.run(journey())
