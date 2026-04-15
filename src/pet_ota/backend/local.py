"""LocalBackend — filesystem-based OTA backend implementation."""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pet_infra.logging import get_logger

from pet_ota.backend.base import DeploymentStatus

logger = get_logger("pet-ota")


class LocalBackend:
    """OTA backend backed by local filesystem.

    Directory layout under root_dir:
        artifacts/store/<version>/   — uploaded tarballs
        deployments/                 — deployment JSON state files
        device_groups/               — device group membership files
    """

    def __init__(self, root_dir: str) -> None:
        """Initialize LocalBackend.

        Args:
            root_dir: Root directory for all OTA data.
        """
        self._root = Path(root_dir)
        self._store = self._root / "artifacts" / "store"
        self._deployments = self._root / "deployments"
        self._device_groups = self._root / "device_groups"

    def upload_artifact(self, artifact_path: str, version: str) -> str:
        """Copy artifact to versioned store directory.

        Args:
            artifact_path: Path to the tarball file.
            version: Semantic version string.

        Returns:
            artifact_id (same as version for LocalBackend).
        """
        dest_dir = self._store / f"v{version}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = Path(artifact_path)
        shutil.copy2(src, dest_dir / src.name)
        logger.info(
            "artifact_uploaded", extra={"version": version, "path": str(dest_dir / src.name)}
        )
        return version

    def list_device_groups(self) -> list[str]:
        """List device group names from JSON files in device_groups/.

        Returns:
            Sorted list of device group names (filename stems).
        """
        return sorted(p.stem for p in self._device_groups.glob("*.json"))

    def _load_devices(self, device_group: str) -> list[str]:
        """Load device IDs from a device group JSON file.

        Args:
            device_group: Name of the device group.

        Returns:
            List of device ID strings.

        Raises:
            FileNotFoundError: If the device group file does not exist.
        """
        path = self._device_groups / f"{device_group}.json"
        return json.loads(path.read_text())  # type: ignore[no-any-return]

    def create_deployment(
        self, artifact_id: str, device_group: str, name: str
    ) -> str:
        """Create a new deployment JSON file.

        Args:
            artifact_id: The version/artifact identifier.
            device_group: Target device group name.
            name: Deployment name (used as deployment_id).

        Returns:
            deployment_id (same as name).
        """
        devices = self._load_devices(device_group)
        now = datetime.now(UTC).isoformat()
        data = {
            "deployment_id": name,
            "version": artifact_id,
            "device_group": device_group,
            "status": "canary_deploying",
            "created_at": now,
            "updated_at": now,
            "devices": {d: "pending" for d in devices},
        }
        dep_file = self._deployments / f"{name}.json"
        dep_file.write_text(json.dumps(data, indent=2))
        logger.info(
            "deployment_created", extra={"deployment_id": name, "device_group": device_group}
        )
        return name

    def get_deployment_status(self, deployment_id: str) -> DeploymentStatus:
        """Read deployment JSON and return a DeploymentStatus snapshot.

        Args:
            deployment_id: The deployment identifier.

        Returns:
            Frozen DeploymentStatus instance.

        Raises:
            FileNotFoundError: If the deployment file does not exist.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        devices: dict[str, str] = data.get("devices", {})
        success = sum(1 for v in devices.values() if v == "success")
        failure = sum(1 for v in devices.values() if v in ("failed", "timeout"))
        pending = sum(1 for v in devices.values() if v == "pending")
        return DeploymentStatus(
            deployment_id=data["deployment_id"],
            version=data["version"],
            device_group=data["device_group"],
            status=data["status"],
            total_devices=len(devices),
            success_count=success,
            failure_count=failure,
            pending_count=pending,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def abort_deployment(self, deployment_id: str) -> None:
        """Set deployment status to 'rolling_back'.

        Args:
            deployment_id: The deployment to abort.
        """
        self.update_deployment_status(deployment_id, "rolling_back")
        logger.info("deployment_aborted", extra={"deployment_id": deployment_id})

    def update_deployment_status(self, deployment_id: str, status: str) -> None:
        """Update the status field in a deployment JSON file.

        Args:
            deployment_id: The deployment identifier.
            status: New status string.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        data["status"] = status
        data["updated_at"] = datetime.now(UTC).isoformat()
        dep_file.write_text(json.dumps(data, indent=2))

    def update_deployment_metadata(
        self, deployment_id: str, updates: dict[str, str]
    ) -> None:
        """Merge key-value updates into a deployment JSON record.

        Args:
            deployment_id: The deployment identifier.
            updates: Key-value pairs to merge into the deployment record.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        data.update(updates)
        data["updated_at"] = datetime.now(UTC).isoformat()
        dep_file.write_text(json.dumps(data, indent=2))

    def get_device_update_history(self, device_group: str) -> list[dict[str, Any]]:
        """Return all deployments targeting the given device group.

        Args:
            device_group: Name of the device group.

        Returns:
            List of deployment dicts, sorted by created_at ascending.
        """
        results: list[dict[str, Any]] = []
        for dep_file in self._deployments.glob("*.json"):
            data = json.loads(dep_file.read_text())
            if data.get("device_group") == device_group:
                results.append(data)
        return sorted(results, key=lambda d: d.get("created_at", ""))
