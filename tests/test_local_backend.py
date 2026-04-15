"""Tests for pet_ota.backend.local.LocalBackend."""
from __future__ import annotations

import json
import pathlib
import tarfile

from pet_ota.backend.local import LocalBackend


def _make_tarball(tmp_dir: pathlib.Path, name: str) -> pathlib.Path:
    """Create a minimal tarball for testing."""
    content_file = tmp_dir / "model.bin"
    content_file.write_bytes(b"fake model weights")
    tar_path = tmp_dir / name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(content_file, arcname="model.bin")
    return tar_path


def test_upload_artifact(backend_root: pathlib.Path) -> None:
    """upload_artifact copies tarball to store and returns artifact_id."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    artifact_id = backend.upload_artifact(str(tarball), "1.0.0")
    assert artifact_id == "1.0.0"
    stored = backend_root / "artifacts" / "store" / "v1.0.0" / "model-v1.0.0.tar.gz"
    assert stored.exists()


def test_list_device_groups(backend_root: pathlib.Path) -> None:
    """list_device_groups returns names of JSON files in device_groups/."""
    backend = LocalBackend(root_dir=str(backend_root))
    groups = backend.list_device_groups()
    assert sorted(groups) == ["canary", "production"]


def test_create_deployment(backend_root: pathlib.Path) -> None:
    """create_deployment writes a deployment JSON and returns its ID."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    dep_id = backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    assert dep_id == "v1.0.0-canary"
    dep_file = backend_root / "deployments" / "v1.0.0-canary.json"
    assert dep_file.exists()
    data = json.loads(dep_file.read_text())
    assert data["status"] == "canary_deploying"
    assert data["device_group"] == "canary"


def test_get_deployment_status(backend_root: pathlib.Path) -> None:
    """get_deployment_status reads back a valid DeploymentStatus."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.deployment_id == "v1.0.0-canary"
    assert status.total_devices == 2
    assert status.pending_count == 2
    assert status.success_count == 0


def test_abort_deployment(backend_root: pathlib.Path) -> None:
    """abort_deployment sets status to 'rolling_back'."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    backend.abort_deployment("v1.0.0-canary")
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.status == "rolling_back"


def test_get_device_update_history_empty(backend_root: pathlib.Path) -> None:
    """get_device_update_history returns empty list when no deployments exist."""
    backend = LocalBackend(root_dir=str(backend_root))
    history = backend.get_device_update_history("canary")
    assert history == []


def test_get_device_update_history_with_data(backend_root: pathlib.Path) -> None:
    """get_device_update_history returns deployment records for the group."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    history = backend.get_device_update_history("canary")
    assert len(history) == 1
    assert history[0]["version"] == "1.0.0"
