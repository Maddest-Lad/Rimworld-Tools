.PHONY: install submodules fix lint format check start

# Setup
install:
	uv sync

submodules:
	git submodule update --init --recursive

fix: install
	uv run black .
	uv run ruff check --fix . --unsafe-fixes

lint:
	uv run ruff check .

format:
	uv run black --check .

check: lint format

start:
	uv run src/main.py
