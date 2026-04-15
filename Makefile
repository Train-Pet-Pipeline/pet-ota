.PHONY: setup test lint clean release

setup:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/ && mypy src/

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist/ *.egg-info artifacts/ deployments/

release:
	python -m pet_ota.release.canary_rollout
