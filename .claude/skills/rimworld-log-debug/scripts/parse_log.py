"""Summarise a RimWorld Player.log without loading it into memory.

    python parse_log.py [FILE] [--prev] [--since-startup] [--top N] [--mod PKG] [--grep RE]
                        [--json] [--mods-json PATH] [--all-noise]

Streams the file once, groups consecutive lines into entries (a message plus its stack trace and
`[Source:]`/`[File:]` annotations), classifies each entry against the signature catalogue in
../reference/signatures.md, dedupes by a normalised signature and reports per session:
the active mod list RimWorld printed, the first real error, the top recurring entries with
counts and the mods implicated. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LOG = Path(
    os.path.expanduser(
        "~/AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios/Player.log"
    )
)
WORKSPACE_LOG = Path(__file__).resolve().parents[4] / "links" / "logs" / "Player.log"

# ---------------------------------------------------------------- catalogue

# (name, regex, kind, severity). First match wins; order matters for overlapping patterns.
# kind: noise | load | runtime | save | perf | info
SIGNATURES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "fallback_dll",
        re.compile(r"^Fallback handler could not load library"),
        "noise",
        "none",
    ),
    ("thread_abort", re.compile(r"ThreadAbortException"), "noise", "none"),
    ("texture_mult4", re.compile(r"^Texture .* not multiples of 4"), "noise", "none"),
    ("prepatcher", re.compile(r"^Prepatcher:"), "info", "none"),
    ("keybind_conflict", re.compile(r"^Key binding conflict:"), "info", "low"),
    ("parsed_as_int", re.compile(r"^Parsed .* as int\."), "noise", "none"),
    (
        "workshop_no_folder",
        re.compile(r"^Created WorkshopItem for (\d+) but there is no folder"),
        "load",
        "medium",
    ),
    (
        "dependency_no_url",
        re.compile(r"^Mod .* dependency \(.*\) needs to have <downloadUrl>"),
        "info",
        "low",
    ),
    (
        "xml_unknown_field",
        re.compile(
            r"^XML error: <(\w+)>.*doesn't correspond to any field in type (\w+)"
        ),
        "load",
        "high",
    ),
    ("xml_error", re.compile(r"^XML error:"), "load", "high"),
    (
        "xref_unresolved",
        re.compile(
            r"^Could not resolve cross-reference to (\S+) named (\S+) \(wanter=(\w+)\)"
        ),
        "load",
        "medium",
    ),
    (
        "type_not_found",
        re.compile(r"^Could not find a type named (\S+)"),
        "load",
        "high",
    ),
    ("def_not_found", re.compile(r"Def named (\S+) not found"), "load", "medium"),
    (
        "duplicate_def",
        re.compile(r"^(?:Duplicate|.*duplicate) (?:defName|def name)", re.IGNORECASE),
        "load",
        "medium",
    ),
    (
        "assembly_missing",
        re.compile(r"Cannot resolve dependency to assembly '([^',]+)"),
        "load",
        "low",
    ),
    (
        "reflection_typeload",
        re.compile(r"ReflectionTypeLoadException"),
        "load",
        "high",
    ),
    (
        "missing_method",
        re.compile(r"MissingMethodException|MissingFieldException"),
        "runtime",
        "high",
    ),
    ("typeload", re.compile(r"\bTypeLoadException"), "load", "high"),
    ("exception_ticking", re.compile(r"^Exception ticking"), "runtime", "high"),
    (
        "exception_window",
        re.compile(r"^Exception filling window for (\S+)"),
        "runtime",
        "medium",
    ),
    ("exception_drawing", re.compile(r"^Exception draw"), "runtime", "medium"),
    (
        "exception_jobdriver",
        re.compile(r"^Exception in JobDriver"),
        "runtime",
        "medium",
    ),
    (
        "exception_loading_save",
        re.compile(r"^Exception (?:loading|from asynchronous)", re.IGNORECASE),
        "save",
        "high",
    ),
    (
        "save_load_error",
        re.compile(
            r"(?:Could not load reference to|Loading saved|SaveLoad)", re.IGNORECASE
        ),
        "save",
        "medium",
    ),
    (
        "harmony_exception",
        re.compile(
            r"HarmonyException|Patching exception in method|Error while patching"
        ),
        "runtime",
        "high",
    ),
    ("null_ref", re.compile(r"NullReferenceException"), "runtime", "high"),
    (
        "generic_exception",
        re.compile(r"^(?:\w+\.)*\w*Exception\b|^Exception "),
        "runtime",
        "medium",
    ),
    (
        "error_word",
        re.compile(r"\b(?:error|exception)\b(?!.*Failed count)", re.IGNORECASE),
        "runtime",
        "low",
    ),
]

SESSION_START = re.compile(r"^Mono path\[0\] = ")
MODLIST_START = re.compile(r"^Initializing new game with mods:")
MODLIST_ITEM = re.compile(r"^  - (\S+)")
SOURCE_LINE = re.compile(r"^\[Source: (.+?)\]")
FILE_LINE = re.compile(r"^\[File: (.+?)\]")
REF_LINE = re.compile(r"^\[Ref ([0-9A-F]+)\]( Duplicate stacktrace)?")
BRACKET_TAG = re.compile(r"^(?:<color=[^>]+>)?\[([^\]\n]{2,40})\]")
STACK_FRAME = re.compile(r"^\s*at (\S+?) ?\(")
CONTINUATION = re.compile(
    r"^(?:\s+at |\s*\(wrapper |\[Source: |\[File: |\[Ref |Possible Matches:|Context: |\s*$|"
    r"--- End of|Parameter name:|Rethrow as |\s+--- |Error in |\s*Verse\.|\s*RimWorld\.|"
    r"(?:System|Verse|RimWorld|UnityEngine)\.[\w.]*Exception\b|\s*at \S)"
)
WORKSHOP_PATH = re.compile(r"[\\/]workshop[\\/]content[\\/]294100[\\/](\d+)[\\/]")
MODS_PATH = re.compile(r"[\\/]RimWorld[\\/]Mods[\\/]([^\\/]+)[\\/]")
NOISE_TOKENS = re.compile(
    r"(0x[0-9A-Fa-f]+|<[0-9a-f]{32}>|thread=\d+|\[Ref [0-9A-F]+\]|\d+(?:\.\d+)?(?:ms|s)\b|"
    r"ID \d+|\bmap with ID \d+|-\d{8,}\b|\b\d{5,}\b)"
)
ENGINE_FRAMES = (
    "System.",
    "UnityEngine.",
    "Verse.",
    "RimWorld.",
    "HarmonyLib.",
    "Mono.",
    "(wrapper",
)


@dataclass
class Entry:
    line_no: int
    message: str
    lines: list[str] = field(default_factory=list)
    ref: str | None = None
    duplicate_of: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Signature:
    name: str
    kind: str
    severity: str
    key: str
    sample: str
    first_line: int
    count: int = 0
    mods: Counter = field(default_factory=Counter)

    def signature_label(self) -> str:
        return f"{self.name}/{self.severity}"


@dataclass
class Session:
    start_line: int
    mods: list[str] = field(default_factory=list)
    signatures: OrderedDict[str, Signature] = field(default_factory=OrderedDict)
    noise: Counter = field(default_factory=Counter)
    first_error: Signature | None = None
    entries: int = 0
    refs: dict[str, str] = field(default_factory=dict)  # ref id -> signature key


# ---------------------------------------------------------------- parsing


def iter_lines(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            yield line.rstrip("\r\n")


def iter_entries(lines: Iterable[str]) -> Iterator[Entry | tuple[str, int, str]]:
    """Yield Entry objects, or ('session', line_no, text) / ('mod', line_no, packageId) markers.

    An entry is a top-level line followed by continuation lines (stack frames, annotations).
    Blank lines are rare in Player.log, so continuation is decided by line shape, not gaps.
    """
    current: Entry | None = None
    in_modlist = False
    for n, line in enumerate(lines, 1):
        if SESSION_START.match(line):
            if current:
                yield current
                current = None
            yield ("session", n, line)
            continue
        if MODLIST_START.match(line):
            if current:
                yield current
                current = None
            in_modlist = True
            continue
        if in_modlist:
            m = MODLIST_ITEM.match(line)
            if m:
                yield ("mod", n, m.group(1))
                continue
            in_modlist = False
        if current is not None and CONTINUATION.match(line):
            current.lines.append(line)
            m = REF_LINE.match(line)
            if m:
                if m.group(2):
                    current.duplicate_of = m.group(1)
                else:
                    current.ref = m.group(1)
            continue
        if current:
            yield current
        current = Entry(n, line, [line])
    if current:
        yield current


def classify(entry: Entry) -> tuple[str, str, str] | None:
    head = entry.message
    # Exceptions are often announced on the line after "Exception thrown from thread=..." etc.
    probe = head if len(entry.lines) == 1 else "\n".join(entry.lines[:3])
    for name, rx, kind, sev in SIGNATURES:
        if rx.search(head) or rx.search(probe):
            return name, kind, sev
    return None


def normalise(entry: Entry, name: str) -> str:
    """Signature key: catalogue name + message with volatile tokens stripped + first mod frame."""
    msg = NOISE_TOKENS.sub("#", entry.message)[:160]
    frame = first_mod_frame(entry) or ""
    return f"{name}|{msg}|{frame}"


def first_mod_frame(entry: Entry) -> str | None:
    """First stack frame whose namespace is not engine/vanilla. Harmony wrappers are skipped."""
    for line in entry.lines:
        m = STACK_FRAME.match(line)
        if not m:
            continue
        sym = m.group(1)
        if sym.startswith(ENGINE_FRAMES):
            continue
        if "_Patch" in sym or "DMD<" in sym:
            continue
        return sym.rsplit(".", 1)[0]
    return None


def harmony_patch_frames(entry: Entry) -> list[str]:
    out = []
    for line in entry.lines:
        if "(wrapper dynamic-method)" in line or "_Patch" in line or "DMD<" in line:
            m = re.search(r"([\w.]+)_Patch\d*", line) or re.search(
                r"DMD<[^>]*>\?\S*?([\w.]+)", line
            )
            if m:
                out.append(m.group(1))
    return out


def attribute(entry: Entry, mod_index: dict[str, str]) -> list[str]:
    """Mods implicated by an entry, most reliable evidence first."""
    found: list[str] = []
    for line in entry.lines:
        m = SOURCE_LINE.match(line)
        if m:
            found.append(f"source:{m.group(1)}")
        m = FILE_LINE.match(line)
        if m:
            w = WORKSHOP_PATH.search(m.group(1))
            if w:
                found.append(f"pfid:{w.group(1)}")
            l = MODS_PATH.search(m.group(1))
            if l:
                found.append(f"local:{l.group(1)}")
    m = BRACKET_TAG.match(entry.message)
    if m and not SOURCE_LINE.match(entry.message) and not REF_LINE.match(entry.message):
        found.append(f"tag:{m.group(1)}")
    frame = first_mod_frame(entry)
    if frame:
        ns = frame.split(".")[0]
        found.append(f"ns:{mod_index.get(ns.lower(), ns)}")
    for patcher in harmony_patch_frames(entry):
        ns = patcher.split(".")[0]
        found.append(f"harmony:{mod_index.get(ns.lower(), ns)}")
    for line in entry.lines:
        w = WORKSHOP_PATH.search(line)
        if w and f"pfid:{w.group(1)}" not in found:
            found.append(f"pfid:{w.group(1)}")
            break
    # Preserve order, drop duplicates.
    return list(OrderedDict.fromkeys(found))


def parse(
    path: Path, mod_index: dict[str, str] | None = None, grep: re.Pattern | None = None
) -> list[Session]:
    mod_index = mod_index or {}
    sessions: list[Session] = [Session(start_line=1)]
    for item in iter_entries(iter_lines(path)):
        if isinstance(item, tuple):
            kind, n, val = item
            if kind == "session":
                if sessions[-1].entries == 0 and not sessions[-1].mods:
                    sessions[-1].start_line = n
                else:
                    sessions.append(Session(start_line=n))
            else:
                sessions[-1].mods.append(val)
            continue
        s = sessions[-1]
        s.entries += 1
        if grep and not grep.search(item.text):
            continue
        cls = classify(item)
        if cls is None:
            continue
        name, kind, sev = cls
        if kind in ("noise", "info"):
            s.noise[name] += 1
            continue
        if item.duplicate_of and item.duplicate_of in s.refs:
            key = s.refs[item.duplicate_of]
        else:
            key = normalise(item, name)
            if item.ref:
                s.refs[item.ref] = key
        sig = s.signatures.get(key)
        if sig is None:
            sig = Signature(
                name, kind, sev, key, "\n".join(item.lines[:12]), item.line_no
            )
            s.signatures[key] = sig
            if (
                s.first_error is None
                and sev in ("high", "medium")
                and kind in ("load", "runtime", "save")
            ):
                s.first_error = sig
        sig.count += 1
        for mod in attribute(item, mod_index):
            sig.mods[mod] += 1
    return sessions


# ---------------------------------------------------------------- mod index


def load_mod_index(path: Path) -> dict[str, str]:
    """Map lowercase assembly/namespace hints -> packageId from a saved list_installed_mods result."""
    data = json.loads(path.read_text(encoding="utf-8"))
    mods = data.get("mods", data) if isinstance(data, dict) else data
    index: dict[str, str] = {}
    for m in mods:
        pid = m.get("package_id") or m.get("packageId") or ""
        if not pid:
            continue
        author, _, name = pid.partition(".")
        for hint in (name, author, m.get("name", "")):
            if hint:
                index.setdefault(hint.lower().replace(" ", ""), pid)
        for asm in m.get("assemblies", []):
            index.setdefault(Path(asm).stem.lower(), pid)
    return index


# ---------------------------------------------------------------- output

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


def ranked(session: Session, top: int, mod: str | None) -> list[Signature]:
    sigs = [s for s in session.signatures.values() if s.kind not in ("noise",)]
    if mod:
        m = mod.lower()
        sigs = [s for s in sigs if any(m in k.lower() for k in s.mods)]
    sigs.sort(key=lambda s: (SEV_ORDER[s.severity], -s.count, s.first_line))
    return sigs[:top]


def to_dict(session: Session, top: int, mod: str | None) -> dict:
    return {
        "start_line": session.start_line,
        "mod_count": len(session.mods),
        "mods": session.mods,
        "entries": session.entries,
        "first_error": _sig_dict(session.first_error) if session.first_error else None,
        "top": [_sig_dict(s) for s in ranked(session, top, mod)],
        "noise": dict(session.noise),
    }


def _sig_dict(s: Signature) -> dict:
    return {
        "signature": s.name,
        "kind": s.kind,
        "severity": s.severity,
        "count": s.count,
        "first_line": s.first_line,
        "mods": [f"{k} x{v}" for k, v in s.mods.most_common(6)],
        "sample": s.sample,
    }


def render_markdown(
    sessions: list[Session], top: int, mod: str | None, all_noise: bool
) -> str:
    out: list[str] = []
    for i, s in enumerate(sessions, 1):
        out.append(
            f"## Session {i} (line {s.start_line}) — {s.entries} entries, {len(s.mods)} active mods"
        )
        if s.first_error:
            fe = s.first_error
            out.append(
                f"\n**First real error** (line {fe.first_line}, {fe.signature_label()}):\n"
            )
            out.append("```\n" + fe.sample[:600] + "\n```")
        sigs = ranked(s, top, mod)
        if sigs:
            out.append(f"\n### Top {len(sigs)} entries\n")
            out.append("| # | count | sev | signature | first line | mods |")
            out.append("|---|---|---|---|---|---|")
            for n, sig in enumerate(sigs, 1):
                mods = ", ".join(f"{k}×{v}" for k, v in sig.mods.most_common(3)) or "—"
                out.append(
                    f"| {n} | {sig.count} | {sig.severity} | {sig.name} | {sig.first_line} | {mods} |"
                )
            out.append("")
            for n, sig in enumerate(sigs, 1):
                out.append(
                    f"<details><summary>#{n} {sig.name} ×{sig.count}</summary>\n"
                )
                out.append("```\n" + sig.sample[:900] + "\n```\n</details>")
        else:
            out.append("\nNo classified errors.")
        if s.noise:
            shown = s.noise.most_common(None if all_noise else 6)
            out.append("\nNoise/info: " + ", ".join(f"{k}×{v}" for k, v in shown))
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- cli


def resolve_log(arg: str | None, prev: bool) -> Path:
    if arg:
        p = Path(arg)
    elif WORKSPACE_LOG.exists():
        p = WORKSPACE_LOG
    else:
        p = DEFAULT_LOG
    if prev:
        p = p.with_name("Player-prev.log")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Summarise a RimWorld Player.log")
    ap.add_argument("file", nargs="?", help="log file (default: links/logs/Player.log)")
    ap.add_argument(
        "--prev", action="store_true", help="use Player-prev.log next to the file"
    )
    ap.add_argument(
        "--since-startup", action="store_true", help="only the last session"
    )
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument(
        "--mod", help="only entries attributed to this mod/pfid/namespace substring"
    )
    ap.add_argument("--grep", help="regex; only entries whose text matches")
    ap.add_argument("--json", action="store_true", help="JSON instead of markdown")
    ap.add_argument(
        "--mods-json", help="saved list_installed_mods output for namespace attribution"
    )
    ap.add_argument("--all-noise", action="store_true", help="list every noise bucket")
    args = ap.parse_args(argv)

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8")  # console code pages mangle the × and — glyphs
    path = resolve_log(args.file, args.prev)
    if not path.is_file():
        print(f"log not found: {path}", file=sys.stderr)
        return 2
    index = load_mod_index(Path(args.mods_json)) if args.mods_json else {}
    grep = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    sessions = parse(path, index, grep)
    if args.since_startup:
        sessions = sessions[-1:]
    if args.json:
        print(
            json.dumps(
                {
                    "file": str(path),
                    "sessions": [to_dict(s, args.top, args.mod) for s in sessions],
                },
                indent=2,
            )
        )
    else:
        print(f"# {path} ({path.stat().st_size // 1024} KB)\n")
        print(render_markdown(sessions, args.top, args.mod, args.all_noise))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
