"""HttpBackendPlugin — uploads OTA artifacts + manifest to an HTTP endpoint via PUT.

Resolves source artifacts via the STORAGE registry so ``file://``, ``local://``,
``s3://``, and ``http://`` source URIs all work transparently.
Supports no-auth, Bearer token, and HTTP Basic authentication modes.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

# Trigger registration of the storage backends so STORAGE.build() resolves them.
import pet_infra.storage.local  # noqa: F401
import pet_infra.storage.s3  # noqa: F401
import requests
from pet_infra.registry import OTA, STORAGE
from pet_schema.model_card import DeploymentStatus, ModelCard
from pet_schema.recipe import ExperimentRecipe


@OTA.register_module(name="http_backend", force=True)
class HttpBackendPlugin:
    """Uploads edge_artifacts and manifest.json to an HTTP endpoint via PUT."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        basic_auth: tuple[str, str] | None = None,
        timeout_s: float = 30.0,
        **_: object,
    ) -> None:
        """Initialize with HTTP destination parameters.

        Args:
            base_url: Root URL of the HTTP OTA server.  Trailing slashes are
                stripped so paths are always built as ``{base}/{card_id}/…``.
            auth_token: When set, every request includes an
                ``Authorization: Bearer <token>`` header.
            basic_auth: Optional ``(username, password)`` tuple forwarded as
                HTTP Basic auth.  Mutually exclusive with ``auth_token`` in
                typical deployments, though both may be supplied.
            timeout_s: Per-request timeout in seconds (default 30).
            **_: Extra kwargs accepted and silently ignored for
                forward-compatibility with registry configs.
        """
        self._base = base_url.rstrip("/")
        self._headers: dict[str, str] = (
            {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        )
        self._auth = basic_auth
        self._timeout = timeout_s

    def run(self, input_card: ModelCard, recipe: ExperimentRecipe) -> ModelCard:
        """Upload edge artifacts and manifest.json to the HTTP endpoint.

        Gate guard: raises ValueError when gate_status != 'passed'.
        For each EdgeArtifact, reads source bytes via the STORAGE registry
        (supports file://, local://, s3://, http:// sources) and PUTs to
        ``{base_url}/{card_id}/{filename}``.  Writes a compact manifest JSON
        and appends a DeploymentStatus to deployment_history.

        Args:
            input_card: The ModelCard to deploy.
            recipe: The ExperimentRecipe that produced the card (unused,
                accepted for interface compatibility).

        Returns:
            A copy of ``input_card`` with a new DeploymentStatus appended.

        Raises:
            ValueError: When ``input_card.gate_status`` is not ``'passed'``.
            requests.HTTPError: When the server returns a non-2xx response.
        """
        if input_card.gate_status != "passed":
            raise ValueError(
                f"HttpBackendPlugin refused: gate_status={input_card.gate_status!r} "
                "(must be 'passed' to deploy to OTA)"
            )

        artifact_entries: list[dict[str, object]] = []
        for art in input_card.edge_artifacts:
            # Resolve source bytes via the STORAGE registry so any scheme works.
            scheme = urlparse(art.artifact_uri).scheme or "file"
            data = STORAGE.build({"type": scheme}).read(art.artifact_uri)

            filename = PurePosixPath(urlparse(art.artifact_uri).path).name
            url = f"{self._base}/{input_card.id}/{filename}"
            requests.put(
                url,
                data=data,
                timeout=self._timeout,
                headers=self._headers,
                auth=self._auth,
            ).raise_for_status()

            artifact_entries.append(
                {
                    "format": art.format,
                    "target_hardware": art.target_hardware,
                    "artifact_uri": url,
                    "sha256": art.sha256,
                    "size_bytes": art.size_bytes,
                }
            )

        manifest: dict[str, object] = {
            "card_id": input_card.id,
            "version": input_card.version,
            "edge_artifacts": artifact_entries,
        }
        manifest_url = f"{self._base}/{input_card.id}/manifest.json"
        manifest_headers = {**self._headers, "Content-Type": "application/json"}
        requests.put(
            manifest_url,
            data=json.dumps(manifest, indent=2).encode(),
            timeout=self._timeout,
            headers=manifest_headers,
            auth=self._auth,
        ).raise_for_status()

        status = DeploymentStatus(
            backend="http",
            state="deployed",
            deployed_at=datetime.now(UTC),
            manifest_uri=manifest_url,
        )
        return input_card.model_copy(
            update={"deployment_history": [*input_card.deployment_history, status]}
        )
