"""Canary rollout state machine — gate check -> canary -> observe -> full -> done."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pet_infra.logging import get_logger
from pydantic import BaseModel

from pet_ota.backend.base import OTABackend
from pet_ota.backend.local import LocalBackend
from pet_ota.monitoring.alert import check_and_alert
from pet_ota.monitoring.check_update_rate import check_update_rate
from pet_ota.packaging.create_deployment import create_deployment
from pet_ota.packaging.upload_artifact import upload_artifact
from pet_ota.release.check_gate import check_gate
from pet_ota.release.rollback import rollback

logger = get_logger("pet-ota")

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

    States: GATE_CHECK -> CANARY_DEPLOYING -> CANARY_OBSERVING ->
            FULL_DEPLOYING -> DONE (with ROLLING_BACK paths)

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

    # --- Resume check ---
    resume_state = _check_resume(backend, canary_dep_id, full_dep_id)

    if resume_state == "canary_observing":
        logger.info("rollout_resume", extra={"state": "canary_observing", "version": version})
        return _observe_and_continue(
            version, canary_dep_id, full_dep_id, params, backend, device_simulator,
        )
    if resume_state == "full_deploying":
        logger.info("rollout_resume", extra={"state": "full_deploying", "version": version})
        return _full_deploy_and_finish(
            version, canary_dep_id, full_dep_id, params, backend, device_simulator,
        )

    # --- GATE_CHECK ---
    logger.info("rollout_state", extra={"state": "gate_check", "version": version})
    passed, gate_failures = check_gate(params_path)
    if not passed:
        logger.info("rollout_gate_failed", extra={"failures": gate_failures})
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
    logger.info("rollout_state", extra={"state": "canary_deploying", "version": version})
    canary_dep_id = create_deployment(
        artifact_id=artifact_id, device_group="canary",
        name=canary_dep_id, backend=backend,
    )

    if device_simulator:
        device_simulator(backend, canary_dep_id)

    return _observe_and_continue(
        version, canary_dep_id, full_dep_id, params, backend, device_simulator,
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
    version: str, canary_dep_id: str, full_dep_id: str,
    params: Any, backend: LocalBackend,
    device_simulator: Callable[[OTABackend, str], None] | None,
) -> RolloutResult:
    """Run canary observation phase, then continue to full deploy."""
    logger.info("rollout_state", extra={"state": "canary_observing", "version": version})
    backend.update_deployment_status(canary_dep_id, "canary_observing")

    observe_seconds = params.release.canary_observe_hours * 3600
    poll_interval = params.monitoring.poll_interval_seconds
    failure_threshold = params.release.failure_rate_threshold
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
    params: Any, backend: LocalBackend,
    device_simulator: Callable[[OTABackend, str], None] | None,
) -> RolloutResult:
    """Deploy to production and finish."""
    logger.info("rollout_state", extra={"state": "full_deploying", "version": version})
    failure_threshold = params.release.failure_rate_threshold

    try:
        backend.get_deployment_status(full_dep_id)
    except FileNotFoundError:
        artifact_id = version
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
    logger.info("rollout_state", extra={"state": "done", "version": version})
    return RolloutResult(
        version=version, final_status="done", gate_failures=[],
        canary_deployment_id=canary_dep_id, full_deployment_id=full_dep_id,
    )


def _do_rollback(
    version: str, dep_id: str, other_dep_id: str,
    backend: OTABackend, reason: str,
) -> RolloutResult:
    """Execute rollback and return appropriate result."""
    logger.info(
        "rollout_state", extra={"state": "rolling_back", "version": version, "reason": reason}
    )
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
