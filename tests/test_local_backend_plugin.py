"""Tests for LocalBackendPlugin (P4-C)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pet_schema.model_card import EdgeArtifact, ModelCard


def _base_card_kwargs() -> dict[str, object]:
    return dict(
        id="ota-test",
        version="v1",
        modality="vision",
        task="pet_mood",
        arch="qwen2_vl_2b",
        training_recipe="sft_lora",
        hydra_config_sha="abc123",
        git_shas={"pet-train": "deadbeef"},
        dataset_versions={"ds": "v1"},
        checkpoint_uri="file:///tmp/ckpt",
        metrics={"mood_correlation": 0.85},
        gate_status="passed",
        trained_at=datetime(2026, 4, 21, tzinfo=UTC),
        trained_by="ci",
    )


@pytest.fixture
def passed_card(tmp_path: Path) -> ModelCard:
    """ModelCard with gate_status='passed' and a real edge artifact file."""
    artifact_file = tmp_path / "m.rknn"
    artifact_file.write_bytes(b"x" * 1024)
    edge = EdgeArtifact(
        format="rknn",
        target_hardware=["rk3576"],
        artifact_uri=str(artifact_file),
        sha256="b" * 64,
        size_bytes=1024,
        input_shape={"pixel_values": [1, 3, 448, 448]},
    )
    return ModelCard(**_base_card_kwargs(), edge_artifacts=[edge])


def test_local_backend_writes_manifest_and_artifact(passed_card: ModelCard, tmp_path: Path) -> None:
    from pet_ota.plugins.backends.local import LocalBackendPlugin

    plugin = LocalBackendPlugin(storage_root=str(tmp_path / "ota"))
    out = plugin.run(passed_card, recipe=MagicMock())

    storage = tmp_path / "ota" / out.id
    assert (storage / "manifest.json").exists()
    assert len(list(storage.glob("*.rknn"))) == 1
    assert len(out.deployment_history) == 1
    assert out.deployment_history[0].backend == "local"
    assert out.deployment_history[0].state == "deployed"


def test_manifest_uses_to_manifest_entry(passed_card: ModelCard, tmp_path: Path) -> None:
    from pet_ota.plugins.backends.local import LocalBackendPlugin

    plugin = LocalBackendPlugin(storage_root=str(tmp_path / "ota"))
    out = plugin.run(passed_card, recipe=MagicMock())

    manifest_path = tmp_path / "ota" / out.id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["id"] == "ota-test"
    assert "edge_artifacts" in manifest


def test_registered_in_ota_registry() -> None:
    """Importing triggers @OTA.register_module side-effect under name 'local_backend'."""
    from pet_infra.registry import OTA

    from pet_ota.plugins.backends import local  # noqa: F401  trigger registration

    assert "local_backend" in OTA.module_dict
