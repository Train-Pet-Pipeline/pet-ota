# pet-ota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an OTA update system with delta packaging, canary rollout state machine, gate checks, and monitoring — the final stage of the Train-Pet-Pipeline.

**Architecture:** OTABackend Protocol abstraction with LocalBackend (filesystem) for v1. Canary rollout state machine orchestrates: gate check → 5% canary deploy → observation period → 100% full deploy, with rollback at any stage. All state persisted as JSON files.

**Tech Stack:** Python 3.11, bsdiff4 (delta packaging), Pydantic v2 (config/models), tenacity (retry), structlog (JSON logging), pet-quantize (verify_package)

**Spec:** `docs/superpowers/specs/2026-04-15-pet-ota-design.md`

---

## File Map

```
pet-ota/
├── src/pet_ota/
│   ├── __init__.py
│   ├── config.py                     # Pydantic params + setup_logging()
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── base.py                   # OTABackend Protocol + DeploymentStatus
│   │   └── local.py                  # LocalBackend (filesystem)
│   ├── packaging/
│   │   ├── __init__.py
│   │   ├── make_delta.py             # bsdiff4 delta creation
│   │   ├── upload_artifact.py        # Verify + upload to backend
│   │   └── create_deployment.py      # Create deployment for device group
│   ├── release/
│   │   ├── __init__.py
│   │   ├── check_gate.py             # 5-check release gate
│   │   ├── canary_rollout.py         # Full rollout state machine
│   │   └── rollback.py               # Abort + restore previous version
│   └── monitoring/
│       ├── __init__.py
│       ├── check_update_rate.py      # Success/failure rate calculation
│       └── alert.py                  # CRITICAL log alerting
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Shared fixtures (tmp dirs, params, backend)
│   ├── test_config.py
│   ├── test_local_backend.py
│   ├── test_make_delta.py
│   ├── test_upload_artifact.py
│   ├── test_create_deployment.py
│   ├── test_check_gate.py
│   ├── test_check_update_rate.py
│   ├── test_alert.py
│   ├── test_rollback.py
│   └── test_canary_rollout.py
├── pyproject.toml
├── params.yaml
└── Makefile
```

**Parallelism:** After Tasks 1-3 (scaffolding → types → LocalBackend), Tasks 4-10 are independent and can run in parallel. Task 11 (canary_rollout) depends on all of them. Tasks 12-14 are sequential finalization.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `params.yaml`
- Create: `Makefile`
- Create: `src/pet_ota/__init__.py`
- Create: `src/pet_ota/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "pet-ota"
version = "1.0.0"
requires-python = ">=3.11,<3.12"
dependencies = [
    "bsdiff4>=1.2.0,<2.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "tenacity",
    "structlog",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
    "ruff",
    "mypy",
]
signing = [
    "pet-quantize>=1.0.0",
]

[tool.setuptools.packages.find]
where = ["src"]
include = ["pet_ota", "pet_ota.*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true

[[tool.mypy.overrides]]
module = ["bsdiff4", "pet_quantize.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create params.yaml**

```yaml
release:
  canary_percentage: 5
  canary_observe_hours: 48
  rollback_timeout_minutes: 5
  failure_rate_threshold: 0.10

gate_overrides:
  eval_passed: true
  dpo_pairs: 600
  days_since_last_release: 10
  open_p0_bugs: 0
  canary_group_ready: true

packaging:
  delta_enabled: true
  artifact_store_dir: "artifacts/store"
  public_key_path: ""

monitoring:
  poll_interval_seconds: 30
  device_pending_timeout_minutes: 30

device_groups:
  canary: "device_groups/canary.json"
  production: "device_groups/production.json"
```

- [ ] **Step 3: Create Makefile**

```makefile
.PHONY: setup test lint clean release

setup:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/ && mypy src/

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist/ *.egg-info artifacts/ deployments/

release:
	python -m pet_ota.release.canary_rollout
```

- [ ] **Step 4: Create src/pet_ota/__init__.py**

```python
"""pet-ota: OTA delta updates, canary rollout, and rollback."""
```

- [ ] **Step 5: Create src/pet_ota/config.py**

Pydantic config hierarchy + `load_params()` + `setup_logging()`. Follow pet-quantize pattern exactly.

```python
"""Pydantic params loader and structured JSON logging setup."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field


class ReleaseConfig(BaseModel):
    """Release / canary rollout configuration."""

    model_config = ConfigDict(populate_by_name=True)

    canary_percentage: int = 5
    canary_observe_hours: int = 48
    rollback_timeout_minutes: int = 5
    failure_rate_threshold: float = 0.10


class GateOverrides(BaseModel):
    """Gate check override values injected via params.yaml."""

    eval_passed: bool = True
    dpo_pairs: int = 600
    days_since_last_release: int = 10
    open_p0_bugs: int = 0
    canary_group_ready: bool = True


class PackagingConfig(BaseModel):
    """Packaging configuration."""

    delta_enabled: bool = True
    artifact_store_dir: str = "artifacts/store"
    public_key_path: str = ""


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""

    poll_interval_seconds: int = 30
    device_pending_timeout_minutes: int = 30


class DeviceGroupsConfig(BaseModel):
    """Device group file paths."""

    canary: str = "device_groups/canary.json"
    production: str = "device_groups/production.json"


class OTAParams(BaseModel):
    """Root configuration model for pet-ota."""

    model_config = ConfigDict(populate_by_name=True)

    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    gate_overrides: GateOverrides = Field(default_factory=GateOverrides)
    packaging: PackagingConfig = Field(default_factory=PackagingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    device_groups: DeviceGroupsConfig = Field(default_factory=DeviceGroupsConfig)


def load_params(path: str | Path = "params.yaml") -> OTAParams:
    """Load and validate params.yaml into OTAParams.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated OTAParams instance.

    Raises:
        FileNotFoundError: If the params file does not exist.
        pydantic.ValidationError: If the YAML content is invalid.
    """
    with open(path) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return OTAParams(**raw)


def setup_logging() -> None:
    """Configure structured JSON logging (idempotent).

    Sets up structlog with JSON rendering. Safe to call multiple times.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 6: Write tests/conftest.py with shared fixtures**

```python
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
            "canary_observe_hours": 0,  # instant for tests
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
```

- [ ] **Step 7: Write tests/test_config.py**

```python
"""Tests for pet_ota.config."""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from pet_ota.config import OTAParams, load_params


def test_load_params_from_yaml(
    tmp_dir: pathlib.Path, sample_params: dict[str, Any]
) -> None:
    """load_params returns a valid OTAParams from YAML."""
    p = tmp_dir / "params.yaml"
    p.write_text(yaml.dump(sample_params))
    params = load_params(p)
    assert isinstance(params, OTAParams)
    assert params.release.canary_percentage == 5
    assert params.gate_overrides.dpo_pairs == 600


def test_load_params_defaults(tmp_dir: pathlib.Path) -> None:
    """load_params fills defaults when YAML is empty."""
    p = tmp_dir / "params.yaml"
    p.write_text("{}")
    params = load_params(p)
    assert params.release.failure_rate_threshold == 0.10
    assert params.monitoring.poll_interval_seconds == 30
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/bamboo/Githubs/Train-Pet-Pipeline/pet-ota && pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: 2 tests PASS

- [ ] **Step 9: Run lint**

Run: `ruff check src/ tests/ && mypy src/`
Expected: No errors

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(pet-ota): project scaffolding — config, params, Makefile, pyproject"
```

---

### Task 2: OTABackend Protocol + DeploymentStatus

**Files:**
- Create: `src/pet_ota/backend/__init__.py`
- Create: `src/pet_ota/backend/base.py`

- [ ] **Step 1: Create src/pet_ota/backend/__init__.py**

```python
"""OTA backend abstraction layer."""
from pet_ota.backend.base import DeploymentStatus, OTABackend

__all__ = ["DeploymentStatus", "OTABackend"]
```

- [ ] **Step 2: Create src/pet_ota/backend/base.py**

```python
"""OTABackend Protocol and DeploymentStatus model."""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class DeploymentStatus(BaseModel, frozen=True):
    """Immutable snapshot of a deployment's current state."""

    deployment_id: str
    version: str
    device_group: str
    status: Literal[
        "gate_check",
        "canary_deploying",
        "canary_observing",
        "full_deploying",
        "done",
        "failed",
        "rolling_back",
        "rolled_back",
        "rollback_failed",
    ]
    total_devices: int
    success_count: int
    failure_count: int
    pending_count: int
    created_at: str
    updated_at: str


class OTABackend(Protocol):
    """OTA backend unified interface.

    v1: LocalBackend (filesystem). Future: MenderBackend.
    """

    def upload_artifact(self, artifact_path: str, version: str) -> str:
        """Upload an artifact, return artifact_id."""
        ...

    def list_device_groups(self) -> list[str]:
        """List all device group names."""
        ...

    def create_deployment(
        self, artifact_id: str, device_group: str, name: str
    ) -> str:
        """Create a deployment, return deployment_id."""
        ...

    def get_deployment_status(self, deployment_id: str) -> DeploymentStatus:
        """Query deployment status."""
        ...

    def abort_deployment(self, deployment_id: str) -> None:
        """Abort a deployment (used for rollback)."""
        ...

    def update_deployment_status(self, deployment_id: str, status: str) -> None:
        """Update the status field of a deployment."""
        ...

    def update_deployment_metadata(
        self, deployment_id: str, updates: dict[str, str]
    ) -> None:
        """Merge key-value updates into a deployment record."""
        ...

    def get_device_update_history(self, device_group: str) -> list[dict]:
        """Query update history for a device group."""
        ...
```

- [ ] **Step 3: Run lint**

Run: `ruff check src/pet_ota/backend/ && mypy src/pet_ota/backend/`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/pet_ota/backend/
git commit -m "feat(pet-ota): OTABackend Protocol + DeploymentStatus model"
```

---

### Task 3: LocalBackend Implementation

**Files:**
- Create: `src/pet_ota/backend/local.py`
- Create: `tests/test_local_backend.py`

- [ ] **Step 1: Write tests/test_local_backend.py**

```python
"""Tests for pet_ota.backend.local.LocalBackend."""
from __future__ import annotations

import json
import pathlib
import tarfile

import pytest

from pet_ota.backend.local import LocalBackend


def _make_tarball(tmp_dir: pathlib.Path, name: str) -> pathlib.Path:
    """Create a minimal tarball for testing."""
    content_file = tmp_dir / "model.bin"
    content_file.write_bytes(b"fake model weights")
    tar_path = tmp_dir / name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(content_file, arcname="model.bin")
    return tar_path


def test_upload_artifact(backend_root: pathlib.Path) -> None:
    """upload_artifact copies tarball to store and returns artifact_id."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    artifact_id = backend.upload_artifact(str(tarball), "1.0.0")
    assert artifact_id == "1.0.0"
    stored = backend_root / "artifacts" / "store" / "v1.0.0" / "model-v1.0.0.tar.gz"
    assert stored.exists()


def test_list_device_groups(backend_root: pathlib.Path) -> None:
    """list_device_groups returns names of JSON files in device_groups/."""
    backend = LocalBackend(root_dir=str(backend_root))
    groups = backend.list_device_groups()
    assert sorted(groups) == ["canary", "production"]


def test_create_deployment(backend_root: pathlib.Path) -> None:
    """create_deployment writes a deployment JSON and returns its ID."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    dep_id = backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    assert dep_id == "v1.0.0-canary"
    dep_file = backend_root / "deployments" / "v1.0.0-canary.json"
    assert dep_file.exists()
    data = json.loads(dep_file.read_text())
    assert data["status"] == "canary_deploying"
    assert data["device_group"] == "canary"


def test_get_deployment_status(backend_root: pathlib.Path) -> None:
    """get_deployment_status reads back a valid DeploymentStatus."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.deployment_id == "v1.0.0-canary"
    assert status.total_devices == 2  # canary has 2 devices
    assert status.pending_count == 2
    assert status.success_count == 0


def test_abort_deployment(backend_root: pathlib.Path) -> None:
    """abort_deployment sets status to 'rolling_back'."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    backend.abort_deployment("v1.0.0-canary")
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.status == "rolling_back"


def test_get_device_update_history_empty(backend_root: pathlib.Path) -> None:
    """get_device_update_history returns empty list when no deployments exist."""
    backend = LocalBackend(root_dir=str(backend_root))
    history = backend.get_device_update_history("canary")
    assert history == []


def test_get_device_update_history_with_data(backend_root: pathlib.Path) -> None:
    """get_device_update_history returns deployment records for the group."""
    backend = LocalBackend(root_dir=str(backend_root))
    tarball = _make_tarball(backend_root, "model-v1.0.0.tar.gz")
    backend.upload_artifact(str(tarball), "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    history = backend.get_device_update_history("canary")
    assert len(history) == 1
    assert history[0]["version"] == "1.0.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_local_backend.py -v`
Expected: FAIL (LocalBackend not implemented)

- [ ] **Step 3: Implement src/pet_ota/backend/local.py**

```python
"""LocalBackend — filesystem-based OTA backend implementation."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import structlog

from pet_ota.backend.base import DeploymentStatus

logger = structlog.get_logger()


class LocalBackend:
    """OTA backend backed by local filesystem.

    Directory layout under root_dir:
        artifacts/store/<version>/   — uploaded tarballs
        deployments/                 — deployment JSON state files
        device_groups/               — device group membership files
    """

    def __init__(self, root_dir: str) -> None:
        """Initialize LocalBackend.

        Args:
            root_dir: Root directory for all OTA data.
        """
        self._root = Path(root_dir)
        self._store = self._root / "artifacts" / "store"
        self._deployments = self._root / "deployments"
        self._device_groups = self._root / "device_groups"

    def upload_artifact(self, artifact_path: str, version: str) -> str:
        """Copy artifact to versioned store directory.

        Args:
            artifact_path: Path to the tarball file.
            version: Semantic version string.

        Returns:
            artifact_id (same as version for LocalBackend).
        """
        dest_dir = self._store / f"v{version}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = Path(artifact_path)
        shutil.copy2(src, dest_dir / src.name)
        logger.info("artifact_uploaded", version=version, path=str(dest_dir / src.name))
        return version

    def list_device_groups(self) -> list[str]:
        """List device group names from JSON files in device_groups/.

        Returns:
            Sorted list of device group names (filename stems).
        """
        return sorted(p.stem for p in self._device_groups.glob("*.json"))

    def _load_devices(self, device_group: str) -> list[str]:
        """Load device IDs from a device group JSON file.

        Args:
            device_group: Name of the device group.

        Returns:
            List of device ID strings.

        Raises:
            FileNotFoundError: If the device group file does not exist.
        """
        path = self._device_groups / f"{device_group}.json"
        return json.loads(path.read_text())  # type: ignore[no-any-return]

    def create_deployment(
        self, artifact_id: str, device_group: str, name: str
    ) -> str:
        """Create a new deployment JSON file.

        Args:
            artifact_id: The version/artifact identifier.
            device_group: Target device group name.
            name: Deployment name (used as deployment_id).

        Returns:
            deployment_id (same as name).
        """
        devices = self._load_devices(device_group)
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "deployment_id": name,
            "version": artifact_id,
            "device_group": device_group,
            "status": "canary_deploying",
            "created_at": now,
            "updated_at": now,
            "devices": {d: "pending" for d in devices},
        }
        dep_file = self._deployments / f"{name}.json"
        dep_file.write_text(json.dumps(data, indent=2))
        logger.info("deployment_created", deployment_id=name, device_group=device_group)
        return name

    def get_deployment_status(self, deployment_id: str) -> DeploymentStatus:
        """Read deployment JSON and return a DeploymentStatus snapshot.

        Args:
            deployment_id: The deployment identifier.

        Returns:
            Frozen DeploymentStatus instance.

        Raises:
            FileNotFoundError: If the deployment file does not exist.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        devices: dict[str, str] = data.get("devices", {})
        success = sum(1 for v in devices.values() if v == "success")
        failure = sum(1 for v in devices.values() if v in ("failed", "timeout"))
        pending = sum(1 for v in devices.values() if v == "pending")
        return DeploymentStatus(
            deployment_id=data["deployment_id"],
            version=data["version"],
            device_group=data["device_group"],
            status=data["status"],
            total_devices=len(devices),
            success_count=success,
            failure_count=failure,
            pending_count=pending,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def abort_deployment(self, deployment_id: str) -> None:
        """Set deployment status to 'rolling_back'.

        Args:
            deployment_id: The deployment to abort.
        """
        self.update_deployment_status(deployment_id, "rolling_back")
        logger.info("deployment_aborted", deployment_id=deployment_id)

    def update_deployment_status(self, deployment_id: str, status: str) -> None:
        """Update the status field in a deployment JSON file.

        Args:
            deployment_id: The deployment identifier.
            status: New status string.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        data["status"] = status
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        dep_file.write_text(json.dumps(data, indent=2))

    def update_deployment_metadata(
        self, deployment_id: str, updates: dict[str, str]
    ) -> None:
        """Merge key-value updates into a deployment JSON record.

        Args:
            deployment_id: The deployment identifier.
            updates: Key-value pairs to merge into the deployment record.
        """
        dep_file = self._deployments / f"{deployment_id}.json"
        data = json.loads(dep_file.read_text())
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        dep_file.write_text(json.dumps(data, indent=2))

    def get_device_update_history(self, device_group: str) -> list[dict]:
        """Return all deployments targeting the given device group.

        Args:
            device_group: Name of the device group.

        Returns:
            List of deployment dicts, sorted by created_at ascending.
        """
        results: list[dict] = []
        for dep_file in self._deployments.glob("*.json"):
            data = json.loads(dep_file.read_text())
            if data.get("device_group") == device_group:
                results.append(data)
        return sorted(results, key=lambda d: d.get("created_at", ""))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_local_backend.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Run lint**

Run: `ruff check src/pet_ota/backend/ tests/test_local_backend.py && mypy src/pet_ota/backend/`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/pet_ota/backend/ tests/test_local_backend.py
git commit -m "feat(pet-ota): LocalBackend filesystem implementation with 7 tests"
```

---

### Task 4: packaging/make_delta.py — bsdiff4 Delta Creation

**Files:**
- Create: `src/pet_ota/packaging/__init__.py`
- Create: `src/pet_ota/packaging/make_delta.py`
- Create: `tests/test_make_delta.py`

**Depends on:** Task 1 (config)

- [ ] **Step 1: Create src/pet_ota/packaging/__init__.py**

```python
"""OTA packaging — delta creation, upload, deployment."""
```

- [ ] **Step 2: Write tests/test_make_delta.py**

```python
"""Tests for pet_ota.packaging.make_delta."""
from __future__ import annotations

import pathlib
import tarfile

import bsdiff4

from pet_ota.packaging.make_delta import make_delta


def _make_tarball(tmp_dir: pathlib.Path, name: str, content: bytes) -> pathlib.Path:
    """Create a tarball containing a single model.bin with given content."""
    model_file = tmp_dir / "model.bin"
    model_file.write_bytes(content)
    tar_path = tmp_dir / name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")
    return tar_path


def test_make_delta_creates_patch(tmp_dir: pathlib.Path) -> None:
    """make_delta produces a .patch file."""
    old_tar = _make_tarball(tmp_dir, "old.tar.gz", b"old model weights v1")
    new_tar = _make_tarball(tmp_dir, "new.tar.gz", b"new model weights v2 with extras")
    output = tmp_dir / "delta.patch"
    result = make_delta(str(old_tar), str(new_tar), str(output))
    assert pathlib.Path(result).exists()
    assert pathlib.Path(result).stat().st_size > 0


def test_make_delta_roundtrip(tmp_dir: pathlib.Path) -> None:
    """Applying the delta to the old tarball reproduces the new tarball exactly."""
    old_content = b"old model weights version 1.0"
    new_content = b"new model weights version 2.0 with LoRA adapters"
    old_tar = _make_tarball(tmp_dir, "old.tar.gz", old_content)
    new_tar = _make_tarball(tmp_dir, "new.tar.gz", new_content)
    patch_path = tmp_dir / "delta.patch"
    make_delta(str(old_tar), str(new_tar), str(patch_path))

    old_bytes = old_tar.read_bytes()
    patch_bytes = patch_path.read_bytes()
    reconstructed = bsdiff4.patch(old_bytes, patch_bytes)
    assert reconstructed == new_tar.read_bytes()


def test_make_delta_identical_files(tmp_dir: pathlib.Path) -> None:
    """Delta of identical tarballs produces a small patch."""
    content = b"same model weights"
    old_tar = _make_tarball(tmp_dir, "old.tar.gz", content)
    new_tar = _make_tarball(tmp_dir, "new.tar.gz", content)
    patch_path = tmp_dir / "delta.patch"
    make_delta(str(old_tar), str(new_tar), str(patch_path))
    # Identical content should produce a very small patch
    assert patch_path.stat().st_size < old_tar.stat().st_size
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_make_delta.py -v`
Expected: FAIL (make_delta not defined)

- [ ] **Step 4: Implement src/pet_ota/packaging/make_delta.py**

```python
"""bsdiff4-based delta patch creation for OTA updates."""
from __future__ import annotations

import structlog
from tenacity import retry, stop_after_attempt, wait_fixed

logger = structlog.get_logger()


@retry(stop=stop_after_attempt(3), wait=wait_fixed(1), reraise=True)
def make_delta(old_tarball: str, new_tarball: str, output_path: str) -> str:
    """Create a binary delta patch between two tarballs using bsdiff4.

    Args:
        old_tarball: Path to the old version tarball.
        new_tarball: Path to the new version tarball.
        output_path: Path where the delta .patch file will be written.

    Returns:
        The output_path where the patch was written.

    Raises:
        FileNotFoundError: If either tarball does not exist.
        Exception: If bsdiff4 fails after 3 retries.
    """
    import bsdiff4
    from pathlib import Path

    old_bytes = Path(old_tarball).read_bytes()
    new_bytes = Path(new_tarball).read_bytes()

    logger.info(
        "make_delta_start",
        old_size=len(old_bytes),
        new_size=len(new_bytes),
        output_path=output_path,
    )

    patch_bytes = bsdiff4.diff(old_bytes, new_bytes)

    with open(output_path, "wb") as fh:
        fh.write(patch_bytes)

    logger.info(
        "make_delta_done",
        patch_size=len(patch_bytes),
        output_path=output_path,
    )
    return output_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_make_delta.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/pet_ota/packaging/ tests/test_make_delta.py
git commit -m "feat(pet-ota): bsdiff4 delta packaging with roundtrip test"
```

---

### Task 5: packaging/upload_artifact.py

**Files:**
- Create: `src/pet_ota/packaging/upload_artifact.py`
- Create: `tests/test_upload_artifact.py`

**Depends on:** Task 2 (OTABackend Protocol), Task 3 (LocalBackend)

- [ ] **Step 1: Write tests/test_upload_artifact.py**

```python
"""Tests for pet_ota.packaging.upload_artifact."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tarfile

import pytest

from pet_ota.backend.local import LocalBackend
from pet_ota.packaging.upload_artifact import upload_artifact


def _make_release_dir(tmp_dir: pathlib.Path, version: str) -> pathlib.Path:
    """Create a release directory with a tarball and manifest.json."""
    release_dir = tmp_dir / "release"
    release_dir.mkdir()

    # Create a tarball
    model_file = tmp_dir / "model.bin"
    model_file.write_bytes(b"fake quantized model weights")
    tar_name = f"pet-model-v{version}.tar.gz"
    tar_path = release_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")

    # Create manifest.json with correct sha256
    sha256 = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    manifest = {
        "version": version,
        "files": {tar_name: {"sha256": sha256, "size": tar_path.stat().st_size}},
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest))
    return release_dir


def test_upload_artifact_success(backend_root: pathlib.Path) -> None:
    """upload_artifact stores artifact and returns artifact_id."""
    backend = LocalBackend(root_dir=str(backend_root))
    release_dir = _make_release_dir(backend_root / "tmp_release", "1.0.0")
    artifact_id = upload_artifact(
        release_dir=str(release_dir),
        version="1.0.0",
        backend=backend,
        public_key_path="",
    )
    assert artifact_id == "1.0.0"
    stored = backend_root / "artifacts" / "store" / "v1.0.0"
    assert stored.exists()


def test_upload_artifact_bad_manifest(
    backend_root: pathlib.Path, tmp_dir: pathlib.Path
) -> None:
    """upload_artifact raises when manifest sha256 doesn't match."""
    release_dir = _make_release_dir(tmp_dir / "bad_release", "1.0.0")
    # Corrupt the manifest
    manifest_path = release_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for f in manifest["files"]:
        manifest["files"][f]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))

    backend = LocalBackend(root_dir=str(backend_root))
    with pytest.raises(Exception):  # noqa: B017
        upload_artifact(
            release_dir=str(release_dir),
            version="1.0.0",
            backend=backend,
            public_key_path="",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_upload_artifact.py -v`
Expected: FAIL

- [ ] **Step 3: Implement src/pet_ota/packaging/upload_artifact.py**

```python
"""Upload a verified artifact to the OTA backend."""
from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

import structlog

from pet_ota.backend.base import OTABackend

logger = structlog.get_logger()


def _verify_manifest(release_dir: str) -> None:
    """Verify all files in manifest.json match their sha256 checksums.

    Args:
        release_dir: Path to the release directory containing manifest.json.

    Raises:
        FileNotFoundError: If manifest.json or a listed file is missing.
        ValueError: If a sha256 checksum does not match.
    """
    rd = Path(release_dir)
    manifest_path = rd / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    for filename, meta in manifest.get("files", {}).items():
        file_path = rd / filename
        if not file_path.exists():
            msg = f"File listed in manifest not found: {file_path}"
            raise FileNotFoundError(msg)
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        expected_sha = meta["sha256"]
        if actual_sha != expected_sha:
            msg = f"SHA256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}"
            raise ValueError(msg)

    logger.info("manifest_verified", release_dir=release_dir)


def upload_artifact(
    release_dir: str,
    version: str,
    backend: OTABackend,
    public_key_path: str = "",
) -> str:
    """Verify package integrity and upload to the OTA backend.

    Verifies manifest.json checksums. If pet_quantize is available and
    public_key_path is set, also verifies the cryptographic signature.
    Then uploads the first tarball found in the release directory.

    Args:
        release_dir: Path to the release directory (tarball + manifest.json).
        version: Semantic version string.
        backend: OTABackend instance to upload to.
        public_key_path: Path to RSA public key PEM (optional).

    Returns:
        artifact_id from the backend.

    Raises:
        ValueError: If integrity verification fails.
        FileNotFoundError: If no tarball is found.
    """
    # Always verify manifest checksums
    _verify_manifest(release_dir)

    # Optionally verify cryptographic signature via pet-quantize
    if public_key_path:
        try:
            from pet_quantize.packaging.verify_package import verify_package

            result = verify_package(release_dir, public_key_path)
            if not result.integrity_ok:
                msg = f"Package integrity check failed: {result}"
                raise ValueError(msg)
            logger.info("signature_verified", release_dir=release_dir)
        except ImportError:
            logger.warning(
                "pet_quantize not available, skipping signature verification"
            )

    # Find tarball to upload
    tarballs = glob.glob(str(Path(release_dir) / "*.tar.gz"))
    if not tarballs:
        msg = f"No tarball found in {release_dir}"
        raise FileNotFoundError(msg)

    artifact_id = backend.upload_artifact(tarballs[0], version)
    logger.info("artifact_uploaded", artifact_id=artifact_id, version=version)
    return artifact_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_upload_artifact.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pet_ota/packaging/upload_artifact.py tests/test_upload_artifact.py
git commit -m "feat(pet-ota): upload_artifact with manifest verification"
```

---

### Task 6: packaging/create_deployment.py

**Files:**
- Create: `src/pet_ota/packaging/create_deployment.py`
- Create: `tests/test_create_deployment.py`

**Depends on:** Task 2, Task 3

- [ ] **Step 1: Write tests/test_create_deployment.py**

```python
"""Tests for pet_ota.packaging.create_deployment."""
from __future__ import annotations

import pathlib
import tarfile

from pet_ota.backend.local import LocalBackend
from pet_ota.packaging.create_deployment import create_deployment


def _setup_artifact(backend_root: pathlib.Path) -> LocalBackend:
    """Upload a fake artifact and return the backend."""
    backend = LocalBackend(root_dir=str(backend_root))
    model_file = backend_root / "model.bin"
    model_file.write_bytes(b"fake")
    tar_path = backend_root / "model.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model_file, arcname="model.bin")
    backend.upload_artifact(str(tar_path), "1.0.0")
    return backend


def test_create_deployment_returns_id(backend_root: pathlib.Path) -> None:
    """create_deployment returns a deployment_id."""
    backend = _setup_artifact(backend_root)
    dep_id = create_deployment(
        artifact_id="1.0.0",
        device_group="canary",
        name="v1.0.0-canary",
        backend=backend,
    )
    assert dep_id == "v1.0.0-canary"


def test_create_deployment_persists_state(backend_root: pathlib.Path) -> None:
    """create_deployment creates a retrievable deployment."""
    backend = _setup_artifact(backend_root)
    create_deployment(
        artifact_id="1.0.0",
        device_group="canary",
        name="v1.0.0-canary",
        backend=backend,
    )
    status = backend.get_deployment_status("v1.0.0-canary")
    assert status.version == "1.0.0"
    assert status.device_group == "canary"
    assert status.total_devices == 2
```

- [ ] **Step 2: Implement src/pet_ota/packaging/create_deployment.py**

```python
"""Create a deployment targeting a device group."""
from __future__ import annotations

import structlog

from pet_ota.backend.base import OTABackend

logger = structlog.get_logger()


def create_deployment(
    artifact_id: str,
    device_group: str,
    name: str,
    backend: OTABackend,
) -> str:
    """Create a deployment for the given artifact and device group.

    Args:
        artifact_id: The artifact/version identifier.
        device_group: Target device group name.
        name: Human-readable deployment name (becomes deployment_id).
        backend: OTABackend instance.

    Returns:
        deployment_id from the backend.
    """
    dep_id = backend.create_deployment(artifact_id, device_group, name)
    logger.info(
        "deployment_requested",
        deployment_id=dep_id,
        artifact_id=artifact_id,
        device_group=device_group,
    )
    return dep_id
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_create_deployment.py -v`
Expected: 2 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/pet_ota/packaging/create_deployment.py tests/test_create_deployment.py
git commit -m "feat(pet-ota): create_deployment thin wrapper"
```

---

### Task 7: release/check_gate.py — 5-Check Release Gate

**Files:**
- Create: `src/pet_ota/release/__init__.py`
- Create: `src/pet_ota/release/check_gate.py`
- Create: `tests/test_check_gate.py`

**Depends on:** Task 1 (config)

- [ ] **Step 1: Create src/pet_ota/release/__init__.py**

```python
"""Release management — gate checks, canary rollout, rollback."""
```

- [ ] **Step 2: Write tests/test_check_gate.py**

```python
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
        "packaging": {"delta_enabled": True, "artifact_store_dir": "artifacts/store", "public_key_path": ""},
        "monitoring": {"poll_interval_seconds": 0, "device_pending_timeout_minutes": 30},
        "device_groups": {"canary": "device_groups/canary.json", "production": "device_groups/production.json"},
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_check_gate.py -v`
Expected: FAIL

- [ ] **Step 4: Implement src/pet_ota/release/check_gate.py**

```python
"""Release gate — 5 pre-release checks read from params.yaml gate_overrides."""
from __future__ import annotations

import structlog

from pet_ota.config import load_params

logger = structlog.get_logger()


def check_gate(params_path: str = "params.yaml") -> tuple[bool, list[str]]:
    """Run 5 release gate checks from gate_overrides in params.yaml.

    Checks:
      1. eval_passed must be True
      2. dpo_pairs must be >= 500
      3. days_since_last_release must be >= 7
      4. open_p0_bugs must be == 0
      5. canary_group_ready must be True

    Args:
        params_path: Path to params.yaml.

    Returns:
        Tuple of (passed, failures). passed is True if all checks pass.
        failures is a list of human-readable failure descriptions.
    """
    params = load_params(params_path)
    g = params.gate_overrides
    failures: list[str] = []

    if not g.eval_passed:
        failures.append("eval_passed: evaluation did not pass")

    if g.dpo_pairs < 500:
        failures.append(f"dpo_pairs: {g.dpo_pairs} < 500 required")

    if g.days_since_last_release < 7:
        failures.append(
            f"days_since_last_release: {g.days_since_last_release} < 7 required"
        )

    if g.open_p0_bugs != 0:
        failures.append(f"open_p0_bugs: {g.open_p0_bugs} != 0")

    if not g.canary_group_ready:
        failures.append("canary_group_ready: canary group is not ready")

    passed = len(failures) == 0
    logger.info("gate_check_complete", passed=passed, failures=failures)
    return passed, failures
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_check_gate.py -v`
Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/pet_ota/release/ tests/test_check_gate.py
git commit -m "feat(pet-ota): 5-check release gate from params.yaml overrides"
```

---

### Task 8: monitoring/check_update_rate.py

**Files:**
- Create: `src/pet_ota/monitoring/__init__.py`
- Create: `src/pet_ota/monitoring/check_update_rate.py`
- Create: `tests/test_check_update_rate.py`

**Depends on:** Task 2, Task 3

- [ ] **Step 1: Create src/pet_ota/monitoring/__init__.py**

```python
"""Deployment monitoring — update rate statistics and alerting."""
```

- [ ] **Step 2: Write tests/test_check_update_rate.py**

```python
"""Tests for pet_ota.monitoring.check_update_rate."""
from __future__ import annotations

import json
import pathlib

from pet_ota.backend.local import LocalBackend
from pet_ota.monitoring.check_update_rate import UpdateRateResult, check_update_rate


def _create_deployment_json(
    backend_root: pathlib.Path,
    deployment_id: str,
    devices: dict[str, str],
) -> None:
    """Write a deployment JSON file directly for testing."""
    data = {
        "deployment_id": deployment_id,
        "version": "1.0.0",
        "device_group": "canary",
        "status": "canary_deploying",
        "created_at": "2026-04-15T10:00:00Z",
        "updated_at": "2026-04-15T10:05:00Z",
        "devices": devices,
    }
    dep_file = backend_root / "deployments" / f"{deployment_id}.json"
    dep_file.write_text(json.dumps(data, indent=2))


def test_all_success(backend_root: pathlib.Path) -> None:
    """100% success rate when all devices succeed."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"dev1": "success", "dev2": "success"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert isinstance(result, UpdateRateResult)
    assert result.success_rate == 1.0
    assert result.failure_rate == 0.0
    assert result.pending_rate == 0.0


def test_mixed_statuses(backend_root: pathlib.Path) -> None:
    """Correct rates with mixed device statuses."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"d1": "success", "d2": "failed", "d3": "pending", "d4": "success"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert result.success_rate == 0.5
    assert result.failure_rate == 0.25
    assert result.pending_rate == 0.25


def test_all_pending(backend_root: pathlib.Path) -> None:
    """100% pending rate when no device has responded."""
    _create_deployment_json(
        backend_root, "v1-canary",
        {"d1": "pending", "d2": "pending"},
    )
    backend = LocalBackend(root_dir=str(backend_root))
    result = check_update_rate("v1-canary", backend)
    assert result.success_rate == 0.0
    assert result.pending_rate == 1.0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_check_update_rate.py -v`
Expected: FAIL

- [ ] **Step 4: Implement src/pet_ota/monitoring/check_update_rate.py**

```python
"""Check deployment update rates — success, failure, pending."""
from __future__ import annotations

import structlog
from pydantic import BaseModel

from pet_ota.backend.base import OTABackend

logger = structlog.get_logger()


class UpdateRateResult(BaseModel, frozen=True):
    """Deployment update rate statistics."""

    deployment_id: str
    total_devices: int
    success_count: int
    failure_count: int
    pending_count: int
    success_rate: float
    failure_rate: float
    pending_rate: float


def check_update_rate(
    deployment_id: str,
    backend: OTABackend,
) -> UpdateRateResult:
    """Query deployment status and compute update rates.

    Args:
        deployment_id: The deployment to check.
        backend: OTABackend instance.

    Returns:
        UpdateRateResult with computed rates.
    """
    status = backend.get_deployment_status(deployment_id)
    total = status.total_devices
    result = UpdateRateResult(
        deployment_id=deployment_id,
        total_devices=total,
        success_count=status.success_count,
        failure_count=status.failure_count,
        pending_count=status.pending_count,
        success_rate=status.success_count / total if total > 0 else 0.0,
        failure_rate=status.failure_count / total if total > 0 else 0.0,
        pending_rate=status.pending_count / total if total > 0 else 0.0,
    )
    logger.info(
        "update_rate_checked",
        deployment_id=deployment_id,
        success_rate=result.success_rate,
        failure_rate=result.failure_rate,
        pending_rate=result.pending_rate,
    )
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_check_update_rate.py -v`
Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/pet_ota/monitoring/ tests/test_check_update_rate.py
git commit -m "feat(pet-ota): check_update_rate success/failure/pending statistics"
```

---

### Task 9: monitoring/alert.py

**Files:**
- Create: `src/pet_ota/monitoring/alert.py`
- Create: `tests/test_alert.py`

**Depends on:** Task 8 (check_update_rate)

- [ ] **Step 1: Write tests/test_alert.py**

```python
"""Tests for pet_ota.monitoring.alert."""
from __future__ import annotations

from pet_ota.monitoring.alert import check_and_alert
from pet_ota.monitoring.check_update_rate import UpdateRateResult


def test_alert_fires_on_high_failure_rate(capsys: object) -> None:
    """CRITICAL log emitted when failure_rate exceeds threshold."""
    result = UpdateRateResult(
        deployment_id="v1-canary",
        total_devices=10,
        success_count=8,
        failure_count=2,
        pending_count=0,
        success_rate=0.8,
        failure_rate=0.2,
        pending_rate=0.0,
    )
    fired = check_and_alert(result, threshold=0.10)
    assert fired is True
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "critical" in captured.out.lower()


def test_no_alert_below_threshold() -> None:
    """No alert when failure_rate is below threshold."""
    result = UpdateRateResult(
        deployment_id="v1-canary",
        total_devices=10,
        success_count=10,
        failure_count=0,
        pending_count=0,
        success_rate=1.0,
        failure_rate=0.0,
        pending_rate=0.0,
    )
    fired = check_and_alert(result, threshold=0.10)
    assert fired is False


def test_alert_at_exact_threshold() -> None:
    """Alert fires when failure_rate equals threshold."""
    result = UpdateRateResult(
        deployment_id="v1-canary",
        total_devices=10,
        success_count=9,
        failure_count=1,
        pending_count=0,
        success_rate=0.9,
        failure_rate=0.1,
        pending_rate=0.0,
    )
    fired = check_and_alert(result, threshold=0.10)
    assert fired is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alert.py -v`
Expected: FAIL

- [ ] **Step 3: Implement src/pet_ota/monitoring/alert.py**

```python
"""Failure rate alerting via structured CRITICAL logging."""
from __future__ import annotations

import structlog

from pet_ota.monitoring.check_update_rate import UpdateRateResult

logger = structlog.get_logger()


def check_and_alert(result: UpdateRateResult, threshold: float) -> bool:
    """Check if failure rate meets or exceeds threshold and emit CRITICAL log.

    Args:
        result: UpdateRateResult from check_update_rate.
        threshold: Failure rate threshold (0.0 to 1.0).

    Returns:
        True if alert was fired, False otherwise.
    """
    if result.failure_rate >= threshold:
        logger.critical(
            "deployment_failure_rate_exceeded",
            deployment_id=result.deployment_id,
            failure_rate=result.failure_rate,
            threshold=threshold,
            failure_count=result.failure_count,
            total_devices=result.total_devices,
        )
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alert.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pet_ota/monitoring/alert.py tests/test_alert.py
git commit -m "feat(pet-ota): CRITICAL log alerting on failure rate threshold"
```

---

### Task 10: release/rollback.py

**Files:**
- Create: `src/pet_ota/release/rollback.py`
- Create: `tests/test_rollback.py`

**Depends on:** Task 2, Task 3

- [ ] **Step 1: Write tests/test_rollback.py**

```python
"""Tests for pet_ota.release.rollback."""
from __future__ import annotations

import json
import pathlib
import tarfile

import pytest

from pet_ota.backend.local import LocalBackend
from pet_ota.release.rollback import rollback


def _setup_deployment(
    backend_root: pathlib.Path, version: str, group: str, name: str, status: str = "done"
) -> LocalBackend:
    """Create a backend with an uploaded artifact and deployment."""
    backend = LocalBackend(root_dir=str(backend_root))
    model = backend_root / f"model-{version}.bin"
    model.write_bytes(f"model {version}".encode())
    tar_path = backend_root / f"model-v{version}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar_path), version)
    backend.create_deployment(version, group, name)
    # Set status directly for test setup
    dep_file = backend_root / "deployments" / f"{name}.json"
    data = json.loads(dep_file.read_text())
    data["status"] = status
    if status == "done":
        data["devices"] = {d: "success" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))
    return backend


def test_rollback_aborts_current(backend_root: pathlib.Path) -> None:
    """rollback aborts the current deployment."""
    # First: a successful old deployment
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    # Second: a new deployment in progress
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2.0.0")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    rollback(
        current_deployment_id="v2.0.0-canary",
        backend=backend,
        reason="high failure rate",
    )
    status = backend.get_deployment_status("v2.0.0-canary")
    assert status.status == "rolled_back"


def test_rollback_records_reason(backend_root: pathlib.Path) -> None:
    """rollback writes the reason to the deployment JSON."""
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2.0.0")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    rollback(
        current_deployment_id="v2.0.0-canary",
        backend=backend,
        reason="test rollback reason",
    )
    dep_file = backend_root / "deployments" / "v2.0.0-canary.json"
    data = json.loads(dep_file.read_text())
    assert data["rollback_reason"] == "test rollback reason"


def test_rollback_failure_marks_rollback_failed(backend_root: pathlib.Path) -> None:
    """If abort raises, status should be rollback_failed."""
    backend = _setup_deployment(backend_root, "1.0.0", "canary", "v1.0.0-canary", "done")
    # Create deployment but delete the file to cause abort to fail
    model = backend_root / "model-2.bin"
    model.write_bytes(b"model 2")
    tar = backend_root / "model-v2.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(model, arcname="model.bin")
    backend.upload_artifact(str(tar), "2.0.0")
    backend.create_deployment("2.0.0", "canary", "v2.0.0-canary")

    # Corrupt the deployment file to trigger rollback failure
    dep_file = backend_root / "deployments" / "v2.0.0-canary.json"
    dep_file.unlink()

    with pytest.raises(Exception):  # noqa: B017
        rollback(
            current_deployment_id="v2.0.0-canary",
            backend=backend,
            reason="should fail",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rollback.py -v`
Expected: FAIL

- [ ] **Step 3: Implement src/pet_ota/release/rollback.py**

```python
"""Rollback — abort current deployment and restore previous version."""
from __future__ import annotations

import structlog

from pet_ota.backend.base import OTABackend

logger = structlog.get_logger()


def rollback(
    current_deployment_id: str,
    backend: OTABackend,
    reason: str,
) -> None:
    """Abort the current deployment and mark it as rolled back.

    Args:
        current_deployment_id: The deployment to roll back.
        backend: OTABackend instance.
        reason: Human-readable reason for the rollback.

    Raises:
        Exception: If the rollback itself fails (logged as CRITICAL,
            status set to rollback_failed if possible).
    """
    logger.info(
        "rollback_start",
        deployment_id=current_deployment_id,
        reason=reason,
    )
    try:
        backend.abort_deployment(current_deployment_id)
        backend.update_deployment_status(current_deployment_id, "rolled_back")
        backend.update_deployment_metadata(
            current_deployment_id, {"rollback_reason": reason}
        )
        logger.info("rollback_complete", deployment_id=current_deployment_id)
    except Exception:
        logger.critical(
            "rollback_failed",
            deployment_id=current_deployment_id,
            reason=reason,
        )
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rollback.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pet_ota/release/rollback.py tests/test_rollback.py
git commit -m "feat(pet-ota): rollback with reason recording and CRITICAL on failure"
```

---

### Task 11: release/canary_rollout.py — Full State Machine

**Files:**
- Create: `src/pet_ota/release/canary_rollout.py`
- Create: `tests/test_canary_rollout.py`

**Depends on:** Tasks 3, 5, 6, 7, 8, 9, 10 (all modules)

This is the orchestrator that wires everything together. Tests use `canary_observe_hours=0` and `poll_interval_seconds=0` for instant execution.

- [ ] **Step 1: Write tests/test_canary_rollout.py**

```python
"""Tests for pet_ota.release.canary_rollout — full state machine."""
from __future__ import annotations

import hashlib
import json
import pathlib
import tarfile
from typing import Any

import yaml

from pet_ota.release.canary_rollout import canary_rollout, RolloutResult


def _setup_full_env(
    tmp_dir: pathlib.Path, gate_overrides: dict[str, Any] | None = None
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Set up a complete OTA environment for rollout testing.

    Returns (root_dir, release_dir, params_path).
    """
    # OTA root with device groups
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

    # Release dir with tarball + manifest
    release_dir = tmp_dir / "release"
    release_dir.mkdir()
    model = tmp_dir / "model.bin"
    model.write_bytes(b"quantized model weights v1.0.0")
    tar_name = "pet-model-v1.0.0.tar.gz"
    tar_path = release_dir / tar_name
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(model, arcname="model.bin")
    sha256 = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    manifest = {"version": "1.0.0", "files": {tar_name: {"sha256": sha256, "size": tar_path.stat().st_size}}}
    (release_dir / "manifest.json").write_text(json.dumps(manifest))

    # Params
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
        "packaging": {"delta_enabled": True, "artifact_store_dir": "artifacts/store", "public_key_path": ""},
        "monitoring": {"poll_interval_seconds": 0, "device_pending_timeout_minutes": 30},
        "device_groups": {"canary": str(dg / "canary.json"), "production": str(dg / "production.json")},
    }
    params_path = tmp_dir / "params.yaml"
    params_path.write_text(yaml.dump(params))

    return root, release_dir, params_path


def _simulate_all_success(root: pathlib.Path, deployment_name: str) -> None:
    """Simulate all devices succeeding for a deployment."""
    dep_file = root / "deployments" / f"{deployment_name}.json"
    data = json.loads(dep_file.read_text())
    data["devices"] = {d: "success" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))


def _sim_success(backend: object, dep_id: str) -> None:
    """Simulate all devices succeeding (test helper)."""
    import json
    dep_file = backend._root / "deployments" / f"{dep_id}.json"  # type: ignore[attr-defined]
    data = json.loads(dep_file.read_text())
    data["devices"] = {d: "success" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))


def _sim_failure(backend: object, dep_id: str) -> None:
    """Simulate all devices failing (test helper)."""
    import json
    dep_file = backend._root / "deployments" / f"{dep_id}.json"  # type: ignore[attr-defined]
    data = json.loads(dep_file.read_text())
    data["devices"] = {d: "failed" for d in data["devices"]}
    dep_file.write_text(json.dumps(data, indent=2))


def test_happy_path_full_rollout(tmp_dir: pathlib.Path) -> None:
    """Full canary → production rollout succeeds when all devices pass."""
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

    # Manually create a canary deployment at "canary_observing" state
    from pet_ota.backend.local import LocalBackend
    backend = LocalBackend(root_dir=str(root))
    # Upload artifact first
    import glob
    tarballs = glob.glob(str(release_dir / "*.tar.gz"))
    backend.upload_artifact(tarballs[0], "1.0.0")
    backend.create_deployment("1.0.0", "canary", "v1.0.0-canary")
    backend.update_deployment_status("v1.0.0-canary", "canary_observing")
    _sim_success(backend, "v1.0.0-canary")

    # Now call canary_rollout — it should resume, not re-run gate check
    result = canary_rollout(
        version="1.0.0",
        release_dir=str(release_dir),
        root_dir=str(root),
        params_path=str(params_path),
        device_simulator=_sim_success,
    )
    assert result.final_status == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_canary_rollout.py -v`
Expected: FAIL

- [ ] **Step 3: Implement src/pet_ota/release/canary_rollout.py**

```python
"""Canary rollout state machine — gate check → canary → observe → full → done."""
from __future__ import annotations

import time
from typing import Callable

import structlog
from pydantic import BaseModel

from pet_ota.backend.base import OTABackend
from pet_ota.backend.local import LocalBackend
from pet_ota.monitoring.alert import check_and_alert
from pet_ota.monitoring.check_update_rate import check_update_rate
from pet_ota.packaging.create_deployment import create_deployment
from pet_ota.packaging.upload_artifact import upload_artifact
from pet_ota.release.check_gate import check_gate
from pet_ota.release.rollback import rollback

logger = structlog.get_logger()

# States that can be resumed after process restart
_RESUMABLE_STATES = {
    "canary_deploying",
    "canary_observing",
    "full_deploying",
}


class RolloutResult(BaseModel, frozen=True):
    """Result of a canary rollout attempt."""

    version: str
    final_status: str
    gate_failures: list[str]
    canary_deployment_id: str
    full_deployment_id: str


def canary_rollout(
    version: str,
    release_dir: str,
    root_dir: str,
    params_path: str = "params.yaml",
    device_simulator: Callable[[OTABackend, str], None] | None = None,
) -> RolloutResult:
    """Execute the full canary rollout state machine.

    States: GATE_CHECK → CANARY_DEPLOYING → CANARY_OBSERVING →
            FULL_DEPLOYING → DONE (with ROLLING_BACK paths)

    Supports process resume: if a deployment JSON already exists for this
    version, resumes from the persisted state instead of starting fresh.

    Args:
        version: Semantic version to deploy.
        release_dir: Path to release directory (tarball + manifest).
        root_dir: Root directory for LocalBackend.
        params_path: Path to params.yaml.
        device_simulator: Optional callback(backend, deployment_id) to
            simulate device responses in tests. Not used in production.

    Returns:
        RolloutResult with final status and metadata.
    """
    from pet_ota.config import load_params

    params = load_params(params_path)
    backend = LocalBackend(root_dir=root_dir)

    canary_dep_id = f"v{version}-canary"
    full_dep_id = f"v{version}-full"
    gate_failures: list[str] = []

    # --- Resume check: look for existing deployment state ---
    resume_state = _check_resume(backend, canary_dep_id, full_dep_id)

    if resume_state == "canary_observing":
        logger.info("rollout_resume", state="canary_observing", version=version)
        return _observe_and_continue(
            version, release_dir, canary_dep_id, full_dep_id,
            params, backend, device_simulator,
        )
    if resume_state == "full_deploying":
        logger.info("rollout_resume", state="full_deploying", version=version)
        return _full_deploy_and_finish(
            version, canary_dep_id, full_dep_id, params, backend, device_simulator,
        )

    # --- GATE_CHECK ---
    logger.info("rollout_state", state="gate_check", version=version)
    passed, gate_failures = check_gate(params_path)
    if not passed:
        logger.info("rollout_gate_failed", failures=gate_failures)
        return RolloutResult(
            version=version, final_status="failed",
            gate_failures=gate_failures,
            canary_deployment_id="", full_deployment_id="",
        )

    # --- Upload artifact ---
    artifact_id = upload_artifact(
        release_dir=release_dir, version=version,
        backend=backend, public_key_path=params.packaging.public_key_path,
    )

    # --- CANARY_DEPLOYING ---
    logger.info("rollout_state", state="canary_deploying", version=version)
    canary_dep_id = create_deployment(
        artifact_id=artifact_id, device_group="canary",
        name=canary_dep_id, backend=backend,
    )

    if device_simulator:
        device_simulator(backend, canary_dep_id)

    # --- CANARY_OBSERVING + FULL_DEPLOYING + DONE ---
    return _observe_and_continue(
        version, release_dir, canary_dep_id, full_dep_id,
        params, backend, device_simulator,
    )


def _check_resume(
    backend: LocalBackend, canary_id: str, full_id: str
) -> str | None:
    """Check for existing deployment state to resume from.

    Returns the state to resume from, or None for fresh start.
    """
    try:
        full_status = backend.get_deployment_status(full_id)
        if full_status.status in _RESUMABLE_STATES:
            return full_status.status
    except FileNotFoundError:
        pass
    try:
        canary_status = backend.get_deployment_status(canary_id)
        if canary_status.status in _RESUMABLE_STATES:
            return canary_status.status
    except FileNotFoundError:
        pass
    return None


def _observe_and_continue(
    version: str, release_dir: str, canary_dep_id: str,
    full_dep_id: str, params: object, backend: LocalBackend,
    device_simulator: Callable[[OTABackend, str], None] | None,
) -> RolloutResult:
    """Run canary observation phase, then continue to full deploy."""
    logger.info("rollout_state", state="canary_observing", version=version)
    backend.update_deployment_status(canary_dep_id, "canary_observing")

    observe_seconds = params.release.canary_observe_hours * 3600  # type: ignore[attr-defined]
    poll_interval = params.monitoring.poll_interval_seconds  # type: ignore[attr-defined]
    failure_threshold = params.release.failure_rate_threshold  # type: ignore[attr-defined]
    elapsed = 0

    while elapsed < observe_seconds or observe_seconds == 0:
        rate_result = check_update_rate(canary_dep_id, backend)
        if check_and_alert(rate_result, failure_threshold):
            return _do_rollback(version, canary_dep_id, "", backend, "canary failure rate exceeded")

        if rate_result.pending_count == 0 or observe_seconds == 0:
            break

        if poll_interval > 0:
            time.sleep(poll_interval)
        elapsed += max(poll_interval, 1)

    backend.update_deployment_status(canary_dep_id, "done")
    return _full_deploy_and_finish(
        version, canary_dep_id, full_dep_id, params, backend, device_simulator,
    )


def _full_deploy_and_finish(
    version: str, canary_dep_id: str, full_dep_id: str,
    params: object, backend: LocalBackend,
    device_simulator: Callable[[OTABackend, str], None] | None,
) -> RolloutResult:
    """Deploy to production and finish."""
    logger.info("rollout_state", state="full_deploying", version=version)
    failure_threshold = params.release.failure_rate_threshold  # type: ignore[attr-defined]

    # Create full deployment if it doesn't exist yet
    try:
        backend.get_deployment_status(full_dep_id)
    except FileNotFoundError:
        artifact_id = version  # artifact_id == version for LocalBackend
        full_dep_id = create_deployment(
            artifact_id=artifact_id, device_group="production",
            name=full_dep_id, backend=backend,
        )
    backend.update_deployment_status(full_dep_id, "full_deploying")

    if device_simulator:
        device_simulator(backend, full_dep_id)

    rate_result = check_update_rate(full_dep_id, backend)
    if check_and_alert(rate_result, failure_threshold):
        return _do_rollback(
            version, full_dep_id, canary_dep_id, backend,
            "full deployment failure rate exceeded",
        )

    backend.update_deployment_status(full_dep_id, "done")
    logger.info("rollout_state", state="done", version=version)
    return RolloutResult(
        version=version, final_status="done", gate_failures=[],
        canary_deployment_id=canary_dep_id, full_deployment_id=full_dep_id,
    )


def _do_rollback(
    version: str, dep_id: str, other_dep_id: str,
    backend: OTABackend, reason: str,
) -> RolloutResult:
    """Execute rollback and return appropriate result."""
    logger.info("rollout_state", state="rolling_back", version=version, reason=reason)
    try:
        rollback(dep_id, backend, reason)
        return RolloutResult(
            version=version, final_status="rolled_back", gate_failures=[],
            canary_deployment_id=other_dep_id if dep_id.endswith("-full") else dep_id,
            full_deployment_id=dep_id if dep_id.endswith("-full") else "",
        )
    except Exception:
        return RolloutResult(
            version=version, final_status="rollback_failed", gate_failures=[],
            canary_deployment_id=other_dep_id if dep_id.endswith("-full") else dep_id,
            full_deployment_id=dep_id if dep_id.endswith("-full") else "",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_canary_rollout.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS (should be ~35+ tests total)

- [ ] **Step 6: Commit**

```bash
git add src/pet_ota/release/canary_rollout.py tests/test_canary_rollout.py
git commit -m "feat(pet-ota): canary rollout state machine with gate/observe/rollback"
```

---

### Task 12: Lint + Type Check Full Codebase

**Files:**
- Modify: any files with lint/type errors

- [ ] **Step 1: Run ruff**

Run: `ruff check src/ tests/`
Fix any errors (likely import ordering, unused imports).

- [ ] **Step 2: Run mypy**

Run: `mypy src/`
Fix any type errors. Common issues: Protocol attribute access in rollback.py.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix(pet-ota): lint and type check cleanup"
```

---

### Task 13: Update DEVELOPMENT_GUIDE

**Files:**
- Modify: `/Users/bamboo/Githubs/Train-Pet-Pipeline/pet-infra/docs/DEVELOPMENT_GUIDE.md` (pet-ota section)

- [ ] **Step 1: Read current DEVELOPMENT_GUIDE pet-ota section**

Find the pet-ota section (around section 5.7) and read it.

- [ ] **Step 2: Update to reflect actual implementation**

Update the file structure listing to match the actual implementation:
- `backend/` instead of `server/`
- `make_delta.py` instead of `make_delta.sh`
- Add `config.py`, `monitoring/`, `release/` structure
- Note: no `mender.env`, `nginx.conf`, `docker-compose.yml` in v1
- Add deviation notes matching spec Section 11

- [ ] **Step 3: Commit to pet-infra**

```bash
cd /Users/bamboo/Githubs/Train-Pet-Pipeline/pet-infra
git checkout dev
git add docs/DEVELOPMENT_GUIDE.md
git commit -m "docs(pet-infra): sync DEVELOPMENT_GUIDE with pet-ota v1 implementation"
```

---

### Task 14: Create PR + Final Verification

**Files:** None (process task)

- [ ] **Step 1: Run full test suite one last time**

Run: `cd /Users/bamboo/Githubs/Train-Pet-Pipeline/pet-ota && pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run lint one last time**

Run: `ruff check src/ tests/ && mypy src/`
Expected: No errors

- [ ] **Step 3: Push feature branch and create PR**

```bash
git push -u origin feature/v1-implementation
gh pr create --base dev --title "feat(pet-ota): v1 OTA system" --body "..."
```

- [ ] **Step 4: After PR merge, sync branches**

```bash
git checkout dev && git pull
git checkout main && git merge dev
git push origin main
git tag v1.0.0 && git push origin v1.0.0
```
