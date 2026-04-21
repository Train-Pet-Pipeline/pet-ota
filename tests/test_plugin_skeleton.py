"""Smoke tests for pet-ota plugins skeleton (P4-B)."""
from __future__ import annotations

from importlib.metadata import entry_points


def test_pet_ota_entry_point_declared():
    eps = entry_points(group="pet_infra.plugins")
    names = {ep.name for ep in eps}
    assert "pet_ota" in names, f"pet_ota entry-point missing; got: {names}"


def test_register_all_is_callable_without_error():
    from pet_ota.plugins._register import register_all
    # No plugins registered yet (P4-C adds LocalBackendPlugin); call must simply
    # succeed without raising.
    register_all()
