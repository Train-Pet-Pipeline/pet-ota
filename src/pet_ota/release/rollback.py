"""Rollback — abort current deployment and restore previous version."""
from __future__ import annotations

from pet_infra.logging import get_logger

from pet_ota.backend.base import OTABackend

logger = get_logger("pet-ota")


def rollback(
    current_deployment_id: str,
    backend: OTABackend,
    reason: str,
) -> None:
    """Abort the current deployment and mark it as rolled back.

    Args:
        current_deployment_id: The deployment to roll back.
        backend: OTABackend instance.
        reason: Human-readable reason for the rollback.

    Raises:
        Exception: If the rollback itself fails (logged as CRITICAL).
    """
    logger.info(
        "rollback_start",
        extra={"deployment_id": current_deployment_id, "reason": reason},
    )
    try:
        backend.abort_deployment(current_deployment_id)
        backend.update_deployment_status(current_deployment_id, "rolled_back")
        backend.update_deployment_metadata(
            current_deployment_id, {"rollback_reason": reason}
        )
        logger.info("rollback_complete", extra={"deployment_id": current_deployment_id})
    except Exception:
        logger.critical(
            "rollback_failed",
            extra={"deployment_id": current_deployment_id, "reason": reason},
        )
        raise
