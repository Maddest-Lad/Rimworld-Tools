"""Look up RimWorld (or any mod's) C# from a local ilspycmd decompile. Read-only on the game.

    python decompile.py TYPE                       # file path + member outline, e.g. ThingComp
    python decompile.py TYPE --full                # whole file (can be thousands of lines)
    python decompile.py TYPE --grep REGEX          # matching lines in that type's file
    python decompile.py --grep REGEX [--limit N]   # search the whole assembly
    python decompile.py --dll PATH ...             # another assembly (a mod's DLL, 0Harmony)
    python decompile.py --path                     # print the cache directory and exit

The first call decompiles the assembly into `.claude/skills/rimworld-mod-dev/.cache/decompiled/
<dll>-<game version or size>/` (≈1 min for Assembly-CSharp, then instant). The cache is
gitignored and must never be committed or published: it is Ludeon's code, for reference only.
TYPE may be `ThingComp`, `Verse.ThingComp` or a nested `Pawn_HealthTracker`; nested types are
found inside their outer type's file.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rwxml import GAME, game_version

SKILL = Path(__file__).resolve().parents[1]
CACHE = SKILL / ".cache" / "decompiled"
GAME_DLL = GAME / "RimWorldWin64_Data" / "Managed" / "Assembly-CSharp.dll"
MEMBER_RE = re.compile(
    r"^\t{1,2}(?:\[[^\]]+\]\s*)*(?:(?:public|protected|internal|private|static|virtual|override|"
    r"abstract|sealed|readonly|const|extern|new|unsafe|partial|event)\s+)+[^;=]*?"
    r"(?:\(|\{|;|=|$)"
)
TYPE_RE = (
    r"^\s*(?:\[[^\]]+\]\s*)*(?:(?:public|internal|private|protected|static|abstract|sealed|"
    r"partial|readonly|ref)\s+)*(?:class|struct|interface|enum|record)\s+{name}\b"
)


def cache_dir(dll: Path) -> Path:
    if dll.resolve() == GAME_DLL.resolve():
        tag = ".".join(map(str, game_version()))
    else:
        st = dll.stat()
        tag = f"{st.st_size}-{int(st.st_mtime)}"
    return CACHE / f"{dll.stem}-{tag}"


def ensure_decompiled(dll: Path, rebuild: bool = False) -> Path:
    out = cache_dir(dll)
    if rebuild and out.exists():
        shutil.rmtree(out)
    if out.exists() and any(out.rglob("*.cs")):
        return out
    exe = shutil.which("ilspycmd")
    if not exe:
        raise SystemExit("ilspycmd not found. Install: dotnet tool install -g ilspycmd")
    out.mkdir(parents=True, exist_ok=True)
    print(f"decompiling {dll.name} -> {out} (one-time, ~1 min)...", file=sys.stderr)
    refs = [f"-r={dll.parent}"]
    if dll.resolve() != GAME_DLL.resolve():
        refs.append(f"-r={GAME_DLL.parent}")
    proc = subprocess.run(
        [exe, "-p", "-o", str(out), *refs, str(dll)], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0 or not any(out.rglob("*.cs")):
        shutil.rmtree(out, ignore_errors=True)
        raise SystemExit(f"ilspycmd failed ({proc.returncode}):\n{proc.stderr[-2000:]}")
    return out


def find_type(root: Path, name: str) -> list[tuple[Path, int]]:
    """(file, line) of the declaration; tries file name first, then a declaration search."""
    simple = name.split(".")[-1]
    namespace = ".".join(name.split(".")[:-1])
    pattern = re.compile(TYPE_RE.format(name=re.escape(simple)))
    hits: list[tuple[Path, int]] = []
    candidates = [p for p in root.rglob(f"{simple}.cs")]
    if namespace:
        candidates = [
            p for p in candidates if namespace.replace(".", "/") in p.as_posix()
        ] or candidates
    for p in candidates:
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.match(line):
                hits.append((p, i))
                break
    if hits:
        return hits
    for p in root.rglob("*.cs"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if simple not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.match(line):
                hits.append((p, i))
    return hits


def outline(path: Path, start: int) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = [f"{start}: {lines[start - 1].strip()}"]
    for i, line in enumerate(lines[start:], start + 1):
        if MEMBER_RE.match(line):
            out.append(f"{i}: {line.strip()}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("type", nargs="?", help="type name, optionally namespace-qualified")
    ap.add_argument("--grep", help="regex; within TYPE's file, or the whole assembly")
    ap.add_argument("--full", action="store_true", help="print the whole file")
    ap.add_argument("--dll", type=Path, default=GAME_DLL, help="assembly (default: game)")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--rebuild", action="store_true", help="re-decompile")
    ap.add_argument("--path", action="store_true", help="print the cache directory")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = ensure_decompiled(args.dll, args.rebuild)
    if args.path:
        print(root)
        return 0
    if not args.type and not args.grep:
        ap.error("give TYPE and/or --grep")

    if args.type:
        hits = find_type(root, args.type)
        if not hits:
            print(f"type {args.type!r} not found in {args.dll.name}")
            return 1
        for path, line in hits:
            rel = path.relative_to(root).as_posix()
            n = sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
            print(f"{path}  ({rel}, {n} lines, declared at line {line})")
            if args.full:
                print(path.read_text(encoding="utf-8", errors="replace"))
            elif args.grep:
                rx = re.compile(args.grep)
                for i, text in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if rx.search(text):
                        print(f"{i}: {text.rstrip()}")
            else:
                body = outline(path, line)
                print("\n".join(body[: args.limit * 4]))
                if len(body) > args.limit * 4:
                    print(f"... {len(body) - args.limit * 4} more members (use --grep / Read)")
        return 0

    rx = re.compile(args.grep)
    count = 0
    for path in sorted(root.rglob("*.cs")):
        for i, text in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if rx.search(text):
                count += 1
                if count <= args.limit:
                    print(f"{path.relative_to(root).as_posix()}:{i}: {text.strip()}")
    if count > args.limit:
        print(f"... {count - args.limit} more matches (--limit)")
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
