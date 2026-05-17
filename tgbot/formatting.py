"""Format ScanOutcome objects into Telegram-friendly HTML messages."""

from __future__ import annotations

import html
import json
from typing import Any

from . import config
from .scanner import ScanOutcome


# Per-message length budget. Telegram's hard cap is 4096; we stop a
# little early so we can safely append truncation notes.
MAX_MESSAGE_LEN = 3800
MAX_VALUE_LEN = 400


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return repr(value)
    return str(value)


def _truncate(text: str, limit: int = MAX_VALUE_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"  # …


def format_outcome(outcome: ScanOutcome) -> str:
    """Render a single ``ScanOutcome`` as an HTML message body."""
    emoji = config.site_emoji(outcome.site)
    status = "<b>\u2705 ALIVE</b>" if outcome.alive else "<b>\u274c DEAD</b>"

    lines = [
        f"{emoji} <b>{_esc(outcome.site)}</b> \u2014 {status}",
        f"<i>{_esc(outcome.filename)}</i>  \u00b7  <code>{outcome.elapsed_s:.1f}s</code>",
    ]

    if outcome.error:
        lines.append("")
        lines.append(f"\u26a0\ufe0f {_esc(_truncate(outcome.error, 800))}")

    if outcome.info:
        lines.append("")
        lines.append("<pre>")
        # sort for stable ordering, but prefer the high-signal keys first
        priority = (
            "email",
            "name",
            "username",
            "plan",
            "is_pro",
            "id",
            "user_id",
            "subscription_status",
            "renewal",
            "renewal_date",
            "renewal_timestamp",
            "expires_at",
            "session_expires",
            "session_issued",
            "country",
            "token_expires",
        )
        seen: set[str] = set()
        ordered: list[tuple[str, Any]] = []
        for key in priority:
            if key in outcome.info:
                ordered.append((key, outcome.info[key]))
                seen.add(key)
        for key in sorted(outcome.info.keys()):
            if key in seen:
                continue
            ordered.append((key, outcome.info[key]))

        for key, value in ordered:
            text_val = _truncate(_stringify(value))
            lines.append(f"{_esc(key)}: {_esc(text_val)}")
        lines.append("</pre>")

    body = "\n".join(lines)
    if len(body) > MAX_MESSAGE_LEN:
        body = body[: MAX_MESSAGE_LEN - 40] + "\n\u2026 (truncated)"
    return body


def format_summary(outcomes: list[ScanOutcome]) -> str:
    """Compact one-liner summary used when a zip yields many results."""
    alive = sum(1 for o in outcomes if o.alive)
    dead = sum(1 for o in outcomes if not o.alive)
    return (
        f"\U0001f9ee Scanned <b>{len(outcomes)}</b> file(s) "
        f"\u2014 <b>\u2705 {alive}</b> alive / <b>\u274c {dead}</b> dead"
    )


def format_hit(outcome: ScanOutcome) -> str:
    """Hit-style notification body sent when an ALIVE result lands.

    Kept terse on purpose; the full info still ships in the main result
    message that's sent alongside.
    """
    emoji = config.site_emoji(outcome.site)
    info = outcome.info or {}
    email = info.get("email") or info.get("username") or info.get("user_id") or "n/a"
    plan = info.get("plan") or info.get("subscription_tier") or info.get("payment_tier") or "n/a"
    renewal = (
        info.get("renewal")
        or info.get("renewal_date")
        or info.get("expires_at")
        or info.get("session_expires")
        or "n/a"
    )
    lines = [
        f"\U0001f6a8 <b>HIT</b> \u2014 {emoji} <b>{_esc(outcome.site)}</b>",
        f"\U0001f4e7 <code>{_esc(_truncate(str(email), 200))}</code>",
        f"\U0001f4b3 plan: <code>{_esc(_truncate(str(plan), 200))}</code>",
        f"\U0001f4c5 renewal/expiry: <code>{_esc(_truncate(str(renewal), 200))}</code>",
        f"\U0001f4ce <i>{_esc(outcome.filename)}</i>",
    ]
    return "\n".join(lines)
