# /// script
# requires-python = ">=3.11"
# dependencies = ["UnityPy>=1.20", "Pillow>=10.1", "numpy>=1.26"]
# ///
"""Build the reference sprite sheets in `assets/` from the installed game (one-time, ~1-2 min).

    uv run build_assets.py                 # all categories (skips sheets that already exist)
    uv run build_assets.py --only plants,ui_gene_icons --force
    uv run build_assets.py --list          # category names and their regexes

Per category it writes to `.claude/skills/rimworld-svg-art/assets/`:

- `sheets/<category>_<n>.png`  labelled contact sheets, sprites at native size (up to 128 px;
                                larger ones scaled down, marked with *) on a neutral ground
- `detail/<category>.png`       4 representative sprites at 3x, nearest-neighbour: outline,
                                anti-aliasing and shading at pixel level
- `INDEX.md`                    what each sheet holds (every file name in reading order)
- `stats.md`, `stats.json`      analyze.py p10/median/p90 per category

The folder is gitignored (Ludeon's art, study only — never copy, trace or ship it); only
`assets/README.md` is tracked. Rebuild after a game update with --force.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze
import vanilla_tex as vt

ASSETS = vt.SKILL / "assets"
MASK = r"(_m|(north|east|south|west)m)$"
DLC = "(royalty|ideology|biotech|anomaly|odyssey)"

# name, regex over "src:path", note, per-category cap (sampled evenly above it)
CATEGORIES: list[tuple[str, str, str, int]] = [
    ("weapons_ranged", r"core:things/item/equipment/weaponranged/", "128 px, east-facing", 96),
    ("weapons_melee", r"core:things/item/equipment/weaponmelee/", "stuff-tinted: white", 96),
    ("weapons_dlc", DLC + r":things/item/equipment/weapon", "DLC weapons", 96),
    ("resources", r"core:things/item/resource/", "64 px, StackCount _a/_b/_c", 144),
    ("drugs_medicine", r"core:things/item/(drug|health|serum)", "64 px", 96),
    ("meals", r":things/item/meal/", "MealVariants", 48),
    ("items_misc", r"core:things/item/(special|artifact|book|chunk|unfinished|relic)", "", 96),
    ("furniture", r"core:things/building/furniture/.*_south$", "south, 64 px/cell, white", 96),
    (
        "furniture_rotations",
        (
            r"core:things/building/furniture/(bed/bed|bed/doublebed|"
            r"diningchair|armchair|dresser|endtable)_(north|east|south)$"
        ),
        "north/east/south",
        48,
    ),
    (
        "masks",
        r"core:things/building/furniture/bed/(bed|royalbed|doublebed)_south(m)?$",
        "texture + _southm mask pairs (red = stuff, green = colorTwo)",
        12,
    ),
    ("production", r"core:things/building/production/.*_south$", "64 px/cell", 48),
    (
        "buildings_misc",
        (
            r"core:things/building/(power|security|misc|temperature|joy|art|ship)"
            r"/(?!.*_(north|east|west)$)"
        ),
        "south or single",
        144,
    ),
    ("buildings_dlc", DLC + r":things/building/.*(?<!_north)(?<!_east)(?<!_west)$", "", 144),
    (
        "apparel_worn",
        r"core:things/pawn/humanlike/apparel/[^/]+/[^/_]+(_male)?_south$",
        "worn, male/headgear south, white",
        96,
    ),
    (
        "apparel_bodytypes",
        r"core:things/pawn/humanlike/apparel/(duster|flakjacket)/",
        "one garment x 5 body types x 3 sides",
        48,
    ),
    (
        "apparel_dlc",
        DLC + r":things/pawn/humanlike/apparel/[^/]+/[^/_]+(_male)?_south$",
        "worn, DLC",
        96,
    ),
    ("bodies", r"core:things/pawn/humanlike/bodies/naked_", "white; bbox reference", 24),
    ("heads", r"core:things/pawn/humanlike/heads/(male|female)/.*_average_", "white", 24),
    ("hair_beards", r"core:things/pawn/humanlike/(hairs|beards)/.*_south$", "white", 96),
    (
        "animals",
        r"core:things/pawn/animal/(?!.*dessicated)[^/]+/[^/]+_east$",
        "east side view, greyscale tinted",
        144,
    ),
    ("animals_dlc", DLC + r":things/pawn/animal/.*_east$", "", 96),
    ("mechanoids", r":things/pawn/mechanoid/.*_south$", "", 96),
    ("anomaly_entities", r"anomaly:things/pawn/.*_south$", "", 96),
    ("plants", r":things/plant/", "no black outline", 144),
    ("ui_gene_icons", r"biotech:ui/icons/genes/", "128 px", 144),
    ("ui_commands", r"core:ui/commands/", "gizmos, drawn at 75 px", 144),
    ("ui_designators", r"core:ui/designators/", "", 96),
    ("ui_abilities", r":ui/abilities/", "", 96),
    ("ui_icons", r"core:ui/icons/", "small UI icons", 96),
    ("ui_memes_ideo", r"ideology:ui/(memes|ideoligions|issues|roles)/", "", 96),
    ("terrain", r"core:terrain/surfaces/", "floors/ground, scaled down", 48),
]

COLS, ROWS, CELL, LABEL = 8, 6, 144, 16
BG = (110, 100, 80, 255)


def font(size: int = 11) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def pick(entries: list[dict], regex: str, cap: int, keep_masks: bool = False) -> tuple[list, int]:
    import re

    hits = vt.search(entries, regex)
    if not keep_masks:
        hits = [h for h in hits if not re.search(MASK, h["path"])]
    total = len(hits)
    if total > cap:
        step = total / cap
        hits = [hits[int(i * step)] for i in range(cap)]
    return hits, total


def fit(im: Image.Image, box: int) -> tuple[Image.Image, bool]:
    if im.width <= box and im.height <= box:
        return im, False
    s = box / max(im.width, im.height)
    return (
        im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS),
        True,
    )


def contact_sheets(name: str, files: list[Path], out: Path) -> list[tuple[Path, list[str]]]:
    per = COLS * ROWS
    pages = []
    f = font()
    for p in range(math.ceil(len(files) / per)):
        chunk = files[p * per : (p + 1) * per]
        rows = math.ceil(len(chunk) / COLS)
        sheet = Image.new("RGBA", (COLS * CELL, rows * (CELL + LABEL)), BG)
        d = ImageDraw.Draw(sheet)
        names = []
        for i, fp in enumerate(chunk):
            im, scaled = fit(Image.open(fp).convert("RGBA"), CELL - 12)
            x, y = (i % COLS) * CELL, (i // COLS) * (CELL + LABEL)
            sheet.alpha_composite(im, (x + (CELL - im.width) // 2, y + (CELL - im.height) // 2))
            label = fp.stem + ("*" if scaled else "")
            names.append(label)
            d.text((x + 3, y + CELL), label[:24], fill=(255, 255, 255, 255), font=f)
        dest = out / f"{name}_{p + 1}.png"
        sheet.convert("RGB").save(dest, optimize=True)
        pages.append((dest, names))
    return pages


def detail_sheet(files: list[Path], dest: Path, scale: int = 3) -> None:
    if not files:
        return
    step = max(1, len(files) // 4)
    chosen = files[::step][:4]
    tiles = []
    for fp in chosen:
        im = Image.open(fp).convert("RGBA")
        bbox = im.getbbox() or (0, 0, im.width, im.height)
        pad = 4
        im = im.crop(
            (
                max(0, bbox[0] - pad),
                max(0, bbox[1] - pad),
                min(im.width, bbox[2] + pad),
                min(im.height, bbox[3] + pad),
            )
        )
        im, _ = fit(im, 128)
        tiles.append((fp.stem, im.resize((im.width * scale, im.height * scale), Image.NEAREST)))
    w = sum(t.width for _, t in tiles) + 12 * (len(tiles) + 1)
    h = max(t.height for _, t in tiles) + LABEL + 16
    sheet = Image.new("RGBA", (w, h), BG)
    d = ImageDraw.Draw(sheet)
    x = 12
    for n, t in tiles:
        sheet.alpha_composite(t, (x, 8))
        d.text((x, h - LABEL), f"{n} (x{scale})", fill=(255, 255, 255, 255), font=font())
        x += t.width + 12
    sheet.convert("RGB").save(dest, optimize=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--only", help="comma list of category names")
    ap.add_argument("--force", action="store_true", help="rebuild existing sheets")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for n, rx, note, cap in CATEGORIES:
            print(f"{n:22} {rx}  (≤{cap}) {note}")
        return 0
    only = set(a.only.split(",")) if a.only else None
    sheets, detail = ASSETS / "sheets", ASSETS / "detail"
    sheets.mkdir(parents=True, exist_ok=True)
    detail.mkdir(parents=True, exist_ok=True)
    entries = vt.load_index()
    stats_file = ASSETS / "stats.json"
    stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
    index = (
        json.loads((ASSETS / "index.json").read_text()) if (ASSETS / "index.json").exists() else {}
    )
    for name, rx, note, cap in CATEGORIES:
        if only and name not in only:
            continue
        if (
            not a.force
            and name in index
            and all(Path(ASSETS / p).exists() for p in index[name]["sheets"])
        ):
            print(f"{name}: up to date")
            continue
        hits, total = pick(entries, rx, cap, keep_masks=name == "masks")
        if not hits:
            print(f"{name}: no textures match {rx}", file=sys.stderr)
            continue
        files = vt.extract(hits, vt.CACHE / "png")
        for old in sheets.glob(f"{name}_*.png"):
            old.unlink()
        pages = contact_sheets(name, files, sheets)
        detail_sheet(files, detail / f"{name}.png")
        s = analyze.summarize([analyze.analyze(f) for f in files])
        stats[name] = s
        index[name] = {
            "regex": rx,
            "note": note,
            "shown": len(files),
            "total": total,
            "sheets": [str(p.relative_to(ASSETS)).replace("\\", "/") for p, _ in pages],
            "names": [n for _, ns in pages for n in ns],
        }
        print(f"{name}: {len(files)}/{total} sprites, {len(pages)} sheet(s)")
    stats_file.write_text(json.dumps(stats, indent=1))
    (ASSETS / "index.json").write_text(json.dumps(index, indent=1))
    write_markdown(index, stats)
    return 0


def write_markdown(index: dict, stats: dict) -> None:
    ver = vt.game_version()
    lines = [
        f"# Vanilla sprite sheets (game {ver}) — generated by build_assets.py, do not edit",
        "",
        (
            "Sprites at native size on a neutral ground (`*` = larger than 128 px, scaled down). "
            "`detail/<category>.png` = 4 sprites at 3x. Numbers per category in `stats.md`."
        ),
        "",
    ]
    for name, _, _, _ in CATEGORIES:
        if name not in index:
            continue
        e = index[name]
        sampled = f", sampled {e['shown']} of {e['total']}" if e["shown"] < e["total"] else ""
        lines.append(f"## {name}  ({e['shown']} sprites{sampled})")
        lines.append(f"`{e['regex']}`" + (f" — {e['note']}" if e["note"] else ""))
        lines.append("")
        per = COLS * ROWS
        for i, sheet in enumerate(e["sheets"]):
            names = e["names"][i * per : (i + 1) * per]
            lines.append(f"- `{sheet}`: " + ", ".join(names))
        lines.append(f"- `detail/{name}.png`")
        lines.append("")
    (ASSETS / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    keys = [k for k in analyze.KEYS]
    out = [
        f"# Style numbers per category (game {ver}) — p10 / median / p90",
        "",
        "| category | n | " + " | ".join(keys) + " | common sizes |",
        "|---|---|" + "---|" * len(keys) + "---|",
    ]
    for name, _, _, _ in CATEGORIES:
        s = stats.get(name)
        if not s:
            continue
        cells = [
            f"{s[k]['p10']:g} / **{s[k]['median']:g}** / {s[k]['p90']:g}" if k in s else "-"
            for k in keys
        ]
        sizes = ", ".join(f"{k} ({v})" for k, v in list(s.get("sizes", {}).items())[:3])
        out.append(f"| {name} | {s['n']} | " + " | ".join(cells) + f" | {sizes} |")
    (ASSETS / "stats.md").write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
