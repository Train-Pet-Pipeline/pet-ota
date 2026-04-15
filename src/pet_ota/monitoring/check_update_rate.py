"""Check deployment update rates — success, failure, pending."""
from __future__ import annotations

import structlog
from pydantic import BaseModel

from pet_ota.backend.base import OTABackend

logger = structlog.get_logger()


class UpdateRateResult(BaseModel, frozen=True):
    """Deployment update rate statistics."""

    deployment_id: str
    total_devices: int
    success_count: int
    failure_count: int
    pending_count: int
    success_rate: float
    failure_rate: float
    pending_rate: float


def check_update_rate(
    deployment_id: str,
    backend: OTABackend,
) -> UpdateRateResult:
    """Query deployment status and compute update rates.

    Args:
        deployment_id: The deployment to check.
        backend: OTABackend instance.

    Returns:
        UpdateRateResult with computed rates.
    """
    status = backend.get_deployment_status(deployment_id)
    total = status.total_devices
    result = UpdateRateResult(
        deployment_id=deployment_id,
        total_devices=total,
        success_count=status.success_count,
        failure_count=status.failure_count,
        pending_count=status.pending_count,
        success_rate=status.success_count / total if total > 0 else 0.0,
        failure_rate=status.failure_count / total if total > 0 else 0.0,
        pending_rate=status.pending_count / total if total > 0 else 0.0,
    )
    logger.info(
        "update_rate_checked",
        deployment_id=deployment_id,
        success_rate=result.success_rate,
        failure_rate=result.failure_rate,
        pending_rate=result.pending_rate,
    )
    return result
