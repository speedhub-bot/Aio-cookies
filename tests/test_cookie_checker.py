"""Tests for the legacy ``cookie_checker.py`` loaders.

Focused on the ``#HttpOnly_`` Netscape prefix handling because the
session cookies that actually matter for claude.ai
(``sessionKey``), crunchyroll.com (``etp_rt`` / ``sess_id``) and
chatgpt.com (``__Secure-next-auth.session-token``) are exported with
that prefix by curl / Chrome / yt-dlp.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Repo root contains ``cookie_checker.py`` as a top-level module.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import cookie_checker  # noqa: E402


_CLAUDE_COOKIES_TXT = (
    "# Netscape HTTP Cookie File\n"
    "# https://curl.se/docs/http-cookies.html\n"
    "# This is a generated file!  Do not edit.\n"
    "\n"
    "#HttpOnly_.claude.ai\tTRUE\t/\tTRUE\t1999999999\tsessionKey\tsk-ant-sid01-abc\n"
    "#HttpOnly_.claude.ai\tTRUE\t/\tTRUE\t1999999999\t__cf_bm\tcfbm-value\n"
    ".claude.ai\tTRUE\t/\tFALSE\t1999999999\tlang\ten-US\n"
)


_CRUNCHY_COOKIES_TXT = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.crunchyroll.com\tTRUE\t/\tTRUE\t1999999999\tetp_rt\tetp-rt-token\n"
    "#HttpOnly_.crunchyroll.com\tTRUE\t/\tTRUE\t1999999999\tsess_id\tsess-id-token\n"
    ".crunchyroll.com\tTRUE\t/\tFALSE\t1999999999\tc_locale\tenUS\n"
)


_ONLY_HTTPONLY_COOKIES_TXT = (
    "#HttpOnly_.claude.ai\tTRUE\t/\tTRUE\t1999999999\tsessionKey\tsk-ant-sid01-xyz\n"
)


def test_netscape_loader_keeps_httponly_cookies(tmp_path: Path) -> None:
    p = tmp_path / "claude_cookies.txt"
    p.write_text(_CLAUDE_COOKIES_TXT)

    cookies = cookie_checker.load_cookies_netscape(str(p))
    names = {c["name"]: c for c in cookies}

    assert "sessionKey" in names, "HttpOnly sessionKey was dropped by the loader"
    assert "__cf_bm" in names
    assert "lang" in names
    assert names["sessionKey"]["value"] == "sk-ant-sid01-abc"
    assert names["sessionKey"]["domain"] == "claude.ai"
    assert names["sessionKey"]["secure"] is True


def test_netscape_loader_keeps_crunchyroll_httponly_cookies(tmp_path: Path) -> None:
    p = tmp_path / "crunchy_cookies.txt"
    p.write_text(_CRUNCHY_COOKIES_TXT)

    cookies = cookie_checker.load_cookies_netscape(str(p))
    names = {c["name"]: c for c in cookies}

    assert {"etp_rt", "sess_id", "c_locale"}.issubset(names.keys())
    assert names["etp_rt"]["value"] == "etp-rt-token"
    assert names["sess_id"]["domain"] == "crunchyroll.com"


def test_load_cookie_file_autodetects_httponly_only_files(tmp_path: Path) -> None:
    """Files that contain *only* HttpOnly rows must still parse as Netscape.

    Before the fix the autodetect filtered out every ``#``-prefixed line,
    so a file like a fresh claude.ai export (one ``sessionKey`` cookie)
    fell through to the ``name=value`` parser and returned zero cookies.
    """
    p = tmp_path / "cookies.txt"
    p.write_text(_ONLY_HTTPONLY_COOKIES_TXT)

    cookies = cookie_checker.load_cookie_file(str(p))
    assert len(cookies) == 1
    assert cookies[0]["name"] == "sessionKey"
    assert cookies[0]["domain"] == "claude.ai"


def test_detect_site_claude_from_httponly(tmp_path: Path) -> None:
    p = tmp_path / "claude_cookies.txt"
    p.write_text(_CLAUDE_COOKIES_TXT)
    cookies = cookie_checker.load_cookie_file(str(p))
    assert cookie_checker.detect_site(cookies, p.name) == "claude.ai"


def test_detect_site_crunchyroll_from_httponly(tmp_path: Path) -> None:
    p = tmp_path / "anonymous.txt"  # no hint from filename
    p.write_text(_CRUNCHY_COOKIES_TXT)
    cookies = cookie_checker.load_cookie_file(str(p))
    assert cookie_checker.detect_site(cookies, p.name) == "crunchyroll.com"


def test_detect_site_strips_stray_httponly_prefix_on_domain() -> None:
    """Older callers occasionally hand pre-parsed dicts whose ``domain``
    still contains the ``#HttpOnly_`` marker. ``detect_site`` should
    cope rather than miss every site."""
    cookies = [
        {"domain": "#HttpOnly_.crunchyroll.com", "name": "etp_rt", "value": "x"},
    ]
    assert cookie_checker.detect_site(cookies, "") == "crunchyroll.com"


@pytest.mark.parametrize(
    "expires_field, expected",
    [
        ("1999999999", 1999999999),
        ("0", 0),
        ("-1", -1),  # session cookies sometimes serialise as -1
        ("", 0),
        ("garbage", 0),
    ],
)
def test_netscape_loader_expires_parsing(tmp_path: Path, expires_field: str, expected: int) -> None:
    p = tmp_path / "cookies.txt"
    p.write_text(
        f"#HttpOnly_.claude.ai\tTRUE\t/\tTRUE\t{expires_field}\tsessionKey\tabc\n"
    )
    cookies = cookie_checker.load_cookies_netscape(str(p))
    assert len(cookies) == 1
    assert cookies[0]["expires"] == expected
