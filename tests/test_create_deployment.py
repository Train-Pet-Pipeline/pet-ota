"""Tests for pet_ota.packaging.create_deployment."""
from __future__ import annotations

import pathlib
import tarfile

from pet_ota.backend.local import LocalBackend
from pet_ota.packaging.create_deployment import create_deployment


def _setup_artifact(backend_root: pathlib.Path) -> LocalBackend:
    """Upload a fake artifact and return the backend."""
    backend = LocalBackend(root_dir=str(backend_root))
    model_file = backend_root / "model.bin"
    model_file.write_bytes(b"fake")
    tar_path = backend_root / "model.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")
    backend.upload_artifact(str(tar_path), "1.0.0")
    return backend


def test_create_deployment_returns_id(backend_root: pathlib.Path) -> None:
    """create_deployment returns a deployment_id."""
    backend = _setup_artifact(backend_root)
    dep_id = create_deployment(
        artifact_id="1.0.0",
        device_group="canary",
        name="v1.0.0-canary",
        backend=backend,
    )
    assert dep_id == "v1.0.0-canary"


def test_create_deployment_persists_state(backend_root: pathlib.Path) -> None:
    """create_deployment creates a retrievable deployment."""
    backend = _setup_artifact(backend_root)
    create_deployment(
        artifact_id="1.0.0",
        device_group="canary",
        name="v1.0.0-canary",
        backend=backend,
    )
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.version == "1.0.0"
    assert status.device_group == "canary"
    assert status.total_devices == 2
