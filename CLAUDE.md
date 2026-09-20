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
| `list_installed_mods` | Everything on disk: packageId, name, source, pfid, `version_ok`, advisories |
| `sort_modlist`, `diagnose_cycles` | Sort the active list (dry run by default) or explain cycles/missing deps |
| `modlist_snapshot`, `modlist_diff` | Snapshot the active list and compare |

Subscribing does not activate a mod; the user enables it in-game. `sort_modlist(dry_run=False)`
is the only sanctioned writer of `ModsConfig.xml` (it snapshots first and refuses while the game
runs). Success from `workshop_subscribe` means subscribed, not downloaded — poll
`check_mod_updates` before inventorying or sorting new mods.

## Skills

- `/rimworld-modpack` — build, extend, vet and sort a modpack end to end.
- `/rimworld-log-debug` — triage `Player.log` errors and attribute them to mods.

## Rules

- Never open, read or print `.env` files anywhere in this workspace (only `.env-template`).
- Never edit Steam manifests or anything under `links/workshop` or `links/steam`.
- Do not hand-edit `ModsConfig.xml`; go through `sort_modlist` / snapshots.
- Mutating tools (subscribe/unsubscribe/sort write) need the user's go-ahead for their list.
- `make test` / `make check` at the root cover the server and the log parser.
