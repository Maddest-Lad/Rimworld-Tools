# Add-a-mod checklist

Run for every candidate before `workshop_subscribe`. Sources: `workshop_mod_info` (pre-install),
`list_installed_mods(detail=True)` (post-install), community DB advisories on both.

| Check | How | If it fails |
|---|---|---|
| Targets the installed version | Workshop tags include the game `major.minor`; after install `version_ok` is true | Skip unless the No Version Warning DB suppresses it or the user accepts the risk |
| Still maintained | `time_updated` recent; no `replaced` advisory | Prefer the Use This Instead replacement (`replaced.action`) |
| Not blacklisted | No `blacklisted` advisory | Report the community comment; do not subscribe |
| Dependencies present | `modDependencies` / `missing_dependency` advisory | Subscribe the dependency first (advisory carries the ids) |
| Framework prerequisites | See `frameworks.md` | Add the framework in the same batch, before the content mod |
| DLC requirements | `modDependencies` / description mentions a DLC; compare with `list_installed_mods(source="ludeon")` | Warn; the mod will error or be inert |
| No incompatibility with active list | `incompatibleWith` (About.xml) vs active packageIds; `diagnose_cycles()` after install | Ask the user which one to keep |
| No duplicate packageId | `list_installed_mods` shows one entry per packageId per source | Keep the `_steam` selection; never delete the other copy |
| Fits the pack's budget | Texture-heavy packs and 200+ lists cost RAM and load time | Mention it; suggest Performance Optimizer / RocketMan for big lists |
| Lookup failed | `workshop_mod_info` per-item `failed[]` reason | Report the reason; do not assume unpublished |
