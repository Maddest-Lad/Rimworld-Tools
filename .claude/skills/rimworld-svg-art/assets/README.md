# Reference sprite sheets (generated, not in git)

Ready-made contact sheets of vanilla RimWorld sprites, so you can look at the art without
extracting anything. Everything here except this README is generated from the local game
install and gitignored: it is Ludeon's copyrighted art, and the repo is public. Look at it,
measure it; never copy, trace or ship it.

**Missing or stale (after a game update)?** From the repo root:

```sh
make art-refs          # = uv run .claude/skills/rimworld-svg-art/scripts/build_assets.py (~30 s)
make art-refs ARGS=--force
```

| Path | Contents |
|---|---|
| `INDEX.md` | Start here: every category, its source regex, the sheet files, and the sprite names on each sheet in reading order |
| `sheets/<category>_<n>.png` | 8 × 6 labelled sprites per sheet, native size up to 128 px (`*` = bigger, scaled down), neutral ground |
| `detail/<category>.png` | 4 sprites of the category at 3×, nearest-neighbour: outline, anti-aliasing and shading at pixel level |
| `stats.md` / `stats.json` | `analyze.py` p10 / median / p90 per category (outline, edge ratio, value, saturation, contrast, coverage, margin) and common canvas sizes |

31 categories: ranged/melee/DLC weapons, resources, drugs, meals, misc items, furniture (+
rotations, + masks), production, misc and DLC buildings, worn apparel (+ one garment across all
body types, + DLC), bodies, heads, hair/beards, animals (+ DLC), mechanoids, anomaly entities,
plants, gene icons, commands, designators, abilities, UI icons, memes/ideology icons, terrain.

Need something not covered: `vanilla_tex.py --search/--extract REGEX`, or add a row to
`CATEGORIES` in `scripts/build_assets.py`.

## Mod reference sheets (`mods/`)

Use these when matching another mod's style rather than vanilla. They are built from installed
mods by `scripts/build_mod_refs.py`, in the same sheet/detail format, with `mods/INDEX.md` and
`mods/index.json` (including `analyze.py` stats per set). They are gitignored like the rest:
other authors' art, for study only.

Built so far (2026-09-25, for Barn Expanded), rebuildable with:

```sh
S=.claude/skills/rimworld-svg-art/scripts
uv run $S/build_mod_refs.py --name mo_furniture --mod 3219596926 --regex '^Textures/Things/Building/Furniture/[^/]*_south\.png$'
uv run $S/build_mod_refs.py --name mo_beds_rotations --mod 3219596926 --regex '^Textures/Things/Building/Furniture/Bed(Straw|Wicker|Fur)(Double)?_(north|east|south)\.png$'
uv run $S/build_mod_refs.py --name mo_storage --mod 3219596926 --regex '^Textures/Things/Building/Storage/' --cap 144
uv run $S/build_mod_refs.py --name mo_asf_storage --mod 3425601715 --regex '^Textures/Things/Building/Storage/' --cap 144
uv run $S/build_mod_refs.py --name mo_production --mod 3219596926 --regex '^Textures/(Production|Things/Building/Production)/.*(south|Hay|Filled).*\.png$'
```

Medieval Overhaul in numbers: 128 px per cell; a 2.5-unit (5 px) rounded black outline; light plank
rims with grey corner rivets; open containers have a dark interior (#949494 fading to #626262) and a
slatted front face; straw is #ceaa64 / #b29259 with #53452d lines. MO: Adaptive Storage draws each
container's front as a separate `…Layer` texture above the contents, so stored items appear inside.
