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
