"""Upload a verified artifact to the OTA backend."""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

from pet_infra.logging import get_logger

from pet_ota.backend.base import OTABackend

logger = get_logger("pet-ota")


def _verify_manifest(release_dir: str) -> None:
    """Verify all files in manifest.json match their sha256 checksums.

    Args:
        release_dir: Path to the release directory containing manifest.json.

    Raises:
        FileNotFoundError: If manifest.json or a listed file is missing.
        ValueError: If a sha256 checksum does not match.
    """
    rd = Path(release_dir)
    manifest_path = rd / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    for filename, meta in manifest.get("files", {}).items():
        file_path = rd / filename
        if not file_path.exists():
            msg = f"File listed in manifest not found: {file_path}"
            raise FileNotFoundError(msg)
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        expected_sha = meta["sha256"]
        if actual_sha != expected_sha:
            msg = f"SHA256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}"
            raise ValueError(msg)

    logger.info("manifest_verified", extra={"release_dir": release_dir})


def upload_artifact(
    release_dir: str,
    version: str,
    backend: OTABackend,
    public_key_path: str = "",
) -> str:
    """Verify package integrity and upload to the OTA backend.

    Args:
        release_dir: Path to the release directory (tarball + manifest.json).
        version: Semantic version string.
        backend: OTABackend instance to upload to.
        public_key_path: Path to RSA public key PEM (optional).

    Returns:
        artifact_id from the backend.

    Raises:
        ValueError: If integrity verification fails.
        FileNotFoundError: If no tarball is found.
    """
    _verify_manifest(release_dir)

    if public_key_path:
        try:
            from pet_quantize.packaging.verify_package import verify_package

            result = verify_package(release_dir, public_key_path)
            if not result.integrity_ok:
                msg = f"Package integrity check failed: {result}"
                raise ValueError(msg)
            logger.info("signature_verified", extra={"release_dir": release_dir})
        except ImportError:
            logger.warning("pet_quantize not available, skipping signature verification", extra={})

    tarballs = glob.glob(str(Path(release_dir) / "*.tar.gz"))
    if not tarballs:
        msg = f"No tarball found in {release_dir}"
        raise FileNotFoundError(msg)

    artifact_id = backend.upload_artifact(tarballs[0], version)
    logger.info("artifact_uploaded", extra={"artifact_id": artifact_id, "version": version})
    return artifact_id
