"""Parity test: __version__ in __init__.py must match importlib.metadata version."""
from __future__ import annotations

import importlib.metadata

import pet_ota


def test_version_attribute_matches_metadata() -> None:
    """pet_ota.__version__ must equal the installed package version from pip metadata."""
    installed = importlib.metadata.version("pet-ota")
    assert pet_ota.__version__ == installed, (
        f"pet_ota.__version__ ({pet_ota.__version__!r}) does not match "
        f"installed package metadata ({installed!r}). "
        "Update src/pet_ota/__init__.py to match pyproject.toml version."
    )
