"""Shared result types (kept here to avoid circular imports)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ScanResult:
    site: str
    alive: bool
    info: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    endpoints_tried: list[dict[str, Any]] = field(default_factory=list)
    # Cookies the adapter *rotated* during the scan (e.g. Roblox's
    # ``.ROBLOSECURITY`` after a successful auth-ticket refresh).
    # Maps cookie name to its fresh value. Callers can write these back
    # to their on-disk jar so the next scan uses the rotated token.
    refreshed_cookies: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
