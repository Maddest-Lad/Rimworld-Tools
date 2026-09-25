"""Tests for the SVG art scripts. Pure functions only; no game files needed.

    uv run --no-project --python 3.12 --with pytest --with numpy --with Pillow --with resvg-py \
        pytest .claude/skills/rimworld-svg-art/scripts/tests
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1]
TEMPLATES = SCRIPTS.parent / "templates"
sys.path.insert(0, str(SCRIPTS))

import analyze
import render
import vanilla_tex


def outlined_square(size: int = 64, outline: int = 3, fill=(200, 60, 60)) -> Image.Image:
    a = np.zeros((size, size, 4), np.uint8)
    lo, hi = size // 4, size * 3 // 4
    a[lo:hi, lo:hi] = (0, 0, 0, 255)
    a[lo + outline : hi - outline, lo + outline : hi - outline] = (*fill, 255)
    return Image.fromarray(a, "RGBA")


# ---------------------------------------------------------------- analyze


def test_outline_thickness_measured():
    r = analyze.analyze_image(outlined_square(outline=3))
    assert r["outline_px"] == 3
    assert r["outline_rgb"] == "#000000"
    assert r["edge_ratio"] == 0.0
    assert r["margin_px"] == 16


def test_own_hue_edge_is_not_an_outline():
    a = np.asarray(outlined_square(outline=3, fill=(100, 160, 60))).copy()
    ring = (a[..., 3] == 255) & (a[..., :3].sum(-1) == 0)
    a[ring, :3] = (60, 96, 36)  # 60 % of the fill: a plant-style edge
    r = analyze.analyze_image(Image.fromarray(a, "RGBA"))
    assert r["outline_px"] == 0
    assert 0.5 < r["edge_ratio"] < 0.7


def test_empty_sprite():
    assert analyze.analyze_image(Image.new("RGBA", (32, 32)))["empty"]


def test_compare_flags_outliers():
    base = analyze.summarize([analyze.analyze_image(outlined_square(outline=3))] * 3)
    thick = analyze.analyze_image(outlined_square(outline=8))
    assert any(f.startswith("outline_px") for f in analyze.compare(thick, base))
    assert analyze.compare(analyze.analyze_image(outlined_square(outline=3)), base) == []


# ---------------------------------------------------------------- render


@pytest.mark.parametrize(
    "head,size",
    [
        ('<svg width="128" height="64" viewBox="0 0 10 10">', (128, 64)),
        ('<svg viewBox="0 0 64 32">', (64, 32)),
        ('<svg width="48px" height="48px">', (48, 48)),
        ("<svg>", None),
    ],
)
def test_svg_size(head, size):
    assert render.svg_size(head + "</svg>") == size


def test_rasterise_scales_to_requested_size(tmp_path):
    f = tmp_path / "a.svg"
    f.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect x="16" y="16" width="32" height="32" fill="#f00"/></svg>'
    )
    assert render.rasterise(f, None).size == (64, 64)
    im = render.rasterise(f, (128, 128))
    assert im.size == (128, 128)
    assert im.getpixel((64, 64)) == (255, 0, 0, 255)
    assert im.getpixel((10, 10))[3] == 0


def test_rasterise_reports_bad_xml(tmp_path):
    f = tmp_path / "bad.svg"
    f.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">' "<!-- a -- b --></svg>"
    )
    with pytest.raises(SystemExit, match="bad.svg"):
        render.rasterise(f, None)


def test_bleed_fills_colour_keeps_alpha():
    a = np.zeros((8, 8, 4), np.uint8)
    a[3:5, 3:5] = (10, 200, 30, 255)
    out = np.asarray(render.bleed(Image.fromarray(a, "RGBA")))
    assert (out[..., 3] == a[..., 3]).all()
    assert tuple(out[0, 0, :3]) == (10, 200, 30)


def test_lint_sizes_and_edges():
    assert any(i.startswith("ERROR") for i in render.lint(outlined_square(size=30), "x"))
    npot = Image.new("RGBA", (96, 64))
    npot.paste(outlined_square(size=64), (16, 0))
    assert any("power of two" in i for i in render.lint(npot, "x"))
    full = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    assert any("canvas edge" in i for i in render.lint(full, "x"))
    assert render.lint(outlined_square(), "x") == []


def test_mask_names_and_pairing():
    assert render.is_mask(Path("Bed_southm")) and render.is_mask(Path("Sword_m"))
    assert not render.is_mask(Path("Bed_south")) and not render.is_mask(Path("Drum"))
    assert render.mask_names("Bed_south") == ["Bed_southm"]
    assert render.mask_names("Sword") == ["Sword_m"]
    im = Image.new("RGBA", (4, 4))
    paired = render.pair_masks([("Bed_south", im), ("Bed_southm", im), ("Cup", im)])
    assert [p["name"] for p in paired] == ["Bed_south", "Cup"]
    assert paired[0]["mask"] is im and paired[1]["mask"] is None


def test_lint_multi_missing_sides():
    paths = [Path("a/Bed_south.svg"), Path("a/Bed_east.svg"), Path("a/Bed_southm.svg")]
    out = render.lint_multi(paths)
    assert len(out) == 1 and "north" in out[0]
    full = paths + [Path("a/Bed_north.svg")]
    assert render.lint_multi(full) == []


def test_colorize_mask_channels():
    im = Image.new("RGBA", (2, 1), (200, 200, 200, 255))
    mask = Image.new("RGB", (2, 1))
    mask.putpixel((0, 0), (255, 0, 0))  # red: tinted, right pixel black: untouched
    out = render.colorize(im, (128, 0, 0), mask, (0, 0, 255))
    assert out.getpixel((0, 0))[:3] == (100, 0, 0)
    assert out.getpixel((1, 0))[:3] == (200, 200, 200)
    assert render.colorize(im, (128, 128, 128)).getpixel((1, 0))[:3] == (100, 100, 100)


def test_parse_tints():
    assert render.parse_tints("steel,#ff0000") == [
        ("steel", render.STUFF["steel"]),
        ("#ff0000", (255, 0, 0)),
    ]
    with pytest.raises(SystemExit):
        render.parse_tints("mauve")


# ---------------------------------------------------------------- vanilla_tex


def test_path_normalisation():
    assert vanilla_tex.norm_core_path("textures/things/item/x") == "things/item/x"
    assert vanilla_tex.norm_core_path("fonts/x") is None
    assert (
        vanilla_tex.norm_bundle_path("assets/data/biotech/textures/things/pawn/y.png")
        == "things/pawn/y"
    )
    assert vanilla_tex.norm_bundle_path("assets/data/biotech/sounds/z.ogg") is None


def test_search_is_case_insensitive_and_sorted():
    idx = [{"src": "core", "path": "things/b"}, {"src": "biotech", "path": "things/a"}]
    assert [vanilla_tex.key(e) for e in vanilla_tex.search(idx, "THINGS")] == [
        "biotech:things/a",
        "core:things/b",
    ]


# ---------------------------------------------------------------- templates


TEMPLATE_FILES = sorted(TEMPLATES.glob("*.svg"))


@pytest.mark.parametrize("svg", TEMPLATE_FILES, ids=lambda p: p.name)
def test_templates_render_clean(svg):
    text = svg.read_text(encoding="utf-8")
    for comment in re.findall(r"<!--(.*?)-->", text, re.DOTALL):
        assert "--" not in comment, "'--' inside an XML comment breaks the parser"
    im = render.rasterise(svg, None)
    issues = render.lint(im, svg.stem)
    assert not [i for i in issues if i.startswith(("ERROR", "warn"))], issues


def test_template_sets_complete():
    assert render.lint_multi(TEMPLATE_FILES) == []


def test_guides_are_stripped(tmp_path):
    f = tmp_path / "g.svg"
    f.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="8" height="8"><defs><rect id="r" width="8" height="8"/></defs>'
        '<g id="guide-body"><use xlink:href="#r" fill="#f00"/></g>'
        '<rect id="guide" x="0" y="0" width="8" height="8" fill="#0f0"/></svg>'
    )
    assert render.rasterise(f, None).getpixel((4, 4))[3] == 0
    kept = render.strip_guides(f.read_text())
    assert "guide" not in kept and 'id="r"' in kept


def test_build_assets_pick_filters_masks_and_samples():
    import build_assets

    idx = [{"src": "core", "path": f"things/x/a{i:02}"} for i in range(10)]
    idx += [{"src": "core", "path": "things/x/bed_southm"}, {"src": "core", "path": "things/x/y_m"}]
    hits, total = build_assets.pick(idx, "things/x/", cap=5)
    assert total == 10 and len(hits) == 5
    assert all(not h["path"].endswith("m") for h in hits)
    hits, total = build_assets.pick(idx, "things/x/", cap=50, keep_masks=True)
    assert total == 12


# ---------------------------------------------------------------- compose / lint allow / per cell


def test_link_index_bits_and_y_down():
    import compose

    cells = {(1, 1), (1, 0), (2, 1), (1, 2), (0, 1)}
    assert compose.link_index((1, 1), cells) == 15  # N1 + E2 + S4 + W8
    assert compose.link_index((1, 0), cells) == 4  # only south (y + 1) neighbour
    assert compose.link_index((2, 1), cells) == 8  # only west


def test_atlas_tile_crops_centre_from_bottom_rows():
    import compose

    atlas = Image.new("RGBA", (640, 640))
    # index 0 = column 0, bottom row: visible area x 20..140, y 500..620
    for x in range(640):
        for y in range(480, 640):
            atlas.putpixel((x, y), (255, 0, 0, 255))
    tile = compose.atlas_tile(atlas, 0)
    assert tile.size == (120, 120)
    assert tile.getpixel((60, 60)) == (255, 0, 0, 255)
    assert compose.atlas_tile(atlas, 15).getpixel((60, 60))[3] == 0  # top-right tile


def test_lint_allow_codes(tmp_path):
    full = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    assert any("[edge]" in i for i in render.lint(full, "x"))
    assert not any("[edge]" in i for i in render.lint(full, "x", {"edge"}))
    assert render.allowed_codes("<!-- svg-art: allow edge, Outline -->") == {"edge", "outline"}
    notes = render.lint_multi([Path("a/Door_south.svg"), Path("a/Door_east.svg")])
    assert len(notes) == 1 and notes[0].startswith("note") and "_south for north" in notes[0]
    assert render.lint_multi([Path("a/Door_south.svg")], {"multi"}) == []


def test_per_cell_normalises_density():
    a = analyze.per_cell(analyze.analyze_image(outlined_square(size=64, outline=3)), 64)
    b = analyze.per_cell(analyze.analyze_image(outlined_square(size=128, outline=6)), 128)
    assert a["outline_cell"] == b["outline_cell"] == 3
    base = analyze.summarize_keys([a, a, a], analyze.CELL_KEYS)
    assert not [f for f in analyze.compare(b, base, analyze.CELL_KEYS) if "outline" in f]


def test_door_layers_follow_engine_offsets():
    import compose

    one = compose.door_layers({"door": {"mover": "m.png"}, "center": [2, 2], "open": 1.0})
    assert [x["center"] for x in one] == [[2 - 0.45, 2], [2 + 0.45, 2]]
    assert [x["flip"] for x in one] == [False, True] and one[0]["size"] == [1.0, 1.0]
    two = compose.door_layers(
        {"door": {"mover": "m.png", "top": "t.png"}, "center": [5, 1], "cells": 2, "tint": "stuff"}
    )
    assert [x["center"] for x in two[:2]] == [[4.5, 1], [5.5, 1]]
    assert two[0]["size"] == [1.0, 1.0] and two[2]["size"] == [2, 1] and two[2]["tint"] == "stuff"
    east = compose.door_layers({"door": {"mover": "m.png"}, "center": [0, 0], "axis": "y"})
    assert east[0]["rot"] == 90 and east[1]["center"] == [0, 0.0]
