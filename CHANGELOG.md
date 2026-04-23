# Changelog

All notable changes to pet-ota are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.2.0 — 2026-04-23

Phase 8 — ecosystem optimization pass for pet-ota. Peer-dep governance
fix (spec §5.1 #1), pet-quantize version-range removal (spec §5.1 #2),
W&B residue guard, version parity, no-hardcode refactor on release gate
thresholds, and `architecture.md`.

### Added
- `docs/architecture.md` (9-章 template per ecosystem-optimization spec §4.1).
- `.github/workflows/no-wandb-residue.yml` — positive-list CI guard
  scanning first-party code for `\bwandb\b` matches.
- `tests/test_version.py` — `test_version_attribute_matches_metadata`
  parity between `pet_ota.__version__` and `importlib.metadata`.
- `ReleaseConfig.min_dpo_pairs` (default 500) +
  `ReleaseConfig.min_days_since_last_release` (default 7) — gate
  thresholds moved from hardcoded literals in `release/check_gate.py`
  to `params.yaml:release.*` (no-hardcode rule).
- README Prerequisites + quick-start + entry-point snippet + canary
  rollout state-machine diagram.

### Changed
- **pet-infra migrated from hardpin to β peer-dep** (spec §5.1 #1):
  `pyproject.toml` drops `pet-infra @ git+...@v2.5.0` from
  `dependencies`. Matches Phase 7 pet-quantize decision (option X /
  delayed-guard per DEV_GUIDE §11.3) — plan Phase 8 mandates
  "两仓决策必须一致".
- **pet-quantize version range dropped** (spec §5.1 #2): `[signing]`
  extras `"pet-quantize>=1.0.0"` → `"pet-quantize"` (no pin). Cross-repo
  plugin-dep style aligned with pet-eval.
- `.github/workflows/{ci,peer-dep-smoke}.yml`:
  - Step 1 `pet-infra @v2.5.0` → `@v2.6.0` (matrix 2026.09).
  - Step 4 assertion tightened `startswith('2.5')` → `startswith('2.6')`.
- `tests/peer_dep/test_smoke_versions.py::test_pet_infra_version` —
  assertion widened from `startswith('2.5')` to `startswith('2.')`
  so dev envs need not reinstall pet-infra on every matrix row bump
  (CI step 4 owns the tight check).
- `plugins/_register.py` — "Install via matrix row 2026.08" →
  "Install via latest matrix row (...)" (stale); header comment added
  explaining delayed-guard option-X rationale.
- `release/check_gate.py` — threshold comparisons read from
  `params.release.min_dpo_pairs` / `min_days_since_last_release`
  instead of inline literals.

### Fixed
- `pet_ota.__version__` synced to pyproject `2.2.0` (was `2.0.0` when
  pyproject was `2.1.0` — drift since Phase 4 P5-A-3).

## 2.1.0 — 2026-04-22

Phase 4 W1 (OTA backends slice).

### Added
- `S3BackendPlugin` (P2-A-2) — uploads edge artifacts + manifest.json to
  `s3://<bucket>/<prefix>/<card_id>/`. Source artifacts resolved through the
  STORAGE registry (file / local / s3 / http schemes). Tested with moto.
- `HttpBackendPlugin` (P2-A-3) — PUT-style upload to `<base_url>/<card_id>/`
  with three auth modes: none, bearer token, HTTP basic. Tested via in-process
  `http.server`.
- `peer-dep-smoke` CI assertion now requires all 3 OTA backends
  (`local_backend`, `s3_backend`, `http_backend`) to register against the
  tagged `pet-infra @ v2.5.0-rc1` peer-dep (P2-A-4).
- Runtime dep: `requests>=2.31` (HTTP backend).
- Dev deps: `boto3>=1.34`, `moto[s3]>=5.0`.

### Changed
- Peer-dep bumped: `pet-infra @ git+...@v2.5.0-rc1` (P2-A-1).
- CI install order normalised to 3 steps (peer-dep first, then editable, then
  dev extras).
