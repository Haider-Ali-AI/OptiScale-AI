"""Reproducible fictional demonstrations through the real normalizers and catalog."""

from datetime import date
from pathlib import Path

from ads_optimizer.commerce.contracts import CampaignMapping, ImportConfig, ReconcileConfig
from ads_optimizer.commerce.importer import stage, validate
from ads_optimizer.commerce.reconcile import save_reconciliation
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.data.csv_importer import commit_import, stage_csv
from ads_optimizer.data.repository import frame_fingerprint
from ads_optimizer.domain import DomainError, ImportOptions

FIXTURES = Path(__file__).parent / "fixtures"


def prepare(repo, variant):
    prefix = "history" if variant == "history" else "pilot"
    store_id = f"fictional-{prefix}"
    store = CommerceStore(repo.root)
    before = repo.selected()
    ad_file = FIXTURES / f"{prefix}-ads.csv"
    staged_ad = stage_csv(repo, ad_file.read_bytes(), ad_file.name, "generic")
    try:
        ad = commit_import(
            repo,
            staged_ad["token"],
            ImportOptions(
                name=f"Fictional commerce {prefix} ads",
                mapping=staged_ad["suggested_mapping"],
                confirmed=True,
                is_synthetic=True,
            ),
        )
    except DomainError as error:
        if error.status != 409:
            raise
        # Exact supplied fixture inputs, not an arbitrary source with a similar name.
        from ads_optimizer.data.csv_importer import validate_import

        frame, _, _ = validate_import(
            repo,
            staged_ad["token"],
            ImportOptions(
                mapping=staged_ad["suggested_mapping"],
                is_synthetic=True,
                confirmed=True,
            ),
        )
        fingerprint = frame_fingerprint(frame)
        ad = next(
            meta for meta in repo.list() if frame_fingerprint(repo.read(meta.id)) == fingerprint
        )
        (repo.root / "staging" / f"{staged_ad['token']}.json").unlink(missing_ok=True)
    finally:
        repo.select(before.id if before else None)
    existing = next(
        (
            meta
            for meta in store.list("orders")
            if meta["store_id"] == store_id
            and meta["is_synthetic"]
            and meta["profile"] == ("generic" if prefix == "history" else "shopify")
        ),
        None,
    )
    start, end = (
        (date(2026, 7, 1), date(2026, 9, 28))
        if prefix == "history"
        else (date(2026, 1, 1), date(2026, 1, 3))
    )
    if existing:
        order = existing
        store.select(order["id"])
    else:
        path = FIXTURES / ("history-orders.csv" if prefix == "history" else "pilot-shopify.csv")
        staged = stage(
            repo, path.read_bytes(), path.name, "generic" if prefix == "history" else "shopify"
        )
        order = validate(
            repo,
            staged["token"],
            ImportConfig(
                name=f"Fictional {prefix} orders",
                store_id=store_id,
                mapping=staged["suggested_mapping"],
                is_synthetic=True,
                confirmed=True,
                order_grain="orders" if prefix == "history" else "line_items",
                period_start=start,
                period_end=end,
                complete_export=True,
                refunds_verified=True,
                snapshot_as_of=date(2026, 10, 30),
                subtotal_basis="after_discounts",
            ),
            commit=True,
        )
    cost = next(
        (
            meta
            for meta in store.list("costs")
            if meta["order_batch_id"] == order["id"] and meta["profile"] == "expenses"
        ),
        None,
    )
    if not cost:
        path = FIXTURES / ("history-costs.csv" if prefix == "history" else "pilot-expenses.csv")
        staged = stage(repo, path.read_bytes(), path.name, "expenses")
        cost = validate(
            repo,
            staged["token"],
            ImportConfig(
                name=f"Fictional {prefix} costs",
                store_id=store_id,
                mapping=staged["suggested_mapping"],
                order_batch_id=order["id"],
                is_synthetic=True,
                confirmed=True,
            ),
            commit=True,
        )
    mappings = (
        [
            CampaignMapping(
                utm_source="merchant-google",
                utm_campaign="winter-launch",
                platform="Google",
                campaign_id="g-01",
                account_id="main",
            )
        ]
        if prefix == "pilot"
        else []
    )
    result = save_reconciliation(
        repo,
        ReconcileConfig(
            order_batch_id=order["id"],
            ad_dataset_id=ad.id,
            cost_batch_ids=[cost["id"]],
            start_date=start,
            end_date=end,
            ad_scope_confirmed=True,
            timezones_confirmed=True,
            mappings=mappings,
            mappings_confirmed=True,
            reference_net_sales=6400 if prefix == "pilot" else None,
            reference_eligible_orders=6 if prefix == "pilot" else 450,
        ),
    )
    return {
        "order_batch_id": order["id"],
        "ad_dataset_id": ad.id,
        "cost_batch_ids": [cost["id"]],
        "reconciliation_id": result["manifest"]["id"],
        "notice": (
            "Fictional fixture only; actual import/reconciliation code, not merchant validation."
        ),
    }
