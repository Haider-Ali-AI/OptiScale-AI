"""Versioned workspace capability contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ads_optimizer.domain import DatasetManifest


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    phase: int
    available: bool = False
    reason: str


class WorkspaceState(BaseModel):
    api_version: Literal["v1"] = "v1"
    phase: Literal[6] = 6
    mode: Literal["local_single_user"] = "local_single_user"
    workspace_id: Literal["local"] = "local"
    currency: Literal["PKR"] = "PKR"
    dataset_count: int = 0
    selected_dataset_id: str | None = None
    selected_dataset: DatasetManifest | None = None
    datasets: list[DatasetManifest] = Field(default_factory=list)
    revenue_source: str | None = None
    model_status: Literal["not_trained", "trained", "validated"] = "not_trained"
    hosting_notice: str | None = None
    connected_providers: list[str] = Field(default_factory=list)
    capabilities: list[Capability]
