.PHONY: check test lint format build check-docs check-package

check: lint test check-docs

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

format:
	uv run --locked ruff format .

build:
	uv build

check-docs:
	uv run --locked python scripts/check_repository.py

check-package:
	uv run --locked python scripts/check_package.py
