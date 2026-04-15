"""Failure rate alerting via structured CRITICAL logging."""
from __future__ import annotations

from pet_infra.logging import get_logger

from pet_ota.monitoring.check_update_rate import UpdateRateResult

logger = get_logger("pet-ota")


def check_and_alert(result: UpdateRateResult, threshold: float) -> bool:
    """Check if failure rate meets or exceeds threshold and emit CRITICAL log.

    Args:
        result: UpdateRateResult from check_update_rate.
        threshold: Failure rate threshold (0.0 to 1.0).

    Returns:
        True if alert was fired, False otherwise.
    """
    if result.failure_rate >= threshold:
        logger.critical(
            "deployment_failure_rate_exceeded",
            extra={
                "deployment_id": result.deployment_id,
                "failure_rate": result.failure_rate,
                "threshold": threshold,
                "failure_count": result.failure_count,
                "total_devices": result.total_devices,
            },
        )
        return True
    return False
