from datetime import date

from pydantic import Field

from ads_optimizer.domain import Platform, StrictModel


class TrainingConfig(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    as_of_date: date = Field(default_factory=date.today)
    label_lag_days: int = Field(default=7, ge=0, le=90)


class Prediction(StrictModel):
    date: date
    platform: Platform
    spend: float = Field(ge=0, le=1e10, allow_inf_nan=False)
    age: str = Field(default="unknown", max_length=100)
    gender: str = Field(default="unknown", max_length=100)
    city: str = Field(default="unknown", max_length=100)
    device: str = Field(default="unknown", max_length=100)


TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
