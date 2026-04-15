"""Shared pytest fixtures for pet-ota tests."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
import yaml


@pytest.fixture()
def tmp_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture()
def sample_params() -> dict[str, Any]:
    """Return a minimal valid params dict for testing."""
    return {
        "release": {
            "canary_percentage": 5,
            "canary_observe_hours": 0,
            "rollback_timeout_minutes": 5,
            "failure_rate_threshold": 0.10,
        },
        "gate_overrides": {
            "eval_passed": True,
            "dpo_pairs": 600,
            "days_since_last_release": 10,
            "open_p0_bugs": 0,
            "canary_group_ready": True,
        },
        "packaging": {
            "delta_enabled": True,
            "artifact_store_dir": "artifacts/store",
            "public_key_path": "",
        },
        "monitoring": {
            "poll_interval_seconds": 0,
            "device_pending_timeout_minutes": 30,
        },
        "device_groups": {
            "canary": "device_groups/canary.json",
            "production": "device_groups/production.json",
        },
    }


@pytest.fixture()
def sample_params_path(
    tmp_dir: pathlib.Path, sample_params: dict[str, Any]
) -> pathlib.Path:
    """Write sample_params to a YAML file and return its path."""
    params_file = tmp_dir / "params.yaml"
    params_file.write_text(yaml.dump(sample_params))
    return params_file


@pytest.fixture()
def backend_root(tmp_dir: pathlib.Path) -> pathlib.Path:
    """Create and return a root directory for LocalBackend with device groups."""
    root = tmp_dir / "ota_root"
    root.mkdir()
    (root / "artifacts" / "store").mkdir(parents=True)
    (root / "deployments").mkdir()
    dg = root / "device_groups"
    dg.mkdir()
    (dg / "canary.json").write_text(json.dumps(["device_001", "device_002"]))
    (dg / "production.json").write_text(
        json.dumps([f"device_{i:03d}" for i in range(1, 41)])
    )
    return root
