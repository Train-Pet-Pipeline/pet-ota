"""Tests for pet_ota.packaging.upload_artifact."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tarfile

import pytest

from pet_ota.backend.local import LocalBackend
from pet_ota.packaging.upload_artifact import upload_artifact


def _make_release_dir(tmp_dir: pathlib.Path, version: str) -> pathlib.Path:
    """Create a release directory with a tarball and manifest.json."""
    release_dir = tmp_dir / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    model_file = tmp_dir / "model.bin"
    model_file.write_bytes(b"fake quantized model weights")
    tar_name = f"pet-model-v{version}.tar.gz"
    tar_path = release_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")
    sha256 = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    manifest = {
        "version": version,
        "files": {tar_name: {"sha256": sha256, "size": tar_path.stat().st_size}},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest))
    return release_dir


def test_upload_artifact_success(backend_root: pathlib.Path) -> None:
    """upload_artifact stores artifact and returns artifact_id."""
    backend = LocalBackend(root_dir=str(backend_root))
    release_dir = _make_release_dir(backend_root / "tmp_release", "1.0.0")
    artifact_id = upload_artifact(
        release_dir=str(release_dir),
        version="1.0.0",
        backend=backend,
        public_key_path="",
    )
    assert artifact_id == "1.0.0"
    stored = backend_root / "artifacts" / "store" / "v1.0.0"
    assert stored.exists()


def test_upload_artifact_bad_manifest(
    backend_root: pathlib.Path, tmp_dir: pathlib.Path
) -> None:
    """upload_artifact raises when manifest sha256 doesn't match."""
    release_dir = _make_release_dir(tmp_dir / "bad_release", "1.0.0")
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for f in manifest["files"]:
        manifest["files"][f]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    backend = LocalBackend(root_dir=str(backend_root))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        upload_artifact(
            release_dir=str(release_dir),
            version="1.0.0",
            backend=backend,
            public_key_path="",
        )
