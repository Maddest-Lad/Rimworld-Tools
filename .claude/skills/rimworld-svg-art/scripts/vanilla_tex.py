# /// script
# requires-python = ">=3.11"
# dependencies = ["zstandard>=0.22", "Pillow>=10.1"]
# ///
"""Find and extract vanilla RimWorld 1.7 textures (Core + DLC) as PNGs, for reference only.

    uv run vanilla_tex.py --search 'things/item/.*/(steel|gold)'   # list matches (regex)
    uv run vanilla_tex.py --extract 'weapon/.*rifle' [--limit 40]   # write PNGs to the cache
    uv run vanilla_tex.py --extract ... --out DIR                   # somewhere else (not a mod!)
    uv run vanilla_tex.py --stats [PREFIX]                          # counts + typical sizes
    uv run vanilla_tex.py --overrides 'eggbox|furniture/bed/'      # installed mods that
                                                                    # replace these textures
    uv run vanilla_tex.py --path                                    # print the cache dir

1.7 ships textures as BC7 DDS in zstd-compressed zips: Core in `<game>/Assets.zip`
(`Resources/Textures/<path>.<source ext>.dds`), each DLC in `Data/<DLC>/Assets.zip`
(`Textures/...`). Each pack's `textures.info` lists every texture with its size; `bake.manifest`
maps deduplicated entries to the stored copy. Paths are normalised to the texPath form mods use,
lower-cased and prefixed by the source: `core:things/item/resource/steel/steel_a`,
`biotech:things/pawn/mechanoid/...`.

The first run builds `.cache/textures/index-<game version>.json` (seconds). Extracted PNGs go to
`.cache/textures/png-<game version>/<source>/<path>.png`. The cache is gitignored: this is
Ludeon's art — study it, measure it, never copy it into a mod or commit it.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[2]
GAME = REPO / "links" / "game"
CACHE = SKILL / ".cache" / "textures"
DLCS = ("Royalty", "Ideology", "Biotech", "Anomaly", "Odyssey")
ZSTD = 93  # zip compression method id
SOURCE_EXTS = (".png", ".psd", ".jpg", ".jpeg", ".tga", ".dds")


def game_version() -> str:
    try:
        return (GAME / "Version.txt").read_text().split()[0]
    except OSError:
        return "unknown"


def png_dir() -> Path:
    """Default extraction folder, per game build so a game update never serves stale art."""
    return CACHE / f"png-{game_version()}"


def packs() -> list[tuple[str, Path, str]]:
    """(source, pack file, texture prefix inside the pack) for Core and every installed DLC."""
    out = [("core", GAME / "Assets.zip", "Resources/Textures/")]
    out += [(d.lower(), GAME / "Data" / d / "Assets.zip", "Textures/") for d in DLCS]
    return [p for p in out if p[1].is_file()]


def norm_pack_path(name: str, prefix: str) -> str | None:
    """'Resources/Textures/Things/Item/Steel_a.psd.dds' -> 'things/item/steel_a' (None if the
    entry is not a texture under prefix)."""
    if not name.startswith(prefix) or not name.lower().endswith(".dds"):
        return None
    rel = name[len(prefix) : -len(".dds")]
    for ext in SOURCE_EXTS:
        if rel.lower().endswith(ext):
            rel = rel[: -len(ext)]
            break
    return rel.lower()


class Pack:
    """Read members of a 1.7 asset pack. Python's zipfile can't inflate zstd entries before 3.14,
    so members are read raw from their local header and decompressed here."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.fh = path.open("rb")
        self.names = set(self.zip.namelist())

    def read(self, name: str) -> bytes:
        info = self.zip.getinfo(name)
        if info.compress_type != ZSTD:
            return self.zip.read(name)
        import zstandard

        self.fh.seek(info.header_offset)
        header = self.fh.read(30)
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        self.fh.seek(info.header_offset + 30 + name_len + extra_len)
        raw = self.fh.read(info.compress_size)
        return zstandard.ZstdDecompressor().decompress(raw, max_output_size=info.file_size)

    def close(self) -> None:
        self.fh.close()
        self.zip.close()


def build_index() -> list[dict]:
    entries: list[dict] = []
    for src, path, prefix in packs():
        pack = Pack(path)
        try:
            info = pack.read("textures.info").decode("utf-8").splitlines()
            stored_by_hash: dict[str, str] = {}
            hash_of: dict[str, str] = {}
            for line in pack.read("bake.manifest").decode("utf-8").splitlines():
                member, _, digest = line.rpartition(" ")
                hash_of[member] = digest
                if member in pack.names:
                    stored_by_hash.setdefault(digest, member)
            for line in info:
                cols = line.split()
                if len(cols) < 3:
                    continue
                member = cols[0]
                tp = norm_pack_path(member, prefix)
                if tp is None:
                    continue
                stored = member if member in pack.names else stored_by_hash.get(hash_of.get(member))
                if stored is None:
                    continue
                entries.append(
                    {
                        "src": src,
                        "path": tp,
                        "file": path.relative_to(GAME).as_posix(),
                        "member": stored,
                        "w": int(cols[1]),
                        "h": int(cols[2]),
                    }
                )
        finally:
            pack.close()
    return entries


def load_index(rebuild: bool = False) -> list[dict]:
    f = CACHE / f"index-{game_version()}.json"
    if f.exists() and not rebuild:
        return json.loads(f.read_text())
    print("indexing game textures (one-time, seconds)...", file=sys.stderr)
    entries = build_index()
    if not entries:
        raise SystemExit(f"no textures found under {GAME} (Assets.zip missing? run make bootstrap)")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(entries))
    return entries


def key(e: dict) -> str:
    return f"{e['src']}:{e['path']}"


def search(entries: list[dict], pattern: str) -> list[dict]:
    rx = re.compile(pattern, re.IGNORECASE)
    return sorted((e for e in entries if rx.search(key(e))), key=key)


def extract(hits: list[dict], out: Path | None = None) -> list[Path]:
    from PIL import Image

    out = out or png_dir()
    by_file: dict[str, list[dict]] = collections.defaultdict(list)
    for e in hits:
        by_file[e["file"]].append(e)
    written = []
    for file, es in by_file.items():
        pack = None
        try:
            for e in es:
                dest = out / e["src"] / (e["path"] + ".png")
                if not dest.exists():
                    pack = pack or Pack(GAME / file)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    Image.open(io.BytesIO(pack.read(e["member"]))).save(dest)
                written.append(dest)
        finally:
            if pack:
                pack.close()
    return written


def mod_roots() -> list[Path]:
    roots = []
    for base in (REPO / "links" / "mods", REPO / "links" / "workshop"):
        if base.exists():
            roots.extend(d for d in base.iterdir() if d.is_dir())
    return roots


def mod_name(root: Path) -> str:
    about = root / "About" / "About.xml"
    try:
        m = re.search(r"<name>(.*?)</name>", about.read_text(encoding="utf-8", errors="replace"))
        return m.group(1).strip() if m else root.name
    except OSError:
        return root.name


def active_ids() -> set[str]:
    cfg = REPO / "links" / "config" / "ModsConfig.xml"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    block = re.search(r"<activeMods>(.*?)</activeMods>", text, re.DOTALL)
    return (
        {x.strip().lower() for x in re.findall(r"<li>(.*?)</li>", block.group(1))}
        if block
        else set()
    )


def package_id(root: Path) -> str:
    about = root / "About" / "About.xml"
    try:
        m = re.search(
            r"<packageId>(.*?)</packageId>", about.read_text(encoding="utf-8", errors="replace")
        )
        return m.group(1).strip().lower() if m else ""
    except OSError:
        return ""


def overrides(entries: list[dict], pattern: str) -> list[tuple[str, str, bool, str]]:
    """(vanilla key, mod name, active, file) for mod textures at the same path as a vanilla one.
    Texture-replacement mods (upscales, retextures) change what the user calls "vanilla".
    Loose files only: a replacement baked into a mod's own Assets.zip is not seen."""
    wanted = {e["path"]: key(e) for e in search(entries, pattern)}
    if not wanted:
        return []
    active = active_ids()
    out = []
    for root in mod_roots():
        for f in root.rglob("*"):
            if f.suffix.lower() not in (".png", ".dds", ".jpg", ".jpeg", ".psd"):
                continue
            parts = [x.lower() for x in f.relative_to(root).parts]
            if "textures" not in parts:
                continue
            rel = "/".join(parts[parts.index("textures") + 1 :])
            rel = rel.rsplit(".", 1)[0]
            if rel in wanted:
                out.append((wanted[rel], mod_name(root), package_id(root) in active, str(f)))
    return sorted(out)


def stats(entries: list[dict], prefix: str, depth: int) -> None:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for e in entries:
        if e["path"].startswith(prefix):
            parts = e["path"].split("/")
            groups["/".join(parts[:depth])].append(e)
    for g, es in sorted(groups.items()):
        sizes = collections.Counter(f"{e['w']}x{e['h']}" for e in es)
        common = ", ".join(f"{s} ({n})" for s, n in sizes.most_common(3))
        print(f"{len(es):5}  {g:45}  {common}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--search", metavar="REGEX")
    ap.add_argument("--extract", metavar="REGEX")
    ap.add_argument("--stats", nargs="?", const="", metavar="PREFIX")
    ap.add_argument("--depth", type=int, default=3, help="--stats grouping depth (default 3)")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", type=Path, default=None, help="default: the per-build PNG cache")
    ap.add_argument("--rebuild", action="store_true", help="re-index the game files")
    ap.add_argument("--overrides", metavar="REGEX", help="installed mods replacing these")
    ap.add_argument("--path", action="store_true")
    a = ap.parse_args(argv)
    if a.path:
        print(CACHE)
        return 0
    entries = load_index(a.rebuild)
    if a.overrides:
        rows = overrides(entries, a.overrides)
        for k, name, act, f in rows:
            print(f"{k:55} {'ACTIVE ' if act else 'inactive'} {name}\n    {f}")
        if not rows:
            print("no installed mod replaces these textures")
        return 0
    if a.stats is not None:
        stats(entries, a.stats, a.depth)
        return 0
    pattern = a.search or a.extract
    if not pattern:
        ap.print_help()
        return 2
    hits = search(entries, pattern)
    shown = hits[: a.limit]
    if a.extract:
        for p in extract(shown, a.out):
            print(p)
    else:
        for e in shown:
            print(f"{key(e):70} {e['w']}x{e['h']}")
    if len(hits) > len(shown):
        print(f"... {len(hits) - len(shown)} more (--limit)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
