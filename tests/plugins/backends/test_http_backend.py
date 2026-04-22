"""Tests for HttpBackendPlugin (P2-A-3)."""
from __future__ import annotations

import base64
import http.server
import socketserver
import threading
from collections.abc import Iterator
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


class _AuthHandler(http.server.SimpleHTTPRequestHandler):
    expected_auth: str | None = None
    received: list[tuple[str, bytes]] = []

    def do_PUT(self) -> None:  # noqa: N802
        if self.expected_auth and self.headers.get("Authorization") != self.expected_auth:
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers["Content-Length"])
        _AuthHandler.received.append((self.path, self.rfile.read(length)))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args: object, **kwargs: object) -> None:  # noqa: ANN002
        pass  # silence test logs


@pytest.fixture()
def http_server() -> Iterator[dict[str, object]]:
    """Spin up an in-process HTTP server on an ephemeral port."""
    # Reset class-level state before each test
    _AuthHandler.received = []
    _AuthHandler.expected_auth = None

    httpd = socketserver.TCPServer(("127.0.0.1", 0), _AuthHandler)
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    yield {"base_url": f"http://127.0.0.1:{port}", "handler": _AuthHandler}

    httpd.shutdown()
    httpd.server_close()


def _make_card(tmp_path: Path, filename: str = "edge.rknn") -> ModelCard:
    """Build a passing ModelCard with a real local artifact file."""
    artifact_file = tmp_path / filename
    artifact_file.write_bytes(b"BIN")
    edge = EdgeArtifact(
        format="rknn",
        target_hardware=["rk3576"],
        artifact_uri=f"file://{artifact_file}",
        sha256="a" * 64,
        size_bytes=3,
        input_shape={"pixel_values": [1, 3, 448, 448]},
    )
    return ModelCard(**_base_card_kwargs(), edge_artifacts=[edge])


def test_http_backend_no_auth(http_server: dict[str, object], tmp_path: Path) -> None:
    """Plugin PUTs artifact and manifest without auth; DeploymentStatus appended."""
    from pet_ota.plugins.backends.http import HttpBackendPlugin

    card = _make_card(tmp_path)
    plugin = HttpBackendPlugin(base_url=str(http_server["base_url"]))
    out = plugin.run(card, MagicMock())

    handler = http_server["handler"]
    assert any(path == "/card-1/edge.rknn" for path, _ in handler.received)  # type: ignore[union-attr]
    assert len(out.deployment_history) == 1
    status = out.deployment_history[-1]
    assert status.backend == "http"
    assert status.state == "deployed"
    assert status.manifest_uri == f"{http_server['base_url']}/card-1/manifest.json"


def test_http_backend_bearer(http_server: dict[str, object], tmp_path: Path) -> None:
    """Bearer token auth succeeds; server receives and accepts the Authorization header."""
    from pet_ota.plugins.backends.http import HttpBackendPlugin

    _AuthHandler.expected_auth = "Bearer T0K3N"
    card = _make_card(tmp_path)
    plugin = HttpBackendPlugin(base_url=str(http_server["base_url"]), auth_token="T0K3N")
    plugin.run(card, MagicMock())

    assert len(http_server["handler"].received) > 0  # type: ignore[union-attr]


def test_http_backend_basic(http_server: dict[str, object], tmp_path: Path) -> None:
    """HTTP Basic auth succeeds; server receives and accepts the Authorization header."""
    from pet_ota.plugins.backends.http import HttpBackendPlugin

    enc = base64.b64encode(b"u:p").decode()
    _AuthHandler.expected_auth = f"Basic {enc}"
    card = _make_card(tmp_path)
    plugin = HttpBackendPlugin(base_url=str(http_server["base_url"]), basic_auth=("u", "p"))
    plugin.run(card, MagicMock())

    assert len(http_server["handler"].received) > 0  # type: ignore[union-attr]


def test_http_backend_rejects_unpassed_gate(
    http_server: dict[str, object], tmp_path: Path
) -> None:
    """Plugin raises ValueError containing 'gate_status' when gate is not 'passed'."""
    from pet_ota.plugins.backends.http import HttpBackendPlugin

    card = _make_card(tmp_path)
    card = card.model_copy(update={"gate_status": "pending"})
    plugin = HttpBackendPlugin(base_url=str(http_server["base_url"]))
    with pytest.raises(ValueError, match="gate_status"):
        plugin.run(card, MagicMock())
