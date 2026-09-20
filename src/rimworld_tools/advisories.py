from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import db
from .config import Settings


@dataclass(frozen=True)
class Advisory:
    kind: str  # replaced | unpublished | blacklisted | version_mismatch | missing_dependency
    severity: str  # info | warn
    message: str
    action: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "severity": self.severity, "message": self.message}
        if self.action:
            d["action"] = self.action
        return d


@dataclass
class Context:
    """Everything loaded once per tool call. Missing DBs degrade to 'no advisory', never an error."""

    game_mm: str | None
    steam: db.SteamDB | None
    replacements: dict[str, db.Replacement] | None
    no_version_warning: set[str] | None
    missing_dbs: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, settings: Settings, game_mm: str | None) -> Context:
        steam = db.steam_db(settings)
        repl = db.use_this_instead(settings)
        novw = db.no_version_warning(settings, game_mm)
        missing = [
            n
            for n, v in (
                ("steam_db", steam),
                ("use_this_instead", repl),
                ("no_version_warning", novw),
            )
            if v is None
        ]
        return cls(game_mm, steam, repl, novw, missing)

    def db_notice(self) -> dict[str, Any] | None:
        """One top-level notice per response when DBs are missing — never one per mod."""
        if not self.missing_dbs:
            return None
        return {
            "kind": "databases_missing",
            "severity": "info",
            "message": f"Community databases not synced: {self.missing_dbs}. "
            "Advisories (forks, blacklist, version suppression) are unavailable until then.",
            "action": {"tool": "db_sync"},
        }

    def name_of(self, package_id: str | None, pfid: str | None = None) -> str | None:
        if self.steam is None:
            return None
        if pfid and (e := self.steam.by_pfid.get(pfid)):
            return e.name
        return self.steam.name_for(package_id) if package_id else None

    def pfid_of(self, package_id: str) -> str | None:
        return self.steam.pfid_by_package_id.get(package_id.lower()) if self.steam else None

    # --- individual rules -------------------------------------------------------------

    def version(
        self, package_id: str | None, supported: list[str], version_ok: bool | None
    ) -> Advisory | None:
        if version_ok is not False or not package_id:
            return None
        if self.no_version_warning is not None and package_id.lower() in self.no_version_warning:
            return None  # community says it works; suppressed entirely, not flagged
        return Advisory(
            "version_mismatch",
            "warn",
            f"Declares {supported}; game is {self.game_mm}. May still work — check the Workshop page.",
        )

    def replacement(self, pfid: str | None, unpublished: bool | None) -> Advisory | None:
        """`unpublished` must come from a live Web API result, never the community Steam DB —
        that DB's flag was 4-for-4 wrong on a real mod set (it lags republishing by months)."""
        if not pfid:
            return None
        repl = self.replacements.get(pfid) if self.replacements else None
        if repl:
            versions = f" (supports {', '.join(repl.new_versions)})" if repl.new_versions else ""
            state = "Unpublished" if unpublished else "Superseded"
            return Advisory(
                "replaced",
                "warn" if unpublished else "info",
                f"{state}. Maintained replacement: '{repl.new_name or repl.new_pfid}' "
                f"(pfid {repl.new_pfid}){versions}.",
                {"tool": "workshop_download", "pfids": [repl.new_pfid]},
            )
        if unpublished:
            return Advisory(
                "unpublished",
                "warn",
                "Removed from the Workshop (deleted or private); no known replacement.",
            )
        return None

    def blacklist(self, pfid: str | None) -> Advisory | None:
        if not pfid or self.steam is None:
            return None
        e = self.steam.by_pfid.get(pfid)
        if e and e.blacklist_comment:
            return Advisory("blacklisted", "warn", f"Community blacklist: {e.blacklist_comment}")
        return None

    def missing_dependency(
        self,
        dep_package_id: str,
        dep_name: str | None,
        dep_pfid: str | None,
        alternatives: list[str],
        installed: set[str],
    ) -> Advisory | None:
        pid = dep_package_id.lower()
        if pid in installed or any(a.lower() in installed for a in alternatives):
            return None
        pfid = dep_pfid or self.pfid_of(pid)
        name = dep_name or self.name_of(pid, pfid) or pid
        action = {"tool": "workshop_download", "pfids": [pfid]} if pfid else None
        where = f" (pfid {pfid})" if pfid else " (no Workshop id known)"
        return Advisory(
            "missing_dependency", "warn", f"Requires '{name}'{where}, not installed.", action
        )


def for_mod(
    ctx: Context,
    package_id: str | None,
    pfid: str | None,
    supported_versions: list[str],
    version_ok: bool | None,
    unpublished: bool | None,
    dependencies: list[tuple[str, str | None, str | None, list[str]]],
    installed: set[str],
) -> list[dict[str, Any]]:
    """All advisories for one mod, pre-resolved. Suppressed ones are simply absent.

    `unpublished=None` means "no live API result" and yields no unpublished advisory.
    """
    found = [
        ctx.version(package_id, supported_versions, version_ok),
        ctx.replacement(pfid, unpublished),
        ctx.blacklist(pfid),
    ]
    found += [
        ctx.missing_dependency(dpid, dname, dpfid, alts, installed)
        for dpid, dname, dpfid, alts in dependencies
    ]
    return [a.to_dict() for a in found if a is not None]
