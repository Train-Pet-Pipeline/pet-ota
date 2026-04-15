"""Create a deployment targeting a device group."""
from __future__ import annotations

from pet_infra.logging import get_logger

from pet_ota.backend.base import OTABackend

logger = get_logger("pet-ota")


def create_deployment(
    artifact_id: str,
    device_group: str,
    name: str,
    backend: OTABackend,
) -> str:
    """Create a deployment for the given artifact and device group.

    Args:
        artifact_id: The artifact/version identifier.
        device_group: Target device group name.
        name: Human-readable deployment name (becomes deployment_id).
        backend: OTABackend instance.

    Returns:
        deployment_id from the backend.
    """
    dep_id = backend.create_deployment(artifact_id, device_group, name)
    logger.info(
        "deployment_requested",
        extra={"deployment_id": dep_id, "artifact_id": artifact_id, "device_group": device_group},
    )
    return dep_id
