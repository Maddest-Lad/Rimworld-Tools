# About.xml and ModsConfig.xml fields that matter for curation

## `About/About.xml` (per mod; parsed by `list_installed_mods`)

| Field | Meaning | Curation use |
|---|---|---|
| `packageId` | `author.modname`, case-insensitive | identity; duplicates across local/Steam copies are normal |
| `name` | display name | tie-breaking in sort; DLC omit it (server fills from `DLC_NAMES`) |
| `supportedVersions` | list of `major.minor` | `version_ok`; normalised at parse time |
| `modDependencies` | packageId + `steamWorkshopUrl` (`workshopUrl` accepted as alias) | `missing_dependency` advisory; a dependency implies `loadAfter` |
| `loadAfter` / `loadBefore` | soft order hints | edges with source `about:<pid>` |
| `forceLoadAfter` / `forceLoadBefore` | always appended, even with a `*ByVersion` block | same |
| `incompatibleWith` | packageIds that must not be active together | `diagnose_cycles` reports active pairs |
| `*ByVersion` (`modDependenciesByVersion`, `loadAfterByVersion`, …) | per-version blocks | **replace** the base list when the game version matches; an empty block means none |
| `descriptionsByVersion`, `description` | text | DLC / framework hints when metadata is silent |
| `MayRequire="ludeon.rimworld.biotech"` (attribute on defs/patches, not About) | content gated on a DLC or mod | explains why a mod is inert without the DLC |

Parse pitfalls the server already handles: stray `&` / `<` in descriptions, missing `<name>` on
DLC, Workshop items shipping a stray `.git` directory (classification checks
`PublishedFileId.txt` first).

## `Config/ModsConfig.xml` (`links/config/ModsConfig.xml`)

```xml
<ModsConfigData>
  <version>1.6.4871 rev590</version>
  <activeMods>
    <li>ludeon.rimworld</li>
    <li>brrainz.harmony_steam</li>
    ...
  </activeMods>
  <knownExpansions>
    <li>ludeon.rimworld.royalty</li>
  </knownExpansions>
</ModsConfigData>
```

- `activeMods` order **is** the load order.
- The `_steam` suffix means "use the Workshop copy" when a local copy shares the packageId; the
  server preserves it on write.
- Ids that resolve to no installed mod are kept at the end by `sort_modlist`, never dropped —
  they usually mean an unsubscribed or not-yet-downloaded mod.
- Read it to inspect; write it only through `sort_modlist(dry_run=False)`.

## Per-mod settings

`links/config/Mod_<pfid>_<Class>.xml` — a mod's saved settings. Safe to read when diagnosing;
deleting one resets that mod to defaults (ask first).
