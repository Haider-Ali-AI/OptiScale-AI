"""Financial ground truth, source separation and conservative commerce forecasts."""

import asyncio
import copy
import csv
import io
import json
import stat
from datetime import date
from decimal import Decimal

import pytest
from ads_optimizer.api import app
from ads_optimizer.commerce import importer, profit, reconcile
from ads_optimizer.commerce.contracts import ImportConfig, ProfitConfig, ReconcileConfig
from ads_optimizer.commerce.demo import FIXTURES, prepare
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.domain import DomainError
from ads_optimizer.optimization.contracts import PlatformLimit
from httpx import ASGITransport, AsyncClient


def options(staged, **changes):
    return ImportConfig(
        name="Fictional test snapshot",
        store_id="fictional-test",
        mapping=staged["suggested_mapping"],
        confirmed=True,
        is_synthetic=True,
        snapshot_as_of=date(2026, 10, 30),
        **changes,
    )


def imported(repo, filename="pilot-shopify.csv", profile="shopify", raw=None, **changes):
    staged = importer.stage(repo, raw or (FIXTURES / filename).read_bytes(), filename, profile)
    return importer.validate(repo, staged["token"], options(staged, **changes), commit=True)


def altered(filename, modify):
    rows = list(csv.DictReader(io.StringIO((FIXTURES / filename).read_text())))
    modify(rows)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def request(method, path, body=None, content=None):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(
                method, "/api/v1/commerce" + path, json=body, content=content
            )

    return asyncio.run(run())


def test_shopify_order_grain_privacy_and_repeated_totals(isolated_repository):
    repo = isolated_repository
    staged = importer.stage(
        repo, (FIXTURES / "pilot-shopify.csv").read_bytes(), "orders.csv", "shopify"
    )
    assert staged["removed_columns"] == 2 and "Email" not in staged["headers"]
    config = options(staged, subtotal_basis="after_discounts")
    # A recognized file marker cannot be removed by changing manual mapping.
    config.mapping.pop("is_synthetic")
    config.is_synthetic = False
    report = importer.validate(repo, staged["token"], config)
    assert report["can_import"] and report["orders"] == 8 and report["line_items"] == 9
    manifest = importer.validate(repo, staged["token"], config, commit=True)
    store = CommerceStore(repo.root)
    _, data = store.get(manifest["id"])
    encoded = json.dumps(data)
    assert (
        "fictional-buyer" not in encoded
        and "Fictional Buyer" not in encoded
        and "#FIC-A" not in encoded
    )
    order = next(
        row
        for row in data["orders"]
        if row["order_key"] == store.order_key(config.store_id, "#FIC-A")
    )
    assert order["gross"] == 250000 and order["discounts"] == 25000 and order["net_sales"] == 225000
    assert len(data["items"]) == 9 and not (store.staging / f"{staged['token']}.json").exists()
    assert stat.S_IMODE((store.root / "order-id-key").stat().st_mode) == 0o600
    with pytest.raises(DomainError, match="already saved"):
        imported(repo, subtotal_basis="after_discounts")


def test_hand_calculated_reconciliation_is_not_a_sum_of_revenue_origins(isolated_repository):
    demo = prepare(isolated_repository, "pilot")
    _, report = CommerceStore(isolated_repository.root).get(demo["reconciliation_id"])
    assert report["store"] == {
        "unique_orders": 8,
        "eligible_orders": 6,
        "excluded_orders": 2,
        "net_sales": 640000,
        "gross_sales": 830000,
        "discounts": 40000,
        "merchandise_refunds": 150000,
        "net_sales_coverage": 1,
    }
    assert report["advertising"]["spend"] == 100000
    assert report["advertising"]["platform_reported_revenue"] == 1200000
    assert report["attribution"]["matched_net_sales"] == 515000
    assert {
        key: report["attribution"][key] for key in ["matched", "unmatched", "ambiguous", "excluded"]
    } == {
        "matched": 4,
        "unmatched": 1,
        "ambiguous": 1,
        "excluded": 2,
    }
    assert report["costs"]["total"] == 371000
    assert report["profit"]["contribution_after_ads"] == 169000
    assert report["profit"]["merchandise_mer"] == 6.4
    assert report["reference"]["net_sales_difference"] == 0
    assert report["reference"]["order_count_difference"] == 0
    assert not profit.assess(report)["eligible"]
    # Opt-in shipping uses only known charged-minus-refunded values.
    cfg = ReconcileConfig.model_validate({**report["config"], "include_shipping_income": True})
    assert reconcile.build(isolated_repository, cfg)["profit"]["contribution_after_ads"] == 189000


def test_unallocated_refunds_and_missing_discounts_remain_missing(isolated_repository):
    repo = isolated_repository
    staged = importer.stage(
        repo, (FIXTURES / "pilot-shopify.csv").read_bytes(), "orders.csv", "shopify"
    )
    config = options(staged)
    config.mapping.pop("merchandise_refunds")
    report = importer.validate(repo, staged["token"], config)
    assert report["can_import"] and report["unknown_net_sales"] == 2
    manifest = importer.validate(repo, staged["token"], config, commit=True)
    _, payload = CommerceStore(repo.root).get(manifest["id"])
    assert (
        reconcile.known_sum([row for row in payload["orders"] if row["eligible"]], "net_sales")
        is None
    )
    config.mapping.pop("discounts")
    assert (
        importer.validate(
            repo,
            importer.stage(
                repo, (FIXTURES / "pilot-shopify.csv").read_bytes(), "again.csv", "shopify"
            )["token"],
            config,
        )["unknown_net_sales"]
        == 6
    )


@pytest.mark.parametrize(
    "change,pattern",
    [
        (lambda rows: rows[1].update({"Subtotal": "1"}), "conflicting subtotal"),
        (lambda rows: rows[0].update({"Discount Amount": "3000"}), "exceed gross"),
        (lambda rows: rows[2].update({"merchandise_refunds": "3000"}), "refunds"),
        (lambda rows: rows[0].update({"ad_touch_at": "2026-01-02"}), "after the order"),
        (lambda rows: rows[0].update({"Currency": "USD"}), "currencies"),
        (lambda rows: rows[0].update({"Lineitem quantity": "1.5"}), "whole numbers"),
    ],
)
def test_order_integrity_errors_block_commit(isolated_repository, change, pattern):
    raw = altered("pilot-shopify.csv", change)
    staged = importer.stage(isolated_repository, raw, "bad.csv", "shopify")
    result = importer.validate(isolated_repository, staged["token"], options(staged))
    assert not result["can_import"] and pattern in result["errors"][0]
    with pytest.raises(DomainError):
        importer.validate(isolated_repository, staged["token"], options(staged), commit=True)


def test_duplicate_policy_and_timezone_disambiguation(isolated_repository):
    raw = altered("pilot-shopify.csv", lambda rows: rows.append(rows[0].copy()))
    staged = importer.stage(isolated_repository, raw, "duplicates.csv", "shopify")
    assert not importer.validate(isolated_repository, staged["token"], options(staged))[
        "can_import"
    ]
    report = importer.validate(
        isolated_repository, staged["token"], options(staged, duplicate_policy="drop")
    )
    assert report["can_import"] and report["orders"] == 8 and report["duplicate_rows"] == 1
    with pytest.raises(DomainError, match="offset"):
        importer.timestamp("2026-11-01T01:30:00", "America/New_York")
    assert importer.timestamp("2026-01-01T23:30:00Z", "Asia/Karachi").date() == date(2026, 1, 2)


def test_currency_rates_and_store_namespaces(isolated_repository):
    with pytest.raises(ValueError, match="exchange rate"):
        ImportConfig(name="test", store_id="test", mapping={}, original_currency="USD")
    with pytest.raises(ValueError, match="rate of one"):
        ImportConfig(name="test", store_id="test", mapping={}, exchange_rate=2)
    store = CommerceStore(isolated_repository.root)
    assert store.order_key("one", "123") != store.order_key("two", "123")
    raw = (
        b"order_id,ordered_at,financial_status,gross_item_sales,discounts,refunded_amount,"
        b"is_synthetic\n1,2026-01-01,paid,1.01,0,0,true\n"
    )
    manifest = imported(
        isolated_repository,
        "foreign.csv",
        "generic",
        raw=raw,
        order_grain="orders",
        original_currency="USD",
        exchange_rate=Decimal("280.125"),
    )
    _, payload = store.get(manifest["id"])
    assert payload["orders"][0]["net_sales"] == 28293  # 1.01 × 280.125 PKR, half-up paisa
    assert payload["orders"][0]["original_amounts"]["net_sales"] == 101


def test_sku_costs_and_explicit_zero_expenses(isolated_repository):
    repo = isolated_repository
    order = imported(repo)
    expense_raw = altered(
        "pilot-expenses.csv", lambda rows: [row.update({"cogs": ""}) for row in rows]
    )
    expense = imported(repo, "costs.csv", "expenses", raw=expense_raw, order_batch_id=order["id"])
    sku = imported(
        repo,
        "pilot-sku-costs.csv",
        "sku_costs",
        order_batch_id=order["id"],
        cogs_basis="net_refunded_quantity",
    )
    store = CommerceStore(repo.root)
    _, payload = store.get(order["id"])
    assert (
        reconcile.known_sum(
            list(reconcile.resolve_costs(store, order, payload, [expense["id"]]).values()), "cogs"
        )
        is None
    )
    costs = reconcile.resolve_costs(store, order, payload, [expense["id"], sku["id"]])
    assert costs[store.order_key("fictional-test", "#FIC-A")]["cogs"] == 110000
    assert costs[store.order_key("fictional-test", "#FIC-C")]["cogs"] == 0
    assert sum(sum(row.values()) for row in costs.values()) == 371000
    full = imported(repo, "pilot-expenses.csv", "expenses", order_batch_id=order["id"])
    with pytest.raises(DomainError, match="Both order COGS"):
        reconcile.resolve_costs(store, order, payload, [full["id"], sku["id"]])


def test_no_domain_name_inference_and_conflicting_evidence(isolated_repository):
    demo = prepare(isolated_repository, "pilot")
    store = CommerceStore(isolated_repository.root)
    _, payload = store.get(demo["order_batch_id"])
    _, report = store.get(demo["reconciliation_id"])
    cfg = ReconcileConfig.model_validate(report["config"])
    keys = reconcile.campaign_candidates(isolated_repository.read(demo["ad_dataset_id"]))
    organic = next(row for row in payload["orders"] if row["utm_source"] == "facebook.com")
    assert reconcile.match_order(organic, keys, cfg)[0] == "unmatched"
    direct = next(
        row for row in payload["orders"] if row["campaign_id"] == "fb-01" and row["eligible"]
    )
    contradictory = {**direct, "utm_source": "merchant-google", "utm_campaign": "winter-launch"}
    assert reconcile.match_order(contradictory, keys, cfg)[0] == "ambiguous"
    cfg.attribution_window_days = 0
    partial = next(
        row for row in payload["orders"] if row["financial_status"] == "partially_refunded"
    )
    assert reconcile.match_order(partial, keys, cfg)[0] == "unmatched"


def test_reference_discrepancy_and_scope_confirmations_gate_forecasts(isolated_repository):
    demo = prepare(isolated_repository, "pilot")
    _, report = CommerceStore(isolated_repository.root).get(demo["reconciliation_id"])
    cfg = ReconcileConfig.model_validate(report["config"])
    cfg.reference_net_sales = Decimal(6500)
    changed = reconcile.build(isolated_repository, cfg)
    assert changed["reference"]["net_sales_difference"] == -100
    assert any("discrepancies" in reason for reason in changed["profit"]["forecast_reasons"])
    cfg.timezones_confirmed = False
    with pytest.raises(DomainError, match="Confirm"):
        reconcile.build(isolated_repository, cfg)


def test_real_and_synthetic_never_reconcile(isolated_repository, monkeypatch):
    demo = prepare(isolated_repository, "pilot")
    _, report = CommerceStore(isolated_repository.root).get(demo["reconciliation_id"])
    get = isolated_repository.get
    # Explicit fake provenance only, to exercise the refusal boundary; no real data is claimed.
    monkeypatch.setattr(
        isolated_repository, "get", lambda key: get(key).model_copy(update={"is_synthetic": False})
    )
    with pytest.raises(DomainError, match="cannot be reconciled"):
        reconcile.build(isolated_repository, ReconcileConfig.model_validate(report["config"]))


def test_complete_history_fits_and_exact_profit_plan_is_source_bound(isolated_repository):
    demo = prepare(isolated_repository, "history")
    store = CommerceStore(isolated_repository.root)
    _, report = store.get(demo["reconciliation_id"])
    assessment = profit.assess(report)
    assert assessment["eligible"], assessment["reasons"]
    assert assessment["splits"]["train"]["rows"] == 270
    assert (
        assessment["splits"]["validation"]["rows"] == assessment["splits"]["holdout"]["rows"] == 90
    )
    request = ProfitConfig(
        reconciliation_id=demo["reconciliation_id"],
        budget=Decimal("5000.37"),
        start_date=date(2026, 10, 31),
        platforms=[PlatformLimit(platform=p) for p in assessment["parameters"]],
    )
    plan = profit.create(isolated_repository, request)
    assert sum(Decimal(str(row["budget"])) for row in plan["result"]["allocations"]) == Decimal(
        "5000.37"
    )
    assert all(
        row["minimum"] <= row["budget"] <= row["maximum"] for row in plan["result"]["allocations"]
    )
    assert plan["result"]["estimated_contribution_profit"] == pytest.approx(
        plan["result"]["estimated_contribution_before_ads"] - 5000.37
    )
    assert all(comparison["budget"] == 5000.37 for comparison in plan["comparisons"])
    with pytest.raises(DomainError, match="no supported profit forecast"):
        profit.create(isolated_repository, request.model_copy(update={"budget": Decimal(500)}))
    changed = copy.deepcopy(report)
    for row in changed["observations"]:
        if row["date"] >= assessment["splits"]["holdout"]["start"]:
            row["contribution_before_ads"] *= 100
    altered_assessment = profit.assess(changed)
    assert altered_assessment["parameters"] == assessment["parameters"]
    assert not altered_assessment["eligible"]


def test_api_pagination_exports_and_cascade_delete(isolated_repository):
    demo = prepare(isolated_repository, "pilot")
    meta = request("GET", f"/snapshots/{demo['order_batch_id']}").json()
    assert "orders" not in meta and meta["manifest"]["orders"] == 8
    rows = request(
        "GET",
        f"/snapshots/{demo['reconciliation_id']}/rows?table=links&status=unmatched&page_size=1",
    ).json()
    assert rows["total"] == 1 and len(rows["rows"]) == 1
    exported = request("GET", f"/snapshots/{demo['reconciliation_id']}/export").json()
    assert exported["money_unit"] == "paisa" and exported["orders_manifest"]["is_synthetic"]
    csv_export = request("GET", f"/snapshots/{demo['order_batch_id']}/export?format=csv")
    assert csv_export.status_code == 200 and "is_synthetic" in csv_export.text
    assert "#FIC-A" not in csv_export.text and "example.test" not in csv_export.text
    isolated_repository.delete(demo["ad_dataset_id"])
    assert request("GET", f"/snapshots/{demo['reconciliation_id']}").status_code == 404
    assert request("GET", f"/snapshots/{demo['order_batch_id']}").status_code == 200
    request("DELETE", f"/snapshots/{demo['order_batch_id']}")
    state = request("GET", "").json()
    assert not state["orders"] and not state["costs"] and state["selected_order_batch_id"] is None


def test_cancelled_status_and_refund_contradictions(isolated_repository):
    raw = altered("pilot-generic.csv", lambda rows: rows[0].update(financial_status="canceled"))
    manifest = imported(
        isolated_repository, "generic.csv", "generic", raw=raw, order_grain="orders"
    )
    _, payload = CommerceStore(isolated_repository.root).get(manifest["id"])
    cancelled = [row for row in payload["orders"] if row["financial_status"] == "canceled"]
    assert len(cancelled) == 1 and not cancelled[0]["eligible"]
    for changes in [
        {"financial_status": "refunded"},
        {"cancelled_at": "not-a-date"},
    ]:
        raw = altered("pilot-generic.csv", lambda rows: rows[0].update(changes))
        staged = importer.stage(isolated_repository, raw, "invalid.csv", "generic")
        assert not importer.validate(
            isolated_repository, staged["token"], options(staged, order_grain="orders")
        )["can_import"]


def test_sku_overlaps_and_cross_store_costs_are_rejected(isolated_repository):
    order = imported(isolated_repository)
    raw = altered(
        "pilot-sku-costs.csv",
        lambda rows: rows.append({**rows[0], "unit_cost": "1"}),
    )
    staged = importer.stage(isolated_repository, raw, "overlap.csv", "sku_costs")
    cfg = options(staged, order_batch_id=order["id"])
    result = importer.validate(isolated_repository, staged["token"], cfg)
    assert not result["can_import"] and "overlap" in result["errors"][0]
    cfg.store_id = "another-store"
    assert (
        "must match this store"
        in importer.validate(isolated_repository, staged["token"], cfg)["errors"][0]
    )


def test_missing_holdout_platform_and_negative_profit(isolated_repository):
    repo = isolated_repository
    demo = prepare(repo, "history")
    store = CommerceStore(repo.root)
    _, report = store.get(demo["reconciliation_id"])
    assessment = profit.assess(report)
    missing = copy.deepcopy(report)
    missing["observations"] = [
        row
        for row in missing["observations"]
        if row["platform"] != "YouTube" or row["date"] < assessment["splits"]["holdout"]["start"]
    ]
    result = profit.assess(missing)
    assert not result["eligible"] and "YouTube lacks holdout" in " ".join(result["reasons"])
    # Import actual, explicitly fictional costs that leave a small pre-ad margin.
    sales = {
        row["order_id"]: Decimal(row["gross_item_sales"])
        for row in csv.DictReader(io.StringIO((FIXTURES / "history-orders.csv").read_text()))
    }
    raw = altered(
        "history-costs.csv",
        lambda rows: [
            row.update(
                cogs=str((sales[row["order_id"]] * Decimal("0.95")).quantize(Decimal("0.01")))
            )
            for row in rows
        ],
    )
    staged = importer.stage(repo, raw, "low-margin.csv", "expenses")
    cfg = options(staged, order_batch_id=demo["order_batch_id"])
    cfg.store_id = "fictional-history"
    costs = importer.validate(repo, staged["token"], cfg, commit=True)
    cfg = ReconcileConfig.model_validate({**report["config"], "cost_batch_ids": [costs["id"]]})
    saved = reconcile.save_reconciliation(repo, cfg)
    plan = profit.create(
        repo,
        ProfitConfig(
            reconciliation_id=saved["manifest"]["id"],
            budget=Decimal("5000.37"),
            start_date=date(2026, 10, 31),
            platforms=[PlatformLimit(platform=p) for p in assessment["parameters"]],
        ),
    )
    assert plan["result"]["estimated_contribution_before_ads"] > 0
    assert plan["result"]["estimated_contribution_profit"] < 0
    exported = request("GET", f"/snapshots/{plan['manifest']['id']}/export").json()
    assert exported["money_unit"] == "PKR"


def test_whole_week_comparisons_and_partial_week_rejection(isolated_repository):
    from ads_optimizer.data.csv_importer import commit_import, stage_csv
    from ads_optimizer.domain import ImportOptions

    repo = isolated_repository
    demo = prepare(repo, "history")
    _, report = CommerceStore(repo.root).get(demo["reconciliation_id"])
    raw = altered("history-ads.csv", lambda rows: rows.__setitem__(slice(None), rows[:5]))
    staged = stage_csv(repo, raw, "weekly.csv", "generic")
    weekly = commit_import(
        repo,
        staged["token"],
        ImportOptions(
            mapping=staged["suggested_mapping"],
            confirmed=True,
            is_synthetic=True,
            date_granularity="weekly",
        ),
    )
    cfg = ReconcileConfig.model_validate(
        {
            **report["config"],
            "ad_dataset_id": weekly.id,
            "start_date": "2026-07-01",
            "end_date": "2026-07-07",
        }
    )
    result = reconcile.build(repo, cfg)
    assert result["store"]["unique_orders"] == 35
    assert any("daily ad observations" in r for r in result["profit"]["forecast_reasons"])
    cfg.end_date = date(2026, 7, 6)
    with pytest.raises(DomainError, match="whole reporting weeks"):
        reconcile.build(repo, cfg)


def test_staging_expiry_and_csv_formula_export(isolated_repository):
    import os
    import time

    repo = isolated_repository
    raw = altered("pilot-generic.csv", lambda rows: rows[0].update(campaign_id="=1+1"))
    staged = importer.stage(repo, raw, "orders.csv", "generic")
    cfg = options(staged, order_grain="orders")
    cfg.confirmed = False
    with pytest.raises(DomainError, match="Confirm permission"):
        importer.validate(repo, staged["token"], cfg, commit=True)
    cfg.confirmed = True
    manifest = importer.validate(repo, staged["token"], cfg, commit=True)
    result = request("GET", f"/snapshots/{manifest['id']}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(result.text)))
    assert any(row["campaign_id"] == "'=1+1" for row in rows)
    token = importer.stage(repo, raw, "expiry.csv", "generic")["token"]
    path = CommerceStore(repo.root).staging / f"{token}.json"
    yesterday = time.time() - 90000
    os.utime(path, (yesterday, yesterday))
    with pytest.raises(DomainError, match="expired"):
        CommerceStore(repo.root).staged(token)
    assert not path.exists()
    assert request("GET", "/examples/not-a-fixture").status_code == 404


def test_duplicate_personal_headers_are_removed_before_uniqueness_check(isolated_repository):
    staged = importer.stage(
        isolated_repository,
        b"order_id,Phone,Phone,Email,ordered_at\nO1,private,private,private,2026-01-01\n",
        "shopify-personal-headers.csv",
        "shopify",
    )
    assert staged["removed_columns"] == 3
    assert staged["headers"] == ["order_id", "ordered_at"]
    assert "private" not in json.dumps(
        CommerceStore(isolated_repository.root).staged(staged["token"])
    )
    with pytest.raises(DomainError, match="unique CSV headers"):
        importer.stage(isolated_repository, b"order_id,order_id\nO1,O1\n", "bad.csv", "generic")


def test_marked_test_order_sales_and_costs_are_excluded(isolated_repository):
    repo = isolated_repository
    demo = prepare(repo, "pilot")
    store = CommerceStore(repo.root)
    _, original = store.get(demo["reconciliation_id"])
    raw = altered("pilot-generic.csv", lambda rows: rows[0].update(is_test="true"))
    order = imported(repo, "marked.csv", "generic", raw=raw, order_grain="orders")
    costs = imported(repo, "pilot-expenses.csv", "expenses", order_batch_id=order["id"])
    cfg = ReconcileConfig.model_validate(
        {
            **original["config"],
            "order_batch_id": order["id"],
            "cost_batch_ids": [costs["id"]],
            "reference_net_sales": None,
            "reference_eligible_orders": None,
        }
    )
    result = reconcile.build(repo, cfg)
    assert result["store"]["eligible_orders"] == 5
    assert result["store"]["net_sales"] == 415000
    assert result["costs"]["total"] == 241000
    assert result["profit"]["contribution_after_ads"] == 74000


def test_financial_precision_limit_blocks_unsafe_browser_integers(isolated_repository):
    importer.require_exact_money([importer.MAX_EXACT_PAISA])
    with pytest.raises(DomainError, match="exact-paisa limit"):
        importer.require_exact_money([importer.MAX_EXACT_PAISA, 1])
    raw = (
        b"order_id,ordered_at,financial_status,currency,gross_item_sales,discounts,refunded_amount\n"
        b"O1,2026-01-01,paid,USD,10000000000,0,0\n"
    )
    staged = importer.stage(isolated_repository, raw, "extreme-fx.csv", "generic")
    cfg = options(
        staged, order_grain="orders", original_currency="USD", exchange_rate=Decimal(1000000)
    )
    result = importer.validate(isolated_repository, staged["token"], cfg)
    assert not result["can_import"] and "exact-paisa limit" in result["errors"][0]
