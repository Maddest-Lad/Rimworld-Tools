# Sources (researched 2026-09-25; 1.7 pipeline 2026-10-12)

1. **The installed game, 1.7.4976** (`links/game`).
   - Textures: Core from `Assets.zip` (`Resources/Textures/…`), DLC from
     `Data/<DLC>/Assets.zip` (`Textures/…`) — zstd-compressed BC7 DDS listed by each pack's
     `textures.info`, deduplicated entries resolved through `bake.manifest`. 8,781 textures
     indexed by `vanilla_tex.py` (Core 3,455, Odyssey 1,677, Biotech 1,122, Ideology 1,014,
     Anomaly 991, Royalty 522). ~1,000 studied: ranged/melee weapons, resources, drugs, meals,
     furniture, production buildings, worn apparel, bodies, heads, hair, animals, mechanoids,
     plants, gene icons, commands, designators, UI icons — contact sheets, 3–6× zooms and
     `analyze.py --summary` per folder. The numbers in `style.md` were measured on the 1.6
     extraction of the same sprites; 1.7 decodes match it (same size and orientation, opaque
     pixels within ~2–3 levels — compression noise).
   - Loader, compression and camera behaviour from the decompiled `Assembly-CSharp.dll` and the
     Waylith/UnityStubs assemblies (`rimworld-mod-dev/scripts/decompile.py`):
     `Verse.ModContentLoader` (mipmaps, power-of-two clamp, trilinear), RimWorld's
     `ConfigureTextureCompression` (BC7, ≤16 px raw, `TextureCache`), `GraphicData`
     (`textureRepeats`, `borderMipMaps`), `ModAssetPacks` (upload bake), `CameraDriver.StartingSize`,
     `CameraMapConfig.sizeRange`, `Gizmo.Height`. Tint/mask maths from the shipped GLSL
     (`Data/Core/Shaders/Map/Cutout*.frag.glsl`, `MaskGate.glsl`).
   - Defs via `def_lookup.py`: drawSize of beds, benches, weapons, apparel, animals;
     `stuffProps/color` of vanilla materials (the `render.py` `STUFF` table, re-checked on
     1.7.4976); ShaderTypeDefs/ShaderDefs.
2. **Validation by construction:** each template in `templates/` was rendered, previewed next
   to vanilla sprites at the three zooms and checked with `analyze.py --against` the vanilla
   category until every measure sat inside the vanilla p10–p90 range (crate outline: matches
   production buildings, 1 px heavier than furniture p90 — noted in SKILL.md).
3. **Tools:** resvg (via `resvg-py`, `svg_to_bytes`) — rendering of `href`, `paint-order`,
   `feTurbulence`, clip paths verified by test renders; `zstandard` + Pillow's DDS decoder (BC7,
   BC4, RGBA) for the asset packs.

Ludeon's textures are copyrighted game assets: the extraction cache
(`.claude/skills/rimworld-svg-art/.cache/`) is gitignored, used for study and measurement only,
never copied, traced or shipped with a mod. Using a vanilla body as a positioning underlay
while fitting apparel (then deleting it) is fine; the output must be your own drawing.

## Round 2 (2026-09-25, from the Barn Expanded work)

- `geometry.md` verified in the decompiled code (unchanged in 1.7.4976): `MaterialAtlasPool`
  (4×4, offset 1/32, scale 0.1875), `Graphic_Linked.LinkedDrawMatFrom` +
  `GenAdj.CardinalDirections` (N,E,S,W bits), `Graphic_LinkedAsymmetric`,
  `Building_Door.DrawMovers` (plane10 + plane10Flip, 0.45×open), `Building_MultiTileDoor`
  (scale 0.5×1, 0.25 + 0.35×open), `Building_SupportedDoor` altitudes, `Graphic.MeshAt`
  (drawSize swap), `Graphic_Multi.Init` (side fallbacks). Door leaf placement measured on vanilla
  `DoorSimple_Mover` / `FenceGate_Mover_*` (leaf at x 0–34 of 64).
- Terrain scale: vanilla surfaces are 1024 px; `GenericFloorTile` has 16×16 tiles (one per
  cell) → 64 px/cell. The UV mapping is in the terrain shaders (`TerrainHard`/`TerrainFade`
  ShaderDefs, `MapWorldUV.vert.glsl`).
- Containers/fills, "consistency across a set" and "common rejections": generalised from user
  feedback on a storage/barn mod (rounds 1–3) and storage-mod reference sheets. The mod-specific
  decisions (palettes, straw/kibble recipes, the exact rejected pieces) live in that mod's
  `Art/STYLE.md`, not here.
- Texture replacement: `vanilla_tex.py --overrides` is how to find the user's "vanilla"; at
  research time it reported Vanilla Textures Expanded and Gerrymon's Upscaled Vanilla Textures.
  It sees loose texture files only, not replacements baked into a mod's `Assets.zip`.
