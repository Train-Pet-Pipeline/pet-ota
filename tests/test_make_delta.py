"""Tests for pet_ota.packaging.make_delta."""
from __future__ import annotations

import pathlib
import tarfile

import bsdiff4

from pet_ota.packaging.make_delta import make_delta


def _make_tarball(tmp_dir: pathlib.Path, name: str, content: bytes) -> pathlib.Path:
    """Create a tarball containing a single model.bin with given content."""
    model_file = tmp_dir / "model.bin"
    model_file.write_bytes(content)
    tar_path = tmp_dir / name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")
    return tar_path


def test_make_delta_creates_patch(tmp_dir: pathlib.Path) -> None:
    """make_delta produces a .patch file."""
    old_tar = _make_tarball(tmp_dir, "old.tar.gz", b"old model weights v1")
    new_tar = _make_tarball(tmp_dir, "new.tar.gz", b"new model weights v2 with extras")
    output = tmp_dir / "delta.patch"
    result = make_delta(str(old_tar), str(new_tar), str(output))
    assert pathlib.Path(result).exists()
    assert pathlib.Path(result).stat().st_size > 0


def test_make_delta_roundtrip(tmp_dir: pathlib.Path) -> None:
    """Applying the delta to the old tarball reproduces the new tarball exactly."""
    old_content = b"old model weights version 1.0"
    new_content = b"new model weights version 2.0 with LoRA adapters"
    old_tar = _make_tarball(tmp_dir, "old.tar.gz", old_content)
    new_tar = _make_tarball(tmp_dir, "new.tar.gz", new_content)
    patch_path = tmp_dir / "delta.patch"
    make_delta(str(old_tar), str(new_tar), str(patch_path))

    old_bytes = old_tar.read_bytes()
    patch_bytes = patch_path.read_bytes()
    reconstructed = bsdiff4.patch(old_bytes, patch_bytes)
    assert reconstructed == new_tar.read_bytes()


def test_make_delta_identical_files(tmp_dir: pathlib.Path) -> None:
    """Delta of identical tarballs produces a patch smaller than the original."""
    # Use uncompressed tar so tarball size >> bsdiff4 overhead (~550 bytes).
    content = b"X" * 65536
    model_file = tmp_dir / "model_identical.bin"
    model_file.write_bytes(content)
    old_tar = tmp_dir / "old_identical.tar"
    new_tar = tmp_dir / "new_identical.tar"
    for tar_path in (old_tar, new_tar):
        with tarfile.open(tar_path, "w") as tar:
            tar.add(model_file, arcname="model.bin")
    patch_path = tmp_dir / "delta_identical.patch"
    make_delta(str(old_tar), str(new_tar), str(patch_path))
    assert patch_path.stat().st_size < old_tar.stat().st_size
