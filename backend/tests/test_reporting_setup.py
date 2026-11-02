"""Constructed fixtures for guided reporting setup; no actual advertiser data."""

import asyncio
import hashlib
from datetime import date

import pandas as pd
import pytest
from ads_optimizer.api import app
from ads_optimizer.data.csv_importer import commit_import, stage_csv, validate_import
from ads_optimizer.data.reporting import ReportingAnswers, clarify_report, import_hints
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import DomainError, GenerateConfig, ImportOptions
from ads_optimizer.ml.contracts import TrainingConfig
from ads_optimizer.ml.service import readiness
from ads_optimizer.ml.store import ModelStore
from httpx import ASGITransport, AsyncClient


def unknown_report(repo, mixed=False):
    frame, _ = generate_frame(GenerateConfig(rows=1000))
    frame["is_synthetic"] = False
    frame["conversion_definition"] = "unspecified"
    frame["attribution_window"] = "unspecified"
    if mixed:
        frame["attribution_window"] = ["7-day click", "30-day click"] * 500
    manifest = repo.save(
        frame,
        {
            "name": "Reporting setup fixture",
            "source": "advertiser_csv",
            "is_synthetic": False,
            "revenue_source": "ad_platform_reported",
            "data_ready_for_revenue": False,
            "warnings": [
                "Specify compatible conversion/attribution definitions before forecasting."
            ],
            "conversion_definition": "unspecified",
            "attribution_window": "mixed" if mixed else "unspecified",
        },
    )
    return manifest, frame


def answers(**changes):
    return ReportingAnswers(
        conversion_definition=changes.get("conversion_definition", "purchases"),
        attribution_window=changes.get("attribution_window", "7-day click"),
        confirmed=changes.get("confirmed", True),
    )


def test_detect_explicit_purchase_column_but_never_guess_window(isolated_repository):
    content = b"date,campaign,platform,Purchases,spend,revenue\n2026-01-01,A,Google,1,50,100\n"
    preview = stage_csv(isolated_repository, content, "purchase-fixture.csv", "meta")
    hints = preview["reporting_hints"]
    assert hints["conversion_definition"]["value"] == "purchases"
    assert hints["attribution_window"]["status"] == "missing"
    frame, report, _ = validate_import(
        isolated_repository, preview["token"], ImportOptions(mapping=preview["suggested_mapping"])
    )
    assert frame.conversion_definition.tolist() == ["purchases"]
    assert not report.data_ready_for_revenue
    assert frame.attribution_window.tolist() == ["unspecified"]


def test_explicit_file_rules_detect_and_keep_evidence(isolated_repository):
    content = (
        b"date,campaign,platform,conversions,spend,revenue,conversion_definition,attribution_window\n"
        b"2026-01-01,A,Google,1,50,100,purchases,7-day click\n"
    )
    preview = stage_csv(isolated_repository, content, "explicit-fixture.csv", "generic")
    assert all(h["status"] == "detected" for h in preview["reporting_hints"].values())
    manifest = commit_import(
        isolated_repository,
        preview["token"],
        ImportOptions(mapping=preview["suggested_mapping"], confirmed=True),
    )
    assert manifest.data_ready_for_revenue
    assert "CSV column" in manifest.reporting_evidence["attribution_window"]


def test_generic_conversions_or_sales_objective_are_not_purchase_proof():
    raw = pd.DataFrame(
        {"conversions": [1, 2], "objective": ["Sales", "Sales"], "revenue": [10, 20]}
    )
    hints = import_hints(raw, {"conversions": "conversions"})
    assert hints["conversion_definition"]["status"] == "missing"
    assert hints["attribution_window"]["status"] == "missing"


def test_partial_rule_is_not_automatically_assumed_for_unknown_rows():
    raw = pd.DataFrame({"rule": ["7-day click", "unspecified"]})
    hints = import_hints(raw, {"attribution_window": "rule"})
    assert hints["attribution_window"]["status"] == "partial"


def test_missing_rules_have_plain_question_data(isolated_repository):
    manifest, _ = unknown_report(isolated_repository)
    result = readiness(
        isolated_repository, TrainingConfig(dataset_id=manifest.id, as_of_date=date(2026, 10, 28))
    )
    assert not result["ready"]
    assert result["reporting_setup"]["needs_answers"]
    assert result["reporting_setup"]["financial_complete"]
    assert not result["reporting_setup"]["mixed"]


def test_answers_create_selected_revision_without_altering_source_or_models(isolated_repository):
    repo = isolated_repository
    manifest, original = unknown_report(repo)
    path = repo.root / "datasets" / manifest.id / "campaigns.parquet"
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    store = ModelStore(repo.root)
    old_job = store.create(TrainingConfig(dataset_id=manifest.id), manifest)
    store.update(old_job["id"], status="failed", message="Fixture history")
    revision = clarify_report(repo, manifest.id, answers())
    assert revision.id != manifest.id and revision.parent_dataset_id == manifest.id
    assert repo.selected().id == revision.id
    assert not repo.get(manifest.id).data_ready_for_revenue
    assert revision.data_ready_for_revenue
    assert revision.is_synthetic == manifest.is_synthetic
    assert checksum == hashlib.sha256(path.read_bytes()).hexdigest()
    pd.testing.assert_frame_equal(
        repo.read(revision.id).drop(columns=["conversion_definition", "attribution_window"]),
        original.drop(columns=["conversion_definition", "attribution_window"]),
    )
    assert store.get(old_job["id"])["config"]["dataset_id"] == manifest.id
    assert "User confirmed" in revision.reporting_evidence["attribution_window"]
    assert readiness(repo, TrainingConfig(dataset_id=revision.id, as_of_date=date(2026, 10, 28)))[
        "ready"
    ]


@pytest.mark.parametrize("value", ["unspecified", "unknown", "mixed", "none"])
def test_unsure_is_not_turned_into_a_training_rule(isolated_repository, value):
    manifest, _ = unknown_report(isolated_repository)
    with pytest.raises(DomainError, match="fine to be unsure"):
        clarify_report(isolated_repository, manifest.id, answers(attribution_window=value))
    assert len(isolated_repository.list()) == 1


def test_confirmation_and_selected_source_are_required(isolated_repository):
    manifest, _ = unknown_report(isolated_repository)
    with pytest.raises(DomainError, match="Review your answers"):
        clarify_report(isolated_repository, manifest.id, answers(confirmed=False))
    isolated_repository.select(None)
    with pytest.raises(DomainError, match="Select this report"):
        clarify_report(isolated_repository, manifest.id, answers())


def test_mixed_rules_and_existing_definitions_cannot_be_overwritten(isolated_repository):
    manifest, _ = unknown_report(isolated_repository, mixed=True)
    with pytest.raises(DomainError, match="different reporting rules"):
        clarify_report(isolated_repository, manifest.id, answers())
    # A single known source rule remains immutable too.
    frame = isolated_repository.read(manifest.id)
    frame["attribution_window"] = "30-day click"
    other = isolated_repository.save(
        frame,
        {
            "name": "Known rule",
            "source": "advertiser_csv",
            "is_synthetic": False,
            "revenue_source": "ad_platform_reported",
            "data_ready_for_revenue": False,
            "warnings": [],
            "conversion_definition": "unspecified",
            "attribution_window": "30-day click",
        },
    )
    with pytest.raises(DomainError, match="already contains a different"):
        clarify_report(isolated_repository, other.id, answers())


def test_clarification_endpoint_returns_new_source_bound_report(isolated_repository):
    manifest, _ = unknown_report(isolated_repository)

    async def journey():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/datasets/{manifest.id}/reporting-setup", json=answers().model_dump()
            )
            assert response.status_code == 201
            assert response.json()["parent_dataset_id"] == manifest.id
            state = (await client.get("/api/v1/workspace")).json()
            assert state["selected_dataset_id"] == response.json()["id"]

    asyncio.run(journey())


def test_explicit_file_rule_cannot_be_silently_replaced_by_a_conflicting_answer(
    isolated_repository,
):
    content = (
        b"date,campaign,platform,Purchases,spend,revenue,attribution_window\n"
        b"2026-01-01,A,Google,1,50,100,7-day click\n"
    )
    preview = stage_csv(isolated_repository, content, "explicit-fixture.csv", "generic")
    options = ImportOptions(mapping=preview["suggested_mapping"], attribution_window="30-day click")
    _, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert not report.can_import
    assert any(error.field == "attribution_window" for error in report.errors)
    # Hints always follow the actual, current mapping.
    options = ImportOptions(mapping={**preview["suggested_mapping"], "attribution_window": ""})
    frame, report, _ = validate_import(isolated_repository, preview["token"], options)
    assert report.reporting_hints["attribution_window"]["status"] == "missing"
    assert frame.attribution_window.tolist() == ["unspecified"]


def test_unknown_placeholders_never_mark_a_report_ready_for_forecasting(isolated_repository):
    content = (
        b"date,campaign,platform,conversions,spend,revenue,is_synthetic\n"
        b"2026-01-01,A,Google,1,50,100,true\n"
    )
    preview = stage_csv(isolated_repository, content, "unknown-rule-fixture.csv", "generic")
    _, report, _ = validate_import(
        isolated_repository,
        preview["token"],
        ImportOptions(
            mapping=preview["suggested_mapping"],
            conversion_definition="purchases",
            attribution_window="n/a",
        ),
    )
    assert report.can_import
    assert not report.data_ready_for_revenue
