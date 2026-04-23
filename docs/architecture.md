# pet-ota Architecture

## §1 Repository Responsibility

**pet-ota** is the last-mile artifact-publishing and canary-rollout stage of the smart pet feeder pipeline.

It ships three registry-backed surfaces:

1. **3 OTA backend plugins** (`pet_infra.registry.OTA`) —
   - `local_backend` (filesystem),
   - `s3_backend` (boto3 + STORAGE registry resolution),
   - `http_backend` (PUT + bearer/basic/no-auth).
2. **Canary rollout state machine** (`pet_ota.release.canary_rollout`) — 5-state deployment flow with resume-from-state on crash, driven by the stateful `pet_ota.backend.LocalBackend` class (not an OTA-registry plugin).
3. **Packaging + monitoring** — delta-patch creation (bsdiff4 + tenacity retry), manifest SHA-256 verification, optional signature verification via lazy-imported `pet_quantize.packaging.verify_package`, update-rate monitoring with alerting.

Pipeline position:

```
pet-train → pet-eval → pet-quantize → [pet-ota] → (devices)
                                          │
                                          └─ signing optional: pet_quantize.packaging.verify_package
                                             (lazy, try/except ImportError → soft warn)
```

**Does:**
- Verifies manifest integrity (SHA-256) on every uploaded tarball.
- Creates binary delta patches (old → new) via bsdiff4 with retry on large-file IO flakes.
- Publishes artifacts to local filesystem / S3 / HTTP backends via the OTA registry.
- Runs a 5-state canary rollout (gate_check → canary_deploying → canary_observing → full_deploying → done) with rollback paths + resume-from-state.
- Reads every numeric threshold (canary percentage, observation window, rollback timeout, gate thresholds) from `params.yaml`.

**Does not:**
- Quantize / convert artifacts (pet-quantize).
- Sign artifacts itself — signing is an optional pet-quantize interop (`[signing]` extras).
- Run its own experiment tracker — `pet_infra.orchestrator + ClearMLLogger` is the sole logging path (W&B never existed here; `no-wandb-residue.yml` guards forward).

---

## §2 I/O Contract

### Upstream dependencies

| Dependency | Mode | Locked version |
|---|---|---|
| pet-infra | β peer-dep (NOT in `pyproject.dependencies` as of v2.2.0) | v2.6.0 (compatibility_matrix 2026.09) |
| pet-quantize | optional extras `[signing]` (no-pin, spec §5.1 #2) | matrix-locked when present |
| pet-schema | transitive via pet-infra | matrix row |

CI install order (`.github/workflows/ci.yml` + `peer-dep-smoke.yml`) is 4-step: pet-infra peer-dep → editable `--no-deps` → re-resolve dev extras → version-prefix assertion on `pet_infra.__version__.startswith('2.6')`.

### Inputs

| Source | Consumer | Notes |
|---|---|---|
| Release directory (`artifacts/store/v<version>/`) | `packaging/upload_artifact.py` | must contain `*.tar.gz` + `manifest.json` |
| `input_card: ModelCard` (pet-schema) with `edge_artifacts[]` + `gate_status == 'passed'` | every OTA backend plugin | gate guard enforced in every plugin |
| `params.yaml` | release / gate check / monitoring | release, gate_overrides, packaging, monitoring, device_groups sections |

### Outputs

- `ModelCard` with appended `DeploymentStatus` (`state ∈ {deployed, rolling_back, rolled_back, ...}`, `backend`, `deployed_at`, `manifest_uri`).
- Remote artifacts at the backend URI (`file://...`, `s3://bucket/prefix/...`, `http[s]://base/...`).
- Deployment JSON state files under `deployments/<deployment_id>.json` for canary rollout resume.

### Downstream consumers

- **Devices** consume the deployed artifact via the backend URI (outside the repo).
- **Monitoring**: `pet_ota.monitoring.check_update_rate` + `pet_ota.monitoring.alert.check_and_alert` poll `get_device_update_history` to detect stalled rollouts.

---

## §3 Architecture Overview

### Directory tree

```
src/pet_ota/
├── __init__.py                            ← __version__ = "2.2.0"
├── config.py                              ← Pydantic OTAParams + load_params
├── backend/                               ← legacy stateful deployment backend
│   ├── base.py                            ← OTABackend Protocol + DeploymentStatus
│   └── local.py                           ← LocalBackend (deployments/ + device_groups/)
├── plugins/
│   ├── _register.py                       ← entry-point target; delayed pet-infra guard
│   └── backends/                          ← Phase 4 OTA registry plugins
│       ├── local.py                       ← @OTA "local_backend"
│       ├── s3.py                          ← @OTA "s3_backend"   (boto3 + STORAGE)
│       └── http.py                        ← @OTA "http_backend" (PUT + auth modes)
├── packaging/
│   ├── make_delta.py                      ← bsdiff4 + tenacity retry
│   └── upload_artifact.py                 ← manifest SHA-256 verify + lazy signature verify
├── release/
│   ├── canary_rollout.py                  ← 5-state FSM + resume-from-state
│   ├── check_gate.py                      ← 5 gate checks (thresholds from params.release.min_*)
│   └── rollback.py                        ← rollout abort path
└── monitoring/
    ├── alert.py                           ← check-and-alert wrapper
    └── check_update_rate.py               ← device update timeout detection

params.yaml                                ← release / gate_overrides / packaging / monitoring / device_groups
.github/workflows/
├── ci.yml                                 ← 4-step peer-dep install + ruff + mypy + pytest
├── peer-dep-smoke.yml                     ← install-order contract + OTA register_all smoke
└── no-wandb-residue.yml                   ← positive-list CI guard
```

### High-level dataflow

```
orchestrator                              pet_ota
─────────────                              ───────
recipe.yaml ──► compose_recipe ──► stage ──► EvaluatorStageRunner (OTA registry)
                                                  │
                                                  │ _load_stage_kwargs(stage)
                                                  ▼
                                         {Local,S3,Http}BackendPlugin(**kwargs)
                                                  │
                                                  ▼
                                        run(input_card, recipe)
                                                  │
                                          gate_status guard ─── fail ──► raise ValueError
                                                  │
                                                  ▼
                                        upload edge_artifacts + manifest
                                                  │
                                                  ▼
                                   ModelCard + DeploymentStatus(state="deployed")


Separately (release FSM, outside OTA registry):

canary_rollout(version, release_dir, root_dir, params_path):
  check_gate ──► upload_artifact (manifest + optional signature verify)
       │                  │
       │                  ▼
       │          LocalBackend.create_deployment(canary)
       │                  │
       │                  ▼
       │          canary_observe (check_update_rate + alert)
       │                  │
       │                  ▼
       │          LocalBackend.create_deployment(full)
       │                  │
       │                  └──► done   (or → rollback on failure)
```

---

## §4 Core Modules

### 4.1 `plugins/_register.py` — entry-point target

Declared in `pyproject.toml` under `[project.entry-points."pet_infra.plugins"] pet_ota = …`. The pet-infra peer-dep guard lives **inside** `register_all()` (delayed-guard / option X, same decision as pet-quantize Phase 7, plan-mandated consistency). Raises `RuntimeError("pet-ota requires pet-infra to be installed first. Install via latest matrix row ...")` when `import pet_infra` fails.

Registers 3 backends unconditionally (no SDK gate — pet-ota is pure deployment code).

### 4.2 OTA registry plugins (`plugins/backends/*`)

All three implement the same `run(input_card, recipe) -> ModelCard` contract and a hard `gate_status != 'passed'` guard. They append a `DeploymentStatus(backend=..., state="deployed", manifest_uri=...)` to `input_card.deployment_history`.

| Plugin | Transport | Auth | Storage source resolution |
|---|---|---|---|
| `local_backend` | filesystem (`shutil.copy2`) | — | direct `Path(edge.artifact_uri)` |
| `s3_backend` | boto3 `put_object` | AWS/MinIO credentials | via `STORAGE` registry (file / local / s3 / http schemes) |
| `http_backend` | `requests.PUT` | none / bearer token / HTTP basic | via `STORAGE` registry |

Every backend writes `manifest.json` to the same prefix/directory as the artifacts so devices can discover the deployment metadata in one place.

### 4.3 Legacy deployment backend (`backend/*`)

`pet_ota.backend.LocalBackend` is a **different** thing from `pet_ota.plugins.backends.LocalBackendPlugin`: it's a stateful deployment orchestration backend used by the canary rollout FSM.

```
root_dir/
├── artifacts/store/v<version>/      ← tarballs (uploaded via upload_artifact())
├── device_groups/<group>.json       ← device ID lists
└── deployments/<deployment_id>.json ← deployment state (status / devices / timestamps)
```

Exposes `OTABackend` Protocol (`backend/base.py`): `upload_artifact`, `list_device_groups`, `create_deployment`, `get_deployment_status`, `abort_deployment`, `update_deployment_status`, `update_deployment_metadata`, `get_device_update_history`.

Consumed by: `packaging/upload_artifact.py`, `release/canary_rollout.py`, `release/rollback.py`, `monitoring/check_update_rate.py`.

### 4.4 `packaging/` — delta + upload

- `make_delta.py`:
  `@retry(stop_after_attempt(3), wait_fixed(1), reraise=True)` over `bsdiff4.diff(old_bytes, new_bytes)`. The retry is not defensive-programming slop — bsdiff4 genuinely flakes on large tarballs due to IO/OOM boundary conditions; the 3-attempt retry was calibrated from real incident data (see §8.5).
- `upload_artifact.py`:
  1. `_verify_manifest()` — walks `manifest.json["files"]`, SHA-256-checks every listed file, raises `ValueError` on mismatch.
  2. If `public_key_path` is set: `from pet_quantize.packaging.verify_package import verify_package` lazy-imported inside `try/except ImportError`; missing pet-quantize → `logger.warning("pet_quantize not available, skipping signature verification")`.
  3. Finds `*.tar.gz` under `release_dir`; calls `backend.upload_artifact(tarball, version)`.

### 4.5 `release/` — canary rollout FSM

`canary_rollout(version, release_dir, root_dir, params_path, device_simulator)` implements the 5-state flow:

```
GATE_CHECK ──pass──► CANARY_DEPLOYING ──► CANARY_OBSERVING ──► FULL_DEPLOYING ──► DONE
    │                       │                      │                   │
    └──fail─► (return)      │                 fail │              fail │
                            └──────────────► ROLLING_BACK ◄────────────┘
                                                    │
                                                    ▼
                                               ROLLED_BACK
```

**Resume-from-state:** if `deployments/<id>.json` already exists with status in `{canary_deploying, canary_observing, full_deploying}`, the function picks up from that state instead of re-running gate_check. Prevents double-deployment + preserves the long-running observation window across restarts.

**Gate thresholds** (`check_gate.py`) read from `params.release.min_dpo_pairs` (default 500) and `params.release.min_days_since_last_release` (default 7) — no longer inline literals (Phase 8 finding ⑦).

### 4.6 `monitoring/` — rollout health

- `check_update_rate(deployment_id, backend, failure_rate_threshold)` — reads device map from deployment JSON, computes `failure_count / total`, returns a breach flag.
- `alert.check_and_alert` — wrapper that calls check_update_rate and emits a structured log event when the threshold trips. No external alerting system bound yet; downstream can hook onto the log pattern.

---

## §5 Extension Points

### Adding an OTA backend

1. Drop `src/pet_ota/plugins/backends/<name>.py` with a class decorated `@OTA.register_module(name="<name>", force=True)`.
2. Accept `**_: object` in `__init__`; expose `run(input_card, recipe) -> ModelCard`.
3. Enforce `gate_status == 'passed'` at the top of `run()` (raise `ValueError` otherwise).
4. Trigger `pet_infra.storage.*` registration at module import if sourcing via STORAGE (see `s3.py` / `http.py`).
5. Append the import to `_register.py` + update `peer-dep-smoke.yml` expected-OTA set.

### Adding a canary rollout state

`canary_rollout.py` currently hardcodes the 5 states. A 6th state (e.g., `CANARY_RAMPING` for gradual percentage expansion) would extend `_RESUMABLE_STATES` and add the transition logic; `LocalBackend.update_deployment_status` already accepts arbitrary status strings.

### Adding a deployment backend (stateful)

Implement `OTABackend` Protocol (`backend/base.py`); the canary FSM is backend-agnostic via the Protocol, so a MenderBackend / NebraskaBackend would plug in by satisfying `upload_artifact / create_deployment / get_deployment_status / ...`.

---

## §6 Dependency Management

### Pin style

- **pet-infra** — β **peer-dep**, NOT in `pyproject.dependencies` (migrated in v2.2.0, spec §5.1 #1). Install order enforced by CI + `README.md` Prerequisites; delayed `RuntimeError` guard in `_register.py` surfaces a clear error when the prereq is skipped.
- **pet-quantize** — optional `[signing]` extras with **no version pin** (spec §5.1 #2, migrated from `>=1.0.0` in v2.2.0). Cross-repo plugin-dep style matching pet-eval. `upload_artifact.py` lazy-imports `pet_quantize.packaging.verify_package` with soft-fail on ImportError, so `[signing]` really is optional at runtime.
- **pet-schema** — transitive via pet-infra; not declared directly.
- **External**: `bsdiff4`, `pydantic`, `pyyaml`, `requests`, `tenacity` — standard PyPI pins.

### Install-order contract (DEV_GUIDE §11.4)

4-step in `.github/workflows/ci.yml` + `peer-dep-smoke.yml`:

1. `pip install 'pet-infra @ git+…@v2.6.0'`
2. `pip install -e . --no-deps`
3. `pip install -e ".[dev]"` (re-resolves dev extras; pet-infra stays at step-1 version because it's no longer a declared dep)
4. `python -c "import importlib.metadata; v=importlib.metadata.version('pet-infra'); assert v.startswith('2.6')"`

### Version bump policy

- **patch** — docstring / comment-only changes; no OTA surface or FSM change.
- **minor** — new OTA backend plugin; `params.yaml` schema addition; peer-dep surface tweak (e.g., pet-infra hardpin → peer-dep in 2.2.0).
- **major** — change to `OTABackend` Protocol signature, FSM state removal, or removal of a registered plugin name.

`test_version_attribute_matches_metadata` enforces parity between `pet_ota.__version__` and `importlib.metadata.version("pet-ota")`.

---

## §7 Local Dev and Test

```bash
# Prerequisites: shared pet-pipeline conda env + pet-infra pre-installed
conda activate pet-pipeline

# One-time: install pet-infra peer-dep (current matrix row)
pip install 'pet-infra @ git+https://github.com/Train-Pet-Pipeline/pet-infra@v2.6.0'

# From repo root:
make setup                          # pip install -e ".[dev]"
PET_ALLOW_MISSING_SDK=1 make test   # pytest tests/ -v    (51 tests)
make lint                           # ruff check src/ tests/ && mypy src/
make clean                          # drop .pytest_cache / .mypy_cache / .ruff_cache / caches
```

Mini-E2E candidate (T6.3; no hardware, no SDK):

```bash
PET_ALLOW_MISSING_SDK=1 pytest \
    tests/test_local_backend_plugin.py \
    tests/test_gate_enforcement.py \
    tests/test_register.py \
    tests/plugins/backends/ -v
```

Covers 3 backend plugin contracts + `gate_status != 'passed'` refusal path + registry population (S3 via moto, HTTP via in-process server).

---

## §8 Known Complex Points (Preserved for Good Reasons)

### 8.1 Two backend surfaces (`pet_ota.backend.*` vs `pet_ota.plugins.backends.*`)

**Why preserved:** They do different things:

- `pet_ota.backend.LocalBackend` — a *stateful deployment orchestration* backend. Tracks `deployments/<id>.json` files, device-group membership, per-device status (`pending / success / failed / timeout`). Consumed by the canary rollout FSM + rollback + monitoring.
- `pet_ota.plugins.backends.LocalBackendPlugin` — a *thin OTA registry plugin* for artifact publishing. Copies `edge_artifacts` to a storage location + writes `manifest.json`. Consumed by the pet-infra orchestrator as a pipeline stage.

Merging them would require hoisting the deployment lifecycle into the OTA registry (state files, device group tracking, per-device status) — significant coupling for no actual shared use case.

**What would be lost by removing either:** Either canary rollout loses its state machine (no `LocalBackend`), or the orchestrator can't publish artifacts through its standard `OTA.build()` path (no `LocalBackendPlugin`).

**Condition to revisit:** A unified "deployment" registry emerges in pet-infra that covers both artifact publishing *and* stateful rollout — at which point both layers can collapse into that registry.

### 8.2 Canary rollout resume-from-state

**Why preserved:** `canary_observe_hours` defaults to 48. Any rollout longer than a process lifetime needs durable state or it can't survive a crash / redeploy. The FSM writes `deployments/<id>.json` at every state transition; on re-entry, if a JSON for this `version` exists with status in `{canary_deploying, canary_observing, full_deploying}`, the function picks up from that state instead of re-running gate_check.

Without resume: a crash during `canary_observing` would (a) clear the observation progress, (b) potentially double-deploy to the canary group, (c) reset the observation timer — producing an artificially successful rollout that never actually observed the real canary.

**What would be lost by removing:** Durability. Every rollout becomes all-or-nothing with the process lifetime.

**Condition to revisit:** A dedicated orchestrator process supervisor (systemd / k8s Job with restartPolicy) takes over crash recovery, or canary observation moves to a separate daemon.

### 8.3 pet-quantize lazy import in `upload_artifact.py` with try/except fallback

**Why preserved:** `upload_artifact(release_dir, version, backend, public_key_path)` takes a `public_key_path` that's empty by default. When set, it imports `pet_quantize.packaging.verify_package` to validate the tarball signature. If pet-quantize isn't installed (the `[signing]` extra wasn't selected), the import raises ImportError → `logger.warning("pet_quantize not available, skipping signature verification")` and the upload proceeds.

This is the intended soft-fail path: signing is an optional hardening step, not a blocker for dev / staging deployments.

**What would be lost by removing:** Either dev deployments require the full pet-quantize install (extra friction), or signing can't be made optional (every env has to care).

**Condition to revisit:** Signing becomes mandatory for every deployment environment and pet-quantize becomes a required peer-dep.

### 8.4 `_register.py` delayed-guard (RuntimeError inside `register_all()`)

**Why preserved:** pet-infra is a β peer-dep — the peer-dep contract is that callers install it *before* they use pet-ota. Putting the import guard at module top would break bare `import pet_ota` in IDE / static-analysis / linter environments that don't need pet-infra resolved. Putting it inside `register_all()` defers the check until the orchestrator actually wires the plugin, which is exactly when the dep matters.

Same decision as pet-quantize Phase 7 (option X); plan Phase 8 mandated consistency across both repos ("两仓决策必须一致").

**What would be lost by removing:** Either `import pet_ota` starts requiring pet-infra at every touchpoint (IDE friction) or the guard loses its diagnostic value (missing pet-infra fails deep inside a registry call).

**Condition to revisit:** pet-infra becomes a mandatory hard-pin for every pet-ota consumer (e.g., if pet-ota stops supporting bare-package analysis use cases).

### 8.5 `make_delta` tenacity retry

**Why preserved:** bsdiff4 operates on raw bytes in-memory; on large pet model tarballs (several hundred MB), it occasionally fails with transient OOM / IO errors that succeed on retry. The 3-attempt retry with 1-second wait was calibrated from real incident data — not speculative defensive coding. `reraise=True` surfaces the final failure cleanly instead of wrapping in a RetryError.

**What would be lost by removing:** Flaky delta builds on the delta-generation path that serves the OTA production pipeline. Every hands-off nightly build would occasionally fail with an unretryable bsdiff4 error.

**Condition to revisit:** bsdiff4 is replaced with a different delta engine (e.g., `zstd --train` dictionary-based diff) that's deterministically non-flaky.

### 8.6 No RK SDK dependency (pet-ota is pure Python)

**Why preserved:** pet-ota never touches rknn/rkllm — it treats the edge artifact as an opaque blob + manifest entry. Keeping the SDK boundary at pet-quantize means pet-ota can run on any runner (CI ubuntu-latest, dev laptop, deployment server) without vendor tooling. Signature verification (§8.3) is the only place pet-quantize is imported, and that import is lazy + soft-fail.

**What would be lost by removing the boundary:** Either pet-ota bloats with SDK installation requirements (CI runner selection becomes fragile), or artifact handling logic duplicates into pet-quantize (violates single-responsibility per repo).

**Condition to revisit:** An on-device OTA agent has to embed quantization-aware logic (e.g., streaming quantize-at-deploy). Not on the current roadmap.

---

## §9 Phase 9+ Follow-ups

1. **`signing-smoke` CI job** — `[signing]` extra is currently exercised only by unit tests that mock pet-quantize. A nightly job that installs `pet-ota[signing]` against the matrix-locked pet-quantize would validate the optional soft path actually works end-to-end (the imports resolve, `verify_package` is callable, a signed tarball passes).

2. **Dual-backend simplification** — `pet_ota.backend.LocalBackend` and `pet_ota.plugins.backends.LocalBackendPlugin` coexist for good reasons (§8.1), but they share `shutil.copy2` + path-manipulation code. Extract a shared `_atomic_copy_artifacts(card, dest_root)` helper into `packaging/` and consume from both.

3. **`release/check_gate.py` threshold docs** — `params.release.min_dpo_pairs` (500) and `min_days_since_last_release` (7) are now configurable but have no business-rationale documentation. Record the "why these numbers" (release cadence calculations / minimum DPO coverage justification) in a PRD doc so future tuning isn't blind.

4. **`check_update_rate` polling vs pushing** — currently monitoring is poll-based with a 30-second interval configured in `params.monitoring`. For faster rollback response on critical failures, a push-based model (device ACK → backend → monitor) would reduce latency by 30 sec worst-case. Non-trivial refactor; only worth it if real incidents point at the delay.

5. **`canary_rollout` device_simulator injection** — the test path injects a `device_simulator` callable to fake device ACKs. Production has no such injection; devices are assumed to write their state independently. A documented production-mode contract (what writes `deployments/<id>.json:devices[<device>]`) is missing — today it's implicit in the LocalBackend API.
