"""Tests for pet_ota.monitoring.alert."""
from __future__ import annotations

import logging

import pytest

from pet_ota.monitoring.alert import check_and_alert
from pet_ota.monitoring.check_update_rate import UpdateRateResult


def test_alert_fires_on_high_failure_rate(caplog: pytest.LogCaptureFixture) -> None:
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
    ota_logger = logging.getLogger("pet-ota")
    original_propagate = ota_logger.propagate
    ota_logger.propagate = True
    try:
        with caplog.at_level(logging.CRITICAL, logger="pet-ota"):
            fired = check_and_alert(result, threshold=0.10)
    finally:
        ota_logger.propagate = original_propagate
    assert fired is True
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


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
