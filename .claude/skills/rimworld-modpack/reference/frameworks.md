# Load-order tiers and framework mods

`sort_modlist` partitions the active list into four tiers, topologically sorts each tier alone,
and concatenates. The tier sets are the constants in
`rimworld-mcp/src/rimworld_tools/sorting.py` (`TIER_ZERO`, `TIER_ONE`) plus community rules.

| Tier | Members | Also absorbs |
|---|---|---|
| 0 | `zetrith.prepatcher`, `brrainz.harmony`, `brrainz.visualexceptions`, Core and every DLC | their transitive dependencies |
| 1 | Known frameworks (`TIER_ONE`) and community `loadTop` mods | their transitive dependencies |
| 2 | Everything else | — |
| 3 | Community `loadBottom` mods | their transitive dependants |

Ties inside a topological level break on lowercased display name. Edge sources are
`about:<packageId>`, `community`, `user`, unioned — a user rule never overrides a lower layer, it
only adds; `removeLoadAfter` / `removeLoadBefore` in `userRules.json` is how an edge is dropped.

## Frameworks other mods depend on

| Mod | packageId | Needed by |
|---|---|---|
| Harmony | `brrainz.harmony` | almost every C# mod |
| Prepatcher | `zetrith.prepatcher` | mods that add fields to vanilla types (Multiplayer, some performance mods) |
| HugsLib | `unlimitedhugs.hugslib` | older mods with settings/update news |
| Vanilla Expanded Framework | `oskarpotocki.vanillafactionsexpanded.core` | every Vanilla ... Expanded mod |
| XML Extensions | `imranfish.xmlextensions` | XML-only mods with settings or conditional patches |
| Vehicle Framework | `smashphil.vehicleframework` | vehicle mods |
| Adaptive Storage Framework | `adaptive.storage.framework` | storage building mods |
| EBSG Framework | `ebsg.framework` | many gene/xenotype mods |
| Fishery / Performance Fish | `bs.fishery` | Performance Fish and related |
| Cherry Picker | `owlchemist.cherrypicker` | removing individual defs from other mods |

Framework packageIds not listed in `TIER_ONE` still sort correctly when their dependants declare
them in `modDependencies` / `loadAfter`; the tier just guarantees an early position.

## DLC packageIds

| DLC | packageId | Steam AppID |
|---|---|---|
| Core | `ludeon.rimworld` | 294100 |
| Royalty | `ludeon.rimworld.royalty` | 1149640 |
| Ideology | `ludeon.rimworld.ideology` | 1392840 |
| Biotech | `ludeon.rimworld.biotech` | 1826140 |
| Anomaly | `ludeon.rimworld.anomaly` | 2380740 |
| Odyssey (1.6) | `ludeon.rimworld.odyssey` | 3022790 |

packageIds are case-insensitive everywhere in the server.
