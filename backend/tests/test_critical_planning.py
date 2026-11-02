"""Regression coverage for feasibility, forecast selection and synthetic provenance."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ads_optimizer.data.csv_importer import commit_import, stage_csv, validate_import
from ads_optimizer.data.provenance import provenance_review
from ads_optimizer.domain import DomainError, ImportOptions
from ads_optimizer.ml.baseline import assess_baseline
from ads_optimizer.ml.contracts import TrainingConfig
from ads_optimizer.ml.features import chronological_split
from ads_optimizer.ml.service import prepare
from ads_optimizer.optimization.contracts import PlanConfig, PlatformLimit
from ads_optimizer.optimization.service import (
    create_plan,
    effective_limits,
    representative_contexts,
)
from test_ml import save
from test_optimization import saved_model


def cfg(source, budget, **changes):
    return PlanConfig(
        dataset_id=source.id,
        budget=budget,
        start_date=date(2026, 10, 30),
        as_of_date=date(2026, 10, 29),
        **changes,
    )


def exact(report, budget):
    assert sum(Decimal(str(row["budget"])) for row in report["allocations"]) == Decimal(str(budget))
    assert all(row["budget"] >= 0 for row in report["allocations"])
    assert sum(round(row["share_percent"] * 100) for row in report["allocations"]) == 10000


@pytest.mark.parametrize("budget", [500, 5000, 10000, 25000, 100000, 1000000, 5432.19])
def test_all_user_budgets_feasible_independent_of_historical_scale(isolated_repository, budget):
    source, _ = save(isolated_repository, rows=10000)
    report = create_plan(isolated_repository, cfg(source, budget, horizon_days=13))
    exact(report, budget)
    if budget <= 10000:
        assert report["forecast_status"] == "unavailable"
        assert report["totals"]["estimated_revenue"] is None
        assert report["totals"]["estimated_roas"] is None
        assert any(a["budget"] == 0 for a in report["allocations"])


def test_original_196018_context_range_is_forecast_support_only(isolated_repository):
    source, _ = save(isolated_repository, rows=10000)
    _, _, parts, _ = prepare(
        isolated_repository, TrainingConfig(dataset_id=source.id, as_of_date=date(2026, 10, 29))
    )
    context = representative_contexts(parts[0], ["Facebook"], 13)["Facebook"]
    assert context["supported_min"] == pytest.approx(196017.99728400938)
    assert context["supported_max"] == pytest.approx(1221735.7413532787)
    config = cfg(source, 5000, platforms=[PlatformLimit(platform="Facebook")], horizon_days=13)
    assert effective_limits(config, {"Facebook": context})["Facebook"]["lower_units"] == 0
    report = create_plan(isolated_repository, config)
    exact(report, 5000)
    assert report["allocations"][0]["budget"] == 5000
    assert report["totals"]["estimated_revenue"] is None


def test_actual_user_monetary_restrictions_and_zero_allocation(isolated_repository):
    source, _ = save(isolated_repository, rows=10000)
    with pytest.raises(DomainError, match="user minimum"):
        create_plan(
            isolated_repository,
            cfg(source, 500, platforms=[PlatformLimit(platform="Facebook", min_amount=600)]),
        )
    with pytest.raises(DomainError, match="cannot cover"):
        create_plan(
            isolated_repository,
            cfg(source, 500, platforms=[PlatformLimit(platform="Facebook", max_amount=400)]),
        )
    limits = [
        PlatformLimit(platform="Facebook", min_amount=100, max_amount=200),
        PlatformLimit(platform="Google"),
    ]
    report = create_plan(isolated_repository, cfg(source, 500, platforms=limits))
    exact(report, 500)
    row = next(a for a in report["allocations"] if a["platform"] == "Facebook")
    assert 100 <= row["budget"] <= 200
    zero = create_plan(
        isolated_repository,
        cfg(
            source,
            500,
            method="evidence",
            platforms=[
                PlatformLimit(platform="Facebook", max_percent=0),
                PlatformLimit(platform="Google"),
            ],
        ),
    )
    assert next(a for a in zero["allocations"] if a["platform"] == "Facebook")["budget"] == 0


def test_rejected_model_never_used_as_accepted_forecast(isolated_repository, monkeypatch):
    source, store, model_id = saved_model(isolated_repository)
    result = store.get(model_id)["result"]
    result["acceptance"] = {
        "eligible": False,
        "reasons": ["Validation RMSE must improve by 5%."],
        "policy": "test rejection",
    }
    store.update(model_id, result=result)

    def no_model(*args):
        pytest.fail("Rejected XGBoost was loaded for inference")

    monkeypatch.setattr("ads_optimizer.optimization.service.load_model", no_model)
    report = create_plan(isolated_repository, cfg(source, 5000))
    assert report["model_id"] is None and report["model_evidence"] is None
    assert report["baseline_assessment"] is not None
    exact(report, 5000)


def test_baseline_has_independent_holdout_screen():
    rows = []
    for i, d in enumerate(pd.date_range("2026-01-01", periods=60)):
        for j in range(10):
            spend = float(10 + (i + j) % 40)
            rows.append(
                {
                    "date": str(d.date()),
                    "platform": "Facebook",
                    "spend": spend,
                    "revenue": 3 * spend,
                }
            )
    parts = chronological_split(pd.DataFrame(rows))
    assessment = assess_baseline(parts)
    assert assessment["eligible"] and assessment["metrics"]["test"]["baseline"]["rmse"] == 0
    parts[2]["revenue"] = 0.0
    assert not assess_baseline(parts)["eligible"]


def test_missing_revenue_short_and_weekly_history_allows_allocation_only(isolated_repository):
    source, frame = save(isolated_repository, rows=100)
    frame = frame.iloc[:5].copy()
    frame["revenue"] = np.nan
    metadata = source.model_dump(
        exclude={"id", "rows", "date_start", "date_end", "coverage", "options", "imported_at"}
    )
    metadata["data_ready_for_revenue"] = False
    small = isolated_repository.save(frame, metadata)
    report = create_plan(
        isolated_repository,
        cfg(small, 500, platforms=[PlatformLimit(platform=p) for p in small.options["platform"]]),
    )
    exact(report, 500)
    assert report["totals"]["estimated_revenue"] is None
    frame["date"] = pd.date_range("2026-01-05", periods=5, freq="7D").strftime("%Y-%m-%d")
    frame["date_granularity"] = "weekly"
    metadata["date_granularity"] = "weekly"
    weekly = isolated_repository.save(frame, metadata)
    report = create_plan(
        isolated_repository,
        cfg(
            weekly,
            500,
            horizon_days=13,
            platforms=[PlatformLimit(platform=p) for p in weekly.options["platform"]],
        ),
    )
    exact(report, 500)
    assert report["forecast_status"] == "unavailable"


def test_synthetic_component_flags_and_rate_mapping_are_preserved(isolated_repository):
    raw = (
        b"date,campaign,platform,spend,revenue,date_is_synthetic,revenue_is_synthetic,conversion_rate_pct\n"
        b"2026-01-01,A,Facebook,20,100,1,1,2.5\n"
    )
    stage = stage_csv(isolated_repository, raw, "modified.csv", "generic")
    options = ImportOptions(mapping=stage["suggested_mapping"], confirmed=True)
    frame, report, _ = validate_import(isolated_repository, stage["token"], options)
    assert report.is_synthetic and report.provenance_flags["date_is_synthetic"]
    source = commit_import(isolated_repository, stage["token"], options)
    assert source.is_synthetic and source.revenue_source == "synthetic"
    assert source.provenance_flags["revenue_is_synthetic"] and not provenance_review(source)
    assert frame.revenue.iloc[0] == 100
    old = source.model_copy(update={"provenance_flags": {}, "is_synthetic": False})
    assert provenance_review(old)
    new = stage_csv(isolated_repository, raw, "modified.csv", "generic")
    options.mapping["conversions"] = "conversion_rate_pct"
    with pytest.raises(DomainError, match="rate"):
        validate_import(isolated_repository, new["token"], options)


FACEBOOK = Path("/Users/adnan/Downloads/Facebook_Ad_Campaigns_with_revenue.csv")


@pytest.mark.skipif(
    not FACEBOOK.exists(), reason="User Facebook CSV is local and not redistributed"
)
def test_current_modified_facebook_csv_import_provenance_and_training(
    isolated_repository, tmp_path
):
    raw = pd.read_csv(FACEBOOK)
    assert len(raw) == 1143 and raw.ad_id.nunique() == 1143
    np.testing.assert_allclose(raw.revenue, 100 * raw.approved_conversions)
    stage = stage_csv(isolated_repository, FACEBOOK.read_bytes(), FACEBOOK.name, "generic")
    options = ImportOptions(
        mapping={**stage["suggested_mapping"], "campaign": "fb_campaign_id"},
        conversion_definition="purchases",
        attribution_window="7-day click",
        confirmed=True,
    )
    source = commit_import(isolated_repository, stage["token"], options)
    assert source.is_synthetic and all(source.provenance_flags.values())
    config = TrainingConfig(dataset_id=source.id, as_of_date=date(2026, 10, 29))
    _, _, parts, coverage = prepare(isolated_repository, config)
    from ads_optimizer.ml.train import train

    result = train(parts, coverage, source, config, tmp_path, lambda: None, lambda *_: None)
    assert result["algorithm"] == "XGBoost" and result["validation"]["model"]["rmse"] > 0
    assert result["provenance_flags"] == source.provenance_flags
    report = create_plan(
        isolated_repository, cfg(source, 500, platforms=[PlatformLimit(platform="Facebook")])
    )
    exact(report, 500)
    assert report["model_id"] is None


def test_validated_baseline_used_without_accepted_xgboost(isolated_repository):
    source, frame = save(isolated_repository, rows=10000)
    frame["revenue"] = 3 * frame.spend
    metadata = source.model_dump(
        exclude={"id", "rows", "date_start", "date_end", "coverage", "options", "imported_at"}
    )
    linear = isolated_repository.save(frame, metadata)
    report = create_plan(isolated_repository, cfg(linear, 1000000))
    exact(report, 1000000)
    assert report["forecast_status"] == "baseline" and report["model_id"] is None
    assert report["baseline_assessment"]["eligible"]
    assert report["totals"]["estimated_revenue"] is not None
