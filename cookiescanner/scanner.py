"""Top-level scan orchestration."""

from __future__ import annotations

from .cookies import CookieJar
from .sites import all_adapters
from .types import ScanResult


def scan_all(jar: CookieJar, *, proxy: str | None = None, only: list[str] | None = None) -> list[ScanResult]:
    """Run every registered site adapter and collect results."""
    results: list[ScanResult] = []
    for Adapter in all_adapters():
        adapter = Adapter(jar=jar, proxy=proxy)
        if only and adapter.SITE not in only:
            continue
        try:
            result = adapter.scan()
        except Exception as e:  # noqa: BLE001 — defensive, never let one adapter kill the run
            result = ScanResult(site=adapter.SITE, alive=False, error=f"{type(e).__name__}: {e}")
        results.append(result)
    return results
