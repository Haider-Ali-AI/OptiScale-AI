import asyncio
import csv
import io

import pandas as pd
import pytest
from ads_optimizer.analytics.metrics import analytics_result, safe_csv_cell, summarize
from ads_optimizer.api import app
from ads_optimizer.data.csv_importer import commit_import, stage_csv, validate_import
from ads_optimizer.data.repository import Repository, coverage
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import FIELDS, DomainError, GenerateConfig, ImportOptions
from httpx import ASGITransport, AsyncClient

FIXTURE = (
    b"date,campaign,platform,impressions,clicks,spend,conversions,revenue\n"
    b"2026-01-01,Alpha,Google,100,10,50,2,200\n"
    b"2026-01-02,Beta,Facebook,1000,10,150,1,100\n"
)


def staged(repo, content=FIXTURE):
    preview = stage_csv(repo, content, "campaigns.csv", "generic")
    options = ImportOptions(
        mapping=preview["suggested_mapping"],
        confirmed=True,
        conversion_definition="purchases",
        attribution_window="7-day click",
    )
    return preview["token"], options


def test_generator_deterministic_and_coherent():
    a, truth = generate_frame(GenerateConfig())
    b, _ = generate_frame(GenerateConfig())
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 10000 and all(field in a for field in FIELDS)
    assert (a.clicks <= a.impressions).all() and (a.conversions <= a.clicks).all()
    assert (a.loc[a.conversions == 0, "revenue"] == 0).all()
    assert not a.duplicated(["date", "campaign", "platform"]).any()
    assert a.platform.nunique() == 5 and a.city.nunique() == 5
    assert a.spend.std() > 0 and a.is_synthetic.all()
    assert "delivery_saturation" in truth and "delivery_saturation" not in a.columns
    c, _ = generate_frame(GenerateConfig(seed=43))
    assert not a.equals(c)


def test_generator_bounds_and_platform_selection():
    with pytest.raises(ValueError):
        GenerateConfig(rows=100000)
    with pytest.raises(ValueError):
        GenerateConfig(start_date="2026-01-02", end_date="2026-01-01")
    a, _ = generate_frame(GenerateConfig(rows=100, platforms=["Google"]))
    assert set(a.platform) == {"Google"}


def test_weighted_metrics_and_zero_denominators(isolated_repository):
    token, options = staged(isolated_repository)
    frame, _, _ = validate_import(isolated_repository, token, options)
    result = summarize(frame)
    assert result["ctr"] == pytest.approx(20 / 1100 * 100)
    assert result["cpc"] == 10 and result["cpa"] == pytest.approx(200 / 3)
    assert result["roas"] == 1.5 and result["cvr"] == 15
    frame.loc[:, ["clicks", "spend", "conversions", "impressions"]] = 0
    assert all(summarize(frame)[key] is None for key in ["ctr", "cpc", "cpa", "cvr", "roas"])


def test_missing_metrics_remain_null_and_coverage_gates(isolated_repository):
    token, options = staged(
        isolated_repository, b"date,campaign,platform,spend\n2026-01-01,A,Google,100\n"
    )
    frame, report, _ = validate_import(isolated_repository, token, options)
    assert report.can_import and not report.data_ready_for_revenue
    assert frame.revenue.isna().all() and report.coverage["city"] == 0
    assert summarize(frame)["revenue"] is None and summarize(frame)["spend"] == 100
    assert summarize(frame)["roas"] is None


def test_partially_missing_revenue_is_not_reported_as_total(isolated_repository):
    token, options = staged(isolated_repository, FIXTURE.replace(b",1,100", b",1,"))
    frame, report, _ = validate_import(isolated_repository, token, options)
    assert report.coverage["revenue"] == 0.5 and not report.data_ready_for_revenue
    assert summarize(frame)["revenue"] is None
    assert summarize(frame.iloc[:1])["revenue"] == 200


def test_preview_mapping_currency_and_explicit_rate(isolated_repository):
    data = (
        b"Day,Campaign name,Publisher platform,Impressions,Link clicks,"
        b"Amount spent (USD),Purchases,Purchase conversion value,Currency\n"
        b"2026-01-01,A,instagram,100,10,10,1,20,USD\n"
    )
    preview = stage_csv(isolated_repository, data, "meta.csv", "meta")
    options = ImportOptions(mapping=preview["suggested_mapping"], original_currency="USD")
    _, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert not report.can_import and any(e.field == "currency" for e in report.errors)
    frame, report, _ = validate_import(
        isolated_repository, preview["token"], options.model_copy(update={"exchange_rate": 280})
    )
    assert report.can_import and frame.spend.iloc[0] == 2800
    assert frame.revenue.iloc[0] == 5600 and frame.platform.iloc[0] == "Instagram"
    _, report, _ = validate_import(
        isolated_repository,
        preview["token"],
        options.model_copy(update={"original_currency": "PKR"}),
    )
    assert not report.can_import


def test_invalid_rows_require_explicit_exclusion(isolated_repository):
    token, options = staged(isolated_repository, FIXTURE.replace(b"2026-01-02", b"bad-date"))
    _, report, _ = validate_import(isolated_repository, token, options)
    assert report.invalid_rows == 1 and not report.can_import
    assert report.errors[0].rows == [3]
    frame, report, _ = validate_import(
        isolated_repository, token, options.model_copy(update={"exclude_invalid": True})
    )
    assert report.can_import and len(frame) == 1 and report.excluded_rows == 1


@pytest.mark.parametrize(
    "bad", [b"-1", b"inf", b"1000000000000000000000000000000000000000000000000"]
)
def test_invalid_numeric_values(isolated_repository, bad):
    token, options = staged(isolated_repository, FIXTURE.replace(b",50,", b"," + bad + b","))
    _, report, _ = validate_import(isolated_repository, token, options)
    assert not report.can_import


def test_duplicate_and_conflicting_grain_handling(isolated_repository):
    header, row, second = FIXTURE.decode().splitlines()
    token, options = staged(isolated_repository, f"{header}\n{row}\n{row}\n".encode())
    frame, report, _ = validate_import(isolated_repository, token, options)
    assert len(frame) == 1 and report.duplicate_rows == 1 and report.can_import
    token, options = staged(
        isolated_repository, f"{header}\n{row}\n{row.replace(',50,', ',51,')}\n".encode()
    )
    assert not validate_import(isolated_repository, token, options)[1].can_import


def test_save_selection_restart_and_duplicate_import(isolated_repository):
    token, options = staged(isolated_repository)
    manifest = commit_import(isolated_repository, token, options)
    restored = Repository(isolated_repository.root)
    assert restored.selected().id == manifest.id
    assert restored.read(manifest.id).revenue.sum() == 300
    token, options = staged(restored)
    with pytest.raises(DomainError, match="already saved"):
        commit_import(restored, token, options)
    restored.delete(manifest.id)
    assert restored.selected() is None and restored.list() == []
    with pytest.raises(DomainError):
        restored.read("../../catalog.sqlite")


def test_privacy_and_synthetic_provenance(isolated_repository):
    data = FIXTURE.decode().splitlines()
    content = (data[0] + ",email,is_synthetic\n" + data[1] + ",secret@example.test,true\n").encode()
    preview = stage_csv(isolated_repository, content, "../../private.csv", "generic")
    assert "email" not in preview["columns"] and preview["filename"] == "private.csv"
    stage = (isolated_repository.root / "staging" / f"{preview['token']}.json").read_text()
    assert "secret@example.test" not in stage
    options = ImportOptions(mapping=preview["suggested_mapping"], confirmed=True)
    manifest = commit_import(isolated_repository, preview["token"], options)
    assert manifest.is_synthetic and manifest.source == "synthetic_csv"


def test_order_file_malformed_csv_and_confirmation(isolated_repository):
    with pytest.raises(DomainError, match="orders CSV"):
        stage_csv(
            isolated_repository, b"Order ID,Financial Status\n1,paid\n", "orders.csv", "generic"
        )
    with pytest.raises(DomainError):
        stage_csv(isolated_repository, b"date,date\n1,2\n", "duplicate.csv", "generic")
    token, options = staged(isolated_repository)
    with pytest.raises(DomainError, match="Confirm"):
        commit_import(isolated_repository, token, options.model_copy(update={"confirmed": False}))


def test_filters_grouping_sorting_and_empty_results(isolated_repository):
    token, options = staged(isolated_repository)
    frame, _, _ = validate_import(isolated_repository, token, options)
    result = analytics_result(frame, {"platform": "Google"}, "platform")
    assert result["totals"]["rows"] == 1 and result["totals"]["spend"] == 50
    assert result["platforms"][0]["name"] == "Google"
    assert analytics_result(frame, {"city": "nowhere"})["totals"]["spend"] is None
    assert analytics_result(frame, {}, sort="spend", direction="asc")["table"][0]["name"] == "Alpha"
    with pytest.raises(DomainError):
        analytics_result(frame, {"start_date": "2026-02-01", "end_date": "2026-01-01"})


def test_csv_formula_escape():
    assert safe_csv_cell(" =cmd()") == "' =cmd()"
    assert safe_csv_cell("@SUM(1)") == "'@SUM(1)"
    assert safe_csv_cell(-3) == -3 and safe_csv_cell(float("nan")) == ""


def test_nearly_complete_coverage_is_never_rounded_up():
    frame, _ = generate_frame(GenerateConfig())
    frame = pd.concat([frame] * 10, ignore_index=True)
    frame.loc[0, "revenue"] = float("nan")
    assert coverage(frame)["revenue"] == 0.99999
    assert summarize(frame)["revenue"] is None


def test_duplicate_identity_prefers_campaign_ids(isolated_repository):
    data = (
        b"date,campaign,campaign_id,platform,spend\n"
        b"2026-01-01,Old name,stable-1,Google,10\n"
        b"2026-01-01,New name,stable-1,Google,11\n"
    )
    token, options = staged(isolated_repository, data)
    report = validate_import(isolated_repository, token, options)[1]
    assert not report.can_import and any(issue.field == "grain" for issue in report.errors)


def test_overlapping_reports_are_warned_and_kept_separate(isolated_repository):
    token, options = staged(isolated_repository)
    first = commit_import(isolated_repository, token, options)
    token, options = staged(isolated_repository, FIXTURE.replace(b",50,", b",51,"))
    second = commit_import(isolated_repository, token, options)
    assert first.id != second.id and len(isolated_repository.list()) == 2
    assert any("overlap" in warning for warning in second.warnings)


def test_mixed_provenance_and_granularity_are_blocked(isolated_repository):
    header, first, second = FIXTURE.decode().splitlines()
    token, options = staged(
        isolated_repository,
        (header + ",is_synthetic\n" + first + ",true\n" + second + ",false\n").encode(),
    )
    assert not validate_import(isolated_repository, token, options)[1].can_import
    token, options = staged(
        isolated_repository, (header + ",date_granularity\n" + first + ",weekly\n").encode()
    )
    assert validate_import(isolated_repository, token, options)[1].date_granularity == "weekly"


def test_fractional_conversions_missing_platform_and_date_format(isolated_repository):
    data = b"date,campaign,spend,conversions,revenue\n31/01/2026,A,100,1.5,200\n"
    token, options = staged(isolated_repository, data)
    assert not validate_import(isolated_repository, token, options)[1].can_import
    options = options.model_copy(update={"default_platform": "YouTube", "date_format": "%d/%m/%Y"})
    frame, report, _ = validate_import(isolated_repository, token, options)
    assert report.can_import and frame.conversions.iloc[0] == 1.5
    assert frame.platform.iloc[0] == "YouTube" and frame.date.iloc[0] == "2026-01-31"


def test_expired_preview_and_oversize_upload(isolated_repository):
    from ads_optimizer.data.csv_importer import read_stage
    from ads_optimizer.domain import MAX_UPLOAD_BYTES

    with pytest.raises(DomainError, match="10 MiB"):
        stage_csv(isolated_repository, b"x" * (MAX_UPLOAD_BYTES + 1), "large.csv", "generic")
    with pytest.raises(DomainError, match="not found"):
        read_stage(isolated_repository, "../../secret")


def test_http_csv_preview_validate_confirm_commit():
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/imports/preview?filename=fixture.csv&profile=google", content=FIXTURE
            )
            assert response.status_code == 200, response.text
            staged = response.json()
            payload = {"mapping": staged["suggested_mapping"]}
            url = f"/api/v1/imports/{staged['token']}"
            validated = await client.post(url + "/validate", json=payload)
            assert validated.json()["can_import"]
            assert (await client.post(url + "/commit", json=payload)).status_code == 422
            committed = await client.post(url + "/commit", json={**payload, "confirmed": True})
            assert committed.status_code == 201 and committed.json()["import_profile"] == "google"
            assert not committed.json()["is_synthetic"]
            assert (await client.post(url + "/validate", json=payload)).status_code == 404

    asyncio.run(run())


def test_api_generate_analytics_export_and_cross_site_guard():
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            denied = await client.post(
                "/api/v1/datasets/generate", json={}, headers={"Origin": "https://evil.example"}
            )
            assert denied.status_code == 403
            created = await client.post("/api/v1/datasets/generate", json={"rows": 100})
            assert created.status_code == 201, created.text
            dataset_id = created.json()["id"]
            result = await client.get(f"/api/v1/datasets/{dataset_id}/analytics?platform=Google")
            assert result.status_code == 200 and result.json()["dataset"]["is_synthetic"]
            export = await client.get(f"/api/v1/datasets/{dataset_id}/export?platform=Google")
            rows = list(csv.DictReader(io.StringIO(export.text)))
            assert all(
                row["platform"] == "Google" and row["is_synthetic"] == "True" for row in rows
            )
            assert (
                await client.get(f"/api/v1/datasets/{dataset_id}/preview?page_size=1000")
            ).status_code == 422
            assert (await client.delete(f"/api/v1/datasets/{dataset_id}")).status_code == 200

    asyncio.run(run())


def channel_export(*, weekly=False):
    """Small constructed mapping fixture, not an advertiser performance claim."""
    frame = pd.DataFrame(
        {
            "date": ["2026-09-01"] * 6,
            "campaign_name": [f"Fixture {i}" for i in range(6)],
            "ad_platform": [
                "Google Ads",
                "Google Ads",
                "Meta Ads",
                "Meta Ads",
                "TikTok Ads",
                "Google Ads",
            ],
            "channel": [
                "Google Search",
                "Google Display",
                "Facebook",
                "Instagram",
                "TikTok",
                "YouTube",
            ],
            "spend_pkr": [100, 200, 300, 400, 500, 600],
            "revenue_pkr": [200, 400, 600, 800, 1000, 1200],
            "conversions": [1] * 6,
        }
    )
    if weekly:
        frame = frame.rename(columns={"date": "week_start"})
        frame["week_end"] = "2026-09-07"
    return frame.to_csv(index=False).encode()


def test_channel_and_pkr_headers_are_suggested_without_losing_youtube(isolated_repository):
    preview = stage_csv(isolated_repository, channel_export(), "channels.csv", "generic")
    mapping = preview["suggested_mapping"]
    assert mapping["platform"] == "channel"
    assert mapping["spend"] == "spend_pkr" and mapping["revenue"] == "revenue_pkr"
    frame, report, _ = validate_import(
        isolated_repository, preview["token"], ImportOptions(mapping=mapping)
    )
    assert report.can_import and report.valid_rows == 6 and report.invalid_rows == 0
    assert frame.platform.tolist() == [
        "Google",
        "Google",
        "Facebook",
        "Instagram",
        "TikTok",
        "YouTube",
    ]
    assert frame.spend.sum() == 2100 and frame.revenue.sum() == 4200


def test_provider_mapping_cannot_silently_group_youtube_into_google(isolated_repository):
    preview = stage_csv(isolated_repository, channel_export(), "channels.csv", "generic")
    options = ImportOptions(
        mapping={**preview["suggested_mapping"], "platform": "ad_platform"}, exclude_invalid=True
    )
    _, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert not report.can_import
    assert any("Map channel to platform" in error.message for error in report.errors)


def test_meta_provider_stays_ambiguous_without_a_channel(isolated_repository):
    data = (
        b"date,campaign,ad_platform,spend_pkr\n"
        b"2026-09-01,A,Meta Ads,100\n2026-09-02,B,TikTok Ads,200\n"
    )
    preview = stage_csv(isolated_repository, data, "providers.csv", "generic")
    frame, report, _ = validate_import(
        isolated_repository, preview["token"], ImportOptions(mapping=preview["suggested_mapping"])
    )
    assert not report.can_import and report.invalid_rows == 1
    assert frame.platform.tolist() == ["TikTok"]
    assert "Meta Ads alone is ambiguous" in report.errors[0].message


def test_pkr_named_metrics_cannot_be_reinterpreted_as_usd(isolated_repository):
    preview = stage_csv(isolated_repository, channel_export(), "channels.csv", "generic")
    _, report, _ = validate_import(
        isolated_repository,
        preview["token"],
        ImportOptions(
            mapping=preview["suggested_mapping"], original_currency="USD", exchange_rate=280
        ),
    )
    assert not report.can_import
    assert any(error.field == "currency" for error in report.errors)


def test_weekly_rows_cannot_be_saved_as_daily_even_with_exclusions(isolated_repository):
    preview = stage_csv(isolated_repository, channel_export(weekly=True), "weekly.csv", "generic")
    assert preview["suggested_mapping"]["date"] == "week_start"
    options = ImportOptions(
        mapping={**preview["suggested_mapping"], "date": "week_start"},
        date_granularity="daily",
        exclude_invalid=True,
        confirmed=True,
    )
    _, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert not report.can_import and not any(e.field == "platform" for e in report.errors)
    assert any(e.field == "date_granularity" for e in report.errors)
    with pytest.raises(DomainError, match="blocking validation"):
        commit_import(isolated_repository, preview["token"], options)
    assert isolated_repository.list() == []


def test_aggregated_reporting_start_end_dates_are_not_daily(isolated_repository):
    data = channel_export().decode().replace("date,", "Reporting starts,", 1)
    data = pd.read_csv(io.StringIO(data))
    data["Reporting ends"] = "2026-09-07"
    preview = stage_csv(
        isolated_repository, data.to_csv(index=False).encode(), "period.csv", "meta"
    )
    options = ImportOptions(mapping=preview["suggested_mapping"])
    _, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert report.can_import and report.date_granularity == "weekly"
    # The same provider's actual day-by-day export remains valid.
    data["Reporting ends"] = data["Reporting starts"]
    preview = stage_csv(isolated_repository, data.to_csv(index=False).encode(), "daily.csv", "meta")
    options = ImportOptions(mapping=preview["suggested_mapping"])
    assert validate_import(isolated_repository, preview["token"], options)[1].can_import
