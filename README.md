# RimWorld Tools

A workspace for building, curating and debugging RimWorld modpacks on Windows 10 LTSC with
Claude Code. It bundles:

| Part | What it is |
|---|---|
| [`rimworld-mcp/`](rimworld-mcp/README.md) | MCP server: Workshop search/subscriptions via the Steam client, mod inventory, advisories, load-order sorting, modlist snapshots |
| `.claude/skills/rimworld-modpack/` | Skill: workflow for building and maintaining a modpack with those tools |
| `.claude/skills/rimworld-log-debug/` | Skill + `parse_log.py`: triage RimWorld `Player.log` errors, even when the log is huge |
| `bootstrap.py` | Discovers the game and creates `links/` junctions plus `.mcp.json` |
| `links/` | Junctions to the game, Mods, Workshop, Config, Saves and log folders (local, gitignored) |

## Setup

Requires 64-bit Python 3.12+, [uv](https://docs.astral.sh/uv/), GNU make and the Steam edition
of RimWorld.

```sh
make install     # uv sync inside rimworld-mcp/
make bootstrap   # discover RimWorld, create links/, write .mcp.json, sync community databases
```

`make bootstrap ARGS="--dry-run"` shows what would be created. Add `--symlinks` to use
symbolic links instead of junctions (needs Developer Mode or elevation), `--force` to replace
links that point elsewhere, and `--no-db-sync` to skip the community database download.

Open Claude Code in this directory: `.mcp.json` attaches the `rimworld-tools` server automatically
and `CLAUDE.md` describes what is available. Restart the client after changing server code.

## Development

```sh
make test    # server tests + log parser tests
make check   # ruff + black
make start   # run the server over stdio
make config  # print registration snippets for other MCP clients
```

See [`rimworld-mcp/AGENTS.md`](rimworld-mcp/AGENTS.md) for server architecture and rules.
