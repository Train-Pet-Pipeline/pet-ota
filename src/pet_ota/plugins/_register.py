"""Entry-point target for pet-infra's plugin discovery.

Imports pet-ota plugin modules to trigger @OTA.register_module side-effects.
v2.0.0 ships LocalBackendPlugin in P4-C; this skeleton lands first so the
entry-point wiring is proven independently.
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

    # Plugins arrive in P4-C (LocalBackendPlugin). This skeleton deliberately
    # registers nothing so the entry-point wiring can be validated in isolation.
