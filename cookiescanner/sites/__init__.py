"""Per-site adapters.

Each adapter is responsible for: pulling the right cookies out of the
jar, hitting one or more authenticated endpoints, deciding whether the
cookie is alive, and extracting whatever account info the site
exposes (email, plan, renewal date, credits…).
"""

from __future__ import annotations

from .base import SiteAdapter
from .blackbox import BlackboxAdapter
from .manus import ManusAdapter
from .netflix import NetflixAdapter
from .perplexity import PerplexityAdapter
from .prime import PrimeVideoAdapter
from .roblox import RobloxAdapter
from .spotify import SpotifyAdapter


def all_adapters() -> list[type[SiteAdapter]]:
    return [
        BlackboxAdapter,
        ManusAdapter,
        PerplexityAdapter,
        NetflixAdapter,
        PrimeVideoAdapter,
        RobloxAdapter,
        SpotifyAdapter,
    ]


__all__ = [
    "SiteAdapter",
    "all_adapters",
    "BlackboxAdapter",
    "ManusAdapter",
    "NetflixAdapter",
    "PerplexityAdapter",
    "PrimeVideoAdapter",
    "RobloxAdapter",
    "SpotifyAdapter",
]
