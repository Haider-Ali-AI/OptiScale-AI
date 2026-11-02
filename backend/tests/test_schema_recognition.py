"""Constructed CSV fixtures: values exercise contracts, not business accuracy claims."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from ads_optimizer.data.csv_importer import commit_import, stage_csv, validate_import
from ads_optimizer.domain import DomainError, ImportOptions
from ads_optimizer.ml.contracts import TrainingConfig
from ads_optimizer.ml.service import prepare, readiness
from ads_optimizer.ml.train import train


def stage(repo, csv, **options):
    preview = stage_csv(repo, csv.encode(), "fixture.csv", "generic")
    config = ImportOptions(mapping=preview["suggested_mapping"], **options)
    return preview, config


@pytest.mark.parametrize(
    "header",
    [
        "date",
        "week_start",
        "Week Start",
        "campaign_date",
        "Date Recorded",
        "reporting-date",
        "WeekStart",
    ],
)
def test_alternative_headers_and_preserved_periods(isolated_repository, header):
    preview, options = stage(
        isolated_repository,
        f"{header},Campaign Name,Ad Platform,Amount Spent,Sales Revenue,"
        "Ad Impressions,Total Clicks,Purchases,unrelated\n"
        "2026-10-20,A,Google Ads,100,300,1000,50,3,hello\n",
        confirmed=True,
    )
    assert preview["suggested_mapping"]["date"] == header
    frame, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert report.can_import and len(frame) == 1
    manifest = commit_import(isolated_repository, preview["token"], options)
    assert manifest.import_mapping["selected"]["date"] == header
    assert manifest.date_granularity == ("weekly" if "week" in header.lower() else "daily")
    assert frame.spend.sum() == 100


def test_ambiguous_and_fuzzy_headers_require_manual_choice(isolated_repository):
    preview, options = stage(
        isolated_repository,
        "date,campaign,platform,spend,revenue,Sales Revenue,Total Cliks,Results\n"
        "2026-10-20,A,Google,10,20,30,5,1\n",
    )
    for field in ["revenue", "clicks", "conversions"]:
        assert preview["suggested_mapping"][field] == ""
        assert preview["mapping_details"][field]["status"] == "confirm"
    options.mapping["revenue"] = "Sales Revenue"
    assert validate_import(isolated_repository, preview["token"], options)[0].revenue.iloc[0] == 30


def test_iso_weeks_week_end_ambiguous_dates_and_yearless_weeks(isolated_repository):
    for header, value, expected in [
        ("week", "2026-W43", "2026-10-19"),
        ("week_end", "2026-10-25", "2026-10-19"),
    ]:
        preview, options = stage(
            isolated_repository, f"{header},campaign,platform,spend\n{value},A,Facebook,100\n"
        )
        frame, report, _ = validate_import(isolated_repository, preview["token"], options)
        assert report.can_import and report.date_granularity == "weekly"
        assert frame.date.iloc[0] == expected
    preview, options = stage(
        isolated_repository, "date,campaign,platform,spend\n01/02/2026,A,Facebook,100\n"
    )
    assert not validate_import(isolated_repository, preview["token"], options)[1].can_import
    options.date_format = "%d/%m/%Y"
    assert (
        validate_import(isolated_repository, preview["token"], options)[0].date.iloc[0]
        == "2026-02-01"
    )
    preview, options = stage(
        isolated_repository, "week,campaign,platform,spend\n43,A,Facebook,100\n"
    )
    options.mapping["date"] = "week"
    report = validate_import(isolated_repository, preview["token"], options)[1]
    assert not report.can_import and any("year" in e.message for e in report.errors)


def test_money_nulls_percentages_and_currency_are_not_invented(isolated_repository):
    preview, options = stage(
        isolated_repository,
        "date,campaign,platform,spend,revenue,conversions\n"
        '2026-10-20,A,Google,"PKR 1,234.50",NaN,2\n2026-10-21,A,Google,500,2000,3\n',
    )
    frame, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert report.can_import and frame.spend.iloc[0] == 1234.5 and pd.isna(frame.revenue.iloc[0])
    assert not report.data_ready_for_revenue
    for value in ['"USD 1,234.50"', '"1.234,50"', "12%", "-10"]:
        preview, options = stage(
            isolated_repository, f"date,campaign,platform,spend\n2026-10-20,A,Google,{value}\n"
        )
        options.mapping["spend"] = "spend"
        assert not validate_import(isolated_repository, preview["token"], options)[1].can_import


def weekly_csv():
    rng = np.random.default_rng(13)
    rows = []
    for week in pd.date_range("2025-01-06", periods=40, freq="7D"):
        for i in range(12):
            spend = float(rng.uniform(100, 1000))
            rows.append(
                {
                    "Week Start": week.strftime("%Y-%m-%d"),
                    "Campaign Name": f"Fixture {i}",
                    "Ad Platform": "Google Ads",
                    "Amount Spent": round(spend, 2),
                    "Sales Revenue": round(4000 * spend / (spend + 400), 2),
                    "conversion_definition": "purchases",
                    "attribution_window": "7-day click",
                    "is_synthetic": "true",
                }
            )
    return pd.DataFrame(rows).to_csv(index=False)


def test_weekly_upload_actual_training_without_optional_counts(isolated_repository, tmp_path):
    preview, options = stage(isolated_repository, weekly_csv(), confirmed=True)
    source = commit_import(isolated_repository, preview["token"], options)
    assert source.rows == 480 and source.coverage["conversions"] == 0
    config = TrainingConfig(dataset_id=source.id, as_of_date=date(2026, 10, 29))
    _, mature, parts, coverage = prepare(isolated_repository, config)
    assert len(mature) == 480 and coverage["period_days"] == 7
    assert parts[0].date.max() < parts[1].date.min() < parts[2].date.min()
    from ads_optimizer.ml.service import sha256
    from ads_optimizer.ml.store import ModelStore
    from ads_optimizer.optimization.contracts import PlanConfig, PlatformLimit
    from ads_optimizer.optimization.service import create_plan, representative_contexts

    store = ModelStore(isolated_repository.root)
    job = store.create(config, source)
    folder = store.root / job["id"]
    result = train(parts, coverage, source, config, folder, lambda: None, lambda *_: None)
    assert result["algorithm"] == "XGBoost" and result["date_granularity"] == "weekly"
    assert result["test"]["model"]["rows"] == 96
    assert result["test"]["model"]["rmse"] >= 0 and result["test"]["model"]["r2"] is not None
    assert result["acceptance"]["eligible"], result["acceptance"]
    parts[2].to_parquet(folder / "holdout.parquet", index=False)
    result["hashes"]["holdout.parquet"] = sha256(folder / "holdout.parquet")
    store.update(
        job["id"],
        status="succeeded",
        result=result,
        input_sha256=sha256(
            isolated_repository.root / "datasets" / source.id / "campaigns.parquet"
        ),
    )
    context = representative_contexts(parts[0], ["Google"], 1)["Google"]
    budget = round(context["reference_budget"], 2)
    cfg = PlanConfig(
        dataset_id=source.id,
        model_id=job["id"],
        budget=budget,
        start_date=date(2026, 11, 2),
        horizon_days=7,
        platforms=[PlatformLimit(platform="Google", max_percent=100)],
    )
    report = create_plan(isolated_repository, cfg)
    assert report["totals"]["budget"] == budget and report["period_days"] == 7
    assert report["prediction_rows"] == len(report["curves"][0]["points"]) * len(context["rows"])
    unsupported = create_plan(isolated_repository, cfg.model_copy(update={"horizon_days": 1}))
    assert unsupported["forecast_status"] == "unavailable"


def test_tiny_upload_has_analytics_but_no_trained_model(isolated_repository):
    preview, options = stage(
        isolated_repository,
        "date,campaign,platform,spend,revenue\n2026-01-01,A,Google,10,20\n",
        confirmed=True,
        conversion_definition="purchases",
        attribution_window="7-day click",
    )
    source = commit_import(isolated_repository, preview["token"], options)
    config = TrainingConfig(dataset_id=source.id)
    assert not readiness(isolated_repository, config)["ready"]
    with pytest.raises(DomainError, match="300 mature"):
        prepare(isolated_repository, config)
