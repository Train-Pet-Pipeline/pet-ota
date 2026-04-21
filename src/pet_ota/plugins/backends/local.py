"""LocalBackend plugin — writes OTA manifest + artifact to local filesystem.

YAGNI: pet-ota 2.0.0 ships only this backend. Production backends (S3/HTTP/CDN)
are future scope.
"""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pet_infra.registry import OTA
from pet_schema.model_card import DeploymentStatus, ModelCard
from pet_schema.recipe import ExperimentRecipe


@OTA.register_module(name="local_backend", force=True)
class LocalBackendPlugin:
    """Copies edge_artifacts to local storage and writes manifest.json."""

    def __init__(self, storage_root: str | Path = "./ota_artifacts", **kwargs: object) -> None:
        """Initialize with storage root directory."""
        self.storage_root = Path(storage_root)
        self.extra = kwargs

    def run(self, input_card: ModelCard, recipe: ExperimentRecipe) -> ModelCard:
        """Deploy model artifacts to local filesystem OTA storage.

        Gate guard: raises ValueError when gate_status != 'passed'.
        Copies edge_artifacts to storage_root/<card.id>/, writes manifest.json,
        appends DeploymentStatus to deployment_history.
        """
        if input_card.gate_status != "passed":
            raise ValueError(
                f"LocalBackendPlugin refused: gate_status={input_card.gate_status!r} "
                "(must be 'passed' to deploy to OTA)"
            )

        storage = self.storage_root / input_card.id
        storage.mkdir(parents=True, exist_ok=True)

        for edge in input_card.edge_artifacts:
            src = Path(edge.artifact_uri)
            if src.exists():
                shutil.copy2(src, storage / src.name)

        manifest_path = storage / "manifest.json"
        manifest = input_card.to_manifest_entry()
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

        status = DeploymentStatus(
            backend="local",
            state="deployed",
            deployed_at=datetime.now(UTC),
            manifest_uri=f"file://{manifest_path}",
        )
        return input_card.model_copy(
            update={"deployment_history": [*input_card.deployment_history, status]}
        )
