"""Strict completeness: partial observations never masquerade as complete totals."""

from datetime import date

import numpy as np
import pandas as pd

from ads_optimizer.domain import DIMENSIONS, METRICS, DomainError

RATIOS = {
    "ctr": ("clicks", "impressions", 100),
    "cpc": ("spend", "clicks", 1),
    "cpa": ("spend", "conversions", 1),
    "cvr": ("conversions", "clicks", 100),
    "roas": ("revenue", "spend", 1),
}


def summarize(frame: pd.DataFrame) -> dict:
    totals = {
        key: float(frame[key].sum()) if len(frame) and frame[key].notna().all() else None
        for key in METRICS
    }
    ratios = {}
    for name, (numerator, denominator, scale) in RATIOS.items():
        a, b = totals[numerator], totals[denominator]
        ratios[name] = a / b * scale if a is not None and b is not None and b > 0 else None
    return {
        "rows": len(frame),
        **totals,
        **ratios,
        "coverage": {key: float(frame[key].notna().mean()) if len(frame) else 0 for key in METRICS},
    }


def filter_frame(frame: pd.DataFrame, filters: dict[str, str]) -> pd.DataFrame:
    result = frame
    for key, value in filters.items():
        if not value:
            continue
        if key in ["start_date", "end_date"]:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise DomainError("Use YYYY-MM-DD for date filters.") from error
            result = (
                result[result.date >= value]
                if key == "start_date"
                else result[result.date <= value]
            )
        elif key in DIMENSIONS:
            result = result[result[key] == value]
        else:
            raise DomainError("An unsupported filter was supplied.")
    if (
        filters.get("start_date")
        and filters.get("end_date")
        and filters["start_date"] > filters["end_date"]
    ):
        raise DomainError("The start date must not be after the end date.")
    return result


def aggregate(frame: pd.DataFrame, dimension: str) -> list[dict]:
    if dimension not in DIMENSIONS:
        raise DomainError("Choose a supported grouping dimension.")
    return [
        {"name": str(name), **summarize(group)}
        for name, group in frame.groupby(dimension, sort=True, observed=True)
    ]


def analytics_result(
    frame: pd.DataFrame,
    filters: dict,
    dimension="campaign",
    page=1,
    page_size=10,
    sort="revenue",
    direction="desc",
) -> dict:
    filtered = filter_frame(frame, filters)
    grouped = aggregate(filtered, dimension)
    allowed_sort = ["name", "rows", *METRICS, *RATIOS]
    if sort not in allowed_sort or direction not in ["asc", "desc"]:
        raise DomainError("Choose a supported table sort order.")
    present = [row for row in grouped if row[sort] is not None]
    missing = [row for row in grouped if row[sort] is None]
    grouped = sorted(present, key=lambda row: row[sort], reverse=direction == "desc") + missing
    daily = aggregate(filtered, "date")
    # Keep charts bounded for later datasets even though Phase 1 dates are usually short.
    if len(daily) > 120:
        filtered = filtered.copy()
        filtered["date"] = (
            pd.to_datetime(filtered.date).dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
        )
        daily = aggregate(filtered, "date")
        trend_grain = "week starting"
    else:
        trend_grain = (
            "week starting"
            if "date_granularity" in frame and frame.date_granularity.eq("weekly").all()
            else "day"
        )
    return {
        "totals": summarize(filter_frame(frame, filters)),
        "filters": filters,
        "platforms": aggregate(filter_frame(frame, filters), "platform"),
        "trend": daily,
        "trend_grain": trend_grain,
        "group_by": dimension,
        "table": grouped[(page - 1) * page_size : page * page_size],
        "table_total": len(grouped),
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "direction": direction,
    }


def safe_csv_cell(value):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return ""
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value
