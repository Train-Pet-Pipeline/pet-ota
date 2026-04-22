"""S3BackendPlugin — uploads OTA artifacts + manifest to an S3-compatible bucket.

Resolves source artifacts via the STORAGE registry so ``file://``, ``local://``,
``s3://``, and ``http://`` source URIs all work transparently.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

# Trigger registration of the storage backends so STORAGE.build() resolves them.
import pet_infra.storage.local  # noqa: F401
import pet_infra.storage.s3  # noqa: F401
from pet_infra.registry import OTA, STORAGE
from pet_schema.model_card import DeploymentStatus, ModelCard
from pet_schema.recipe import ExperimentRecipe


@OTA.register_module(name="s3_backend", force=True)
class S3BackendPlugin:
    """Uploads edge_artifacts to S3 and writes a manifest.json to the same prefix."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "ota/",
        endpoint_url: str | None = None,
        **_: object,
    ) -> None:
        """Initialize with S3 destination parameters.

        Args:
            bucket: Target S3 bucket name.
            prefix: Key prefix under which card artifacts are written.
                Trailing slash is normalised automatically.
            endpoint_url: Optional custom endpoint (e.g. MinIO, moto).
                When ``None`` (default), boto3 resolves AWS endpoints.
            **_: Extra kwargs are accepted and silently ignored so the
                plugin stays forward-compatible with registry configs.
        """
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._endpoint_url = endpoint_url

    def run(self, input_card: ModelCard, recipe: ExperimentRecipe) -> ModelCard:
        """Upload edge artifacts and manifest.json to S3.

        Gate guard: raises ValueError when gate_status != 'passed'.
        For each EdgeArtifact, reads source bytes via the STORAGE registry
        (supports file://, local://, s3://, http:// sources) and writes to
        s3://<bucket>/<prefix>/<card_id>/<filename>.  Writes a compact
        manifest JSON and appends a DeploymentStatus to deployment_history.

        Args:
            input_card: The ModelCard to deploy.
            recipe: The ExperimentRecipe that produced the card (unused,
                accepted for interface compatibility).

        Returns:
            A copy of ``input_card`` with a new DeploymentStatus appended.

        Raises:
            ValueError: When ``input_card.gate_status`` is not ``'passed'``.
        """
        if input_card.gate_status != "passed":
            raise ValueError(
                f"S3BackendPlugin refused: gate_status={input_card.gate_status!r} "
                "(must be 'passed' to deploy to OTA)"
            )

        from pet_infra.storage.s3 import S3Storage

        dest_storage = S3Storage(endpoint_url=self._endpoint_url)
        card_prefix = f"{self._prefix}{input_card.id}/"

        artifact_entries: list[dict[str, object]] = []
        for art in input_card.edge_artifacts:
            # Resolve source bytes via the STORAGE registry so any scheme works.
            parsed = urlparse(art.artifact_uri)
            scheme = parsed.scheme or "file"
            # Bare paths have no scheme; normalise to a file:// URI so LocalStorage
            # can handle them without a scheme-validation error.
            read_uri = art.artifact_uri if parsed.scheme else f"file://{art.artifact_uri}"
            src_data = STORAGE.build({"type": scheme}).read(read_uri)

            filename = PurePosixPath(urlparse(art.artifact_uri).path).name
            dest_uri = f"s3://{self._bucket}/{card_prefix}{filename}"
            dest_storage.write(dest_uri, src_data)

            artifact_entries.append(
                {
                    "format": art.format,
                    "target_hardware": art.target_hardware,
                    "artifact_uri": dest_uri,
                    "sha256": art.sha256,
                    "size_bytes": art.size_bytes,
                }
            )

        manifest: dict[str, object] = {
            "card_id": input_card.id,
            "version": input_card.version,
            "edge_artifacts": artifact_entries,
        }
        manifest_uri = f"s3://{self._bucket}/{card_prefix}manifest.json"
        dest_storage.write(manifest_uri, json.dumps(manifest, indent=2).encode())

        status = DeploymentStatus(
            backend="s3",
            state="deployed",
            deployed_at=datetime.now(UTC),
            manifest_uri=manifest_uri,
        )
        return input_card.model_copy(
            update={"deployment_history": [*input_card.deployment_history, status]}
        )
