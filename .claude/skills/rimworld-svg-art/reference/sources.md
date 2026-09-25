# Sources (researched 2026-09-25)

1. **The installed game, 1.6.4871** (`links/game`).
   - Textures: Core from `RimWorldWin64_Data/resources.assets` (+ `.resS`), paths from the
     `ResourceManager` container in `globalgamemanagers`; DLC from
     `Data/<DLC>/AssetBundles/resources_<dlc>`. 8,781 textures indexed by `vanilla_tex.py`
     (UnityPy; Core 3,455, Odyssey 1,677, Biotech 1,122, Ideology 1,014, Anomaly 991,
     Royalty 522). ~1,000 studied: ranged/melee weapons, resources, drugs, meals, furniture,
     production buildings, worn apparel, bodies, heads, hair, animals, mechanoids, plants,
     gene icons, commands, designators, UI icons — contact sheets, 3–6× zooms and
     `analyze.py --summary` per folder. All numbers in `style.md` come from these runs.
   - Loader and camera behaviour from the decompiled `Assembly-CSharp.dll`
     (`rimworld-mod-dev/scripts/decompile.py`): `Verse.ModContentLoader` (mipmaps, DXT,
     power-of-two clamp, trilinear), `CameraDriver.StartingSize`, `CameraMapConfig.sizeRange`,
     `Gizmo.Height`.
   - Defs via `def_lookup.py`: drawSize of beds, benches, weapons, apparel, animals;
     `stuffProps/color` of vanilla materials (the `render.py` `STUFF` table); ShaderTypeDefs.
2. **Validation by construction:** each template in `templates/` was rendered, previewed next
   to vanilla sprites at the three zooms and checked with `analyze.py --against` the vanilla
   category until every measure sat inside the vanilla p10–p90 range (crate outline: matches
   production buildings, 1 px heavier than furniture p90 — noted in SKILL.md).
3. **Tools:** resvg (via `resvg-py`, `svg_to_bytes`) — rendering of `href`, `paint-order`,
   `feTurbulence`, clip paths verified by test renders; UnityPy 1.25 for asset reading.

Ludeon's textures are copyrighted game assets: the extraction cache
(`.claude/skills/rimworld-svg-art/.cache/`) is gitignored, used for study and measurement only,
never copied, traced or shipped with a mod. Using a vanilla body as a positioning underlay
while fitting apparel (then deleting it) is fine; the output must be your own drawing.

## Round 2 (2026-09-25, from the Barn Expanded work)

- `geometry.md` verified in the decompiled 1.6.4871 code: `MaterialAtlasPool` (4×4, offset 1/32,
  scale 0.1875), `Graphic_Linked.LinkedDrawMatFrom` + `GenAdj.CardinalDirections` (N,E,S,W bits),
  `Graphic_LinkedAsymmetric`, `Building_Door.DrawMovers` (plane10 + plane10Flip, 0.45×open),
  `Building_MultiTileDoor` (scale 0.5×1, 0.25 + 0.35×open), `Building_SupportedDoor` altitudes,
  `Graphic.MeshAt` (drawSize swap), `Graphic_Multi.Init` (side fallbacks). Door leaf placement
  measured on vanilla `DoorSimple_Mover` / `FenceGate_Mover_*` (leaf at x 0–34 of 64).
- Terrain scale: vanilla surfaces are 1024 px; `GenericFloorTile` has 16×16 tiles (one per
  cell) → 64 px/cell. The UV mapping itself is in the terrain shader (not decompilable here).
- Containers/fills, "consistency across a set" and "common rejections": generalised from user
  feedback on a storage/barn mod (rounds 1–3) and storage-mod reference sheets. The mod-specific
  decisions (palettes, straw/kibble recipes, the exact rejected pieces) live in that mod's
  `Art/STYLE.md`, not here.
- Texture replacement: `vanilla_tex.py --overrides` is how to find the user's "vanilla"; at
  research time it reported Vanilla Textures Expanded and Gerrymon's Upscaled Vanilla Textures.
