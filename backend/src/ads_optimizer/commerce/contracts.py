"""Explicit definitions for immutable, separately stored commerce snapshots."""

from datetime import date
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from ads_optimizer.domain import StrictModel
from ads_optimizer.optimization.contracts import PlatformLimit


class ImportConfig(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    store_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    mapping: dict[str, str] = Field(max_length=40)
    timezone: str = "Asia/Karachi"
    original_currency: str = Field(default="PKR", pattern=r"^[A-Z]{3}$")
    exchange_rate: Decimal | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    is_synthetic: bool = False
    confirmed: bool = False
    duplicate_policy: Literal["reject", "drop", "keep"] = "reject"
    order_grain: Literal["orders", "line_items"] = "line_items"
    discount_basis: Literal["order_total", "order_plus_line"] = "order_total"
    refund_basis: Literal["unallocated", "merchandise_only"] = "unallocated"
    subtotal_basis: Literal["unknown", "before_discounts", "after_discounts"] = "unknown"
    snapshot_as_of: date = Field(default_factory=date.today)
    period_start: date | None = None
    period_end: date | None = None
    complete_export: bool = False
    refunds_verified: bool = False
    order_batch_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    cogs_basis: Literal["sold_quantity", "net_refunded_quantity"] = "sold_quantity"

    @model_validator(mode="after")
    def definitions(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Choose a valid IANA timezone, such as Asia/Karachi.") from error
        if self.original_currency != "PKR" and self.exchange_rate is None:
            raise ValueError("Supply a verified PKR-per-unit exchange rate.")
        if self.original_currency == "PKR" and self.exchange_rate not in {None, Decimal(1)}:
            raise ValueError("PKR uses an exchange rate of one.")
        if bool(self.period_start) != bool(self.period_end):
            raise ValueError("Supply both coverage dates or neither.")
        if self.period_start and (
            not 0 <= (self.period_end - self.period_start).days <= 365
            or self.period_end > self.snapshot_as_of
        ):
            raise ValueError(
                "Coverage must be ordered, at most one year, and not after the snapshot."
            )
        if self.complete_export and not self.period_start:
            raise ValueError("A complete export needs explicit coverage start and end dates.")
        return self


class CampaignMapping(StrictModel):
    utm_source: str = Field(min_length=1, max_length=200)
    utm_campaign: str = Field(min_length=1, max_length=200)
    platform: Literal["Facebook", "Instagram", "Google", "TikTok", "YouTube"]
    campaign_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def identifiers(self):
        if any(
            any(char in value for char in "@\r\n")
            for value in [self.utm_source, self.utm_campaign, self.campaign_id, self.account_id]
        ):
            raise ValueError("Campaign mappings cannot contain email addresses or line breaks.")
        return self


class ReconcileConfig(StrictModel):
    order_batch_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    ad_dataset_id: str = Field(min_length=1, max_length=64)
    cost_batch_ids: list[str] = Field(default_factory=list, max_length=10)
    start_date: date
    end_date: date
    ad_scope_confirmed: bool = False
    timezones_confirmed: bool = False
    mappings_confirmed: bool = False
    mappings: list[CampaignMapping] = Field(default_factory=list, max_length=1000)
    attribution_window_days: int = Field(default=7, ge=0, le=90)
    maturity_days: int = Field(default=30, ge=0, le=90)
    include_shipping_income: bool = False
    reference_net_sales: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    reference_eligible_orders: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def window(self):
        if not 0 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Reconcile an ordered window of at most one year.")
        if len(set(self.cost_batch_ids)) != len(self.cost_batch_ids):
            raise ValueError("Select each cost snapshot once.")
        return self


class ProfitConfig(StrictModel):
    reconciliation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    budget: Decimal = Field(gt=0, le=100000000, decimal_places=2, allow_inf_nan=False)
    start_date: date
    horizon_days: int = Field(default=7, ge=1, le=30)
    platforms: list[PlatformLimit] = Field(min_length=1, max_length=5)
