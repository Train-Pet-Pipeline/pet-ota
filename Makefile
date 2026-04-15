-include ../pet-infra/shared/Makefile.include

.PHONY: setup test release

setup:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

release:
	python -m pet_ota.release.canary_rollout
