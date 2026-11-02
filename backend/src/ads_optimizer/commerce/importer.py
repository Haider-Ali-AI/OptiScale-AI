"""Preview -> explicit mapping/definitions -> validated immutable commerce snapshot."""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from ads_optimizer.commerce.contracts import ImportConfig
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.domain import MAX_IMPORT_ROWS, MAX_UPLOAD_BYTES, DomainError

ALIASES = {
    "order_id": ["Name", "order_id", "Order ID", "Id"],
    "ordered_at": ["Created at", "ordered_at", "Order Date"],
    "financial_status": ["Financial Status", "financial_status", "payment_status"],
    "fulfillment_status": ["Fulfillment Status", "fulfillment_status"],
    "currency": ["Currency", "currency"],
    "store_id": ["store_id"],
    "gross_item_sales": ["gross_item_sales", "Gross item sales"],
    "subtotal": ["Subtotal", "subtotal"],
    "discounts": ["Discount Amount", "discounts"],
    "refunded_amount": ["Refunded Amount", "refunded_amount"],
    "merchandise_refunds": ["Merchandise Refunds", "merchandise_refunds"],
    "shipping_charged": ["Shipping", "shipping_charged"],
    "shipping_refunded": ["Shipping Refunded", "shipping_refunded"],
    "tax": ["Taxes", "tax"],
    "cancelled_at": ["Canceled at", "cancelled_at", "Cancelled at"],
    "is_test": ["Test", "is_test"],
    "is_synthetic": ["is_synthetic"],
    "sku": ["Lineitem SKU", "sku", "SKU"],
    "quantity": ["Lineitem quantity", "quantity"],
    "unit_price": ["Lineitem price", "unit_price"],
    "line_discount": ["Lineitem discount", "line_discount"],
    "line_item_id": ["line_item_id"],
    "refunded_quantity": ["refunded_quantity"],
    "campaign_id": ["campaign_id", "Ad campaign ID"],
    "account_id": ["account_id"],
    "platform": ["platform", "Ad platform"],
    "utm_source": ["utm_source"],
    "utm_campaign": ["utm_campaign"],
    "ad_touch_at": ["ad_touch_at"],
    "cogs": ["cogs", "COGS"],
    "payment_fees": ["payment_fees", "Payment fees"],
    "fulfillment": ["fulfillment", "Fulfillment cost"],
    "packaging": ["packaging"],
    "other_variable_costs": ["other_variable_costs"],
    "unit_cost": ["unit_cost"],
    "effective_from": ["effective_from"],
    "effective_to": ["effective_to"],
}
COST_FIELDS = ["cogs", "payment_fees", "fulfillment", "packaging", "other_variable_costs"]
PROFILES = {"shopify", "generic", "expenses", "sku_costs"}
# Leave ample headroom for integer JSON parsing and cent display after dividing by 100.
MAX_EXACT_PAISA = 10**14


def require_exact_money(values):
    if sum(abs(value) for value in values if value is not None) > MAX_EXACT_PAISA:
        raise DomainError("These financial totals exceed the local pilot's exact-paisa limit.")


def payload_numbers(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from payload_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from payload_numbers(child)
    elif type(value) is int:
        yield value


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def personal_header(value):
    word = normalized(value)
    return any(
        term in word
        for term in [
            "email",
            "phone",
            "address",
            "billing",
            "shippingname",
            "shippingstreet",
            "shippingcity",
            "shippingzip",
            "shippingcountry",
            "shippingprovince",
            "customer",
            "paymentreference",
            "paymentid",
            "cardnumber",
            "notes",
            "noteattributes",
            "ipaddress",
            "firstname",
            "lastname",
        ]
    ) or word in {"tags", "employee", "acceptsmarketing", "deviceid", "lineitemname"}


def stage(repo, raw, filename, profile):
    if profile not in PROFILES:
        raise DomainError("Choose Shopify, generic orders, order expenses or SKU costs.")
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise DomainError("Use a nonempty UTF-8 CSV of at most 10 MiB.", 413)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        headers = reader.fieldnames or []
        retained = [header for header in headers if not personal_header(header)]
        if not headers or len(headers) > 100 or len(set(retained)) != len(retained):
            raise DomainError("Use unique CSV headers, with at most one hundred columns.")
        headers = retained
        rows = []
        for row in reader:
            if len(rows) >= MAX_IMPORT_ROWS:
                raise DomainError("Commerce imports are limited to one hundred thousand rows.")
            if None in row or any(value is None for value in row.values()):
                raise DomainError(
                    "Every CSV row must have the same number of columns as the header."
                )
            rows.append({key: row[key].strip() for key in headers})
    except (UnicodeDecodeError, csv.Error) as error:
        raise DomainError("Use a valid UTF-8 comma-separated CSV.") from error
    if not rows:
        raise DomainError("This CSV has no data rows.")
    suggestions = {}
    for field, aliases in ALIASES.items():
        if profile != "shopify" and field == "order_id":
            aliases = ["order_id", "Order ID", "Id", "Name"]
        match = next(
            (
                header
                for alias in aliases
                for header in headers
                if normalized(alias) == normalized(header)
            ),
            None,
        )
        if match:
            suggestions[field] = match
    if profile in {"shopify", "generic"} and not suggestions.get("order_id"):
        if any(normalized(h) in {"impressions", "clicks", "spend"} for h in headers):
            raise DomainError("This appears to be an advertising report. Use Data Studio for ads.")
    store = CommerceStore(repo.root)
    token = store.stage(
        {
            "rows": rows,
            "headers": headers,
            "profile": profile,
            "filename": Path(filename.replace("\\", "/")).name[:250],
        }
    )
    return {
        "token": token,
        "profile": profile,
        "headers": headers,
        "suggested_mapping": suggestions,
        "input_rows": len(rows),
        "removed_columns": len(reader.fieldnames) - len(headers),
        "fields": list(ALIASES),
        "notice": "Recognized personal columns removed. Raw order IDs will be pseudonymized. "
        "Only mapped canonical fields survive saving. Preview expires after a day.",
    }


def amount(value, currency):
    if value == "":
        return None
    if value.startswith(currency + " "):
        value = value[len(currency) + 1 :]
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", value):
        raise DomainError("Money needs nonnegative decimal-dot amounts with at most two decimals.")
    result = Decimal(value.replace(",", ""))
    if result > Decimal("10000000000"):
        raise DomainError("A monetary value exceeds the local import limit.")
    return int(result * 100)


def count(value):
    if not value:
        return None
    if not re.fullmatch(r"\d+", value) or int(value) > 1000000:
        raise DomainError("Quantities need nonnegative whole numbers within the import limit.")
    return int(value)


def boolean(value):
    if value.lower() in {"true", "yes", "1"}:
        return True
    if value.lower() in {"false", "no", "0", ""}:
        return False
    raise DomainError("Boolean markers must be true/false, yes/no or one/zero.")


def timestamp(value, zone):
    if not value:
        raise DomainError("Every order needs an ISO date or timestamp.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        tz = ZoneInfo(zone)
        if result.tzinfo is None:
            first, second = result.replace(tzinfo=tz, fold=0), result.replace(tzinfo=tz, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise ValueError("ambiguous or nonexistent local time")
            result = first
        return result.astimezone(tz)
    except ValueError as error:
        raise DomainError(
            "Use unambiguous ISO timestamps; provide an offset at daylight-saving boundaries."
        ) from error


def identifier(value):
    if len(value) > 200 or "@" in value or "\n" in value or "\r" in value:
        raise DomainError("Use nonpersonal identifiers of at most two hundred characters.")
    return value


def synthetic(rows, options):
    values = {boolean(row["is_synthetic"]) for row in rows if row.get("is_synthetic")}
    if len(values) > 1:
        raise DomainError("Synthetic and real rows must be imported as separate snapshots.")
    return options.is_synthetic or values == {True}


def normalize(store, staged, options):
    if not options.mapping.get("order_id") and staged["profile"] != "sku_costs":
        raise DomainError("Map an order identifier before continuing.")
    if any(
        field not in ALIASES or column not in staged["headers"]
        for field, column in options.mapping.items()
    ):
        raise DomainError("Choose recognized canonical fields and available source columns.")
    if len(set(options.mapping.values())) != len(options.mapping):
        raise DomainError("Map each source column only once.")
    rows = [
        {field: row[column] for field, column in options.mapping.items()} for row in staged["rows"]
    ]
    is_synthetic = synthetic(rows, options)
    for header in staged["headers"]:
        if normalized(header) in {
            "issynthetic",
            "dateissynthetic",
            "revenueissynthetic",
            "salesissynthetic",
            "costsissynthetic",
        }:
            values = {boolean(row[header]) for row in staged["rows"] if row[header]}
            if len(values) > 1:
                raise DomainError("Synthetic and real row markers must be imported separately.")
            is_synthetic = is_synthetic or values == {True}
    currency = options.original_currency
    rate = options.exchange_rate or Decimal(1)

    def pkr(value):
        return (
            None
            if value is None
            else int((Decimal(value) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        )

    for row in rows:
        if row.get("currency") and row["currency"].upper() != currency:
            raise DomainError(
                "Mixed or undeclared currencies need separate imports and verified rates."
            )
        if row.get("store_id") and row["store_id"] != options.store_id:
            raise DomainError("The file's store identifier differs from the chosen store.")
    duplicates = 0
    seen, cleaned = set(), []
    for row in rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            duplicates += 1
            if options.duplicate_policy == "reject":
                raise DomainError(
                    (
                        "Identical rows found. Explicitly drop duplicates or confirm legitimate"
                        " repeated lines."
                    )
                )
            if options.duplicate_policy == "drop":
                continue
        seen.add(key)
        cleaned.append(row)
    rows = cleaned
    if staged["profile"] in {"expenses", "sku_costs"}:
        if not options.order_batch_id:
            raise DomainError("Select an orders snapshot before importing costs.")
        manifest, payload = store.get(options.order_batch_id, "orders")
        if manifest["store_id"] != options.store_id or manifest["is_synthetic"] != is_synthetic:
            raise DomainError("Costs must match this store and synthetic/real source type.")
        known = {order["order_key"] for order in payload["orders"]}
        costs = []
        seen_orders = set()
        for row in rows:
            if staged["profile"] == "expenses":
                if not row.get("order_id"):
                    raise DomainError("Each expense row needs an order identifier.")
                key = store.order_key(options.store_id, row["order_id"])
                if key not in known:
                    raise DomainError("An expense row refers to an order outside this snapshot.")
                if key in seen_orders:
                    raise DomainError(
                        "Use one expense row per order; duplicated order costs cannot be summed."
                    )
                seen_orders.add(key)
                costs.append(
                    {
                        "order_key": key,
                        **{
                            field: pkr(amount(row.get(field, ""), currency))
                            for field in COST_FIELDS
                        },
                    }
                )
            else:
                sku = identifier(row.get("sku", ""))
                unit = amount(row.get("unit_cost", ""), currency)
                if not sku or unit is None:
                    raise DomainError("Every product cost needs a SKU and verified unit cost.")
                start, end = (
                    row.get("effective_from", "") or "0001-01-01",
                    row.get("effective_to", "") or "9999-12-31",
                )
                try:
                    start = date.fromisoformat(start).isoformat()
                    end = date.fromisoformat(end).isoformat()
                except ValueError as error:
                    raise DomainError("Cost effective dates need ISO dates.") from error
                if start > end:
                    raise DomainError(
                        "Product-cost date ranges must be ordered and must not overlap for a SKU."
                    )
                costs.append(
                    {
                        "sku": sku,
                        "unit_cost": pkr(unit),
                        "start": start,
                        "end": end,
                        "basis": options.cogs_basis,
                    }
                )
        if staged["profile"] == "sku_costs":
            costs.sort(key=lambda row: (row["sku"], row["start"], row["end"]))
            for previous, current in zip(costs, costs[1:]):
                if previous["sku"] == current["sku"] and current["start"] <= previous["end"]:
                    raise DomainError("Product-cost ranges must not overlap for a SKU.")
        else:
            costs.sort(key=lambda row: row["order_key"])
        return {"costs": costs}, is_synthetic, duplicates

    grouped = defaultdict(list)
    for row in rows:
        if not row.get("order_id"):
            raise DomainError(
                "Every CSV row needs an order identifier; map Shopify Name for continuation rows."
            )
        grouped[row["order_id"]].append(row)
    orders, items = [], []
    for raw_id, lines in grouped.items():

        def unique(field):
            values = {line.get(field, "") for line in lines if line.get(field, "")}
            if len(values) > 1:
                raise DomainError(f"An order has conflicting {field} values across its lines.")
            return next(iter(values), "")

        if options.order_grain == "orders" and len(lines) > 1:
            raise DomainError(
                (
                    "Order-grain imports need one row per order. Use line-item grain or "
                    "drop exact duplicates."
                )
            )
        when = timestamp(unique("ordered_at"), options.timezone)
        day = when.date()
        if day > options.snapshot_as_of or (
            options.period_start and not options.period_start <= day <= options.period_end
        ):
            raise DomainError("An order date lies outside the declared snapshot/coverage window.")
        status = unique("financial_status").lower().replace(" ", "_").replace("-", "_")
        if status not in {
            "paid",
            "partially_refunded",
            "refunded",
            "pending",
            "authorized",
            "partially_paid",
            "voided",
            "expired",
            "cancelled",
            "canceled",
        }:
            raise DomainError(
                "Map a known financial status; unknown statuses cannot imply a paid order."
            )
        key = store.order_key(options.store_id, raw_id)
        line_gross, line_discounts, seen_line_ids = [], [], set()
        for line in lines:
            qty, price = (
                count(line.get("quantity", "")),
                amount(line.get("unit_price", ""), currency),
            )
            refunded_qty = count(line.get("refunded_quantity", ""))
            if refunded_qty is not None and (qty is None or refunded_qty > qty):
                raise DomainError("Refunded quantities cannot exceed known sold quantities.")
            line_id = line.get("line_item_id", "")
            if line_id and line_id in seen_line_ids:
                raise DomainError(
                    "A repeated line-item ID would duplicate a product cost or quantity."
                )
            seen_line_ids.add(line_id)
            line_gross.append(qty * price if qty is not None and price is not None else None)
            line_discounts.append(amount(line.get("line_discount", ""), currency))
            if qty is not None or price is not None or line.get("sku"):
                items.append(
                    {
                        "order_key": key,
                        "sku": identifier(line.get("sku", "")),
                        "quantity": qty,
                        "refunded_quantity": refunded_qty,
                        "line_gross": pkr(line_gross[-1]),
                    }
                )
        gross = amount(unique("gross_item_sales"), currency)
        computed = sum(line_gross) if all(value is not None for value in line_gross) else None
        if gross is None:
            gross = computed
        elif computed is not None and gross != computed:
            raise DomainError("Order gross sales do not match its complete line-item total.")
        if gross is None:
            raise DomainError("Map gross item sales or complete line-item quantities and prices.")
        discount = amount(unique("discounts"), currency)
        if options.discount_basis == "order_plus_line":
            discount = (
                discount + sum(line_discounts)
                if discount is not None and all(v is not None for v in line_discounts)
                else None
            )
        before_refund = gross - discount if discount is not None else None
        if before_refund is not None and before_refund < 0:
            raise DomainError("Discounts cannot exceed gross item sales.")
        subtotal = amount(unique("subtotal"), currency)
        expected = gross if options.subtotal_basis == "before_discounts" else before_refund
        if options.subtotal_basis != "unknown" and subtotal is not None and expected != subtotal:
            raise DomainError(
                (
                    "The declared Subtotal definition does not reconcile with gross sales "
                    "and discounts."
                )
            )
        refunded = amount(unique("refunded_amount"), currency)
        merchandise = amount(unique("merchandise_refunds"), currency)
        if merchandise is None and (options.refund_basis == "merchandise_only" or refunded == 0):
            merchandise = refunded
        shipping_refund = amount(unique("shipping_refunded"), currency)
        if merchandise is not None and refunded is not None and merchandise > refunded:
            raise DomainError("Merchandise refunds cannot exceed the reported total refund.")
        if merchandise is not None and before_refund is not None and merchandise > before_refund:
            raise DomainError("Merchandise refunds exceed this order's merchandise sales.")
        if (
            merchandise is not None
            and shipping_refund is not None
            and refunded is not None
            and merchandise + shipping_refund > refunded
        ):
            raise DomainError("Merchandise and shipping refunds exceed the reported total refund.")
        net = (
            before_refund - merchandise
            if before_refund is not None and merchandise is not None
            else None
        )
        is_test = boolean(unique("is_test"))
        if status == "refunded" and net is not None and net != 0:
            raise DomainError(
                "A fully refunded order must reconcile to zero merchandise net sales."
            )
        cancelled_at = unique("cancelled_at")
        if cancelled_at:
            cancelled_when = timestamp(cancelled_at, options.timezone)
            if cancelled_when < when or cancelled_when.date() > options.snapshot_as_of:
                raise DomainError("Cancellation must be after the order and within the snapshot.")
        cancelled = bool(cancelled_at) or status in {"cancelled", "canceled"}
        touch = (
            timestamp(unique("ad_touch_at"), options.timezone) if unique("ad_touch_at") else None
        )
        if touch and touch > when:
            raise DomainError("An advertising touch cannot occur after the order.")
        platform = identifier(unique("platform"))
        if platform and platform not in {"Facebook", "Instagram", "Google", "TikTok", "YouTube"}:
            raise DomainError(
                "Order platform must explicitly identify one canonical advertising platform."
            )
        orders.append(
            {
                "order_key": key,
                "ordered_at": when.astimezone(timezone.utc).isoformat(),
                "date": day.isoformat(),
                "financial_status": status,
                "fulfillment_status": unique("fulfillment_status") or "unknown",
                "eligible": status in {"paid", "partially_refunded", "refunded"}
                and not cancelled
                and not is_test,
                "exclusion_reason": "test order"
                if is_test
                else "cancelled"
                if cancelled
                else "unsettled"
                if status not in {"paid", "partially_refunded", "refunded"}
                else None,
                "is_test": is_test,
                "gross": pkr(gross),
                "discounts": pkr(discount),
                "refund_total": pkr(refunded),
                "merchandise_refunds": pkr(merchandise),
                "net_sales": pkr(net),
                "shipping_charged": pkr(amount(unique("shipping_charged"), currency)),
                "shipping_refunded": pkr(shipping_refund),
                "tax": pkr(amount(unique("tax"), currency)),
                "original_amounts": {
                    "gross": gross,
                    "discounts": discount,
                    "refund_total": refunded,
                    "merchandise_refunds": merchandise,
                    "net_sales": net,
                },
                "campaign_id": identifier(unique("campaign_id")),
                "account_id": identifier(unique("account_id")),
                "platform": platform,
                "utm_source": identifier(unique("utm_source")),
                "utm_campaign": identifier(unique("utm_campaign")),
                "touch_date": touch.date().isoformat() if touch else None,
            }
        )
    return (
        {
            "orders": sorted(orders, key=lambda item: item["order_key"]),
            "items": sorted(
                items, key=lambda item: (item["order_key"], item["sku"], str(item["quantity"]))
            ),
        },
        is_synthetic,
        duplicates,
    )


def validate(repo, token, options: ImportConfig, *, commit=False):
    store = CommerceStore(repo.root)
    staged = store.staged(token)
    try:
        payload, is_synthetic, duplicates = normalize(store, staged, options)
        require_exact_money(payload_numbers(payload))
        warnings = [
            (
                "Order-cohort snapshot: refunds reduce the original order date, not the"
                " refund-event date. "
                "Tax and shipping income are excluded from merchandise net sales."
            )
        ]
        if "orders" in payload:
            orders = payload["orders"]
            if not options.mapping.get("is_test"):
                warnings.append(
                    "No test-order flag mapped. Unmarked test transactions cannot be identified; "
                    "remove them before importing."
                )
            unknown = sum(order["net_sales"] is None and order["eligible"] for order in orders)
            if unknown:
                warnings.append(
                    f"{unknown} eligible orders lack a verified discount/refund split; "
                    "net sales stay unavailable."
                )
            overlap = sum(
                bool(
                    {o["order_key"] for o in store.get(m["id"])[1]["orders"]}
                    & {o["order_key"] for o in orders}
                )
                for m in store.list("orders")
                if m["store_id"] == options.store_id
            )
            if overlap:
                warnings.append(
                    (
                        "Order identities overlap a prior snapshot. These are separate "
                        "versions; never add their totals."
                    )
                )
        else:
            unknown = 0
        report = {
            "can_import": True,
            "errors": [],
            "input_rows": len(staged["rows"]),
            "orders": len(payload.get("orders", [])),
            "line_items": len(payload.get("items", [])),
            "cost_rows": len(payload.get("costs", [])),
            "duplicate_rows": duplicates,
            "is_synthetic": is_synthetic,
            "unknown_net_sales": unknown,
            "warnings": warnings,
            "preview": payload.get("orders", payload.get("costs", []))[:5],
        }
    except DomainError as error:
        if commit:
            raise
        return {
            "can_import": False,
            "errors": [error.message],
            "warnings": [],
            "input_rows": len(staged["rows"]),
        }
    if not commit:
        return report
    if not options.confirmed:
        raise DomainError("Confirm permission and review the commerce definitions before saving.")
    kind = "orders" if "orders" in payload else "costs"
    definitions = options.model_dump(mode="json", exclude={"name", "confirmed", "mapping"})
    definitions["is_synthetic"] = is_synthetic
    days = [row["date"] for row in payload.get("orders", [])]
    manifest = store.save(
        kind,
        {
            "name": options.name,
            "store_id": options.store_id,
            "is_synthetic": is_synthetic,
            "profile": staged["profile"],
            "filename": staged["filename"],
            "currency": "PKR",
            "original_currency": options.original_currency,
            "exchange_rate": str(options.exchange_rate or 1),
            "timezone": options.timezone,
            "definitions": definitions,
            "mapping": options.mapping,
            "period_start": str(options.period_start or min(days)) if days else None,
            "period_end": str(options.period_end or max(days)) if days else None,
            "orders": report["orders"],
            "line_items": report["line_items"],
            "cost_rows": report["cost_rows"],
            "warnings": warnings,
            "dependencies": [options.order_batch_id] if options.order_batch_id else [],
            "order_batch_id": options.order_batch_id,
        },
        payload,
        select=kind == "orders",
    )
    store.discard(token)
    return manifest
