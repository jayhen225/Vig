.PHONY: install lint format test run web web-install web-build clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	mypy parlay

format:
	ruff format .

test:
	pytest

run:                 ## API backend on :8000 (serves frontend/dist in prod)
	uvicorn parlay.api.main:app --reload --port 8000

web-install:         ## one-time: install frontend deps
	cd frontend && npm install

web:                 ## frontend dev server on :5173 (proxies /api -> :8000)
	cd frontend && npm run dev

web-build:           ## build frontend to frontend/dist (then `make run` serves it)
	cd frontend && npm run build

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
