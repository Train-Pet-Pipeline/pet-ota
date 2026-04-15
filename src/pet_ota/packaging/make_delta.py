"""bsdiff4-based delta patch creation for OTA updates."""
from __future__ import annotations

from pathlib import Path

from pet_infra.logging import get_logger
from tenacity import retry, stop_after_attempt, wait_fixed

logger = get_logger("pet-ota")


@retry(stop=stop_after_attempt(3), wait=wait_fixed(1), reraise=True)
def make_delta(old_tarball: str, new_tarball: str, output_path: str) -> str:
    """Create a binary delta patch between two tarballs using bsdiff4.

    Args:
        old_tarball: Path to the old version tarball.
        new_tarball: Path to the new version tarball.
        output_path: Path where the delta .patch file will be written.

    Returns:
        The output_path where the patch was written.

    Raises:
        FileNotFoundError: If either tarball does not exist.
        Exception: If bsdiff4 fails after 3 retries.
    """
    import bsdiff4

    old_bytes = Path(old_tarball).read_bytes()
    new_bytes = Path(new_tarball).read_bytes()

    logger.info(
        "make_delta_start",
        extra={"old_size": len(old_bytes), "new_size": len(new_bytes), "output_path": output_path},
    )

    patch_bytes = bsdiff4.diff(old_bytes, new_bytes)

    with open(output_path, "wb") as fh:
        fh.write(patch_bytes)

    logger.info(
        "make_delta_done",
        extra={"patch_size": len(patch_bytes), "output_path": output_path},
    )
    return output_path
