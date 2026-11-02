"""Order-cohort comparisons and evidence-supported associations, never causal attribution."""

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ads_optimizer.commerce.contracts import ReconcileConfig
from ads_optimizer.commerce.importer import COST_FIELDS, require_exact_money
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.data.provenance import provenance_review
from ads_optimizer.domain import DomainError


def cents(value):
    return (
        None
        if value is None
        else int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    )


def known_sum(rows, field):
    values = [row.get(field) for row in rows]
    return sum(values) if all(value is not None for value in values) else None


def campaign_key(row):
    return row["platform"], row.get("account_id", "unknown"), row.get("campaign_id", "unknown")


def campaign_candidates(frame):
    return sorted(
        {
            campaign_key(row)
            for row in frame.to_dict("records")
            if row.get("campaign_id") not in {None, "", "unknown"}
        }
    )


def resolve_costs(store, manifest, payload, identifiers):
    expenses, products = {}, []
    row_count = 0
    for identifier in identifiers:
        meta, values = store.get(identifier, "costs")
        row_count += meta["cost_rows"]
        if row_count > 100000:
            raise DomainError(
                "Select at most one hundred thousand combined cost rows for this local pilot."
            )
        if (
            meta["order_batch_id"] != manifest["id"]
            or meta["is_synthetic"] != manifest["is_synthetic"]
        ):
            raise DomainError("Select costs belonging to this orders snapshot and source type.")
        if meta["profile"] == "expenses":
            for row in values["costs"]:
                target = expenses.setdefault(row["order_key"], {})
                for field in COST_FIELDS:
                    if row[field] is not None:
                        if field in target:
                            raise DomainError(
                                (
                                    "Selected cost snapshots overlap an order expense. "
                                    "Select one source per cost field."
                                )
                            )
                        target[field] = row[field]
        else:
            products.extend(values["costs"])
    product_index = defaultdict(list)
    for cost in products:
        product_index[cost["sku"]].append(cost)
    for records in product_index.values():
        records.sort(key=lambda row: row["start"])
        if any(
            current["start"] <= previous["end"] for previous, current in zip(records, records[1:])
        ):
            raise DomainError("Selected SKU cost snapshots have overlapping effective dates.")
    starts = {sku: [row["start"] for row in records] for sku, records in product_index.items()}
    items = defaultdict(list)
    for item in payload["items"]:
        items[item["order_key"]].append(item)
    result = {}
    for order in payload["orders"]:
        row = {field: expenses.get(order["order_key"], {}).get(field) for field in COST_FIELDS}
        sku_costs = []
        for item in items[order["order_key"]]:
            records = product_index[item["sku"]]
            index = bisect_right(starts.get(item["sku"], []), order["date"]) - 1
            if index < 0 or records[index]["end"] < order["date"] or item["quantity"] is None:
                sku_costs.append(None)
                continue
            cost = records[index]
            quantity = item["quantity"]
            if cost["basis"] == "net_refunded_quantity":
                if item["refunded_quantity"] is None:
                    sku_costs.append(None)
                    continue
                quantity -= item["refunded_quantity"]
            sku_costs.append(quantity * cost["unit_cost"])
        derived = sum(sku_costs) if sku_costs and all(v is not None for v in sku_costs) else None
        if row["cogs"] is not None and derived is not None and products:
            raise DomainError(
                "Both order COGS and SKU-derived COGS cover an order. Choose one COGS source."
            )
        if row["cogs"] is None:
            row["cogs"] = derived
        result[order["order_key"]] = row
    require_exact_money(value for row in result.values() for value in row.values())
    return result


def match_order(order, keys, config, by_id=None, mapped=None):
    if not order["eligible"]:
        return "excluded", None, order["exclusion_reason"], None
    lag = (
        (date.fromisoformat(order["date"]) - date.fromisoformat(order["touch_date"])).days
        if order["touch_date"]
        else None
    )
    if lag is not None and (lag < 0 or lag > config.attribution_window_days):
        return "unmatched", None, "Provided touch is outside the selected attribution window.", lag
    direct = (
        {
            key
            for key in (by_id.get(order["campaign_id"], []) if by_id is not None else keys)
            if key[2] == order["campaign_id"]
            and (not order["account_id"] or key[1] == order["account_id"])
            and (not order["platform"] or key[0] == order["platform"])
        }
        if order["campaign_id"]
        else set()
    )
    merchant = set()
    for mapping in (
        mapped.get((order["utm_source"], order["utm_campaign"]), [])
        if mapped is not None
        else config.mappings
    ):
        if (
            mapping.utm_source == order["utm_source"]
            and mapping.utm_campaign == order["utm_campaign"]
        ):
            merchant |= {
                key
                for key in (by_id.get(mapping.campaign_id, []) if by_id is not None else keys)
                if key[0] == mapping.platform
                and key[2] == mapping.campaign_id
                and (not mapping.account_id or key[1] == mapping.account_id)
            }
    if direct and merchant and not direct & merchant:
        return "ambiguous", None, "Campaign identifier and confirmed UTM mapping disagree.", lag
    if order["campaign_id"] and not direct and merchant:
        return (
            "ambiguous",
            None,
            "The supplied campaign identifier conflicts with the mapped campaign.",
            lag,
        )
    candidates = direct & merchant if direct and merchant else direct or merchant
    if len(candidates) != 1:
        return (
            ("ambiguous" if candidates else "unmatched"),
            None,
            (
                "Campaign identifier matches multiple accounts/platforms."
                if candidates
                else "No verifiable campaign identifier or confirmed UTM mapping matched."
            ),
            lag,
        )
    return (
        "matched",
        next(iter(candidates)),
        ("Provided campaign identifier" if direct else "Merchant-confirmed exact UTM mapping"),
        lag,
    )


def build(repo, config: ReconcileConfig):
    if not config.ad_scope_confirmed or not config.timezones_confirmed:
        raise DomainError(
            "Confirm that the ad report belongs to this store and uses comparable local dates."
        )
    if config.mappings and not config.mappings_confirmed:
        raise DomainError("Confirm the campaign evidence behind the UTM mappings.")
    store = CommerceStore(repo.root)
    manifest, payload = store.get(config.order_batch_id, "orders")
    ad = repo.get(config.ad_dataset_id)
    if ad.is_synthetic != manifest["is_synthetic"]:
        raise DomainError("Synthetic and real sources cannot be reconciled together.")
    start, end = config.start_date.isoformat(), config.end_date.isoformat()
    if start < manifest["period_start"] or end > manifest["period_end"]:
        raise DomainError("Choose a comparison window within the declared orders coverage.")
    period = 7 if ad.date_granularity == "weekly" else 1
    if (
        start < ad.date_start
        or end > (date.fromisoformat(ad.date_end) + timedelta(days=period - 1)).isoformat()
    ):
        raise DomainError("Choose a comparison window within the advertising report coverage.")
    frame = repo.read(ad.id)
    period_end = frame.date.map(
        lambda d: (date.fromisoformat(d) + timedelta(days=period - 1)).isoformat()
    )
    intersecting = (frame.date <= end) & (period_end >= start)
    complete = (frame.date >= start) & (period_end <= end)
    if (intersecting & ~complete).any():
        raise DomainError("Weekly ads require whole reporting weeks in the comparison window.")
    frame = frame[complete].copy()
    if frame.empty:
        raise DomainError("No ad observations fall within this comparison window.")
    orders = [row for row in payload["orders"] if start <= row["date"] <= end]
    if not orders:
        raise DomainError("No orders fall within this comparison window.")
    eligible = [row for row in orders if row["eligible"]]
    costs = resolve_costs(store, manifest, payload, config.cost_batch_ids)
    keys = campaign_candidates(frame)
    for mapping in config.mappings:
        if not any(
            k[0] == mapping.platform
            and k[2] == mapping.campaign_id
            and (not mapping.account_id or k[1] == mapping.account_id)
            for k in keys
        ):
            raise DomainError(
                "A UTM mapping targets no campaign/account in the compared ad report."
            )
    links = []
    by_id, mapped = defaultdict(list), defaultdict(list)
    for key in keys:
        by_id[key[2]].append(key)
    for mapping in config.mappings:
        mapped[(mapping.utm_source, mapping.utm_campaign)].append(mapping)
    for order in orders:
        status, key, evidence, lag = match_order(order, keys, config, by_id, mapped)
        if status == "matched" and order["touch_date"] and not start <= order["touch_date"] <= end:
            status, key, evidence = (
                "unmatched",
                None,
                "Provided touch falls outside the comparison period.",
            )
        links.append(
            {
                "order_key": order["order_key"],
                "date": order["date"],
                "status": status,
                "platform": key[0] if key else None,
                "account_id": key[1] if key else None,
                "campaign_id": key[2] if key else None,
                "evidence": evidence,
                "lag_days": lag,
                "net_sales": order["net_sales"],
                "touch_date": order["touch_date"],
            }
        )
    counts = Counter(link["status"] for link in links)
    matched = [link for link in links if link["status"] == "matched"]
    net = known_sum(eligible, "net_sales")
    spend = sum(cents(value) for value in frame.spend) if frame.spend.notna().all() else None
    platform_revenue = (
        sum(cents(value) for value in frame.revenue) if frame.revenue.notna().all() else None
    )
    # Include recorded expenses on cancelled/pending orders, but never test transactions.
    financial_orders = [row for row in orders if not row["is_test"]]
    coverage = {
        field: sum(costs[row["order_key"]][field] is not None for row in financial_orders)
        / len(financial_orders)
        if financial_orders
        else None
        for field in COST_FIELDS
    }
    cost_totals = {
        field: known_sum([costs[row["order_key"]] for row in financial_orders], field)
        for field in COST_FIELDS
    }
    cost_sum = (
        sum(cost_totals.values()) if all(v is not None for v in cost_totals.values()) else None
    )
    shipping = 0
    if config.include_shipping_income:
        shipping = (
            sum(row["shipping_charged"] - row["shipping_refunded"] for row in eligible)
            if all(
                row["shipping_charged"] is not None and row["shipping_refunded"] is not None
                for row in eligible
            )
            else None
        )
    contribution = (
        net + shipping - cost_sum - spend
        if all(v is not None for v in [net, shipping, cost_sum, spend])
        else None
    )
    require_exact_money([net, spend, platform_revenue, cost_sum, shipping, contribution])
    reasons = []
    reasons.extend(provenance_review(ad))
    cells = set(zip(frame.date, frame.platform, strict=True))
    if any((link["date"], link["platform"]) not in cells for link in matched):
        reasons.append(
            (
                "Some matched orders have no same-day advertising observation; a profit"
                " response cannot be fitted."
            )
        )
    definitions = manifest["definitions"]
    if not definitions["complete_export"]:
        reasons.append(
            "Confirm a complete orders export over explicit coverage dates before forecasting."
        )
    if not definitions["refunds_verified"]:
        reasons.append("Refund completeness at the snapshot date has not been verified.")
    if not eligible or any(counts[k] for k in ["unmatched", "ambiguous"]):
        reasons.append(
            "Profit forecasts require every eligible order to have an unambiguous evidenced match."
        )
    if any(link["lag_days"] != 0 for link in matched):
        reasons.append(
            (
                "The pilot forecast requires known same-day touches; missing/lagged "
                "touches remain descriptive only."
            )
        )
    if net is None or cost_sum is None or shipping is None or spend is None or spend <= 0:
        reasons.append(
            (
                "Complete net sales, every variable-cost category, shipping definition "
                "and positive ad spend are required."
            )
        )
    if ad.date_granularity != "daily":
        reasons.append(
            (
                "The pilot profit forecast requires daily ad observations; weekly "
                "comparisons remain descriptive."
            )
        )
    if any(
        not row["eligible"]
        and not row["is_test"]
        and sum(v for v in costs[row["order_key"]].values() if v is not None) > 0
        for row in orders
    ):
        reasons.append(
            (
                "Recorded costs on excluded orders are included in descriptive profit; "
                "forecasting their incidence is not implemented."
            )
        )
    reference = {
        "provided_net_sales": str(config.reference_net_sales)
        if config.reference_net_sales is not None
        else None,
        "net_sales_difference": (net - cents(config.reference_net_sales)) / 100
        if net is not None and config.reference_net_sales is not None
        else None,
        "provided_eligible_orders": config.reference_eligible_orders,
        "order_count_difference": len(eligible) - config.reference_eligible_orders
        if config.reference_eligible_orders is not None
        else None,
        "origin": "User-provided order-cohort reference, not fetched from Shopify.",
    }
    if reference["net_sales_difference"] not in {None, 0} or reference[
        "order_count_difference"
    ] not in {None, 0}:
        reasons.append(
            "Resolve discrepancies against the supplied store reference before forecasting."
        )
    # Aggregate compatible daily platform grain, never join orders onto repeated ad segments.
    observations = []
    order_lookup = {row["order_key"]: row for row in eligible}
    matched_groups = defaultdict(list)
    for link in matched:
        matched_groups[(link["date"], link["platform"])].append(order_lookup[link["order_key"]])
    maturity = (
        date.fromisoformat(definitions["snapshot_as_of"]) - timedelta(days=config.maturity_days)
    ).isoformat()
    for (day, platform), group in frame.groupby(["date", "platform"]):
        rows = matched_groups[(day, platform)]
        daily_net = known_sum(rows, "net_sales")
        daily_costs = [costs[row["order_key"]] for row in rows]
        daily_cost = (
            sum(sum(c[field] for field in COST_FIELDS) for c in daily_costs)
            if all(all(c[field] is not None for field in COST_FIELDS) for c in daily_costs)
            else None
        )
        shipping_income = 0
        if config.include_shipping_income:
            shipping_income = (
                sum(row["shipping_charged"] - row["shipping_refunded"] for row in rows)
                if all(
                    row["shipping_charged"] is not None and row["shipping_refunded"] is not None
                    for row in rows
                )
                else None
            )
        observations.append(
            {
                "date": day,
                "platform": platform,
                "spend": sum(cents(v) for v in group.spend) if group.spend.notna().all() else None,
                "net_sales": daily_net,
                "variable_costs": daily_cost,
                "contribution_before_ads": daily_net + shipping_income - daily_cost
                if all(v is not None for v in [daily_net, shipping_income, daily_cost])
                else None,
                "mature": day <= maturity,
            }
        )
    return {
        "config": config.model_dump(mode="json"),
        "orders_manifest": manifest,
        "ad_source": ad.model_dump(mode="json"),
        "store": {
            "unique_orders": len(orders),
            "eligible_orders": len(eligible),
            "excluded_orders": len(orders) - len(eligible),
            "net_sales": net,
            "gross_sales": known_sum(eligible, "gross"),
            "discounts": known_sum(eligible, "discounts"),
            "merchandise_refunds": known_sum(eligible, "merchandise_refunds"),
            "net_sales_coverage": sum(row["net_sales"] is not None for row in eligible)
            / len(eligible)
            if eligible
            else None,
        },
        "advertising": {
            "spend": spend,
            "platform_reported_revenue": platform_revenue,
            "reported_roas": platform_revenue / spend
            if platform_revenue is not None and spend
            else None,
        },
        "attribution": {
            **{name: counts[name] for name in ["matched", "unmatched", "ambiguous", "excluded"]},
            "matched_net_sales": known_sum(matched, "net_sales"),
            "order_coverage": len(matched) / len(eligible) if eligible else None,
            "unknown_lag_orders": sum(link["lag_days"] is None for link in matched),
        },
        "costs": {"coverage": coverage, "totals": cost_totals, "total": cost_sum},
        "profit": {
            "contribution_after_ads": contribution,
            "shipping_income": shipping,
            "merchandise_mer": net / spend if net is not None and spend else None,
            "margin": contribution / (net + shipping)
            if contribution is not None and net + shipping > 0
            else None,
            "forecast_reasons": reasons,
        },
        "reference": reference,
        "links": links,
        "observations": observations,
        "notice": (
            "Order-cohort merchandise sales at snapshot; tax excluded. Platform-reported revenue, "
        )
        + (
            "store sales and matched sales are different origins, never added. "
            "Matches are observational, not causal."
        ),
    }


def save_reconciliation(repo, config):
    report = build(repo, config)
    meta = CommerceStore(repo.root).save(
        "reconciliation",
        {
            "name": "Commerce reconciliation",
            "store_id": report["orders_manifest"]["store_id"],
            "is_synthetic": report["orders_manifest"]["is_synthetic"],
            "order_batch_id": config.order_batch_id,
            "ad_dataset_id": config.ad_dataset_id,
            "dependencies": [config.order_batch_id, *config.cost_batch_ids],
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
        },
        report,
    )
    return {
        "manifest": meta,
        **{k: v for k, v in report.items() if k not in {"links", "observations"}},
        "links": report["links"][:20],
        "link_total": len(report["links"]),
    }
