"""Pydantic params loader and structured JSON logging setup."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pet_infra.logging import get_logger
from pydantic import BaseModel, ConfigDict, Field


class ReleaseConfig(BaseModel):
    """Release / canary rollout configuration."""

    model_config = ConfigDict(populate_by_name=True)

    canary_percentage: int = 5
    canary_observe_hours: int = 48
    rollback_timeout_minutes: int = 5
    failure_rate_threshold: float = 0.10


class GateOverrides(BaseModel):
    """Gate check override values injected via params.yaml."""

    eval_passed: bool = True
    dpo_pairs: int = 600
    days_since_last_release: int = 10
    open_p0_bugs: int = 0
    canary_group_ready: bool = True


class PackagingConfig(BaseModel):
    """Packaging configuration."""

    delta_enabled: bool = True
    artifact_store_dir: str = "artifacts/store"
    public_key_path: str = ""


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""

    poll_interval_seconds: int = 30
    device_pending_timeout_minutes: int = 30


class DeviceGroupsConfig(BaseModel):
    """Device group file paths."""

    canary: str = "device_groups/canary.json"
    production: str = "device_groups/production.json"


class OTAParams(BaseModel):
    """Root configuration model for pet-ota."""

    model_config = ConfigDict(populate_by_name=True)

    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    gate_overrides: GateOverrides = Field(default_factory=GateOverrides)
    packaging: PackagingConfig = Field(default_factory=PackagingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    device_groups: DeviceGroupsConfig = Field(default_factory=DeviceGroupsConfig)


def load_params(path: str | Path = "params.yaml") -> OTAParams:
    """Load and validate params.yaml into OTAParams.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated OTAParams instance.

    Raises:
        FileNotFoundError: If the params file does not exist.
        pydantic.ValidationError: If the YAML content is invalid.
    """
    with open(path) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return OTAParams(**raw)


def setup_logging() -> None:
    """Configure structured JSON logging (idempotent).

    Sets up pet_infra JSON logging. Safe to call multiple times.
    """
    get_logger("pet-ota")
