.PHONY: help install bootstrap test check fix start config

MCP := rimworld-mcp

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install the MCP server's dependencies (uv sync)
	$(MAKE) -C $(MCP) install

bootstrap: install  ## Link RimWorld folders into links/ and write .mcp.json
	uv run --project $(MCP) python bootstrap.py $(ARGS)

test:  ## Run the MCP server tests and the log-parser tests
	$(MAKE) -C $(MCP) test
	uv run --project $(MCP) pytest .claude/skills/rimworld-log-debug/scripts/tests

check:  ## Lint + format checks
	$(MAKE) -C $(MCP) check

fix:  ## Auto-format and auto-fix lint
	$(MAKE) -C $(MCP) fix

start:  ## Run the MCP server over stdio
	$(MAKE) -C $(MCP) start

config:  ## Print MCP registration snippets
	$(MAKE) -C $(MCP) config
