# Textures, sounds, translations

Verified against `Verse.ModContentLoader`, `Graphic_*`, `ApparelGraphicRecordGetter`,
`LoadedLanguage` in 1.6.4871.

## Textures

- Formats: `.png` (normal), `.jpg/.jpeg`, `.psd`, `.dds` (a `.dds` with the same name wins —
  pre-compressed, faster loading; generate with a tool such as Texconv if the mod is large).
- Paths: `Textures/MyMod/Things/Item/Sword.png` is referenced as `MyMod/Things/Item/Sword` —
  no `Textures/`, no extension, forward slashes. Always put art under your own subfolder so paths
  never collide with vanilla or other mods (same path = one hides the other).
- Size: multiples of 4 (else `Texture … not multiples of 4` and no GPU compression), ideally
  powers of two. Vanilla items ≈ 64 px per cell, newer DLC/mods 128 px per cell.
  `graphicData/drawSize` (cells, e.g. `(2,2)`) sets on-map size independent of pixels.
- Style: items/buildings get a dark outline (~2 px per 64 px); plants usually a green one.

### graphicClass → files

| `graphicClass` | `texPath` points to | Files |
|---|---|---|
| `Graphic_Single` | a file | `Sword.png` (+ mask `Sword_m.png`) |
| `Graphic_Multi` | a file prefix | `Bed_north.png`, `Bed_east.png`, `Bed_south.png`, optional `Bed_west.png` (else east is mirrored); masks `Bed_northm.png` … (note: no underscore before `m`) |
| `Graphic_StackCount` | a **folder** | images sorted by name = stack sizes low → high (`Steel_a.png`, `Steel_b.png`, `Steel_c.png`) |
| `Graphic_Random` | a folder | one image picked per thing |
| `Graphic_Appearances` | a folder | per stuff appearance (`_Planks`, `_Bricks`, `_Smooth`) |
| `Graphic_Linked` / `Graphic_LinkedCornerFiller` | a file | atlas for walls/conduits (`linkType`, `linkFlags`) |
| `Graphic_Flicker`, `Graphic_Cluster`, `Graphic_Indexed`, `Graphic_Mote`… | see a vanilla user: `def_lookup.py --xpath 'Defs/ThingDef[graphicData/graphicClass="Graphic_Cluster"]'` | |

Masks: shader must support them (`shaderType` `CutoutComplex`); red channel = primary colour
(stuff/`colorOne`), green = secondary (`colorTwo`), black = uncoloured.

### Apparel and pawns

- `apparel/wornGraphicPath` + `_<BodyType>_<dir>`: `Things/Pawn/Humanlike/Apparel/MyCoat/MyCoat`
  → `MyCoat_Male_south.png`, `MyCoat_Female_east.png`… for body types `Male`, `Female`, `Thin`,
  `Hulk`, `Fat` (Biotech: `Baby`, `Child` if children can wear it). Headgear/overhead, eye cover
  and packs use **no** body-type suffix: `MyHat_north.png` etc. Plus a ground texture via
  `graphicData`.
- Body/head/hair/beard/tattoo graphics come from their defs (`BodyTypeDef`, `HeadTypeDef`,
  `HairDef`…) with `_north/_east/_south`. Pawn rendering is the render-node tree
  (`PawnRenderTreeDef`, `PawnRenderNodeProperties` in genes/hediffs/apparel) — copy a vanilla
  gene or hediff that draws something (`def_lookup.py --uses renderNodeProperties`).
- Genes: `iconPath` (UI icon), graphics through `renderNodeProperties` or hair/skin/body fields.

## Sounds

- Formats: `.ogg` (preferred), `.wav`, `.mp3` (also tracker formats). Files under
  `Sounds/MyMod/...`, referenced by folder/file path without extension in a `SoundDef`:

```xml
<SoundDef>
  <defName>MyMod_Zap</defName>
  <context>MapOnly</context>
  <maxSimultaneous>2</maxSimultaneous>
  <subSounds>
    <li>
      <grains><li Class="AudioGrain_Folder"><clipFolderPath>MyMod/Zap</clipFolderPath></li></grains>
      <volumeRange>30~40</volumeRange>
      <pitchRange>0.9~1.1</pitchRange>
    </li>
  </subSounds>
</SoundDef>
```
`AudioGrain_Clip` + `clipPath` for a single file. Sustainers (looping, e.g. ambient) need
`<sustain>true</sustain>`; copy a vanilla one (`def_lookup.py --uses sustain --type SoundDef`).

## Languages

```
Languages/English/Keyed/MyMod_Keys.xml
Languages/English/DefInjected/ThingDef/MyMod_Weapons.xml
Languages/English/Strings/Names/MyMod_Names.txt
Languages/<Language (Native)>/...     e.g. "German (Deutsch)", "ChineseSimplified (简体中文)"
```

- **Keyed** (C# UI strings): `<LanguageData><MyMod_Hello>Hello {0}</MyMod_Hello></LanguageData>`;
  used as `"MyMod_Hello".Translate(name)` or with named args `{PAWN_nameDef}` +
  `pawn.Named("PAWN")`. Always prefix keys; missing keys show the raw key (garbled in dev mode).
- **DefInjected** (translate def text in *other* languages; English lives in the def itself):
  `<LanguageData><MyMod_Sword.label>épée</MyMod_Sword.label><MyMod_Sword.tools.head.label>tête</MyMod_Sword.tools.head.label></LanguageData>`
  — `defName.field.path`, list items by index or by their `label`/handle. Folder = def type.
- **Strings**: plain `.txt` word lists for name/grammar generation.
- Dev mode → debug actions → *Translation* tools can dump a translation report for a language.
