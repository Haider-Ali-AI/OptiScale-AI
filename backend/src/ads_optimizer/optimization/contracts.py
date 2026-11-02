from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from ads_optimizer.domain import PLATFORMS, Platform, StrictModel


class PlatformLimit(StrictModel):
    platform: Platform
    min_percent: int = Field(default=0, ge=0, le=100, strict=True)
    max_percent: int = Field(default=100, ge=0, le=100, strict=True)

    min_amount: float = Field(default=0, ge=0, le=100_000_000, allow_inf_nan=False)
    max_amount: float | None = Field(default=None, ge=0, le=100_000_000, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        for amount in [self.min_amount, self.max_amount]:
            if amount is not None and Decimal(str(amount)) * 100 % 1:
                raise ValueError("Platform amounts need at most two decimal places.")
        if self.max_amount is not None and self.min_amount > self.max_amount:
            raise ValueError("Platform minimum amount exceeds its maximum.")
        if self.min_percent > self.max_percent:
            raise ValueError("Each platform's minimum must be at most its maximum.")
        return self


class PlanConfig(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    method: Literal["auto", "model", "baseline", "historical", "evidence"] = "auto"
    model_id: str | None = Field(default=None, min_length=1, max_length=64)
    budget: float = Field(gt=0, le=100_000_000, allow_inf_nan=False)
    step: float | None = Field(default=None, ge=0.01, le=100_000_000, allow_inf_nan=False)
    start_date: date
    horizon_days: int = Field(default=7, ge=1, le=30, strict=True)
    # Used only by the explicit historical method. Model mode uses its saved controls.
    as_of_date: date = Field(default_factory=date.today)
    label_lag_days: int = Field(default=7, ge=0, le=90, strict=True)
    platforms: list[PlatformLimit] = Field(
        default_factory=lambda: [PlatformLimit(platform=p) for p in PLATFORMS],
        min_length=1,
        max_length=5,
    )

    @model_validator(mode="after")
    def feasible_grid(self):
        for value in [self.budget, self.step]:
            if (
                value is not None
                and Decimal(str(value)) * 100 != (Decimal(str(value)) * 100).to_integral_value()
            ):
                raise ValueError("Use at most two decimal places for PKR amounts.")
        if len({p.platform for p in self.platforms}) != len(self.platforms):
            raise ValueError("Choose each enabled platform once.")
        if sum(p.min_percent for p in self.platforms) > 100:
            raise ValueError("Platform minimum percentages cannot total more than 100%.")
        if sum(p.max_percent for p in self.platforms) < 100:
            raise ValueError("Platform maximum percentages must cover 100% of the budget.")
        if self.method == "model" and not self.model_id:
            raise ValueError("Choose an accepted saved model for model-based planning.")
        if self.method in {"historical", "baseline", "evidence"} and self.model_id:
            raise ValueError("Historical-rule plans do not use an ML model.")
        return self

    @property
    def budget_cents(self):
        return int(Decimal(str(self.budget)) * 100)

    @property
    def sample_step_cents(self):
        requested = int(Decimal(str(self.step)) * 100) if self.step is not None else 0
        return max(1, requested, (self.budget_cents + 199) // 200)
