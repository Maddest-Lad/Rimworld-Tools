# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=10", "numpy>=1.26", "UnityPy>=1.20", "resvg-py>=0.2"]
# ///
"""Labelled contact sheet of finished PNGs: the whole set side by side, at native size and at
game zoom. Use it to check that a set speaks one visual language (same material drawn the same
way everywhere) and that different things stay distinguishable at the starting zoom.

    uv run sheet.py 'workspace/MyMod/Textures/MyMod/**/*.png' --out Art/review/all.png
    uv run sheet.py Manure/*.png Troughs/*Kibble3_south.png --tex-ppc 128 --zoom native,30
    uv run sheet.py Stall/*.png Manure/*.png --tint wood,steel --tinted 'Stall|Trough[A-Z][a-z]+_'

Each row is one zoom: `native` (the PNG's own pixels, on a checkerboard) or a screen density
in px per cell (65 / 30 / 12 = closest / starting / far at 1440p), drawn on `--bg` terrain.
`--tex-ppc` is the texture's px per cell (64 vanilla, 128 for MO-scale mods). Mask files
(`…m.png`, `…_m.png`) are skipped as sprites and used for `--tint` (`CutoutComplex`). `--tinted REGEX` limits the tint to stuff-tinted files (default: all), so
own-colour contents and items keep their colours on the same sheet.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render

PAD = 10
LABEL = 14


def expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        if any(c in p for c in "*?["):
            anchor = Path(p).anchor or "."
            rel = p[len(anchor) :] if Path(p).is_absolute() else p
            out.extend(sorted(Path(anchor).glob(rel)))
        else:
            out.append(Path(p))
    return [f for f in out if f.suffix.lower() == ".png"]


def split_masks(files: list[Path]) -> tuple[list[Path], dict[str, Path]]:
    names = {f.stem: f for f in files}
    masks = {}
    for f in files:
        for base in (f.stem[:-2], f.stem[:-1]) if f.stem.endswith(("_m", "m")) else ():
            if base in names:
                masks[base] = f
    sprites = [f for f in files if f not in masks.values()]
    return sprites, masks


def parse_zoom(spec: str) -> list[str | int]:
    out: list[str | int] = []
    for z in filter(None, (s.strip() for s in spec.split(","))):
        out.append("native" if z == "native" else int(z))
    return out


def tile(
    im: Image.Image,
    zoom: str | int,
    tex_ppc: int,
    bg: str,
    tint: tuple[int, int, int] | None,
    mask: Image.Image | None,
) -> Image.Image:
    if tint is not None:
        im = render.colorize(im, tint, mask)
    if zoom == "native":
        base = render.checker(im.width, im.height)
        base.alpha_composite(im)
        return base
    scale = zoom / tex_ppc
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    small = im.resize((w, h), Image.LANCZOS)
    m = max(4, zoom // 3)
    base = render.background(bg, w + 2 * m, h + 2 * m, zoom)
    base.alpha_composite(small, (m, m))
    return base


def build(
    files: list[Path],
    zooms: list[str | int],
    tex_ppc: int,
    bg: str,
    tints: list[tuple[str, tuple[int, int, int]]],
    tinted: str | None = None,
) -> Image.Image:
    sprites, masks = split_masks(files)
    ims = {f: Image.open(f).convert("RGBA") for f in sprites}
    mask_ims = {k: Image.open(v).convert("RGBA") for k, v in masks.items()}
    variants: list[tuple[str, tuple[int, int, int] | None]] = [(n, c) for n, c in tints] or [
        ("", None)
    ]
    rows = []
    for zoom in zooms:
        for tname, tint in variants:
            cells = []
            for f in sprites:
                own = tinted is not None and not re.search(tinted, f.stem)
                t = tile(ims[f], zoom, tex_ppc, bg, None if own else tint, mask_ims.get(f.stem))
                cells.append((f"{f.stem} {ims[f].width}x{ims[f].height}", t))
            head = f"{zoom} px/cell" if zoom != "native" else "native"
            rows.append((head + (f", {tname}" if tname else ""), cells))
    width = PAD + max(sum(max(t.width, 6 * len(n)) + PAD for n, t in cells) for _, cells in rows)
    height = PAD + sum(LABEL * 2 + max(t.height for _, t in cells) + PAD for _, cells in rows)
    sheet = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    d = ImageDraw.Draw(sheet)
    y = PAD
    for head, cells in rows:
        d.text((PAD, y), head, fill=(240, 240, 240, 255))
        y += LABEL
        x = PAD
        for name, t in cells:
            d.text((x, y), name, fill=(180, 180, 180, 255))
            sheet.alpha_composite(t, (x, y + LABEL))
            x += max(t.width, 6 * len(name)) + PAD
        y += LABEL + max(t.height for _, t in cells) + PAD
    return sheet


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("files", nargs="+", help="PNG files or globs (** allowed)")
    ap.add_argument("--out", required=True, help="output PNG")
    ap.add_argument("--zoom", default="native,30", help="comma list: native and/or px per cell")
    ap.add_argument("--tex-ppc", type=int, default=64, help="texture px per cell (64 vanilla)")
    ap.add_argument("--bg", default="soil", help=f"one of {', '.join(render.BACKGROUNDS)}")
    ap.add_argument("--tint", default="", help="comma list of stuff names or #rrggbb")
    ap.add_argument("--tinted", help="regex on file stems that get the tint (default: all)")
    a = ap.parse_args(argv)
    files = expand(a.files)
    if not files:
        raise SystemExit("no PNG files matched")
    if a.bg not in render.BACKGROUNDS:
        raise SystemExit(f"unknown --bg {a.bg}; choose from {', '.join(render.BACKGROUNDS)}")
    sheet = build(files, parse_zoom(a.zoom), a.tex_ppc, a.bg, render.parse_tints(a.tint), a.tinted)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{out}  ({len(files)} files, {sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
