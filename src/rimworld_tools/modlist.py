from __future__ import annotations

import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import advisories, db, mods, paths, sorting
from .config import Settings

_STEAM_SUFFIX = "_steam"
# When one packageId is installed several times, ModsConfig names only the id; pick by source.
_PRIORITY = ("ludeon", "local", "steamcmd", "git", "steam")
_PRIORITY_STEAM = ("steam", "local", "steamcmd", "git", "ludeon")


@dataclass
class ModsConfig:
    version: str | None
    active: list[str]  # config ids exactly as written (may carry _steam)
    known_expansions: list[str]

    @property
    def active_ids(self) -> list[str]:
        return [a.removesuffix(_STEAM_SUFFIX).lower() for a in self.active]


def read_mods_config(path: Path) -> ModsConfig:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))

    def li(tag: str) -> list[str]:
        node = next((c for c in root if c.tag.lower() == tag.lower()), None)
        if node is None:
            return []
        return [(x.text or "").strip() for x in node if (x.text or "").strip()]

    ver = next((c.text for c in root if c.tag.lower() == "version"), None)
    return ModsConfig(ver.strip() if ver else None, li("activeMods"), li("knownExpansions"))


def write_mods_config(path: Path, cfg: ModsConfig) -> Path | None:
    """Update known ModsConfig fields atomically while retaining unknown root fields."""
    backup = None
    if path.is_file():
        backup = path.with_suffix(".xml.backup")
        shutil.copy2(path, backup)
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    else:
        root = ET.Element("ModsConfigData")

    def replace_list(tag: str, values: list[str]) -> None:
        existing = next((node for node in root if node.tag.lower() == tag.lower()), None)
        if existing is not None:
            root.remove(existing)
        node = ET.Element(tag)
        for value in values:
            ET.SubElement(node, "li").text = value
        root.append(node)

    version = next((node for node in root if node.tag.lower() == "version"), None)
    if cfg.version:
        if version is None:
            version = ET.Element("version")
            root.insert(0, version)
        version.text = cfg.version
    elif version is not None:
        root.remove(version)
    replace_list("activeMods", cfg.active)
    replace_list("knownExpansions", cfg.known_expansions)
    ET.indent(root, space="  ")
    body = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as tmp:
        tmp.write(body)
        temp_path = Path(tmp.name)
    try:
        temp_path.replace(path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
    return backup


def config_path(settings: Settings) -> Path | None:
    found = paths.discover(settings).config_dir
    return Path(found.path) / "ModsConfig.xml" if found else None


# --- snapshots -----------------------------------------------------------------------------


def _snap_dir(settings: Settings) -> Path:
    d = settings.db_dir / "modlists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot(settings: Settings, note: str = "", cfg: ModsConfig | None = None) -> dict[str, Any]:
    p = config_path(settings)
    if p is None or not p.is_file():
        return {"error": "ModsConfig.xml not found.", "hint": "Check rimworld_locate()."}
    cfg = cfg or read_mods_config(p)
    snap_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid4().hex[:8]}"
    payload = {
        "id": snap_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": note,
        "version": cfg.version,
        "active": cfg.active,
        "known_expansions": cfg.known_expansions,
    }
    snap_path = _snap_dir(settings) / f"{snap_id}.json"
    with snap_path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    return {"id": snap_id, "count": len(cfg.active), "note": note}


def list_snapshots(settings: Settings) -> list[dict[str, Any]]:
    out = []
    for f in sorted(_snap_dir(settings).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": d["id"],
                    "created_at": d["created_at"],
                    "note": d.get("note", ""),
                    "count": len(d["active"]),
                }
            )
        except (OSError, ValueError, KeyError):
            continue
    return out


def _load_list(settings: Settings, ref: str) -> tuple[list[str], str] | None:
    """`current`, `latest`, or a snapshot id → (config ids, label)."""
    if ref == "current":
        p = config_path(settings)
        return (read_mods_config(p).active, "current ModsConfig.xml") if p and p.is_file() else None
    files = sorted(_snap_dir(settings).glob("*.json"))
    if ref == "latest":
        if not files:
            return None
        ref = files[-1].stem
    if (
        not ref
        or Path(ref).name != ref
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in ref
        )
    ):
        return None
    f = _snap_dir(settings) / f"{ref}.json"
    if not f.is_file():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return d["active"], f"snapshot {ref}" + (f" ({d['note']})" if d.get("note") else "")


def diff(settings: Settings, old_ref: str, new_ref: str) -> dict[str, Any]:
    old = _load_list(settings, old_ref)
    new = _load_list(settings, new_ref)
    if old is None or new is None:
        return {
            "error": f"Could not load {'old' if old is None else 'new'} list.",
            "hint": "Use 'current', 'latest', or an id from modlist_snapshot(list=true).",
            "snapshots": list_snapshots(settings),
        }
    a, b = old[0], new[0]
    sa, sb = set(a), set(b)
    common = [x for x in a if x in sb]
    common_new = [x for x in b if x in sa]
    moved = [
        {"id": x, "from": a.index(x), "to": b.index(x)}
        for x in common
        if common.index(x) != common_new.index(x)
    ]
    return {
        "old": old[1],
        "new": new[1],
        "added": [x for x in b if x not in sa],
        "removed": [x for x in a if x not in sb],
        "moved": moved,
        "unchanged": len(common) - len(moved),
    }


# --- sorting orchestration ------------------------------------------------------------------


@dataclass
class Prepared:
    cfg: ModsConfig
    path: Path
    source_bytes: bytes
    resolved: dict[str, mods.Mod]  # active id -> chosen installed copy
    unresolved: list[str]
    duplicate_active: list[str]
    abouts: dict[str, mods.AboutXml]
    names: dict[str, str]
    compiled: sorting.Compiled
    inventory: mods.Inventory
    dependency_issues: list[dict[str, Any]] = field(default_factory=list)


def _choose(copies: list[mods.Mod], wants_steam: bool) -> mods.Mod:
    order = _PRIORITY_STEAM if wants_steam else _PRIORITY
    return min(
        copies, key=lambda m: (order.index(m.source) if m.source in order else 99, str(m.path))
    )


def prepare(settings: Settings) -> Prepared | dict[str, Any]:
    p = config_path(settings)
    if p is None or not p.is_file():
        return {"error": "ModsConfig.xml not found.", "hint": "Check rimworld_locate()."}
    source_bytes = p.read_bytes()
    cfg = read_mods_config(p)
    inv = mods.scan(settings)
    resolved: dict[str, mods.Mod] = {}
    unresolved: list[str] = []
    duplicate_active: list[str] = []
    for raw in cfg.active:
        pid = raw.removesuffix(_STEAM_SUFFIX).lower()
        if pid in resolved:
            duplicate_active.append(raw)
            continue
        copies = inv.by_package_id.get(mods.PackageId(pid), [])
        if copies:
            resolved[pid] = _choose(copies, raw.lower().endswith(_STEAM_SUFFIX))
        else:
            unresolved.append(raw)
    # Rules must describe the copy RimWorld will load, rather than whichever copy was scanned first.
    abouts = {pid: m.about for pid, m in resolved.items() if m.about is not None}
    names = {pid: m.name for pid, m in resolved.items()}
    compiled = sorting.compile_rules(abouts, db.community_rules(settings), db.user_rules(settings))

    active_ids = set(resolved)
    ctx = advisories.Context.load(settings, mods.major_minor(inv.game_version))
    issues: list[dict[str, Any]] = []
    for pid, m in resolved.items():
        for d in (m.about.dependencies if m.about else []):
            dep = d.package_id
            alts = [a for a in d.alternatives]
            if dep in active_ids or any(a in active_ids for a in alts):
                continue
            installed = dep in inv.by_package_id or any(a in inv.by_package_id for a in alts)
            name = d.display_name or ctx.name_of(dep, d.pfid) or dep
            issue: dict[str, Any] = {
                "mod": names[pid],
                "requires": name,
                "package_id": dep,
                "status": "installed_but_inactive" if installed else "not_installed",
            }
            pfid = d.pfid or ctx.pfid_of(dep)
            if not installed and pfid:
                issue["action"] = {"tool": "workshop_download", "pfids": [pfid]}
            issues.append(issue)
    return Prepared(
        cfg,
        p,
        source_bytes,
        resolved,
        unresolved,
        duplicate_active,
        abouts,
        names,
        compiled,
        inv,
        issues,
    )


def _cycle_dicts(cycles: list[sorting.Cycle], names: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for c in cycles:
        out.append(
            {
                "members": [{"package_id": m, "name": names.get(m, m)} for m in c.members],
                "edges": [
                    {
                        "rule": f"{names.get(e['after'], e['after'])} after {names.get(e['before'], e['before'])}",
                        "after": e["after"],
                        "before": e["before"],
                        "sources": e["sources"],
                    }
                    for e in c.edges
                ],
            }
        )
    return out


def sort_modlist(settings: Settings, dry_run: bool = True) -> dict[str, Any]:
    prep = prepare(settings)
    if isinstance(prep, dict):
        return prep
    if not dry_run and db.community_rules(settings) is None:
        return {
            "error": "Community load-order rules are unavailable, so the active list was not changed.",
            "hint": "Reconnect and retry, or run the maintenance command `db-sync` first.",
        }
    result = sorting.sort(list(prep.resolved), prep.compiled, prep.names)
    out: dict[str, Any] = {
        "dry_run": dry_run,
        "active_count": len(prep.cfg.active),
        "unresolved": prep.unresolved,
        "duplicate_active": prep.duplicate_active,
        "incompatible_active_pairs": [
            [prep.names.get(a, a), prep.names.get(b, b)]
            for a, b in sorting.active_incompatibilities(prep.resolved, prep.compiled)
        ],
        "dependency_issues": prep.dependency_issues,
        "user_rule_removals_applied": prep.compiled.removed,
    }
    if not result.ok:
        out["ok"] = False
        out["failed_tier"] = result.failed_tier
        out["cycles"] = _cycle_dicts(result.cycles, prep.names)
        out["hint"] = (
            "Load order has a dependency cycle; nothing was written. Each edge lists its sources — "
            "add a removeLoadAfter/removeLoadBefore entry to userRules.json for the wrong one."
        )
        return out

    before = prep.cfg.active_ids
    new_ids = result.order + [u.removesuffix(_STEAM_SUFFIX).lower() for u in prep.unresolved]
    moved = sum(1 for i, pid in enumerate(new_ids) if i >= len(before) or before[i] != pid)
    out.update(
        {
            "ok": True,
            "changed_positions": moved,
            "order": [{"package_id": p, "name": prep.names.get(p, p)} for p in result.order],
            "tiers": {k: len(v) for k, v in result.tiers.items()},
        }
    )
    if prep.unresolved:
        out["hint"] = "Unresolved ids (not installed) are kept at the end of the list, not dropped."
    if dry_run or moved == 0:
        return out

    # Write: config ids preserve any _steam suffix the original carried.
    suffix_for = {a.removesuffix(_STEAM_SUFFIX).lower(): a for a in prep.cfg.active}
    if prep.path.read_bytes() != prep.source_bytes:
        return {
            **out,
            "error": "ModsConfig.xml changed while the sort was being prepared.",
            "hint": "Run sort_modlist again to analyze the current active list.",
        }
    snap = snapshot(settings, note="auto: before sort_modlist", cfg=prep.cfg)
    new_cfg = ModsConfig(
        version=prep.cfg.version,
        active=[suffix_for.get(p, p) for p in result.order] + prep.unresolved,
        known_expansions=prep.cfg.known_expansions,
    )
    backup = write_mods_config(prep.path, new_cfg)
    out["written"] = str(prep.path)
    out["backup"] = str(backup) if backup else None
    out["snapshot_before"] = snap.get("id")
    return out


def diagnose(settings: Settings) -> dict[str, Any]:
    prep = prepare(settings)
    if isinstance(prep, dict):
        return prep
    result = sorting.sort(list(prep.resolved), prep.compiled, prep.names)
    return {
        "ok": result.ok,
        "failed_tier": result.failed_tier,
        "cycles": _cycle_dicts(result.cycles, prep.names),
        "incompatible_active_pairs": [
            [prep.names.get(a, a), prep.names.get(b, b)]
            for a, b in sorting.active_incompatibilities(prep.resolved, prep.compiled)
        ],
        "dependency_issues": prep.dependency_issues,
        "hint": (
            None
            if result.ok
            else "Each cycle edge lists its rule sources; remove the wrong one via userRules.json."
        ),
    }
