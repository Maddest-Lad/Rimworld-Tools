.PHONY: help install submodules fix lint format check test start config

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Sync dependencies
	uv sync

submodules:  ## Init/update the RimSort reference submodule
	git submodule update --init --recursive

fix: install  ## Auto-format and auto-fix lint
	uv run black .
	uv run ruff check --fix . --unsafe-fixes

lint:  ## Check lint
	uv run ruff check .

format:  ## Check formatting
	uv run black --check .

check: lint format  ## Lint + format checks

test:  ## Run the test suite
	uv run pytest

start:  ## Run the MCP server (stdio)
	uv run -m src.rimworld_tools.server

config:  ## Print mcp.json, Claude Code, and Codex MCP configuration snippets
	@powershell -NoProfile -Command "$$cwd = (Get-Location).Path.Replace('\', '/'); Write-Output 'mcp.json:'; Write-Output '{'; Write-Output '  \"mcpServers\": {'; Write-Output '    \"rimworld-tools\": {'; Write-Output '      \"command\": \"uv\",'; Write-Output '      \"args\": [\"run\", \"-m\", \"src.rimworld_tools.server\"],'; Write-Output ('      \"cwd\": \"' + $$cwd + '\"'); Write-Output '    }'; Write-Output '  }'; Write-Output '}'; Write-Output ''; Write-Output 'Claude Code (project scope):'; Write-Output ('claude mcp add rimworld-tools --scope project -- uv --directory \"' + $$cwd + '\" run -m src.rimworld_tools.server'); Write-Output ''; Write-Output 'Codex (.codex/config.toml or ~/.codex/config.toml):'; Write-Output '[mcp_servers.rimworld-tools]'; Write-Output 'command = \"uv\"'; Write-Output 'args = [\"run\", \"-m\", \"src.rimworld_tools.server\"]'; Write-Output ('cwd = \"' + $$cwd + '\"')"
