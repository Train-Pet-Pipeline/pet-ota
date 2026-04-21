"""Gate guard tests for LocalBackendPlugin (P4-C)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pet_schema.model_card import ModelCard


def _card_with_status(status: str) -> ModelCard:
    return ModelCard(
        id=f"card-{status}",
        version="v1",
        modality="vision",
        task="pet_mood",
        arch="qwen2_vl_2b",
        training_recipe="sft_lora",
        hydra_config_sha="abc",
        git_shas={},
        dataset_versions={},
        checkpoint_uri="file:///tmp/x",
        metrics={},
        gate_status=status,  # type: ignore[arg-type]
        trained_at=datetime(2026, 4, 21, tzinfo=UTC),
        trained_by="ci",
    )


def test_fails_when_gate_failed(tmp_path):
    from pet_ota.plugins.backends.local import LocalBackendPlugin

    plugin = LocalBackendPlugin(storage_root=str(tmp_path))
    with pytest.raises(ValueError, match="gate"):
        plugin.run(_card_with_status("failed"), recipe=MagicMock())


def test_fails_when_gate_pending(tmp_path):
    from pet_ota.plugins.backends.local import LocalBackendPlugin

    plugin = LocalBackendPlugin(storage_root=str(tmp_path))
    with pytest.raises(ValueError, match="gate"):
        plugin.run(_card_with_status("pending"), recipe=MagicMock())
