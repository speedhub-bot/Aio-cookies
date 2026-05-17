"""Flexible cookie loader.

Supports four input formats so you can paste whatever your browser
extension spits out without conversion:

    1. EditThisCookie / Cookie-Editor JSON  (list of dicts with name/value/domain)
    2. Plain ``{name: value}`` JSON dict
    3. Netscape ``cookies.txt`` (tab-separated, ``# Netscape`` header optional)
    4. Raw ``Cookie:`` HTTP header string (``a=1; b=2; ...``)

The loader auto-detects the format based on the file contents. Cookies
are returned grouped by domain (suffix match) so each site adapter
can pick only the cookies it cares about.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class Cookie:
    """A single cookie. ``domain`` is optional/best-effort."""

    name: str
    value: str
    domain: str = ""

    def matches(self, host: str) -> bool:
        """Domain suffix match (browser-style).

        ``.example.com`` and ``example.com`` both match ``app.example.com``.
        Cookies without a domain are treated as matching everything; the
        caller can then attach them to a specific site by URL.
        """
        if not self.domain:
            return True
        d = self.domain.lstrip(".").lower()
        h = host.lower()
        return h == d or h.endswith("." + d)


@dataclass
class CookieJar:
    cookies: list[Cookie] = field(default_factory=list)

    # ----- public API ---------------------------------------------------

    def for_host(self, host: str) -> dict[str, str]:
        """Return ``{name: value}`` for cookies whose domain matches *host*."""
        out: dict[str, str] = {}
        for c in self.cookies:
            if c.matches(host):
                # Last write wins — later cookies override earlier ones with
                # the same name (matches browser behaviour for same-path).
                out[c.name] = c.value
        return out

    def names(self) -> list[str]:
        return [c.name for c in self.cookies]

    def __len__(self) -> int:
        return len(self.cookies)


# ----- format detectors ------------------------------------------------


def _parse_editthiscookie(data: list[dict]) -> list[Cookie]:
    out: list[Cookie] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("Name")
        value = entry.get("value") or entry.get("Value")
        domain = entry.get("domain") or entry.get("Domain") or ""
        if name and value is not None:
            out.append(Cookie(name=str(name), value=str(value), domain=str(domain)))
    return out


def _parse_dict(data: dict) -> list[Cookie]:
    return [Cookie(name=str(k), value=str(v)) for k, v in data.items()]


def _parse_netscape(text: str) -> list[Cookie]:
    """Parse the Netscape ``cookies.txt`` format."""
    out: list[Cookie] = []
    for raw in text.splitlines():
        line = raw.strip()
        # ``#HttpOnly_`` is a comment-shaped prefix some exporters add to
        # HttpOnly cookies — peel it off before the blanket ``#`` skip.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
        out.append(Cookie(name=name, value=value, domain=domain))
    return out


def _parse_header(text: str) -> list[Cookie]:
    """Parse a raw ``Cookie:`` HTTP header (``a=1; b=2; ...``)."""
    out: list[Cookie] = []
    # Strip leading ``Cookie:`` if present.
    text = re.sub(r"(?i)^\s*cookie\s*:\s*", "", text.strip())
    for piece in text.split(";"):
        if "=" not in piece:
            continue
        name, _, value = piece.partition("=")
        name = name.strip()
        value = value.strip()
        if name:
            out.append(Cookie(name=name, value=value))
    return out


# ----- public entrypoint -----------------------------------------------


def load_cookies(source: str | Path) -> CookieJar:
    """Load cookies from *source* (path or literal string)."""
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    else:
        text = str(source)

    stripped = text.lstrip()

    # Try JSON first.
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return CookieJar(_parse_editthiscookie(data))
        if isinstance(data, dict):
            return CookieJar(_parse_dict(data))

    # Netscape if it looks tab-delimited or has the header.
    if "Netscape HTTP Cookie File" in text or re.search(r"^\S+\t\S+\t\S+\t\S+\t\S+\t\S+\t", text, re.MULTILINE):
        return CookieJar(_parse_netscape(text))

    # Fallback: treat as raw Cookie header.
    return CookieJar(_parse_header(text))


def merge_jars(jars: Iterable[CookieJar]) -> CookieJar:
    """Merge several jars (later jars override earlier names per-domain)."""
    out: list[Cookie] = []
    for j in jars:
        out.extend(j.cookies)
    return CookieJar(out)
