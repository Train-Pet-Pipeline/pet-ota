"""Entry-point target for pet-infra's plugin discovery.

Imports pet-ota plugin modules to trigger @OTA.register_module side-effects.
Phase 4 ships all three OTA backends: local, s3, and http.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register_all() -> None:
    """Import pet-ota plugin modules to trigger registration side-effects."""
    # pet-infra is a β peer-dep (not in pyproject.dependencies as of v2.2.0);
    # the guard is intentionally inside register_all so bare `import pet_ota`
    # remains lightweight for IDE / static-analysis use (see DEV_GUIDE §11.3
    # "delayed-guard" variant — same pattern adopted by pet-quantize Phase 7).
    # peer-dep-smoke.yml is the producer-side contract.
    try:
        import pet_infra  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "pet-ota requires pet-infra to be installed first. "
            "Install via latest matrix row (pet-infra/docs/compatibility_matrix.yaml)."
        ) from e

    from pet_ota.plugins.backends import (
        http,  # noqa: F401  triggers @OTA.register_module
        local,  # noqa: F401  triggers @OTA.register_module
        s3,  # noqa: F401  triggers @OTA.register_module
    )
