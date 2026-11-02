from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from ads_optimizer.domain import PLATFORMS, Platform, StrictModel

Engine = Literal["pandas", "mapreduce", "spark"]
SCALES = [10_000, 100_000, 1_000_000, 10_000_000]
GENERATOR_VERSION = "1.0-batched-v1"
WORKLOAD = "platform_totals_v1"
UNIT_SCALES = {
    "impressions": 1,
    "clicks": 1,
    "spend": 100,
    "conversions": 1_000_000,
    "revenue": 100,
}
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class ExperimentConfig(StrictModel):
    kind: Literal["generate", "benchmark"] = "benchmark"
    rows: Literal[10_000, 100_000, 1_000_000, 10_000_000] = 10_000
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 3, 31)
    platforms: list[Platform] = Field(default_factory=lambda: PLATFORMS.copy(), min_length=1)
    chunk_rows: Literal[10_000, 50_000, 100_000] = 50_000
    engines: list[Engine] = Field(default_factory=lambda: ["pandas", "mapreduce", "spark"])
    repeats: int = Field(default=3, ge=3, le=7)
    workers: int = Field(default=2, ge=1, le=4)
    memory_mib: int = Field(default=2048, ge=512, le=4096)
    dataset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def valid_config(self):
        if not 6 <= (self.end_date - self.start_date).days <= 365:
            raise ValueError("Choose a date range of 7–366 days.")
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError("Choose each platform once.")
        if len(set(self.engines)) != len(self.engines) or len(self.engines) > 3:
            raise ValueError("Choose each engine once.")
        if self.kind == "benchmark" and not self.engines:
            raise ValueError("Select at least one processing engine.")
        return self

    def generation_config(self):
        return {
            key: self.model_dump(mode="json")[key]
            for key in ["rows", "seed", "start_date", "end_date", "platforms", "chunk_rows"]
        }
