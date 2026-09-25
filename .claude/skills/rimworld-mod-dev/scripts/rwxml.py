"""Shared loader that mirrors RimWorld 1.6's XML pipeline closely enough for offline checks.

Behaviour copied from the decompiled game (Verse.ModContentPack.InitLoadFolders,
DirectXmlLoader.XmlAssetsInModFolder, LoadedModManager.CombineIntoUnifiedXML / ApplyPatches /
ParseAndProcessXML, XmlInheritance, PatchOperation*):

- load folders: LoadFolders.xml (best defined version <= game version, else `default`), otherwise
  `<major.minor>/` (or best older version folder), `Common/`, root; earlier = higher priority and
  the first file per relative path wins;
- every mod's `Defs/**/*.xml` top-level nodes are appended, in load order, under one `<Defs>`;
- every mod's `Patches/**/*.xml` `<Operation>` runs, in load order, against that document;
- then inheritance (Name/ParentName, `Inherit="False"`, `li` appends) and MayRequire filtering.

Needs lxml (present in the rimworld-mcp uv environment and usually system-wide).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[4]
LINKS = REPO / "links"
GAME = LINKS / "game"
OFFICIAL = [
    ("ludeon.rimworld", "Core"),
    ("ludeon.rimworld.royalty", "Royalty"),
    ("ludeon.rimworld.ideology", "Ideology"),
    ("ludeon.rimworld.biotech", "Biotech"),
    ("ludeon.rimworld.anomaly", "Anomaly"),
    ("ludeon.rimworld.odyssey", "Odyssey"),
]
PARSER = etree.XMLParser(remove_blank_text=False, remove_comments=False, resolve_entities=False)
DOC_TAG = "__document__"


def norm_id(package_id: str) -> str:
    """ModLister.GetActiveModWithIdentifier(ignorePostfix: true): case-insensitive, no _steam."""
    pid = package_id.strip().lower()
    return pid.removesuffix("_steam")


def game_version(game: Path = GAME) -> tuple[int, int, int]:
    try:
        text = (game / "Version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return (1, 6, 0)
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else (1, 6, 0)


def parse_version(text: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)", text.strip().lower())
    return (int(m[1]), int(m[2])) if m else None


@dataclass
class Mod:
    package_id: str  # as written
    name: str
    root: Path
    source: str  # official | local | workshop | path
    load_order: int = 0

    @property
    def key(self) -> str:
        return norm_id(self.package_id)

    def __str__(self) -> str:
        return f"{self.name} [{self.package_id}]"


def _find_ci(directory: Path, name: str) -> Path | None:
    if not directory.is_dir():
        return None
    exact = directory / name
    if exact.exists():
        return exact
    for child in directory.iterdir():
        if child.name.lower() == name.lower():
            return child
    return None


def read_about(root: Path, source: str = "path") -> Mod | None:
    about_dir = _find_ci(root, "About")
    about = _find_ci(about_dir, "About.xml") if about_dir else None
    if about is None:
        return None
    try:
        meta = etree.parse(str(about), PARSER).getroot()
    except etree.XMLSyntaxError:
        return None
    pid = (meta.findtext("packageId") or "").strip()
    name = (meta.findtext("name") or "").strip() or root.name
    return Mod(pid or root.name, name, root, source)


def official_mods(game: Path = GAME) -> list[Mod]:
    mods = []
    for pid, folder in OFFICIAL:
        root = game / "Data" / folder
        if root.is_dir():
            # ModMetaData.Name returns the ExpansionDef label (= folder name) for official content.
            about = read_about(root)
            mods.append(Mod(about.package_id if about else pid, folder, root, "official"))
    return mods


def installed_mods() -> dict[str, Mod]:
    """packageId (normalised) -> Mod for official, links/mods and links/workshop content."""
    found: dict[str, Mod] = {m.key: m for m in official_mods()}
    for source, base in (("local", LINKS / "mods"), ("workshop", LINKS / "workshop")):
        if not base.is_dir():
            continue
        for root in sorted(base.iterdir()):
            mod = read_about(root, source) if root.is_dir() else None
            if mod and mod.key not in found:
                found[mod.key] = mod
    return found


def active_ids(config: Path = LINKS / "config" / "ModsConfig.xml") -> list[str]:
    try:
        root = etree.parse(str(config), PARSER).getroot()
    except (OSError, etree.XMLSyntaxError):
        return []
    return [li.text.strip() for li in root.findall("activeMods/li") if li.text]


def resolve_mod(spec: str, installed: dict[str, Mod] | None = None) -> Mod:
    """A directory path, packageId, or (unique) name fragment."""
    path = Path(spec)
    if path.is_dir():
        mod = read_about(path.resolve())
        if mod is None:
            raise SystemExit(f"{spec}: no About/About.xml")
        return mod
    installed = installed or installed_mods()
    if norm_id(spec) in installed:
        return installed[norm_id(spec)]
    hits = [m for m in installed.values() if spec.lower() in m.name.lower()]
    if len(hits) == 1:
        return hits[0]
    raise SystemExit(
        f"{spec}: "
        + (
            f"ambiguous ({', '.join(map(str, hits[:8]))})"
            if hits
            else "not a directory, packageId or installed mod name"
        )
    )


# --- load folders -------------------------------------------------------------------------


@dataclass
class LoadFolder:
    folder: str
    any_of: list[str] = field(default_factory=list)
    all_of: list[str] = field(default_factory=list)
    none_of: list[str] = field(default_factory=list)

    def should_load(self, active: set[str] | None) -> bool:
        if active is None:  # unknown mod set: assume every conditional folder loads
            return True
        if self.any_of and not any(norm_id(p) in active for p in self.any_of):
            return False
        if self.all_of and not all(norm_id(p) in active for p in self.all_of):
            return False
        return not (self.none_of and any(norm_id(p) in active for p in self.none_of))


def read_load_folders(root: Path) -> dict[str, list[LoadFolder]]:
    lf = _find_ci(root, "LoadFolders.xml")
    if lf is None:
        return {}
    out: dict[str, list[LoadFolder]] = {}
    doc = etree.parse(str(lf), PARSER).getroot()
    for vnode in doc:
        if not isinstance(vnode.tag, str):
            continue
        key = vnode.tag.lower()
        key = key.removeprefix("v")
        folders = out.setdefault(key, [])
        for li in vnode:
            if not isinstance(li.tag, str):
                continue

            def ids(attr: str, li=li) -> list[str]:
                v = li.get(attr)
                return [s.strip() for s in v.split(",")] if v else []

            text = (li.text or "").strip()
            folders.append(
                LoadFolder(
                    "" if text in ("/", "\\") else text.strip("/\\"),
                    ids("IfModActive"),
                    ids("IfModActiveAll"),
                    ids("IfModNotActive"),
                )
            )
    return out


def load_folders(
    mod: Mod, active: set[str] | None = None, version: tuple[int, int] | None = None
) -> list[Path]:
    """Folders in descending priority, like ModContentPack.foldersToLoadDescendingOrder."""
    version = version or game_version()[:2]
    root = mod.root
    defined = read_load_folders(root)
    if defined:
        chosen = defined.get(f"{version[0]}.{version[1]}")
        if not chosen:
            older = sorted(
                (v for v in defined if (pv := parse_version(v)) and pv <= version),
                key=parse_version,
                reverse=True,
            )
            chosen = defined[older[0]] if older else defined.get("default")
        if chosen:
            return [
                root / f.folder if f.folder else root
                for f in reversed(chosen)
                if f.should_load(active)
            ]
    out: list[Path] = []
    exact = root / f"{version[0]}.{version[1]}"
    if exact.is_dir():
        out.append(exact)
    else:
        versions = sorted(
            pv for d in root.iterdir() if d.is_dir() and (pv := parse_version(d.name))
        )
        best = None
        for v in versions:
            if best is None or (v <= version and (best > version or v > best)):
                best = v
        if best is not None:
            out.append(root / f"{best[0]}.{best[1]}")
    if (root / "Common").is_dir():
        out.append(root / "Common")
    out.append(root)
    return out


def xml_files(mod: Mod, sub: str, active: set[str] | None = None) -> list[Path]:
    """`Defs/` or `Patches/` XML files the game would load; first relative path wins."""
    seen: dict[str, Path] = {}
    for folder in load_folders(mod, active):
        base = _find_ci(folder, sub)
        if base is None:
            continue
        for f in sorted(base.rglob("*.xml")):
            if f.name.startswith("."):
                continue
            seen.setdefault(f.relative_to(base).as_posix().lower(), f)
    return list(seen.values())


# --- unified def document -----------------------------------------------------------------


@dataclass
class Origin:
    mod: Mod
    file: Path

    def where(self, node: etree._Element | None = None) -> str:
        try:
            rel = self.file.relative_to(self.mod.root).as_posix()
        except ValueError:
            rel = str(self.file)
        line = f":{node.sourceline}" if node is not None and node.sourceline else ""
        return f"{self.mod.name}/{rel}{line}"


@dataclass
class DefDocument:
    """`<__document__><Defs>…</Defs></__document__>`; the wrapper stands in for the XML
    document node so relative XPaths (`Defs/ThingDef`) behave like .NET's SelectNodes."""

    wrapper: etree._Element
    origins: dict[etree._Element, Origin]
    mods: list[Mod]
    active: set[str]
    errors: list[str] = field(default_factory=list)

    @property
    def defs(self) -> etree._Element:
        return self.wrapper[0]

    def origin(self, node: etree._Element) -> Origin | None:
        while node is not None:
            if node in self.origins:
                return self.origins[node]
            node = node.getparent()
        return None

    def select(self, xpath: str) -> list:
        fast = self._select_indexed(xpath)
        if fast is not None:
            return fast
        return self.wrapper.xpath(to_document_xpath(xpath))

    # Most patches target `Defs/Type[defName="X" (or defName="Y")*]/rest`. Scanning all ~40k
    # top-level nodes per operation is what makes a full active list slow, so those paths are
    # answered from a (type, defName) index that is rebuilt whenever an operation touches the
    # top level or a defName (see `invalidate`).
    _index: dict | None = None

    def invalidate(self) -> None:
        self._index = None

    def _build_index(self) -> dict:
        index: dict = {}
        for pos, node in enumerate(self.defs):
            if isinstance(node.tag, str):
                node_dn = node.find("defName")
                dn = node_dn.text.strip() if node_dn is not None and node_dn.text else None
                if dn is not None:
                    index.setdefault((node.tag, dn), []).append((pos, node))
                    index.setdefault(("*", dn), []).append((pos, node))
        return index

    def _select_indexed(self, xpath: str) -> list | None:
        m = FAST_XPATH_RE.match(xpath)
        if not m or "|" in m["rest"] or m["rest"][:1] not in ("", "/"):
            return None
        names = DEFNAME_LITERAL_RE.findall(m["names"])
        if self._index is None:
            self._index = self._build_index()
        hits = sorted(
            {
                id(n): (p, n) for dn in names for p, n in self._index.get((m["type"], dn), [])
            }.values(),
            key=lambda pn: pn[0],
        )
        if not m["rest"]:
            return [n for _, n in hits]
        out: list = []
        for _, n in hits:
            out.extend(n.xpath("." + m["rest"]))
        return out


FAST_XPATH_RE = re.compile(
    r"""^\s*/?Defs/(?P<type>\w+|\*)\[(?P<names>\s*defName\s*=\s*(["'])[^"']*\3"""
    r"""(?:\s+or\s+defName\s*=\s*(["'])[^"']*\4)*)\s*\](?P<rest>.*?)\s*$""",
    re.DOTALL,
)
DEFNAME_LITERAL_RE = re.compile(r"""defName\s*=\s*["']([^"']*)["']""")


def to_document_xpath(xpath: str) -> str:
    """Absolute `/Defs/...` → relative to the wrapper (which plays the document node)."""
    return re.sub(r"(^|\|)(\s*)/(?!/)", r"\1\2", xpath.strip())


def parse_file(path: Path, errors: list[str]) -> etree._Element | None:
    try:
        return etree.parse(str(path), PARSER).getroot()
    except etree.XMLSyntaxError as exc:
        errors.append(f"{path}: XML syntax error: {exc}")
        return None


def build_document(mods: Iterable[Mod], active: set[str] | None = None) -> DefDocument:
    mods = list(mods)
    for i, m in enumerate(mods):
        m.load_order = i
    active = active if active is not None else {m.key for m in mods}
    wrapper = etree.Element(DOC_TAG)
    defs = etree.SubElement(wrapper, "Defs")
    doc = DefDocument(wrapper, {}, mods, active)
    for mod in mods:
        for f in xml_files(mod, "Defs", active):
            root = parse_file(f, doc.errors)
            if root is None:
                continue
            if root.tag != "Defs":
                doc.errors.append(f"{f}: root element named {root.tag}; should be named Defs")
            for child in list(root):
                defs.append(child)
                if isinstance(child.tag, str):
                    doc.origins[child] = Origin(mod, f)
    return doc


def default_mods(
    extra: Iterable[Mod] = (), with_active: bool = False
) -> tuple[list[Mod], set[str]]:
    """Official content (+ the active list in ModsConfig order) + extra mods at the end."""
    installed = installed_mods()
    if with_active:
        ids = active_ids()
        mods = [installed[norm_id(i)] for i in ids if norm_id(i) in installed]
    else:
        mods = official_mods()
    keys = {m.key for m in mods}
    for m in extra:
        if m.key in keys:
            mods = [m if x.key == m.key else x for x in mods]  # prefer the given path
        else:
            mods.append(m)
            keys.add(m.key)
    return mods, keys


# --- inheritance --------------------------------------------------------------------------


def _is_list_element(node: etree._Element) -> bool:
    return node.tag == "li"


def merge_into(child: etree._Element, current: etree._Element) -> None:
    """XmlInheritance.RecursiveNodeCopyOverwriteElements(child, current)."""
    import copy

    if (child.get("Inherit") or "").lower() == "false":
        for c in list(current):
            current.remove(c)
        current.text = child.text
        for c in child:
            current.append(copy.deepcopy(c))
        for k, v in child.attrib.items():
            if k != "Inherit":
                current.set(k, v)
        return
    current.attrib.clear()
    current.attrib.update(child.attrib)
    elements = [c for c in child if isinstance(c.tag, str)]
    if child.text and child.text.strip():
        for c in list(current):
            current.remove(c)
        current.text = child.text
        return
    if not elements:
        if not any(isinstance(c.tag, str) for c in current):
            current.text = child.text
        return
    for item in elements:
        if _is_list_element(item):
            current.append(copy.deepcopy(item))
            continue
        existing = next((c for c in current if c.tag == item.tag), None)
        if existing is not None:
            merge_into(item, existing)
        else:
            current.append(copy.deepcopy(item))


class Inheritance:
    """Name/ParentName registry scoped by mod load order, as in XmlInheritance.GetBestParentFor."""

    def __init__(self, doc: DefDocument):
        self.doc = doc
        self.by_name: dict[str, list[etree._Element]] = {}
        for node in doc.defs:
            if isinstance(node.tag, str) and node.get("Name"):
                self.by_name.setdefault(node.get("Name"), []).append(node)

    def _order(self, node: etree._Element) -> int:
        o = self.doc.origin(node)
        return o.mod.load_order if o else -1

    def parent_of(self, node: etree._Element) -> etree._Element | None:
        name = node.get("ParentName")
        cands = self.by_name.get(name or "", [])
        if not cands:
            return None
        mine = self._order(node)
        if mine < 0:  # node added by a patch: first mod-less parent, else lowest load order
            return min(cands, key=self._order)
        eligible = [c for c in cands if self._order(c) <= mine]
        if eligible:
            return max(eligible, key=self._order)
        return next((c for c in cands if self._order(c) < 0), None)

    def chain(self, node: etree._Element) -> list[etree._Element]:
        out, seen = [node], {id(node)}
        while out[-1].get("ParentName"):
            parent = self.parent_of(out[-1])
            if parent is None or id(parent) in seen:
                break
            out.append(parent)
            seen.add(id(parent))
        return out

    def resolve(self, node: etree._Element) -> etree._Element:
        import copy

        chain = self.chain(node)
        resolved = copy.deepcopy(chain[-1])
        for descendant in reversed(chain[:-1]):
            merge_into(descendant, resolved)
        return resolved


def iter_defs(doc: DefDocument, def_type: str | None = None) -> Iterator[etree._Element]:
    for node in doc.defs:
        if isinstance(node.tag, str) and (def_type is None or node.tag == def_type):
            yield node


def label(node: etree._Element) -> str:
    dn = node.findtext("defName")
    name = node.get("Name")
    bits = [node.tag]
    if dn:
        bits.append(dn.strip())
    if name:
        bits.append(f'Name="{name}"')
    if node.get("ParentName"):
        bits.append(f'ParentName="{node.get("ParentName")}"')
    if (node.get("Abstract") or "").lower() == "true":
        bits.append("Abstract")
    return " ".join(bits)
