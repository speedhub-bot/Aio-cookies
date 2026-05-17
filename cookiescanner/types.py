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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
