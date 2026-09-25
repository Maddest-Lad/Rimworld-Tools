# RimWorld Tools workspace

Modpack building and debugging for RimWorld 1.6 (Steam edition, Windows 10 LTSC). The MCP server
`rimworld-tools` is attached through `.mcp.json`; its source lives in `rimworld-mcp/` and has its
own `CLAUDE.md` — read `rimworld-mcp/AGENTS.md` only when changing server code.

## Where things are

`links/` holds directory junctions created by `make bootstrap` (rerun it if one is missing; see
`links/README.md` for the resolved targets).

| Link | Contents |
|---|---|
| `links/game` | RimWorld install (`Version.txt`, `Data/` for Core + DLC defs, `RimWorldWin64_Data/`) |
| `links/mods` | Local `Mods/` folder (non-Workshop copies) |
| `links/workshop` | Steam Workshop content `294100/<pfid>/` — never modify; Steam owns it |
| `links/config` | `ModsConfig.xml` (active list), `Prefs.xml`, per-mod `Mod_<pfid>_*.xml` settings |
| `links/saves` | Save games (`*.rws`) |
| `links/logs` | `Player.log` (current run), `Player-prev.log`, `HugsLib/` |
| `links/steam` | Steam root (`steamapps/`, `config/libraryfolders.vdf`) |

Player.log can be hundreds of MB. Never `Read` it directly; use the log-debug skill's parser.

## MCP tools (`rimworld-tools`)

| Tool | Purpose |
|---|---|
| `environment_status` | Game discovery + Steam readiness; call first |
| `workshop_search`, `workshop_mod_info` | Find mods, read metadata/descriptions |
| `resolve_workshop_url`, `collection_expand` | Resolve pasted links, list collection members |
| `workshop_subscribe`, `workshop_unsubscribe` | Change the signed-in account's subscriptions (≤50 ids) |
| `check_mod_updates` | Live subscription / install / download state |
| `list_installed_mods` | Everything on disk: packageId, name, source, pfid, `version_ok`, `active`, advisories |
| `modlist_enable`, `modlist_disable` | Activate/deactivate installed mods by packageId or pfid (dry run by default) |
| `sort_modlist`, `diagnose_cycles` | Sort the active list (dry run by default) or explain cycles/missing deps |
| `modlist_snapshot`, `modlist_diff` | Snapshot the active list and compare |

Subscribing does not activate a mod; `modlist_enable` does (or the user, in-game).
`modlist_enable`, `modlist_disable` and `sort_modlist` with `dry_run=False` are the only
sanctioned writers of `ModsConfig.xml` (each snapshots first and refuses while the game runs).
Enabled mods land at the end of the load order — sort afterwards. Success from
`workshop_subscribe` means subscribed, not downloaded — poll `check_mod_updates` before
inventorying, enabling or sorting new mods.

## Notes (`notes/`)

Pack-specific knowledge the tools cannot know: `accepted.md` (warnings that are known-fine),
`mods.md` (why a mod is here, quirks), `decisions.md` (history). **Check `accepted.md` before
reporting any advisory, dependency issue, unresolved id or log error**; when the user says a
warning is fine or explains a choice, record it there in the same turn. Convention in
`notes/README.md`.

## Skills

- `/rimworld-modpack` — build, extend, vet and sort a modpack end to end.
- `/rimworld-log-debug` — triage `Player.log` errors and attribute them to mods.
- `/rimworld-mod-dev` — author, patch, port and debug 1.6 mods (XML + C#); offline patch dry-runs,
  def lookup and decompiled-source lookup. Mods under development live in `workspace/<Mod>`.
- `/rimworld-svg-art` — hand-write RimWorld-style art as SVG and render game-ready PNGs; vanilla
  texture extraction/measurement and in-game-scale previews.

## Rules

- Never open, read or print `.env` files anywhere in this workspace (only `.env-template`).
- Never edit Steam manifests or anything under `links/workshop` or `links/steam`.
- Do not hand-edit `ModsConfig.xml`; go through `modlist_enable` / `modlist_disable` / `sort_modlist` / snapshots.
- Mutating tools (subscribe/unsubscribe, enable/disable/sort writes) need the user's go-ahead for their list.
- `make test` / `make check` at the root cover the server, the log parser, the mod-dev and svg-art scripts.
