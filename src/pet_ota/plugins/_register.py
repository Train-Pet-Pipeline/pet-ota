"""Entry-point target for pet-infra's plugin discovery.

Imports pet-ota plugin modules to trigger @OTA.register_module side-effects.
Phase 4 ships all three OTA backends: local, s3, and http.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_all() -> None:
    """Import pet-ota plugin modules to trigger registration side-effects."""
    try:
        import pet_infra  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "pet-ota v2 requires pet-infra. Install via matrix row 2026.08."
        ) from e

    from pet_ota.plugins.backends import (
        http,  # noqa: F401  triggers @OTA.register_module
        local,  # noqa: F401  triggers @OTA.register_module
        s3,  # noqa: F401  triggers @OTA.register_module
    )
