"""Telegram HTML dashboard for live scan stats."""

from __future__ import annotations

import html
from typing import Any

from . import config
from .formatting import BOT_CREDIT


PLAN_ORDER: dict[str, tuple[str, ...]] = {
    "claude.ai": ("Max", "Team/Enterprise", "Team", "Enterprise", "Pro", "Free", "Unknown"),
    "chatgpt.com": ("Team", "Pro", "Plus", "Paid", "Free", "Unknown"),
    "cursor.com": ("Team", "Pro", "Premium", "Free", "Unknown"),
    "devin.ai": ("Team", "Pro", "Free", "Unknown"),
    "crunchyroll.com": ("Ultimate Fan", "Mega Fan", "Fan", "Premium", "Free", "Unknown"),
    "netflix.com": ("Premium", "Standard", "Basic", "Free", "Unknown"),
    "primevideo.com": ("Prime", "Premium", "Free", "Unknown"),
    "spotify.com": ("Premium", "Family", "Duo", "Student", "Free", "Unknown"),
    "roblox.com": ("Premium", "Free", "Unknown"),
    "shopify.com": ("Plus", "Advanced", "Shopify", "Basic", "Free", "Unknown"),
    "facebook.com": ("Free", "Unknown"),
    "blackbox.ai": ("Team", "Premium", "Trial", "Free", "Unknown"),
    "manus.im": ("Max", "Team", "Pro", "Plus", "Premium", "Free", "Unknown"),
    "perplexity.ai": ("Enterprise", "Team", "Max", "Pro", "Free", "Unknown"),
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _ordered_plans(site_id: str, plans: dict[str, int]) -> list[tuple[str, int]]:
    order = PLAN_ORDER.get(site_id, ("Max", "Team", "Pro", "Plus", "Premium", "Free", "Unknown"))
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for label in order:
        count = int(plans.get(label, 0) or 0)
        if count > 0:
            out.append((label, count))
            seen.add(label)
    for label in sorted(plans):
        if label in seen:
            continue
        count = int(plans.get(label, 0) or 0)
        if count > 0:
            out.append((label, count))
    return out


def format_start_dashboard(stats: dict[str, Any]) -> str:
    sites = stats.get("sites") if isinstance(stats.get("sites"), dict) else {}
    total = int(stats.get("total", 0) or 0)
    alive = int(stats.get("alive", 0) or 0)
    dead = int(stats.get("dead", 0) or 0)

    lines = [
        "🍪 <b>AIO Cookies Bot</b>",
        "<b>Live dashboard</b> — checks + plan counts per service.",
        f"🧮 Total: <b>{total}</b> · ✅ Alive: <b>{alive}</b> · ❌ Dead: <b>{dead}</b>",
        "",
    ]

    for site in config.SUPPORTED_SITES:
        site_id = site["id"]
        site_stats = sites.get(site_id) if isinstance(sites.get(site_id), dict) else {}
        site_total = int(site_stats.get("total", 0) or 0)
        site_alive = int(site_stats.get("alive", 0) or 0)
        site_dead = int(site_stats.get("dead", 0) or 0)
        label = f"{site['emoji']} <b>{_esc(site['label'])}</b>"

        if site_total == 0:
            lines.append(f"{label} — <code>0 checks</code>")
            continue

        plan_bits = [
            f"{_esc(plan)} <b>{count}</b>"
            for plan, count in _ordered_plans(site_id, dict(site_stats.get("plans") or {}))
        ]
        plans = " · ".join(plan_bits) if plan_bits else "No alive plans yet"
        lines.append(
            f"{label} — ✅ <b>{site_alive}</b> / ❌ <b>{site_dead}</b> · {plans}"
        )

    lines.extend([
        "",
        "Pick a service below, then send cookies as <code>.json</code>, <code>.txt</code>, or <code>.zip</code>.",
        BOT_CREDIT,
    ])
    return "\n".join(lines)
