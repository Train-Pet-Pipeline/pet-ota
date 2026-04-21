# pet-ota Phase 3B v1 Purge Audit

Generated 2026-04-22 before P4-A deletion commit.

## Delete (legacy orchestration subsumed by LocalBackendPlugin)

| Path | Reason |
| --- | --- |
| `src/pet_ota/packaging/create_deployment.py` | Thin wrapper over `OTABackend.create_deployment()`; call sites in `canary_rollout.py` are inlined directly onto `backend.create_deployment()` instead. `LocalBackendPlugin.run()` (arriving in P4-C) will own the equivalent manifest + artifact copy workflow end-to-end. |
| `tests/test_create_deployment.py` | Follows deleted module. |

## Not deleted (reason: absent)

- `src/pet_ota/cli.py` — never existed
- `src/pet_ota/__main__.py` — never existed
- wandb imports / dep — never introduced

## Preserve

| Path | Reason |
| --- | --- |
| `src/pet_ota/backend/{base,local}.py` | `OTABackend` Protocol + `LocalBackend` impl; reused by `LocalBackendPlugin` in P4-C |
| `src/pet_ota/packaging/{make_delta,upload_artifact}.py` | bsdiff4 wrapper + artifact upload; reused by plugin |
| `src/pet_ota/release/{canary_rollout,check_gate,rollback}.py` | release-phase orchestration (rollout / gate / rollback) — Phase 3B keeps these as library APIs |
| `src/pet_ota/monitoring/{alert,check_update_rate}.py` | operational monitoring — out of Phase 3B scope |
| `src/pet_ota/config.py` | config plumbing — may need adjustments in P4-B/C, preserve for now |

## Next tasks

- P4-B: `plugins/` skeleton + `_register.py` + pyproject entry-point
- P4-C: `LocalBackendPlugin` in `plugins/backends/local.py`; Manifest from ModelCard
- P4-D: release v2.0.0-rc1 + CI workflows
