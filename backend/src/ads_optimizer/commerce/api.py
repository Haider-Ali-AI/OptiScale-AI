"""Local commerce API; all money is integer paisa unless explicitly labelled PKR."""

import csv
import io
import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ads_optimizer.analytics.metrics import safe_csv_cell
from ads_optimizer.commerce import importer, profit, reconcile
from ads_optimizer.commerce.contracts import ImportConfig, ProfitConfig, ReconcileConfig
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.data.repository import Repository, get_repository
from ads_optimizer.domain import MAX_UPLOAD_BYTES, DomainError

router = APIRouter(prefix="/api/v1/commerce", tags=["Commerce CSV pilot"])
Repo = Annotated[Repository, Depends(get_repository)]
EXAMPLES = {
    "shopify": "pilot-shopify.csv",
    "generic": "pilot-generic.csv",
    "expenses": "pilot-expenses.csv",
    "sku_costs": "pilot-sku-costs.csv",
    "pilot_ads": "pilot-ads.csv",
    "history_orders": "history-orders.csv",
    "history_ads": "history-ads.csv",
    "history_costs": "history-costs.csv",
}


def public_report(store, identifier):
    manifest, report = store.get(identifier)
    if manifest["kind"] in {"orders", "costs"}:
        return {"manifest": manifest, "money_unit": "paisa"}
    if manifest["kind"] == "reconciliation":
        return {
            "manifest": manifest,
            **{k: v for k, v in report.items() if k not in {"links", "observations"}},
            "links": report["links"][:20],
            "link_total": len(report["links"]),
            "assessment": profit.assess(report),
        }
    return {"manifest": manifest, **report}


@router.get("")
def state(repo: Repo):
    store = CommerceStore(repo.root)
    return {
        "selected_order_batch_id": store.selected(),
        **{
            kind: store.list(kind)[:50]
            for kind in ["orders", "costs", "reconciliation", "profit_plan"]
        },
        "money_unit": "paisa",
        "connected": False,
    }


class Selection(BaseModel):
    order_batch_id: str | None


@router.put("/selection")
def selection(value: Selection, repo: Repo):
    CommerceStore(repo.root).select(value.order_batch_id)
    return state(repo)


@router.post("/imports/preview")
async def preview(
    request: Request,
    repo: Repo,
    filename: str = Query(max_length=250),
    profile: Literal["shopify", "generic", "expenses", "sku_costs"] = "shopify",
):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
            raise DomainError("The CSV exceeds the 10 MiB limit.", 413)
        data.extend(chunk)
    return await run_in_threadpool(importer.stage, repo, bytes(data), filename, profile)


@router.post("/imports/{token}/validate")
def validate(token: str, config: ImportConfig, repo: Repo):
    return importer.validate(repo, token, config)


@router.post("/imports/{token}/commit", status_code=201)
def commit(token: str, config: ImportConfig, repo: Repo):
    return importer.validate(repo, token, config, commit=True)


@router.delete("/imports/{token}")
def discard(token: str, repo: Repo):
    CommerceStore(repo.root).discard(token)
    return {"discarded": token}


@router.get("/snapshots/{identifier}")
def snapshot(identifier: str, repo: Repo):
    return public_report(CommerceStore(repo.root), identifier)


@router.get("/snapshots/{identifier}/rows")
def rows(
    identifier: str,
    repo: Repo,
    table: Literal["orders", "items", "costs", "links"] = "orders",
    status: Literal["all", "matched", "unmatched", "ambiguous", "excluded"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    _, payload = CommerceStore(repo.root).get(identifier)
    values = payload.get(table, [])
    if table == "links" and status != "all":
        values = [row for row in values if row["status"] == status]
    first = (page - 1) * page_size
    return {
        "rows": values[first : first + page_size],
        "total": len(values),
        "page": page,
        "page_size": page_size,
        "money_unit": "paisa",
    }


@router.delete("/snapshots/{identifier}")
def delete(identifier: str, repo: Repo):
    return {"deleted_snapshots": CommerceStore(repo.root).delete(identifier)}


@router.get("/campaigns/{ad_dataset_id}")
def campaigns(ad_dataset_id: str, repo: Repo):
    repo.get(ad_dataset_id)
    return {
        "campaigns": [
            {"platform": key[0], "account_id": key[1], "campaign_id": key[2]}
            for key in reconcile.campaign_candidates(repo.read(ad_dataset_id))
        ][:1000]
    }


@router.post("/reconciliations", status_code=201)
def reconciliation(config: ReconcileConfig, repo: Repo):
    result = reconcile.save_reconciliation(repo, config)
    _, payload = CommerceStore(repo.root).get(result["manifest"]["id"])
    return {**result, "assessment": profit.assess(payload)}


@router.post("/profit-plans", status_code=201)
def profit_plan(config: ProfitConfig, repo: Repo):
    return profit.create(repo, config)


@router.get("/snapshots/{identifier}/export")
def export(
    identifier: str,
    repo: Repo,
    format: Literal["json", "csv"] = "json",
    table: Literal["orders", "items", "costs", "links"] = "orders",
):
    manifest, payload = CommerceStore(repo.root).get(identifier)
    if format == "json":
        body = json.dumps(
            {
                "manifest": manifest,
                "money_unit": "PKR" if manifest["kind"] == "profit_plan" else "paisa",
                **payload,
            },
            indent=2,
        )
    else:
        values = payload.get(table, [])
        if manifest["kind"] == "profit_plan":
            values = payload["result"]["allocations"]
        if not values:
            raise DomainError("This snapshot has no rows for the selected export table.")
        out = io.StringIO()
        fields = list(values[0])
        writer = csv.writer(out)
        writer.writerow([*fields, "source", "is_synthetic", "money_unit"])
        for row in values:
            writer.writerow(
                [
                    *[
                        safe_csv_cell(
                            json.dumps(row.get(k))
                            if isinstance(row.get(k), (dict, list))
                            else ""
                            if row.get(k) is None
                            else row.get(k)
                        )
                        for k in fields
                    ],
                    "commerce_csv_pilot",
                    manifest["is_synthetic"],
                    "PKR" if manifest["kind"] == "profit_plan" else "paisa",
                ]
            )
        body = out.getvalue()
    return Response(
        body,
        media_type="application/json" if format == "json" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="commerce-'
            f'{"synthetic" if manifest["is_synthetic"] else "imported"}-{identifier[:8]}.{format}"'
        },
    )


@router.get("/examples/{name}")
def example(name: str):
    if name not in EXAMPLES:
        raise DomainError("Choose an available fictional commerce example.", 404)
    path = Path(__file__).parent / "fixtures" / EXAMPLES[name]
    return Response(
        path.read_bytes(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="synthetic-{path.name}"',
        },
    )


@router.post("/demo", status_code=201)
def demo(repo: Repo, variant: Literal["pilot", "history"] = "pilot"):
    from ads_optimizer.commerce.demo import prepare

    return prepare(repo, variant)
