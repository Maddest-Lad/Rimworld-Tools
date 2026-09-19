from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import RIMWORLD_APP_ID

logger = logging.getLogger(__name__)
# The key rides in URLs; keep urllib3 from echoing them at DEBUG.
logging.getLogger("urllib3").setLevel(logging.WARNING)

_API = "https://api.steampowered.com"
_FILE_DETAILS_URL = f"{_API}/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
_COLLECTION_URL = f"{_API}/ISteamRemoteStorage/GetCollectionDetails/v1/"
_QUERY_FILES_URL = f"{_API}/IPublishedFileService/QueryFiles/v1/"
_ITEM_PAGE = "https://steamcommunity.com/sharedfiles/filedetails/?id="
_COLLECTION_PAGE = "https://steamcommunity.com/workshop/filedetails/?id="
_BROWSE_URL = f"https://steamcommunity.com/workshop/browse/?appid={RIMWORLD_APP_ID}"
_BROWSE_SORT = {
    "relevance": "textsearch",
    "trend": "trend",
    "recent": "mostrecent",
    "top": "toprated",
    "updated": "lastupdated",
}
_PRIVATE_SENTINEL = "There was a problem accessing the item. "  # trailing space is real

FILE_DETAILS_CHUNK = 300
COLLECTION_CHUNK = 5000
_RETRYABLE = {429, 500, 502, 503, 504}
_ATTEMPTS = 3
_TIMEOUT = (5, 60)

# EPublishedFileQueryType values QueryFiles accepts.
SORT_MODES = {
    "relevance": 12,  # RankedByTextSearch — needs search_text
    "trend": 3,  # RankedByTrend — uses `days`
    "recent": 1,  # RankedByPublicationDate
    "top": 0,  # RankedByVote
    "updated": 21,  # RankedByLastUpdatedDate
}


_URL_ID_RE = re.compile(r"[?&]id=(\d+)")


def redact(text: str, key: str | None) -> str:
    """Strip an API key wherever it might surface: URLs, tracebacks, error strings."""
    if key:
        text = text.replace(key, "***")
    return re.sub(r"([?&]key=)[^&\s]+", r"\1***", text)


@dataclass
class ChunkedResult:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    failed_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _post_with_retry(url: str, data: dict[str, Any], key: str | None = None) -> dict[str, Any]:
    """POST retried on transient codes; anything else fails immediately."""
    last = ""
    for attempt in range(_ATTEMPTS):
        try:
            with requests.Session() as s:
                resp = s.post(url, data=data, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            last = redact(str(exc), key)
            time.sleep(2**attempt)
            continue
        if resp.status_code in _RETRYABLE:
            last = f"HTTP {resp.status_code}"
            time.sleep(2**attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise requests.RequestException(f"gave up after {_ATTEMPTS} attempts: {last}")


def _normalise(entry: dict[str, Any]) -> dict[str, Any]:
    """Only the fields tools care about. `result != 1` is the sole unpublished signal."""
    return {
        "pfid": str(entry.get("publishedfileid", "")),
        "title": entry.get("title"),
        "unpublished": entry.get("result") != 1,
        "time_created": entry.get("time_created"),
        "time_updated": entry.get("time_updated"),
        "file_size": _int_or_none(entry.get("file_size")),
        "creator": entry.get("creator"),
        "consumer_app_id": entry.get("consumer_app_id"),
        "tags": [t.get("tag") for t in entry.get("tags", []) if isinstance(t, dict)],
        "url": f"{_ITEM_PAGE}{entry.get('publishedfileid', '')}",
    }


def _int_or_none(raw: object) -> int | None:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def file_details(pfids: list[str], key: str | None = None) -> ChunkedResult:
    """GetPublishedFileDetails, chunked at 300. Keyless. Partial results survive a bad chunk."""
    out = ChunkedResult()
    for i in range(0, len(pfids), FILE_DETAILS_CHUNK):
        chunk = pfids[i : i + FILE_DETAILS_CHUNK]
        form: dict[str, Any] = {"itemcount": len(chunk)}
        for n, pfid in enumerate(chunk):
            form[f"publishedfileids[{n}]"] = pfid
        try:
            body = _post_with_retry(_FILE_DETAILS_URL, form, key)
        except (requests.RequestException, ValueError) as exc:
            out.failed_ids.extend(chunk)
            out.errors.append(redact(f"chunk {i // FILE_DETAILS_CHUNK + 1}: {exc}", key))
            continue
        for entry in body.get("response", {}).get("publishedfiledetails", []):
            if isinstance(entry, dict) and entry.get("publishedfileid"):
                item = _normalise(entry)
                out.items[item["pfid"]] = item
        out.failed_ids.extend(p for p in chunk if p not in out.items)
    return out


def _ci_get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    # Steam is inconsistent about key casing in collection responses.
    for k, v in d.items():
        if k.lower() == key.lower():
            return v
    return default


def collection_children(collection_id: str, key: str | None = None) -> list[str] | None:
    """Child pfids of a collection, mods only (filetype == 0). None if not a collection."""
    form = {"collectioncount": 1, "publishedfileids[0]": collection_id}
    body = _post_with_retry(_COLLECTION_URL, form, key)
    details = _ci_get(body.get("response", {}), "collectiondetails", [])
    if not details or not isinstance(details[0], dict):
        return None
    if _ci_get(details[0], "result") != 1:
        return None
    children = _ci_get(details[0], "children")
    if not isinstance(children, list):
        return None
    return [
        str(_ci_get(c, "publishedfileid"))
        for c in children
        if isinstance(c, dict) and _ci_get(c, "filetype") == 0
    ]


def is_private_or_deleted(pfid: str) -> bool | None:
    """Distinguish 'private/deleted' from 'our lookup failed' via the item page sentinel."""
    try:
        with requests.Session() as s:
            resp = s.get(f"{_ITEM_PAGE}{pfid}", timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    return _PRIVATE_SENTINEL in resp.text


def parse_workshop_url(raw: str) -> str | None:
    """pfid from a pasted URL or bare id. Handles the messy URLs users actually paste."""
    s = raw.strip()
    if s.isdigit():
        return s
    if m := _URL_ID_RE.search(s):
        return m.group(1)
    return None


def search(
    query: str,
    key: str,
    limit: int = 20,
    required_tags: list[str] | None = None,
    excluded_tags: list[str] | None = None,
    sort: str = "relevance",
    days: int = 90,
) -> dict[str, Any]:
    """QueryFiles with tag filters. Requires an API key; caller degrades to browse_url without one."""
    params: dict[str, Any] = {
        "key": key,
        "query_type": SORT_MODES[sort],
        "appid": RIMWORLD_APP_ID,
        "creator_appid": RIMWORLD_APP_ID,
        "search_text": query,
        "numperpage": max(1, min(100, limit)),
        "filetype": 0,
        "match_all_tags": "true",
        "return_metadata": "true",
        "return_tags": "true",
        "format": "json",
    }
    if sort == "trend":
        params["days"] = days
    for i, tag in enumerate(required_tags or []):
        params[f"requiredtags[{i}]"] = tag
    for i, tag in enumerate(excluded_tags or []):
        params[f"excludedtags[{i}]"] = tag
    with requests.Session() as s:
        resp = s.get(_QUERY_FILES_URL, params=params, timeout=_TIMEOUT)
    if resp.status_code == 403:
        return {
            "error": "Steam rejected the API key (HTTP 403).",
            "hint": "Check STEAM_WEB_API_KEY.",
        }
    resp.raise_for_status()
    body = resp.json().get("response", {})
    results = [
        _normalise(e)
        for e in body.get("publishedfiledetails", [])
        if isinstance(e, dict) and e.get("publishedfileid")
    ]
    return {"query": query, "total": body.get("total"), "results": results}


def browse_url(
    query: str,
    required_tags: list[str] | None = None,
    excluded_tags: list[str] | None = None,
    sort: str = "relevance",
    days: int = 90,
) -> str:
    q = f"{_BROWSE_URL}&browsesort={_BROWSE_SORT[sort]}&section=readytouseitems&p=1&num_per_page=30"
    if sort == "trend":
        q += f"&days={days}"
    if query:
        q += "&searchtext=" + requests.utils.quote(query)
    for tag in required_tags or []:
        q += "&requiredtags%5B%5D=" + requests.utils.quote(tag)
    for tag in excluded_tags or []:
        q += "&excludedtags%5B%5D=" + requests.utils.quote(tag)
    return q


def collection_url(pfid: str) -> str:
    return f"{_COLLECTION_PAGE}{pfid}"
