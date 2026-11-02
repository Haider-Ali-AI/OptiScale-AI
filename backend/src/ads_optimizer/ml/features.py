"""Only planned spend and pre-period context. No outcome or simulator-truth inputs."""

import numpy as np
import pandas as pd
from sklearn.preprocessing import OneHotEncoder

from ads_optimizer.domain import DomainError

CATEGORICAL = ["platform", "age", "gender", "city", "device"]
NUMERIC = ["spend", "log_spend", "weekday", "month", "year_day_sin", "year_day_cos"]
FEATURES = CATEGORICAL + NUMERIC


def context(frame):
    dates = pd.to_datetime(frame["date"])
    result = frame[CATEGORICAL].fillna("unknown").astype(str).copy()
    result["spend"] = frame.spend.astype(float)
    result["log_spend"] = np.log1p(result.spend)
    result["weekday"] = dates.dt.dayofweek
    result["month"] = dates.dt.month
    result["year_day_sin"] = np.sin(dates.dt.dayofyear * 2 * np.pi / 365.25)
    result["year_day_cos"] = np.cos(dates.dt.dayofyear * 2 * np.pi / 365.25)
    return result


def encoder_for(frame, categories=None):
    encoder = OneHotEncoder(
        categories=categories if categories is not None else "auto",
        handle_unknown="ignore",
        sparse_output=False,
        dtype=np.float32,
    )
    encoder.fit(context(frame)[CATEGORICAL])
    if sum(len(c) for c in encoder.categories_) > 512:
        raise DomainError("Too many targeting categories (maximum 512). Use a coarser report.")
    return encoder


def transform(frame, encoder):
    data = context(frame)
    return np.column_stack([encoder.transform(data[CATEGORICAL]), data[NUMERIC]]).astype(np.float32)


def chronological_split(frame):
    dates = sorted(frame.date.unique())
    if len(dates) < 30:
        raise DomainError("Training needs at least 30 mature observation dates.")
    first, second = dates[int(len(dates) * 0.6)], dates[int(len(dates) * 0.8)]
    parts = [
        frame[frame.date < first],
        frame[(frame.date >= first) & (frame.date < second)],
        frame[frame.date >= second],
    ]
    if any(len(part) < count for part, count in zip(parts, [180, 60, 60], strict=True)):
        raise DomainError("Training needs at least 180 train, 60 validation and 60 test rows.")
    return parts
