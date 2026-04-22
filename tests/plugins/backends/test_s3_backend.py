"""Tests for S3BackendPlugin (P2-A-2)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pet_schema.model_card import EdgeArtifact, ModelCard


def _base_card_kwargs() -> dict[str, object]:
    return dict(
        id="card-1",
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


def test_s3_backend_uploads_artifacts(s3_bucket: dict[str, str | None]) -> None:
    """Plugin uploads artifact bytes and manifest to S3, appends DeploymentStatus."""
    from pet_infra.storage.s3 import S3Storage

    from pet_ota.plugins.backends.s3 import S3BackendPlugin

    bucket = s3_bucket["bucket"]
    endpoint_url = s3_bucket["endpoint_url"]

    # Upload source artifact to mocked S3
    src_uri = f"s3://{bucket}/source/edge.rknn"
    S3Storage(endpoint_url=endpoint_url).write(src_uri, b"BINARY")

    edge = EdgeArtifact(
        format="rknn",
        target_hardware=["rk3576"],
        artifact_uri=src_uri,
        sha256="d4c9d9027326271a89ce51fcaf328ed673f17be33469ff979e8ab8dd501e664f",
        size_bytes=6,
        input_shape={"pixel_values": [1, 3, 448, 448]},
    )
    card = ModelCard(**_base_card_kwargs(), edge_artifacts=[edge])

    plugin = S3BackendPlugin(bucket=bucket, prefix="ota/", endpoint_url=endpoint_url)
    out = plugin.run(card, MagicMock())

    assert len(out.deployment_history) == 1
    status = out.deployment_history[-1]
    assert status.backend == "s3"
    assert status.state == "deployed"
    manifest_uri = f"s3://{bucket}/ota/card-1/manifest.json"
    assert status.manifest_uri == manifest_uri

    # Verify manifest object exists in S3
    assert S3Storage(endpoint_url=endpoint_url).exists(manifest_uri)


def test_s3_backend_rejects_unpassed_gate(s3_bucket: dict[str, str | None]) -> None:
    """Plugin raises ValueError containing 'gate_status' when gate is not 'passed'."""
    from pet_infra.storage.s3 import S3Storage

    from pet_ota.plugins.backends.s3 import S3BackendPlugin

    bucket = s3_bucket["bucket"]
    endpoint_url = s3_bucket["endpoint_url"]

    src_uri = f"s3://{bucket}/source/edge.rknn"
    S3Storage(endpoint_url=endpoint_url).write(src_uri, b"BINARY")

    edge = EdgeArtifact(
        format="rknn",
        target_hardware=["rk3576"],
        artifact_uri=src_uri,
        sha256="a" * 64,
        size_bytes=6,
        input_shape={"pixel_values": [1, 3, 448, 448]},
    )
    base = ModelCard(**_base_card_kwargs(), edge_artifacts=[edge])
    card = base.model_copy(update={"gate_status": "pending"})

    plugin = S3BackendPlugin(bucket=bucket, prefix="ota/", endpoint_url=endpoint_url)
    with pytest.raises(ValueError, match="gate_status"):
        plugin.run(card, MagicMock())


def test_registered_in_ota_registry() -> None:
    """Importing the module triggers @OTA.register_module side-effect under 's3_backend'."""
    from pet_infra.registry import OTA

    from pet_ota.plugins.backends import s3  # noqa: F401  trigger registration

    assert "s3_backend" in OTA.module_dict


def test_resolves_local_source_via_storage_registry(
    tmp_path: Path, s3_bucket: dict[str, str | None]
) -> None:
    """Plugin resolves plain file-path artifacts via STORAGE registry (file scheme)."""
    from pet_ota.plugins.backends.s3 import S3BackendPlugin

    bucket = s3_bucket["bucket"]
    endpoint_url = s3_bucket["endpoint_url"]

    # Create a real local file with no URI scheme (bare path)
    local_file = tmp_path / "edge.rknn"
    local_file.write_bytes(b"X" * 6)

    edge = EdgeArtifact(
        format="rknn",
        target_hardware=["rk3576"],
        artifact_uri=str(local_file),  # bare path, no scheme
        sha256="b" * 64,
        size_bytes=6,
        input_shape={"pixel_values": [1, 3, 448, 448]},
    )
    card = ModelCard(**_base_card_kwargs(), edge_artifacts=[edge])

    plugin = S3BackendPlugin(bucket=bucket, prefix="ota/", endpoint_url=endpoint_url)
    out = plugin.run(card, MagicMock())

    assert out.deployment_history[-1].state == "deployed"

    # Verify the manifest was written
    from pet_infra.storage.s3 import S3Storage

    manifest_uri = f"s3://{bucket}/ota/card-1/manifest.json"
    assert S3Storage(endpoint_url=endpoint_url).exists(manifest_uri)

    # Verify manifest content references the new s3 URI
    manifest_bytes = S3Storage(endpoint_url=endpoint_url).read(manifest_uri)
    manifest = json.loads(manifest_bytes)
    assert manifest["card_id"] == "card-1"
    assert any(
        a["artifact_uri"].startswith("s3://") for a in manifest["edge_artifacts"]
    )
