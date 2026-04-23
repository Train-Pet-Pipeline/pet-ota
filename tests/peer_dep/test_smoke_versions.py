"""Phase 4 P2-A-1: smoke test that pet-ota sees the right pet-infra version
and that pet-infra's storage backends from Phase 4 are reachable via the
shared STORAGE registry."""


def test_pet_infra_version() -> None:
    """pet-infra package resolves to a v2 release.

    Uses importlib.metadata so the check reflects the installed package
    version from pyproject.toml rather than the __version__ attribute in
    __init__.py (which may lag a patch cycle).

    The precise matrix row is pinned by the CI workflows
    (.github/workflows/{ci,peer-dep-smoke}.yml step-4 asserts the current
    minor series). This test intentionally stays broad to major-2 so
    non-CI dev environments can run it without requiring an exact matrix
    row reinstall on every bump.
    """
    import importlib.metadata

    version = importlib.metadata.version("pet-infra")
    assert version.startswith("2."), version


def test_storage_registry_has_phase4_backends() -> None:
    """The STORAGE registry exposes file/local/s3/http after pet-infra import.

    Phase 4 P1-A (S3) + P1-B (HTTP) + P1-E (file alias) plugins must be
    importable so pet-ota's S3/HTTP backends (P2-A-2/P2-A-3) can use them.
    """
    from pet_infra._register import register_all
    from pet_infra.registry import STORAGE

    register_all()
    names = set(STORAGE.module_dict)
    missing = {"local", "file", "s3", "http"} - names
    assert not missing, f"missing storage backends: {missing!r}; got {names!r}"
