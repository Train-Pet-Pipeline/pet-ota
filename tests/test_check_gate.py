"""Tests for pet_ota.release.check_gate."""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from pet_ota.release.check_gate import check_gate


def _write_params(tmp_dir: pathlib.Path, overrides: dict[str, Any]) -> pathlib.Path:
    """Write a params.yaml with the given gate_overrides."""
    params = {
        "release": {
            "canary_percentage": 5,
            "canary_observe_hours": 0,
            "rollback_timeout_minutes": 5,
            "failure_rate_threshold": 0.10,
        },
        "gate_overrides": overrides,
        "packaging": {
            "delta_enabled": True,
            "artifact_store_dir": "artifacts/store",
            "public_key_path": "",
        },
        "monitoring": {"poll_interval_seconds": 0, "device_pending_timeout_minutes": 30},
        "device_groups": {
            "canary": "device_groups/canary.json",
            "production": "device_groups/production.json",
        },
    }
    p = tmp_dir / "params.yaml"
    p.write_text(yaml.dump(params))
    return p


def test_all_gates_pass(tmp_dir: pathlib.Path) -> None:
    """All 5 gates passing returns (True, [])."""
    params_path = _write_params(tmp_dir, {
        "eval_passed": True,
        "dpo_pairs": 600,
        "days_since_last_release": 10,
        "open_p0_bugs": 0,
        "canary_group_ready": True,
    })
    passed, failures = check_gate(str(params_path))
    assert passed is True
    assert failures == []


def test_eval_failed(tmp_dir: pathlib.Path) -> None:
    """eval_passed=False should fail the gate."""
    params_path = _write_params(tmp_dir, {
        "eval_passed": False,
        "dpo_pairs": 600,
        "days_since_last_release": 10,
        "open_p0_bugs": 0,
        "canary_group_ready": True,
    })
    passed, failures = check_gate(str(params_path))
    assert passed is False
    assert "eval_passed" in failures[0]


def test_dpo_pairs_insufficient(tmp_dir: pathlib.Path) -> None:
    """dpo_pairs < 500 should fail."""
    params_path = _write_params(tmp_dir, {
        "eval_passed": True,
        "dpo_pairs": 400,
        "days_since_last_release": 10,
        "open_p0_bugs": 0,
        "canary_group_ready": True,
    })
    passed, failures = check_gate(str(params_path))
    assert passed is False
    assert any("dpo_pairs" in f for f in failures)


def test_multiple_failures(tmp_dir: pathlib.Path) -> None:
    """Multiple gate failures are all reported."""
    params_path = _write_params(tmp_dir, {
        "eval_passed": False,
        "dpo_pairs": 100,
        "days_since_last_release": 3,
        "open_p0_bugs": 2,
        "canary_group_ready": False,
    })
    passed, failures = check_gate(str(params_path))
    assert passed is False
    assert len(failures) == 5
