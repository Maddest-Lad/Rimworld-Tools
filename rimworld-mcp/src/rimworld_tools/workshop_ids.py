from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def normalise(raw: list[str | int]) -> tuple[list[str], list[str]]:
    good, bad = [], []
    for value in raw:
        text = str(value).strip()
        if (
            not text.isascii()
            or not text.isdecimal()
            or len(text) > 20
            or not 0 < int(text) < 2**64
        ):
            bad.append(str(value))
        elif str(int(text)) not in good:
            good.append(str(int(text)))
    return good, bad


def parse_url(raw: str) -> str | None:
    text = raw.strip()
    if not text.isdecimal():
        parsed = urlparse(text if "://" in text else "https://" + text)
        if parsed.hostname not in {"steamcommunity.com", "www.steamcommunity.com"}:
            return None
        text = parse_qs(parsed.query).get("id", [""])[0]
    good, _ = normalise([text])
    return good[0] if good else None
