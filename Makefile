.PHONY: check test lint format build

check: lint test

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

format:
	uv run --locked ruff format .

build:
	uv build
