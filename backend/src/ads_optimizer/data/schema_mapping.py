"""Deterministic header suggestions; fuzzy/type evidence never silently selects a field."""

import re
from difflib import SequenceMatcher

import pandas as pd

ALIASES = {
    "date": ["date", "day", "reporting starts", "reporting start", "stat time day"],
    "campaign": ["campaign", "campaign name", "campaign_name"],
    "platform": ["platform", "publisher platform", "channel", "ad platform"],
    "impressions": ["impressions", "impression"],
    "clicks": ["clicks", "link clicks", "clicks (all)", "destination clicks"],
    "spend": [
        "spend",
        "spend pkr",
        "amount spent (pkr)",
        "amount spent (usd)",
        "cost",
        "total cost",
    ],
    "conversions": ["conversions", "purchases", "results"],
    "revenue": [
        "revenue",
        "revenue pkr",
        "purchase conversion value",
        "conversion value",
        "total conversion value",
        "conv. value",
    ],
    "age": ["age", "age group"],
    "gender": ["gender"],
    "city": ["city"],
    "device": ["device", "device type"],
    "campaign_id": ["campaign id", "campaign_id"],
    "account_id": ["account id", "account_id", "advertiser id"],
    "attribution_window": ["attribution window", "attribution setting", "attribution_window"],
    "conversion_definition": ["conversion definition", "conversion_definition"],
}

ALIASES["date"] += [
    "week start",
    "week end",
    "week",
    "campaign date",
    "reporting date",
    "date recorded",
]
ALIASES["spend"] += ["ad spend pkr", "spent"]
ALIASES["spend"] += ["amount spent", "ad spend", "advertising spend"]
ALIASES["conversions"] += ["orders"]
ALIASES["revenue"] += ["sales revenue", "attributed revenue", "total revenue", "purchase revenue"]
ALIASES["impressions"] += ["ad impressions", "total impressions"]
ALIASES["clicks"] += ["total clicks"]
NULLS = {"", "null", "none", "nan", "n/a", "na", "—", "-"}


def normalized_name(value):
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value))
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def numeric_values(series):
    # Only conventional decimal-dot / grouped-thousands formats. Percentages are
    # not counts or money; never silently turn 12% into 12 conversions.
    text = series.astype(str).str.strip()
    text = text.mask(text.str.lower().isin(NULLS), "")
    cleaned = text.str.replace(r"^(?:PKR|USD|EUR|GBP|Rs\.?|[$€£])\s*", "", regex=True, flags=re.I)
    valid = cleaned.str.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?")
    return pd.to_numeric(
        cleaned.where(valid).str.replace(",", "", regex=False), errors="coerce"
    ), text


def recognize(frame):
    suggestions, details = {}, {}
    for field, aliases in ALIASES.items():
        candidates = []
        for column in frame:
            name = normalized_name(column)
            compact = name.replace(" ", "")
            exact = any(compact == normalized_name(a).replace(" ", "") for a in aliases)
            fuzzy = max(SequenceMatcher(None, name, normalized_name(a)).ratio() for a in aliases)
            if not exact and (len(name) < 5 or fuzzy < 0.86):
                continue
            values = frame[column].head(100)
            present = values[~values.str.lower().isin(NULLS)]
            compatibility = 1.0
            if field in {"spend", "revenue", "clicks", "impressions", "conversions"}:
                compatibility = (
                    float(numeric_values(present)[0].notna().mean()) if len(present) else 0
                )
            elif field == "date":
                compatibility = (
                    float(
                        present.str.fullmatch(
                            r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-W\d{2})"
                        ).mean()
                    )
                    if len(present)
                    else 0
                )
            score = (0.99 if compatibility == 1 else 0.96) if exact else 0.75 * fuzzy
            if compatibility == 0:
                score = 0.6
            reason = (
                "Recognized header and compatible sample values"
                if exact
                else "Similar header; confirm its meaning"
            )
            if compatibility < 1:
                reason = "Recognized header; sample values need review"
            if field == "conversions" and name == "results":
                score = min(score, 0.7)
                reason = (
                    "Results can mean different events; select only the intended conversion count"
                )
            candidates.append({"column": column, "confidence": round(score, 3), "reason": reason})
        candidates.sort(key=lambda c: (-c["confidence"], c["column"]))
        # A granular channel column is safer than a combined ad-provider column.
        if field == "platform":
            for c in candidates:
                if normalized_name(c["column"]) in {"channel", "publisher platform"}:
                    candidates.remove(c)
                    candidates.insert(0, c)
                    break
        # A period's start and end are complementary, not competing observations.
        if field == "date" and {normalized_name(c["column"]) for c in candidates} == {
            "week start",
            "week end",
        }:
            candidates.sort(key=lambda c: normalized_name(c["column"]) != "week start")
            candidates = candidates[:1]
        ambiguous = len(candidates) > 1 and candidates[1]["confidence"] >= 0.9
        if (
            field == "platform"
            and candidates
            and normalized_name(candidates[0]["column"]) in {"channel", "publisher platform"}
        ):
            ambiguous = False
        automatic = bool(candidates and candidates[0]["confidence"] >= 0.95 and not ambiguous)
        suggestions[field] = candidates[0]["column"] if automatic else ""
        details[field] = {
            "status": "automatic" if automatic else "confirm" if candidates else "missing",
            "candidates": candidates[:3],
            "reason": "Multiple plausible columns; choose the intended metric"
            if ambiguous
            else candidates[0]["reason"]
            if candidates
            else "No recognized header; map manually if available",
        }
    return suggestions, details
