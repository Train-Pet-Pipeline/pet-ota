"""Tests for pet_ota.config."""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from pet_ota.config import OTAParams, load_params


def test_load_params_from_yaml(
    tmp_dir: pathlib.Path, sample_params: dict[str, Any]
) -> None:
    """load_params returns a valid OTAParams from YAML."""
    p = tmp_dir / "params.yaml"
    p.write_text(yaml.dump(sample_params))
    params = load_params(p)
    assert isinstance(params, OTAParams)
    assert params.release.canary_percentage == 5
    assert params.gate_overrides.dpo_pairs == 600


def test_load_params_defaults(tmp_dir: pathlib.Path) -> None:
    """load_params fills defaults when YAML is empty."""
    p = tmp_dir / "params.yaml"
    p.write_text("{}")
    params = load_params(p)
    assert params.release.failure_rate_threshold == 0.10
    assert params.monitoring.poll_interval_seconds == 30
