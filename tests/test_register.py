"""Tests for pet-ota plugin _register wiring."""
from __future__ import annotations


def test_three_backends_registered() -> None:
    """register_all() side-effects register local + s3 + http into the OTA registry."""
    from pet_infra.registry import OTA

    from pet_ota.plugins._register import register_all

    register_all()
    names = set(OTA.module_dict.keys())
    assert {"local_backend", "s3_backend", "http_backend"} <= names
