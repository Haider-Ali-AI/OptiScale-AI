"""Retain explicit synthetic components; flag legacy imports that discarded them."""

import re

MARKERS = {"date_is_synthetic", "revenue_is_synthetic"}


def provenance_review(manifest):
    original = {
        re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")
        for c in manifest.import_mapping.get("original_columns", [])
    }
    lost = MARKERS.intersection(original) - manifest.provenance_flags.keys()
    bad_rates = [
        field
        for field, column in manifest.import_mapping.get("selected", {}).items()
        if field in {"conversions", "spend", "revenue", "clicks", "impressions"}
        and any(
            t in re.split(r"[^a-z0-9]+", column.lower())
            for t in ["rate", "pct", "percent", "ctr", "cpc", "roas"]
        )
    ]
    rate_warnings = (
        [
            "An older import maps a rate into a count/amount: "
            + ", ".join(bad_rates)
            + ". Reimport with the actual metric or leave it missing."
        ]
        if bad_rates
        else []
    )
    return rate_warnings + (
        [
            "This older import discarded synthetic date/revenue markers. Reimport the original "
            "CSV to retain its provenance; real revenue forecasting is unavailable."
        ]
        if lost
        else []
    )
