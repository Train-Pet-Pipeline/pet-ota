"""Tests for pet_ota.release.rollback."""
from __future__ import annotations

import json
import pathlib
import tarfile

import pytest

from pet_ota.backend.local import LocalBackend
from pet_ota.release.rollback import rollback


def _setup_deployment(
    backend_root: pathlib.Path, version: str, group: str, name: str, status: str = "done"
) -> LocalBackend:
    """Create a backend with an uploaded artifact and deployment."""
    backend = LocalBackend(root_dir=str(backend_root))
    model = backend_root / f"model-{version}.bin"
    model.write_bytes(f"model {version}".encode())
    tar_path = backend_root / f"model-v{version}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar_path), version)
    backend.create_deployment(version, group, name)
    dep_file = backend_root / "deployments" / f"{name}.json"
    data = json.loads(dep_file.read_text())
    data["status"] = status
    if status == "done":
        data["devices"] = {d: "success" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))
    return backend


def test_rollback_aborts_current(backend_root: pathlib.Path) -> None:
    """rollback aborts the current deployment."""
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2.0.0")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    rollback(
        current_deployment_id="v2.0.0-canary",
        backend=backend,
        reason="high failure rate",
    )
    status = backend.get_deployment_status("v2.0.0-canary")
    assert status.status == "rolled_back"


def test_rollback_records_reason(backend_root: pathlib.Path) -> None:
    """rollback writes the reason to the deployment JSON."""
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2.0.0")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    rollback(
        current_deployment_id="v2.0.0-canary",
        backend=backend,
        reason="test rollback reason",
    )
    dep_file = backend_root / "deployments" / "v2.0.0-canary.json"
    data = json.loads(dep_file.read_text())
    assert data["rollback_reason"] == "test rollback reason"


def test_rollback_failure_raises(backend_root: pathlib.Path) -> None:
    """If abort raises, rollback propagates the exception with CRITICAL log."""
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    # Delete the deployment file to make abort fail
    dep_file = backend_root / "deployments" / "v2.0.0-canary.json"
    dep_file.unlink()

    with pytest.raises(Exception):
        rollback(
            current_deployment_id="v2.0.0-canary",
            backend=backend,
            reason="should fail",
        )
