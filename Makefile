.PHONY: help install bootstrap art-refs test check fix start config

MCP := rimworld-mcp

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install the MCP server's dependencies (uv sync)
	"$(MAKE)" -C $(MCP) install

bootstrap: install  ## Link RimWorld folders into links/ and write .mcp.json
	uv run --project $(MCP) python bootstrap.py $(ARGS)

art-refs:  ## Build the svg-art skill's vanilla reference sprite sheets (local only, gitignored)
	uv run .claude/skills/rimworld-svg-art/scripts/build_assets.py $(ARGS)

test:  ## Run the MCP server tests, the log-parser, mod-dev and svg-art script tests
	"$(MAKE)" -C $(MCP) test
	uv run --project $(MCP) pytest .claude/skills/rimworld-log-debug/scripts/tests
	uv run --project $(MCP) pytest .claude/skills/rimworld-mod-dev/scripts/tests
	uv run --no-project --python 3.12 --with pytest --with numpy --with Pillow --with resvg-py 		pytest .claude/skills/rimworld-svg-art/scripts/tests

check:  ## Lint + format checks
	"$(MAKE)" -C $(MCP) check
	uv run --project $(MCP) ruff check --config $(MCP)/pyproject.toml .claude/skills/rimworld-mod-dev/scripts
	uv run --project $(MCP) black --check -l 100 -q .claude/skills/rimworld-mod-dev/scripts
	uv run --project $(MCP) ruff check --config $(MCP)/pyproject.toml .claude/skills/rimworld-svg-art/scripts
	uv run --project $(MCP) black --check -l 100 -q .claude/skills/rimworld-svg-art/scripts

fix:  ## Auto-format and auto-fix lint
	"$(MAKE)" -C $(MCP) fix

start:  ## Run the MCP server over stdio
	"$(MAKE)" -C $(MCP) start

config:  ## Print MCP registration snippets
	"$(MAKE)" -C $(MCP) config
