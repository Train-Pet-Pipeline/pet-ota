# Changelog

All notable changes to pet-ota are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.1.0-rc1 — 2026-04-22

Phase 4 W1 (OTA backends slice). Release candidate for pet-ota 2.1.0.

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
