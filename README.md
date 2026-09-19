# Rimworld Tools

Tools for interacting with, debugging and modding RimWorld.

Planned:
- A RimWorld-specific SteamCMD MCP server
- A Claude Skill for driving SteamCMD directly, for cases the MCP server doesn't cover
- Integration with [RimSort](https://github.com/RimSort/RimSort) (vendored as a submodule under `modules/RimSort`) for mod sorting/metadata logic

## Setup

```sh
make submodules  # init/update the RimSort submodule
make install      # uv sync
```

## Usage

```sh
make start   # run the app
make lint    # ruff check
make format  # black --check
make fix     # auto-fix lint + format
```
