"""@akaza_isnt branding shows up on every user-facing surface.

Lightweight tests covering the credit line, exported cookies.txt
header, and the bot's hit-filename convention. Pure-function checks —
no Telegram client needed.
"""

from __future__ import annotations

import re

import pytest

from tgbot import formatting
from tgbot.handlers import _hit_filename
from tgbot.scanner import ScanOutcome, dump_netscape


# ── helpers ─────────────────────────────────────────────────


def _outcome(
    *,
    site: str = "claude.ai",
    alive: bool = True,
    info: dict | None = None,
    cookies: list[dict] | None = None,
    refreshed: dict | None = None,
) -> ScanOutcome:
    return ScanOutcome(
        site=site,
        filename="cookies.txt",
        alive=alive,
        info=info or {"email": "a@b.com", "plan": "Free"},
        error=None,
        cookies=cookies
        or [{"name": "sessionKey", "value": "sk-foo", "domain": ".claude.ai"}],
        elapsed_s=0.2,
        refreshed_cookies=refreshed or {},
    )


# ── format_outcome ──────────────────────────────────────────


def test_format_outcome_includes_credit_footer() -> None:
    body = formatting.format_outcome(_outcome())
    assert "@akaza_isnt" in body
    # And it must be the last visible block so users see it.
    assert body.rstrip().endswith(formatting.BOT_CREDIT)


def test_format_outcome_truncation_preserves_credit() -> None:
    # Each individual ``info`` value is truncated to MAX_VALUE_LEN, so a
    # single huge value isn't enough to overflow the message budget.
    # Instead, pile up many medium-sized values until we blow past
    # ``MAX_MESSAGE_LEN`` cumulatively.
    info = {f"k{i}": "X" * (formatting.MAX_VALUE_LEN - 50) for i in range(40)}
    body = formatting.format_outcome(_outcome(info=info))
    # Truncation kicks in (we never overshoot the Telegram cap).
    assert len(body) <= formatting.MAX_MESSAGE_LEN + 1
    # …and the credit line still lands at the end.
    assert body.rstrip().endswith(formatting.BOT_CREDIT)
    # …and the truncation marker survived.
    assert "(truncated)" in body


# ── format_summary ──────────────────────────────────────────


def test_format_summary_includes_credit_footer() -> None:
    text = formatting.format_summary([_outcome(), _outcome(alive=False)])
    assert "1" in text and "Scanned" in text
    assert text.rstrip().endswith(formatting.BOT_CREDIT)


# ── format_hit ──────────────────────────────────────────────


def test_format_hit_includes_credit_footer() -> None:
    text = formatting.format_hit(_outcome())
    assert "HIT" in text
    assert "@akaza_isnt" in text
    assert text.rstrip().endswith(formatting.BOT_CREDIT)


# ── dump_netscape ───────────────────────────────────────────


def test_dump_netscape_starts_with_akaza_banner() -> None:
    body = dump_netscape(
        [{"name": "sessionKey", "value": "sk-foo", "domain": ".claude.ai"}],
    )
    head = body.splitlines()[:10]
    head_text = "\n".join(head)
    # Standard Netscape header survives (yt-dlp expects line 1 to be this).
    assert head[0] == "# Netscape HTTP Cookie File"
    # And the @akaza credit lands in the banner.
    assert "@akaza_isnt" in head_text
    assert "AIO Cookies Bot" in head_text


# ── _hit_filename ───────────────────────────────────────────


def test_hit_filename_format_and_stability() -> None:
    outcome = _outcome()
    name = _hit_filename(outcome)
    assert re.fullmatch(r"@akaza_[a-z0-9_]+_[0-9a-f]{8}\.txt", name), name
    assert name.startswith("@akaza_")
    assert name.endswith(".txt")
    # Same cookies -> same filename (so the user can re-scan and dedupe
    # against their local copy).
    assert _hit_filename(outcome) == name


def test_hit_filename_site_slug_replaces_dots() -> None:
    outcome = _outcome(site="crunchyroll.com")
    name = _hit_filename(outcome)
    assert "@akaza_crunchyroll_com_" in name
    assert ".com_" not in name.split("_")[1:3][0]  # 'crunchyroll' not 'crunchyroll.com'


def test_hit_filename_changes_with_cookie_payload() -> None:
    a = _hit_filename(_outcome(cookies=[{"name": "k", "value": "v1"}]))
    b = _hit_filename(_outcome(cookies=[{"name": "k", "value": "v2"}]))
    assert a != b


# ── About/start text via handlers (text-only assertion) ────


def test_handlers_static_text_includes_credit() -> None:
    from tgbot import handlers

    assert "@akaza_isnt" in handlers._START_TEXT
    assert "@akaza_isnt" in handlers._ABOUT_TEXT


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
