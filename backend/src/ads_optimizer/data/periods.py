"""Strict date/period interpretation, without inventing daily observations."""

from datetime import date

import numpy as np
import pandas as pd

from ads_optimizer.data.schema_mapping import normalized_name


def parse_periods(raw, column, options):
    values = raw[column] if column else pd.Series("", index=raw.index)
    names = {normalized_name(c): c for c in raw}
    name = normalized_name(column)
    errors = []
    iso = values.str.fullmatch(r"\d{4}-W\d{2}")
    weekly = name in {"week", "week start", "week end"} or iso.any()
    declared = set()
    if "date granularity" in names:
        declared = set(raw[names["date granularity"]].str.lower()) - {""}
        declared = {"daily" if v == "day" else "weekly" if v == "week" else v for v in declared}
        if len(declared) > 1 or declared - {"daily", "weekly"}:
            errors.append("Use one consistent daily or weekly reporting period per file.")
        weekly |= declared == {"weekly"}
    if name in {"month start", "month end"}:
        errors.append("Monthly reports are not supported. Export daily or weekly records.")
    fmt = options.date_format
    if iso.any():
        if not iso.all():
            errors.append("Do not mix ISO weeks and daily dates in one report.")

        def week(value):
            try:
                year, number = value.split("-W")
                return pd.Timestamp(date.fromisocalendar(int(year), int(number), 1))
            except (ValueError, OverflowError):
                return pd.NaT

        dates = pd.to_datetime(values.map(week), errors="coerce")
    else:
        if fmt == "auto":
            if (
                values.str.fullmatch(r"\d{4}-\d{2}-\d{2}").any()
                and not values.str.contains("/").any()
            ):
                fmt = "%Y-%m-%d"
            elif values.str.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}").all():
                pieces = values.str.split("/", expand=True).astype(int)
                day_first, month_first = (pieces[0] > 12).any(), (pieces[1] > 12).any()
                if day_first and not month_first:
                    fmt = "%d/%m/%Y"
                elif month_first and not day_first:
                    fmt = "%m/%d/%Y"
                else:
                    errors.append("Ambiguous dates: choose DD/MM/YYYY or MM/DD/YYYY explicitly.")
            else:
                errors.append(
                    "Choose a consistent date format. Week numbers alone need a year; use 2026-W43."
                )
        dates = pd.to_datetime(values, format=fmt, errors="coerce", exact=True)
        if name == "week end":
            dates = pd.Series(
                dates.to_numpy(dtype="datetime64[ns]") - np.timedelta64(6, "D"),
                index=raw.index,
            )
    start = names.get("week start") or names.get("reporting starts") or names.get("reporting start")
    end = names.get("week end") or names.get("reporting ends") or names.get("reporting end")
    if start and end and column in {start, end}:
        starts = pd.to_datetime(raw[start], format=fmt, errors="coerce")
        ends = pd.to_datetime(raw[end], format=fmt, errors="coerce")
        durations = (ends - starts).dt.days
        if durations.eq(6).all():
            weekly = True
            dates = starts
        elif not durations.eq(0).all():
            errors.append(
                "Reporting ranges must consistently cover one day or seven days (inclusive)."
            )
    if weekly and (options.date_granularity == "daily" or declared == {"daily"}):
        errors.append("Weekly totals cannot be relabeled daily. Keep weekly reporting periods.")
    granularity = "weekly" if weekly or options.date_granularity == "weekly" else "daily"
    if granularity == "weekly" and dates.dropna().dt.dayofweek.nunique() > 1:
        errors.append("Use a consistent week-start day; overlapping weeks are unsupported.")
    return dates, granularity, errors
