"""Tests for pet_ota.monitoring.check_update_rate."""
from __future__ import annotations

import json
import pathlib

from pet_ota.backend.local import LocalBackend
from pet_ota.monitoring.check_update_rate import UpdateRateResult, check_update_rate


def _create_deployment_json(
    backend_root: pathlib.Path,
    deployment_id: str,
    devices: dict[str, str],
) -> None:
    """Write a deployment JSON file directly for testing."""
    data = {
        "deployment_id": deployment_id,
        "version": "1.0.0",
        "device_group": "canary",
        "status": "canary_deploying",
        "created_at": "2026-04-15T10:00:00Z",
        "updated_at": "2026-04-15T10:05:00Z",
        "devices": devices,
    }
    dep_file = backend_root / "deployments" / f"{deployment_id}.json"
    dep_file.write_text(json.dumps(data, indent=2))


def test_all_success(backend_root: pathlib.Path) -> None:
    """100% success rate when all devices succeed."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"dev1": "success", "dev2": "success"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert isinstance(result, UpdateRateResult)
    assert result.success_rate == 1.0
    assert result.failure_rate == 0.0
    assert result.pending_rate == 0.0


def test_mixed_statuses(backend_root: pathlib.Path) -> None:
    """Correct rates with mixed device statuses."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"d1": "success", "d2": "failed", "d3": "pending", "d4": "success"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert result.success_rate == 0.5
    assert result.failure_rate == 0.25
    assert result.pending_rate == 0.25


def test_all_pending(backend_root: pathlib.Path) -> None:
    """100% pending rate when no device has responded."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"d1": "pending", "d2": "pending"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert result.success_rate == 0.0
    assert result.pending_rate == 1.0
