"""Explicit preview/map/validate/commit imports; no invented monetary values."""

import csv
import io
import json
import re
import time
import uuid
from pathlib import PureWindowsPath

import numpy as np
import pandas as pd

from ads_optimizer.data.periods import parse_periods
from ads_optimizer.data.reporting import import_hints, known
from ads_optimizer.data.repository import Repository, coverage
from ads_optimizer.data.schema_mapping import normalized_name, numeric_values, recognize
from ads_optimizer.data.validation import grain_frame
from ads_optimizer.domain import (
    EXTRAS,
    FIELDS,
    MAX_IMPORT_ROWS,
    MAX_UPLOAD_BYTES,
    METRICS,
    DomainError,
    ImportOptions,
    Issue,
    ValidationReport,
)

PROFILES = {
    "generic": "Generic campaign CSV",
    "meta": "Meta Ads Manager",
    "google": "Google Ads",
    "tiktok": "TikTok Ads Manager",
}
PII_HEADERS = {
    "name",
    "email",
    "email address",
    "customer name",
    "customer email",
    "phone",
    "phone number",
    "first name",
    "last name",
    "billing name",
    "billing address",
    "shipping name",
    "shipping address",
    "address",
    "ip",
    "ip address",
    "customer id",
    "gclid",
    "fbclid",
    "ttclid",
    "click id",
}
PLATFORM_NAMES = {
    "facebook": "Facebook",
    "fb": "Facebook",
    "instagram": "Instagram",
    "ig": "Instagram",
    "google": "Google",
    "google ads": "Google",
    "google search": "Google",
    "google display": "Google",
    "tiktok": "TikTok",
    "tik tok": "TikTok",
    "tik tok ads": "TikTok",
    "facebook ads": "Facebook",
    "instagram ads": "Instagram",
    "you tube ads": "YouTube",
    "youtube ads": "YouTube",
    "tiktok ads": "TikTok",
    "youtube": "YouTube",
    "you tube": "YouTube",
}


def records(frame: pd.DataFrame, limit=20) -> list[dict]:
    return json.loads(frame.head(limit).to_json(orient="records"))


def stage_csv(repo: Repository, content: bytes, filename: str, profile: str) -> dict:
    if profile not in PROFILES:
        raise DomainError("Choose a supported CSV profile.")
    if not filename.lower().endswith(".csv"):
        raise DomainError("Choose a UTF-8 CSV file. Parquet import is not enabled in Phase 1.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DomainError("This CSV exceeds the 10 MiB upload limit.", 413)
    try:
        text = content.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("binary content")
        reader = csv.reader(io.StringIO(text), strict=True)
        headers = [value.strip() for value in next(reader)]
        if not headers or len(headers) > 100 or any(not h or len(h) > 100 for h in headers):
            raise DomainError("Use 1–100 named CSV columns, each at most 100 characters.")
        if len(set(headers)) != len(headers):
            raise DomainError("The CSV has duplicate column names. Rename them before uploading.")
        names = {normalized_name(h) for h in headers}
        if len(names & {"financial status", "lineitem name", "order id", "billing name"}) >= 2:
            raise DomainError(
                "This looks like an orders CSV. Use ad reports here; orders arrive in Phase 6."
            )
        keep = [i for i, header in enumerate(headers) if normalized_name(header) not in PII_HEADERS]
        removed = [header for i, header in enumerate(headers) if i not in keep]
        rows = []
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(headers):
                raise DomainError(
                    f"CSV row {reader.line_num} has a different number of columns than the header."
                )
            if any(len(cell) > 1000 for cell in row):
                raise DomainError(
                    "A cell exceeds 1,000 characters. Upload aggregated campaign fields only."
                )
            rows.append([row[i].strip() for i in keep])
            if len(rows) > MAX_IMPORT_ROWS:
                raise DomainError(
                    "Phase 1 imports are limited to 100,000 rows. Split this report first.", 413
                )
        if not rows:
            raise DomainError("This CSV has no data rows.")
    except (UnicodeDecodeError, csv.Error, StopIteration, ValueError) as error:
        raise DomainError(
            "This file could not be parsed. Use a comma-separated UTF-8 CSV with a header row."
        ) from error
    columns = [headers[i] for i in keep]
    frame = pd.DataFrame(rows, columns=columns)
    mapping, mapping_details = recognize(frame)
    mapping_warnings = [
        f"Review {field}: {detail['reason']}."
        for field, detail in mapping_details.items()
        if detail["status"] == "confirm"
    ]
    now = time.time()
    for path in (repo.root / "staging").glob("*.json"):
        if now - path.stat().st_mtime > 24 * 3600:
            path.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    safe_filename = PureWindowsPath(filename).name[:120]
    staged = {
        "token": token,
        "columns": columns,
        "rows": rows,
        "filename": safe_filename,
        "profile": profile,
        "mapping_details": mapping_details,
        "suggested_mapping": mapping,
        "warnings": ([f"Discarded personal-data columns: {', '.join(removed)}."] if removed else [])
        + mapping_warnings,
    }
    (repo.root / "staging" / f"{token}.json").write_text(json.dumps(staged))
    frame = pd.DataFrame(rows, columns=columns)
    currencies = set()
    for column in columns:
        if normalized_name(column) in {"currency", "account currency", "currency code"}:
            currencies.update(v.upper() for v in frame[column].unique() if v)
    return {
        "token": token,
        "filename": safe_filename,
        "profile": profile,
        "columns": columns,
        "row_count": len(rows),
        "preview": records(frame),
        "suggested_mapping": mapping,
        "mapping_details": mapping_details,
        "reporting_hints": import_hints(frame, mapping),
        "detected_currencies": sorted(currencies),
        "warnings": staged["warnings"],
    }


def read_stage(repo: Repository, token: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise DomainError("Upload preview was not found. Choose your CSV again.", 404)
    path = repo.root / "staging" / f"{token}.json"
    if not path.exists() or time.time() - path.stat().st_mtime > 24 * 3600:
        path.unlink(missing_ok=True)
        raise DomainError("This preview expired. Choose your CSV again.", 404)
    return json.loads(path.read_text())


def validate_import(repo: Repository, token: str, options: ImportOptions):
    staged = read_stage(repo, token)
    raw = pd.DataFrame(staged["rows"], columns=staged["columns"])
    mapping = {k: v for k, v in options.mapping.items() if v}
    if any(k not in [*FIELDS, *EXTRAS] or v not in raw.columns for k, v in mapping.items()):
        raise DomainError("A mapped column is unavailable. Review the mapping against this CSV.")
    for field in METRICS:
        header = normalized_name(mapping.get(field, ""))
        if any(
            token in header.split()
            for token in ["rate", "pct", "percent", "percentage", "roas", "ctr", "cpc", "cpa"]
        ):
            raise DomainError(
                f"{mapping[field]} is a rate, not a {field} amount/count. "
                "Map the actual metric or leave it missing."
            )
    if len(set(mapping.values())) != len(mapping):
        raise DomainError("Map each CSV column to only one field.")
    frame = pd.DataFrame(index=raw.index)
    for field in [*FIELDS, *EXTRAS]:
        frame[field] = raw[mapping[field]].copy() if field in mapping else ""
    errors = []
    warnings = staged["warnings"].copy()
    invalid = pd.Series(False, index=raw.index)
    blocking = False

    def issue(field, message, mask=None):
        nonlocal invalid, blocking
        if mask is None:
            blocking = True
            errors.append(Issue(field=field, message=message, count=len(raw)))
        elif mask.any():
            invalid |= mask
            errors.append(
                Issue(
                    field=field,
                    message=message,
                    count=int(mask.sum()),
                    rows=[int(i) + 2 for i in mask[mask].index[:10]],
                )
            )

    dates, granularity, period_errors = parse_periods(raw, mapping.get("date", ""), options)
    for message in period_errors:
        issue("date_granularity", message)
    issue(
        "date",
        "Map a valid date; choose the format for ambiguous dates. Weeks need a year (2026-W43).",
        dates.isna(),
    )
    frame["date"] = dates.dt.strftime("%Y-%m-%d")
    period_columns = {normalized_name(c): c for c in raw.columns}
    issue("campaign", "Campaign name or identifier is required.", frame.campaign.eq(""))
    platform = frame.platform.where(frame.platform.ne(""), options.default_platform or "")
    frame["platform"] = platform.map(normalized_name).map(PLATFORM_NAMES)
    issue(
        "platform",
        "Map Facebook, Instagram, Google, TikTok or YouTube. Meta Ads alone is ambiguous; "
        "use the channel/publisher column to separate Facebook and Instagram. "
        "A default only fills empty platform values.",
        frame.platform.isna(),
    )
    channel_column = period_columns.get("channel")
    if channel_column and mapping.get("platform") != channel_column:
        channel_platform = raw[channel_column].map(normalized_name).map(PLATFORM_NAMES)
        if (channel_platform.notna() & channel_platform.ne(frame.platform)).any():
            issue(
                "platform",
                f"Map {channel_column} to platform: provider names combine "
                "Facebook/Instagram or Google/YouTube and would misclassify these channels.",
            )
    for field in METRICS:
        value, supplied = numeric_values(frame[field])
        bad = supplied.ne("") & (value.isna() | ~np.isfinite(value) | (value < 0) | (value > 1e15))
        if field in ["impressions", "clicks"]:
            bad |= value.notna() & (value % 1 != 0)
        issue(
            field,
            "Use non-negative amounts (PKR 1,234.50) or counts; percentages are not counts.",
            bad,
        )
        frame[field] = value.astype(float)
    issue(
        "clicks",
        "Clicks exceed impressions. Verify the source report and metric definitions.",
        frame.clicks.gt(frame.impressions),
    )
    if frame.conversions.gt(frame.clicks).any():
        warnings.append("Conversions exceed clicks in some rows. Verify attribution definitions.")
    if ((frame.conversions == 0) & (frame.revenue > 0)).any():
        warnings.append(
            "Some revenue has zero conversions; confirm reporting lag and conversion definitions."
        )
    currencies = set()
    for column in raw.columns:
        if normalized_name(column) in {"currency", "account currency", "currency code"}:
            currencies.update(v.upper() for v in raw[column].unique() if v)
    # Amount-spent headers also declare units; never assume a USD column is PKR.
    for metric in ["spend", "revenue"]:
        match = re.search(r"\(([A-Z]{3})\)", mapping.get(metric, ""), re.I)
        if match:
            currencies.add(match.group(1).upper())
    for field in ["spend", "revenue"]:
        if normalized_name(mapping.get(field, "")) in {"spend pkr", "revenue pkr"}:
            currencies.add("PKR")
    for field in ["spend", "revenue"]:
        if field in mapping:
            for value in raw[mapping[field]]:
                match = re.match(r"^(PKR|USD|EUR|GBP)(?=\s|\d|[-+])", value, re.I)
                if match:
                    currencies.add(match.group(1).upper())
                for symbol, code in [("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("Rs", "PKR")]:
                    if value.startswith(symbol):
                        currencies.add(code)
    if currencies and currencies != {options.original_currency}:
        issue(
            "currency",
            f"CSV currencies: {', '.join(sorted(currencies))}. "
            "Select matching currency or split mixed-currency files.",
        )
    rate = options.exchange_rate
    if options.original_currency != "PKR" and rate is None:
        issue("currency", "Enter the verified number of PKR per 1 unit of the original currency.")
    if options.original_currency == "PKR" and rate not in (None, 1):
        issue("currency", "The exchange rate for an already-PKR report must be 1.")
    for field in ["spend", "revenue"]:
        frame[field] = (frame[field] * (rate or 1)).round(2)
        issue(
            field,
            "Converted money exceeds supported numeric limits. Check currency and units.",
            frame[field].notna() & (~np.isfinite(frame[field]) | (frame[field] > 1e15)),
        )
    for field in ["age", "gender", "city", "device", "campaign_id", "account_id"]:
        frame[field] = frame[field].replace("", "unknown")
    frame["device"] = frame.device.str.lower()
    for field in ["conversion_definition", "attribution_window"]:
        answer = getattr(options, field)
        detected = import_hints(raw, mapping)[field]
        if (
            known(answer)
            and detected["value"]
            and answer.strip().lower() != detected["value"].lower()
        ):
            issue(
                field,
                "Your answer differs from a reporting rule already stated in the file. "
                "Review the mapped column and keep the source report's actual rule.",
            )
        if not known(answer) and detected["status"] == "detected":
            answer = detected["value"]
        frame[field] = frame[field].replace("", answer)
        if frame[field].nunique() > 1:
            warnings.append(
                f"Mixed {field.replace('_', ' ')} values. "
                "Split compatible reports before forecasting."
            )
    provenance_flags = {}
    for column in raw:
        key = normalized_name(column).replace(" ", "_")
        if key in {"date_is_synthetic", "revenue_is_synthetic"}:
            values = set(raw[column].str.lower()) - {""}
            if values - {"true", "false", "1", "0"}:
                issue(key, "Synthetic component markers must use true/false or 1/0.")
            provenance_flags[key] = bool(values & {"true", "1"})
            frame[key] = raw[column].str.lower().isin(["true", "1"])
    if any(provenance_flags.values()):
        warnings.append(
            "Synthetic dates or revenue declared: this is a simulation, "
            "not evidence of actual temporal revenue performance."
        )
    synthetic_values = set()
    for column in raw.columns:
        if normalized_name(column) == "is synthetic":
            synthetic_values.update(v.lower() for v in raw[column].unique() if v)
    if synthetic_values - {"true", "false", "1", "0"} or (
        synthetic_values & {"true", "1"} and synthetic_values & {"false", "0"}
    ):
        issue("is_synthetic", "Do not mix synthetic and real rows. Split datasets by source.")
    synthetic = (
        options.is_synthetic
        or bool(synthetic_values & {"true", "1"})
        or any(provenance_flags.values())
    )
    if synthetic and not options.is_synthetic:
        warnings.append("This CSV declares synthetic rows and will be saved as Synthetic CSV.")
    frame["is_synthetic"] = synthetic
    frame["currency"] = "PKR"
    if granularity == "weekly":
        frame["date_granularity"] = "weekly"
    valid = frame.loc[~invalid].copy()
    duplicate_count = int(valid.duplicated().sum())
    if duplicate_count and options.drop_duplicates:
        valid = valid.drop_duplicates()
        warnings.append(f"Removed {duplicate_count:,} exact duplicate rows.")
    elif duplicate_count:
        issue("duplicates", "Enable exact-duplicate removal before saving this dataset.")
    conflicting = grain_frame(valid).duplicated(keep=False)
    if conflicting.any():
        issue(
            "grain",
            "Conflicting observation keys. Map separating IDs/segments or fix the export.",
        )
    if int(invalid.sum()):
        warnings.append(
            f"{int(invalid.sum()):,} invalid rows "
            + (
                "excluded by your explicit choice."
                if options.exclude_invalid
                else "require correction or explicit exclusion."
            )
        )
    cov = (
        coverage(valid)
        if len(valid)
        else {key: 0 for key in [*METRICS, "age", "gender", "city", "device"]}
    )
    missing = [key for key in METRICS if cov[key] < 1]
    if missing:
        warnings.append(
            f"Incomplete fields: {', '.join(missing)}. "
            "Affected totals/rates show Not available; missing values stay missing."
        )
    if any(cov[key] < 1 for key in ["age", "gender", "city", "device"]):
        warnings.append("Some audience/device segments are unknown. Coverage is shown separately.")
    definitions_known = all(
        valid[key].nunique() == 1 and valid[key].map(known).all()
        for key in ["conversion_definition", "attribution_window"]
    )
    if not definitions_known:
        warnings.append("Specify compatible conversion/attribution definitions before forecasting.")
    if (valid.spend > 1e8).any() or (valid.revenue > 1e9).any():
        warnings.append(
            "Large monetary outliers detected. Verify currency and units before using these data."
        )
    ready = all(cov[key] == 1 for key in ["spend", "revenue"]) and definitions_known
    report = ValidationReport(
        date_granularity=granularity,
        provenance_flags=provenance_flags,
        input_rows=len(raw),
        valid_rows=len(valid),
        invalid_rows=int(invalid.sum()),
        duplicate_rows=duplicate_count,
        excluded_rows=int(invalid.sum()) if options.exclude_invalid else 0,
        can_import=bool(len(valid))
        and not blocking
        and (not invalid.any() or options.exclude_invalid),
        is_synthetic=synthetic,
        coverage=cov,
        warnings=list(dict.fromkeys(warnings)),
        errors=errors,
        preview=records(valid),
        data_ready_for_revenue=ready,
        reporting_hints=import_hints(raw, mapping),
    )
    return valid.reset_index(drop=True), report, staged


def commit_import(repo: Repository, token: str, options: ImportOptions):
    if not options.confirmed:
        raise DomainError("Confirm the source, currency, mapping and any exclusions before saving.")
    frame, report, staged = validate_import(repo, token, options)
    if not report.can_import:
        raise DomainError(
            "This CSV still has blocking validation issues. Review the validation report."
        )
    metadata = {
        "name": options.name.strip(),
        "date_granularity": report.date_granularity,
        "provenance_flags": report.provenance_flags,
        "import_mapping": {
            "original_columns": staged["columns"],
            "selected": options.mapping,
            "suggestions": staged.get("mapping_details", {}),
            "date_format": options.date_format,
        },
        "source": "synthetic_csv" if report.is_synthetic else "advertiser_csv",
        "is_synthetic": report.is_synthetic,
        "original_filename": staged["filename"],
        "import_profile": staged["profile"],
        "original_currency": options.original_currency,
        "exchange_rate": options.exchange_rate or 1,
        "conversion_definition": frame.conversion_definition.iloc[0]
        if frame.conversion_definition.nunique() == 1
        else "mixed",
        "attribution_window": frame.attribution_window.iloc[0]
        if frame.attribution_window.nunique() == 1
        else "mixed",
        "revenue_source": "synthetic" if report.is_synthetic else "ad_platform_reported",
        "warnings": report.warnings,
        "data_ready_for_revenue": report.data_ready_for_revenue,
        "reporting_evidence": {
            field: detected["evidence"]
            if detected["status"] == "detected"
            else "User supplied during CSV import."
            for field, detected in import_hints(
                pd.DataFrame(staged["rows"], columns=staged["columns"]), options.mapping
            ).items()
            if detected["status"] == "detected" or known(getattr(options, field))
        },
    }
    manifest = repo.save(frame, metadata)
    (repo.root / "staging" / f"{token}.json").unlink(missing_ok=True)
    return manifest
