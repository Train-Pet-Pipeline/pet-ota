# pet-ota

OTA delta-update packaging, canary rollout, and rollback for the Train-Pet-Pipeline.

## Prerequisites

pet-ota is a peer-dep consumer: **pet-infra must be installed first** from the current matrix row in `pet-infra/docs/compatibility_matrix.yaml`. Optional `[signing]` extras add pet-quantize so `upload_artifact` can verify package signatures; signing is a soft path — a missing pet-quantize degrades to a warning, not a hard fail.

For local dev in the shared `pet-pipeline` conda env:

```bash
conda activate pet-pipeline

# 1. Install pet-infra peer-dep (current matrix row)
pip install 'pet-infra @ git+https://github.com/Train-Pet-Pipeline/pet-infra@v2.6.0'

# 2. Editable install
make setup   # → pip install -e ".[dev]"
make test    # → PET_ALLOW_MISSING_SDK=1 pytest tests/ -v
make lint    # → ruff check src/ tests/ && mypy src/
```

## Architecture

See `docs/architecture.md` for the full module map. Two backend surfaces coexist:

- **`pet_ota.plugins.backends.*`** — OTA registry plugins (`local_backend` / `s3_backend` / `http_backend`) consumed by the pet-infra orchestrator for artifact publishing.
- **`pet_ota.backend.*`** — stateful deployment backend (`LocalBackend`) driving the canary rollout state machine in `pet_ota.release.canary_rollout`.

Responsibilities are non-overlapping; see `docs/architecture.md` §8.1.

## Plugin entry point

pet-ota registers 3 OTA backends under the `pet_infra.plugins` entry point:

```python
from pet_ota.plugins._register import register_all
from pet_infra.registry import OTA

register_all()
print(sorted(OTA.module_dict))  # ['http_backend', 'local_backend', 's3_backend']
```

## Canary rollout

`pet_ota.release.canary_rollout.canary_rollout` runs the 5-state machine:

```
GATE_CHECK → CANARY_DEPLOYING → CANARY_OBSERVING → FULL_DEPLOYING → DONE
                                         ↓
                                    ROLLING_BACK → ROLLED_BACK
```

With resume-from-state on crash: if a `deployments/<id>.json` exists with a resumable status, the orchestrator picks up from that state instead of re-deploying. See `docs/architecture.md` §4 / §8.2.

## License

This project is licensed under the [Business Source License 1.1](LICENSE) (BSL 1.1).
On **2030-04-22** it converts automatically to the Apache License, Version 2.0.

> Note: BSL 1.1 is **source-available**, not OSI-approved open source.
> Production / commercial use requires a separate commercial license.

![License: BSL 1.1](https://img.shields.io/badge/license-BSL%201.1-blue.svg)
