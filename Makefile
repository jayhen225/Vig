.PHONY: install lint format test run clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	mypy parlay

format:
	ruff format .

test:
	pytest

run:
	uvicorn parlay.api.main:app --reload

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
