"""Tests for pet_ota.release.canary_rollout — full state machine."""
from __future__ import annotations

import glob
import hashlib
import json
import pathlib
import tarfile
from typing import Any

import yaml

from pet_ota.release.canary_rollout import RolloutResult, canary_rollout


def _setup_full_env(
    tmp_dir: pathlib.Path, gate_overrides: dict[str, Any] | None = None
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Set up a complete OTA environment for rollout testing.

    Returns (root_dir, release_dir, params_path).
    """
    root = tmp_dir / "ota_root"
    root.mkdir()
    (root / "artifacts" / "store").mkdir(parents=True)
    (root / "deployments").mkdir()
    dg = root / "device_groups"
    dg.mkdir()
    (dg / "canary.json").write_text(json.dumps(["device_001", "device_002"]))
    (dg / "production.json").write_text(
        json.dumps([f"device_{i:03d}" for i in range(1, 11)])
    )

    release_dir = tmp_dir / "release"
    release_dir.mkdir()
    model = tmp_dir / "model.bin"
    model.write_bytes(b"quantized model weights v1.0.0")
    tar_name = "pet-model-v1.0.0.tar.gz"
    tar_path = release_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model, arcname="model.bin")
    sha256 = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    manifest = {
        "version": "1.0.0",
        "files": {tar_name: {"sha256": sha256, "size": tar_path.stat().st_size}},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest))

    overrides = gate_overrides or {
        "eval_passed": True,
        "dpo_pairs": 600,
        "days_since_last_release": 10,
        "open_p0_bugs": 0,
        "canary_group_ready": True,
    }
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
            "canary": str(dg / "canary.json"),
            "production": str(dg / "production.json"),
        },
    }
    params_path = tmp_dir / "params.yaml"
    params_path.write_text(yaml.dump(params))

    return root, release_dir, params_path


def _sim_success(backend: object, dep_id: str) -> None:
    """Simulate all devices succeeding (test helper)."""
    dep_file = backend._root / "deployments" / f"{dep_id}.json"  # type: ignore[attr-defined]
    data = json.loads(dep_file.read_text())
    data["devices"] = {d: "success" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))


def _sim_failure(backend: object, dep_id: str) -> None:
    """Simulate all devices failing (test helper)."""
    dep_file = backend._root / "deployments" / f"{dep_id}.json"  # type: ignore[attr-defined]
    data = json.loads(dep_file.read_text())
    data["devices"] = {d: "failed" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))


def test_happy_path_full_rollout(tmp_dir: pathlib.Path) -> None:
    """Full canary -> production rollout succeeds when all devices pass."""
    root, release_dir, params_path = _setup_full_env(tmp_dir)
    result = canary_rollout(
        version="1.0.0",
        release_dir=str(release_dir),
        root_dir=str(root),
        params_path=str(params_path),
        device_simulator=_sim_success,
    )
    assert isinstance(result, RolloutResult)
    assert result.final_status == "done"


def test_gate_failure_stops_rollout(tmp_dir: pathlib.Path) -> None:
    """Gate check failure prevents any deployment."""
    root, release_dir, params_path = _setup_full_env(
        tmp_dir, gate_overrides={"eval_passed": False, "dpo_pairs": 600,
                                  "days_since_last_release": 10, "open_p0_bugs": 0,
                                  "canary_group_ready": True}
    )
    result = canary_rollout(
        version="1.0.0",
        release_dir=str(release_dir),
        root_dir=str(root),
        params_path=str(params_path),
    )
    assert result.final_status == "failed"
    assert "eval_passed" in str(result.gate_failures)


def test_canary_failure_triggers_rollback(tmp_dir: pathlib.Path) -> None:
    """High failure rate during canary triggers rollback."""
    root, release_dir, params_path = _setup_full_env(tmp_dir)
    result = canary_rollout(
        version="1.0.0",
        release_dir=str(release_dir),
        root_dir=str(root),
        params_path=str(params_path),
        device_simulator=_sim_failure,
    )
    assert result.final_status in ("rolled_back", "rollback_failed")


def test_resume_from_canary_observing(tmp_dir: pathlib.Path) -> None:
    """Process restart resumes from canary_observing, skips gate check."""
    root, release_dir, params_path = _setup_full_env(tmp_dir)

    from pet_ota.backend.local import LocalBackend
    backend = LocalBackend(root_dir=str(root))
    tarballs = glob.glob(str(release_dir / "*.tar.gz"))
    backend.upload_artifact(tarballs[0], "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    backend.update_deployment_status("v1.0.0-canary", "canary_observing")
    _sim_success(backend, "v1.0.0-canary")

    result = canary_rollout(
        version="1.0.0",
        release_dir=str(release_dir),
        root_dir=str(root),
        params_path=str(params_path),
        device_simulator=_sim_success,
    )
    assert result.final_status == "done"
