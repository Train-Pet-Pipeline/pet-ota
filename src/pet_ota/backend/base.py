"""OTABackend Protocol and DeploymentStatus model."""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel


class DeploymentStatus(BaseModel, frozen=True):
    """Immutable snapshot of a deployment's current state."""

    deployment_id: str
    version: str
    device_group: str
    status: Literal[
        "gate_check",
        "canary_deploying",
        "canary_observing",
        "full_deploying",
        "done",
        "failed",
        "rolling_back",
        "rolled_back",
        "rollback_failed",
    ]
    total_devices: int
    success_count: int
    failure_count: int
    pending_count: int
    created_at: str
    updated_at: str


class OTABackend(Protocol):
    """OTA backend unified interface.

    v1: LocalBackend (filesystem). Future: MenderBackend.
    """

    def upload_artifact(self, artifact_path: str, version: str) -> str:
        """Upload an artifact, return artifact_id."""
        ...

    def list_device_groups(self) -> list[str]:
        """List all device group names."""
        ...

    def create_deployment(
        self, artifact_id: str, device_group: str, name: str
    ) -> str:
        """Create a deployment, return deployment_id."""
        ...

    def get_deployment_status(self, deployment_id: str) -> DeploymentStatus:
        """Query deployment status."""
        ...

    def abort_deployment(self, deployment_id: str) -> None:
        """Abort a deployment (used for rollback)."""
        ...

    def update_deployment_status(self, deployment_id: str, status: str) -> None:
        """Update the status field of a deployment."""
        ...

    def update_deployment_metadata(
        self, deployment_id: str, updates: dict[str, str]
    ) -> None:
        """Merge key-value updates into a deployment record."""
        ...

    def get_device_update_history(self, device_group: str) -> list[dict[str, Any]]:
        """Query update history for a device group."""
        ...
