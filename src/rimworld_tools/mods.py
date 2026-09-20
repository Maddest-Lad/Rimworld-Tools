from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from bs4 import BeautifulSoup

from . import acf, advisories, paths
from .config import RIMWORLD_APP_ID, RIMWORLD_APP_IDS, Settings

logger = logging.getLogger(__name__)

DLC_NAMES: dict[str, str] = {
    "ludeon.rimworld": "RimWorld",
    "ludeon.rimworld.royalty": "Royalty",
    "ludeon.rimworld.ideology": "Ideology",
    "ludeon.rimworld.biotech": "Biotech",
    "ludeon.rimworld.anomaly": "Anomaly",
    "ludeon.rimworld.odyssey": "Odyssey",
}
_DLC_APP_BY_PID = {
    "ludeon.rimworld": RIMWORLD_APP_IDS["base"],
    "ludeon.rimworld.royalty": RIMWORLD_APP_IDS["royalty"],
    "ludeon.rimworld.ideology": RIMWORLD_APP_IDS["ideology"],
    "ludeon.rimworld.biotech": RIMWORLD_APP_IDS["biotech"],
    "ludeon.rimworld.anomaly": RIMWORLD_APP_IDS["anomaly"],
    "ludeon.rimworld.odyssey": RIMWORLD_APP_IDS["odyssey"],
}

_PFID_URL_RE = re.compile(r"(?:CommunityFilePage/|[?&]id=)(\d+)")
_MAJOR_MINOR_RE = re.compile(r"^\s*v?(\d+)\.(\d+)")

SOURCES = ("ludeon", "steam", "steamcmd", "git", "local", "unknown")


class PackageId(str):
    """packageIds are case-insensitive everywhere in RimWorld; lowercase at the boundary."""

    def __new__(cls, value: str) -> Self:
        return super().__new__(cls, value.strip().lower())


def major_minor(version: str | None) -> str | None:
    if not version:
        return None
    m = _MAJOR_MINOR_RE.match(version)
    return f"{m.group(1)}.{m.group(2)}" if m else None


@dataclass
class Dependency:
    package_id: PackageId
    display_name: str | None = None
    pfid: str | None = None
    download_url: str | None = None
    alternatives: list[PackageId] = field(default_factory=list)


@dataclass
class AboutXml:
    package_id: PackageId | None = None
    name: str | None = None
    authors: list[str] = field(default_factory=list)
    supported_versions: list[str] = field(default_factory=list)  # normalised major.minor
    mod_version: str | None = None
    steam_app_id: int | None = None
    url: str | None = None
    dependencies: list[Dependency] = field(default_factory=list)
    load_after: list[PackageId] = field(default_factory=list)
    load_before: list[PackageId] = field(default_factory=list)
    incompatible_with: list[PackageId] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Mod:
    path: Path
    source: str
    pfid: str | None
    about: AboutXml | None
    warnings: list[str] = field(default_factory=list)

    @property
    def package_id(self) -> PackageId | None:
        return self.about.package_id if self.about else None

    @property
    def name(self) -> str:
        if self.about and self.about.name:
            return self.about.name
        if self.package_id and self.package_id in DLC_NAMES:
            return DLC_NAMES[self.package_id]
        return self.package_id or self.path.name


# --- XML helpers ---------------------------------------------------------------------------


def _find_ci(directory: Path, name: str, want_dir: bool) -> Path | None:
    """Case-insensitive child lookup; real mods ship `about/About.xml` and worse."""
    try:
        for child in directory.iterdir():
            if child.name.lower() == name.lower() and child.is_dir() == want_dir:
                return child
    except OSError:
        pass
    return None


def find_about_xml(mod_dir: Path) -> Path | None:
    about = _find_ci(mod_dir, "About", want_dir=True)
    return _find_ci(about, "About.xml", want_dir=False) if about else None


_BARE_AMP_RE = re.compile(r"&(?!(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);)")
_BARE_LT_RE = re.compile(r"<(?![A-Za-z_/!?])")


def _parse_xml(raw: str) -> tuple[ET.Element, bool]:
    """Strict, then text-level escaping of bare & and <, then BeautifulSoup as a last resort.

    lxml's recovery truncates the document at a stray `<` ("takes < 10s" in a description),
    silently dropping every field after it, so the cheap escape pass goes first.
    """
    try:
        return ET.fromstring(raw), False
    except ET.ParseError:
        pass
    escaped = _BARE_LT_RE.sub("&lt;", _BARE_AMP_RE.sub("&amp;", raw))
    try:
        return ET.fromstring(escaped), True
    except ET.ParseError:
        pass
    soup = BeautifulSoup(escaped, "lxml-xml")
    for tag in soup.find_all():
        if not tag.contents and not tag.attrs and tag.name.lower() != "li":
            tag.decompose()
    return ET.fromstring(str(soup)), True


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    lname = name.lower()
    for c in elem:
        if c.tag.lower() == lname:
            return c
    return None


def _text(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    t = (elem.text or "").strip()
    return t or None


def _is_null(elem: ET.Element) -> bool:
    return any(k.lower() == "isnull" and str(v).lower() == "true" for k, v in elem.attrib.items())


def _li_texts(elem: ET.Element | None) -> list[str]:
    """`<li>` list, or a bare string, as list[str]. Skips isNull/empty entries."""
    if elem is None:
        return []
    items = [c for c in elem if c.tag.lower() == "li"]
    if not items:
        t = _text(elem)
        return [t] if t else []
    out: list[str] = []
    for li in items:
        if _is_null(li):
            continue
        t = _text(li)
        if t:
            out.append(t)
    return out


def _versioned(elem: ET.Element, base: str, game_mm: str | None) -> ET.Element | None:
    """`<base>ByVersion/<v1.6>` replaces `<base>` entirely when the game version matches."""
    by = _child(elem, f"{base}ByVersion")
    if by is not None and game_mm:
        keys = {c.tag.lower(): c for c in by}
        for k in (f"v{game_mm}", game_mm):
            if k in keys:
                return keys[k]
        for k, c in keys.items():
            if k.startswith(f"v{game_mm}."):
                return c
    return _child(elem, base)


def _pfid_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _PFID_URL_RE.search(url)
    return m.group(1) if m else None


def _dependency(li: ET.Element) -> Dependency | None:
    pid = _text(_child(li, "packageId"))
    if not pid:
        return None
    # Real mods write steamWorkshopUrl; RimSort reads workshopUrl (a bug). Accept both.
    url = _text(_child(li, "steamWorkshopUrl")) or _text(_child(li, "workshopUrl"))
    return Dependency(
        package_id=PackageId(pid),
        display_name=_text(_child(li, "displayName")),
        pfid=_pfid_from_url(url),
        download_url=_text(_child(li, "downloadUrl")),
        alternatives=[PackageId(a) for a in _li_texts(_child(li, "alternativePackageIds"))],
    )


def parse_about(path: Path, game_mm: str | None) -> AboutXml:
    out = AboutXml()
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    root, repaired = _parse_xml(raw)
    if repaired:
        out.warnings.append("About.xml was malformed; parsed leniently")
    if root.tag.lower() != "modmetadata":
        out.warnings.append(f"unexpected root <{root.tag}>")

    pid = _text(_child(root, "packageId"))
    out.package_id = PackageId(pid) if pid else None
    if out.package_id is None:
        out.warnings.append("no packageId")
    out.name = _text(_child(root, "name"))
    authors = _li_texts(_child(root, "authors"))
    single = _text(_child(root, "author"))
    if single:
        authors = [a.strip() for a in single.split(",") if a.strip()] + authors
    out.authors = list(dict.fromkeys(authors))
    out.mod_version = _text(_child(root, "modVersion"))
    out.url = _text(_child(root, "url"))

    raw_versions = _li_texts(_child(root, "supportedVersions"))
    # Normalise once here and compare normalised values everywhere; RimSort normalises on the
    # display path only and compares raw strings, producing false "unsupported" warnings.
    out.supported_versions = list(dict.fromkeys(mm for v in raw_versions if (mm := major_minor(v))))

    app = _text(_child(root, "steamAppId"))
    if app and app.isdigit():
        out.steam_app_id = int(app)
    elif out.package_id in _DLC_APP_BY_PID:
        out.steam_app_id = _DLC_APP_BY_PID[out.package_id]

    deps_elem = _versioned(root, "modDependencies", game_mm)
    if deps_elem is not None:
        for li in deps_elem:
            if li.tag.lower() == "li" and not _is_null(li):
                d = _dependency(li)
                if d:
                    out.dependencies.append(d)

    def rule(base: str) -> list[PackageId]:
        ids = _li_texts(_versioned(root, base, game_mm))
        # force* variants are always applied, never replaced by *ByVersion.
        ids += _li_texts(_child(root, f"force{base[0].upper()}{base[1:]}"))
        return [PackageId(i) for i in dict.fromkeys(ids)]

    out.load_after = rule("loadAfter")
    out.load_before = rule("loadBefore")
    out.incompatible_with = rule("incompatibleWith")
    return out


# --- classification and scanning --------------------------------------------------------


def read_pfid_file(mod_dir: Path) -> str | None:
    about = _find_ci(mod_dir, "About", want_dir=True)
    f = _find_ci(about, "PublishedFileId.txt", want_dir=False) if about else None
    if f is None:
        return None
    try:
        s = f.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return s if s.isdigit() and int(s) > 0 else None


def recover_pfid(mod_dir: Path) -> str | None:
    if pfid := read_pfid_file(mod_dir):
        return pfid
    n = mod_dir.name
    return n if n.isdigit() and int(n) > 0 else None


def classify(
    mod_dir: Path, data_dir: Path | None, mods_dir: Path | None, workshop_dir: Path | None
) -> str:
    parent = mod_dir.parent
    if data_dir and parent == data_dir:
        return "ludeon"
    if workshop_dir and parent == workshop_dir:
        return "steam"
    if mods_dir and parent == mods_dir:
        pfid_file = read_pfid_file(mod_dir)
        # SteamCMD before git: some Workshop items ship a stray .git directory.
        if pfid_file and pfid_file == mod_dir.name:
            return "steamcmd"
        if (mod_dir / ".git").exists():  # this folder's repo, not an ancestor's
            return "git"
        if pfid_file:
            return "steamcmd"
        return "local"
    return "unknown"


def load_mod(mod_dir: Path, source: str, game_mm: str | None) -> Mod:
    about_path = find_about_xml(mod_dir)
    if about_path is None:
        warn = "no About/About.xml"
        if any(p.suffix.lower() == ".rsc" for p in mod_dir.iterdir() if p.is_file()):
            warn = "scenario folder (.rsc), not a mod"
        return Mod(
            path=mod_dir, source=source, pfid=recover_pfid(mod_dir), about=None, warnings=[warn]
        )
    try:
        about = parse_about(about_path, game_mm)
    except (ET.ParseError, OSError, ValueError) as exc:
        return Mod(
            path=mod_dir,
            source=source,
            pfid=recover_pfid(mod_dir),
            about=None,
            warnings=[f"About.xml unparseable: {exc}"],
        )
    if about_path.parent.name != "About" or about_path.name != "About.xml":
        about.warnings.append(f"non-standard casing: {about_path.relative_to(mod_dir)}")
    return Mod(path=mod_dir, source=source, pfid=recover_pfid(mod_dir), about=about)


def _subdirs(root: Path | None) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    try:
        return sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []


@dataclass
class Inventory:
    mods: list[Mod]
    game_version: str | None
    by_package_id: dict[PackageId, list[Mod]]
    roots: dict[str, str | None]


def scan(settings: Settings) -> Inventory:
    found = paths.discover(settings)
    game_dir = Path(found.game_dir.path) if found.game_dir else None
    data_dir = game_dir / "Data" if game_dir else None
    mods_dir = (
        settings.mods_dir
        if settings.mods_dir
        else (Path(found.mods_dir.path) if found.mods_dir else None)
    )
    workshop_dir = Path(found.workshop_dir.path) if found.workshop_dir else None
    game_mm = major_minor(found.version)

    mods: list[Mod] = []
    for root in (data_dir, mods_dir, workshop_dir):
        for d in _subdirs(root):
            mods.append(load_mod(d, classify(d, data_dir, mods_dir, workshop_dir), game_mm))

    index: dict[PackageId, list[Mod]] = {}
    for m in mods:
        if m.package_id:
            index.setdefault(m.package_id, []).append(m)
    return Inventory(
        mods=mods,
        game_version=found.version,
        by_package_id=index,
        roots={
            "data": str(data_dir) if data_dir else None,
            "mods": str(mods_dir) if mods_dir else None,
            "workshop": str(workshop_dir) if workshop_dir else None,
        },
    )


# --- tool-facing shaping ----------------------------------------------------------------


def _timestamps(settings: Settings, inv: Inventory) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    steam_root = paths.find_steam_root()
    if steam_root:
        client = (
            Path(steam_root.path) / "steamapps" / "workshop" / f"appworkshop_{RIMWORLD_APP_ID}.acf"
        )
        if client.is_file():
            out.update({p: i.timeupdated for p, i in acf.items(acf.load(client)).items()})
    if settings.acf_path.is_file():
        out.update({p: i.timeupdated for p, i in acf.items(acf.load(settings.acf_path)).items()})
    return out


def _record(
    m: Mod,
    game_mm: str | None,
    detail: bool,
    timeupdated: int | None,
    ctx: advisories.Context,
    installed: set[str],
) -> dict[str, Any]:
    a = m.about
    supported = a.supported_versions if a else []
    version_ok: bool | None = None if not supported or not game_mm else game_mm in supported
    rec: dict[str, Any] = {
        "package_id": m.package_id,
        "name": m.name,
        "source": m.source,
        "pfid": m.pfid,
        "version_ok": version_ok,
    }
    warnings = list(m.warnings) + (list(a.warnings) if a else [])
    if warnings:
        rec["warnings"] = warnings
    found = advisories.for_mod(
        ctx,
        m.package_id,
        m.pfid,
        supported,
        version_ok,
        None,
        [
            (d.package_id, d.display_name, d.pfid, list(d.alternatives))
            for d in (a.dependencies if a else [])
        ],
        installed,
    )
    if found:
        rec["advisories"] = found
    if detail:
        rec.update(
            {
                "path": str(m.path),
                "authors": a.authors if a else [],
                "supported_versions": supported,
                "mod_version": a.mod_version if a else None,
                "timeupdated": timeupdated,
                "dependencies": [
                    {"package_id": d.package_id, "name": d.display_name, "pfid": d.pfid}
                    for d in (a.dependencies if a else [])
                ],
                "load_after": list(a.load_after) if a else [],
                "load_before": list(a.load_before) if a else [],
                "incompatible_with": list(a.incompatible_with) if a else [],
            }
        )
    return rec


def inventory(
    settings: Settings,
    source: str | None = None,
    package_ids: list[str] | None = None,
    detail: bool = False,
    include_invalid: bool = False,
) -> dict[str, Any]:
    if source and source not in SOURCES:
        return {"error": f"Unknown source {source!r}.", "hint": f"One of {list(SOURCES)}."}
    inv = scan(settings)
    game_mm = major_minor(inv.game_version)
    wanted = {PackageId(p) for p in package_ids} if package_ids else None
    stamps = _timestamps(settings, inv) if detail else {}

    mods = inv.mods
    if source:
        mods = [m for m in mods if m.source == source]
    if wanted is not None:
        mods = [m for m in mods if m.package_id in wanted]
    if not include_invalid:
        mods = [m for m in mods if m.about is not None]

    ctx = advisories.Context.load(settings, game_mm)
    installed = {m.package_id for m in inv.mods if m.package_id}
    records = [_record(m, game_mm, detail, stamps.get(m.pfid or ""), ctx, installed) for m in mods]
    duplicates = {
        pid: [str(x.path) for x in ms]
        for pid, ms in inv.by_package_id.items()
        if len(ms) > 1 and (wanted is None or pid in wanted)
    }
    out: dict[str, Any] = {
        "game_version": inv.game_version,
        "roots": inv.roots,
        "count": len(records),
        "by_source": {
            s: sum(1 for m in mods if m.source == s)
            for s in SOURCES
            if any(m.source == s for m in mods)
        },
        "mods": records,
    }
    if duplicates:
        out["duplicates"] = duplicates
    if notice := ctx.db_notice():
        out["notice"] = notice
    flagged = sum(1 for r in records if r.get("advisories"))
    if flagged:
        out["mods_with_advisories"] = flagged
    invalid = sum(1 for m in inv.mods if m.about is None)
    if invalid and not include_invalid:
        out["invalid_folders"] = invalid
        out["hint"] = (
            "Folders without a parseable About.xml were omitted; include_invalid=true lists them."
        )
    if wanted is not None:
        missing = sorted(wanted - {m.package_id for m in mods if m.package_id})
        if missing:
            out["not_installed"] = missing
    return out
