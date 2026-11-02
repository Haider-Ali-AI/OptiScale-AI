from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Platform = Literal["Facebook", "Instagram", "Google", "TikTok", "YouTube"]
PLATFORMS = ["Facebook", "Instagram", "Google", "TikTok", "YouTube"]
DIMENSIONS = ["date", "campaign", "platform", "age", "gender", "city", "device"]
METRICS = ["impressions", "clicks", "spend", "conversions", "revenue"]
FIELDS = ["date", "campaign", "platform", *METRICS, "age", "gender", "city", "device"]
EXTRAS = ["campaign_id", "account_id", "attribution_window", "conversion_definition"]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 100_000


class DomainError(Exception):
    def __init__(self, message: str, status: int = 422):
        self.message = message
        self.status = status
        super().__init__(message)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerateConfig(StrictModel):
    name: str = Field(default="Pakistan campaign demo", min_length=1, max_length=100)
    rows: int = Field(default=10_000, ge=100, le=10_000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 3, 31)
    platforms: list[Platform] = Field(default_factory=lambda: PLATFORMS.copy(), min_length=1)

    @model_validator(mode="after")
    def valid_range(self):
        if not 6 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Choose a date range of 7–366 days.")
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("Choose each platform once.")
        return self


class ImportOptions(StrictModel):
    name: str = Field(default="Imported campaigns", min_length=1, max_length=100)
    mapping: dict[str, str] = Field(max_length=20)
    default_platform: Platform | None = None
    original_currency: str = Field(default="PKR", pattern=r"^[A-Z]{3}$")
    exchange_rate: float | None = Field(default=None, gt=0, le=1e6, allow_inf_nan=False)
    date_format: Literal["auto", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%G-W%V"] = "auto"
    date_granularity: Literal["auto", "daily", "weekly"] = "auto"
    conversion_definition: str = Field(default="unspecified", min_length=1, max_length=100)
    attribution_window: str = Field(default="unspecified", min_length=1, max_length=100)
    is_synthetic: bool = False
    exclude_invalid: bool = False
    drop_duplicates: bool = True
    confirmed: bool = False


class Issue(BaseModel):
    field: str
    message: str
    count: int
    rows: list[int] = Field(default_factory=list)


class ValidationReport(BaseModel):
    date_granularity: Literal["daily", "weekly"] = "daily"
    input_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    excluded_rows: int
    can_import: bool
    is_synthetic: bool
    coverage: dict[str, float]
    warnings: list[str]
    errors: list[Issue]
    preview: list[dict]
    data_ready_for_revenue: bool
    reporting_hints: dict[str, dict] = Field(default_factory=dict)
    provenance_flags: dict[str, bool] = Field(default_factory=dict)


class DatasetManifest(BaseModel):
    id: str
    workspace_id: Literal["local"] = "local"
    name: str
    source: Literal["synthetic_generator", "advertiser_csv", "synthetic_csv"]
    is_synthetic: bool
    original_filename: str | None = None
    import_profile: str | None = None
    imported_at: str
    currency: Literal["PKR"] = "PKR"
    original_currency: str = "PKR"
    exchange_rate: float = 1
    date_granularity: Literal["daily", "weekly"] = "daily"
    import_mapping: dict = Field(default_factory=dict)
    provenance_flags: dict[str, bool] = Field(default_factory=dict)
    date_start: str
    date_end: str
    rows: int
    conversion_definition: str
    attribution_window: str
    revenue_source: Literal["synthetic", "ad_platform_reported"]
    coverage: dict[str, float]
    warnings: list[str]
    data_ready_for_revenue: bool
    options: dict[str, list[str]]
    seed: int | None = None
    parent_dataset_id: str | None = None
    reporting_evidence: dict[str, str] = Field(default_factory=dict)


class AdCampaignDaily(BaseModel):
    """Normalized daily campaign/segment grain; unavailable metrics stay null."""

    date: date
    campaign: str
    platform: Platform
    impressions: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    spend: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    conversions: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    revenue: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    age: str = "unknown"
    gender: str = "unknown"
    city: str = "unknown"
    device: str = "unknown"
    campaign_id: str = "unknown"
    account_id: str = "unknown"
    currency: Literal["PKR"] = "PKR"
    is_synthetic: bool
