"""Tests for the legacy ``cookie_checker.py`` loaders.

Focused on the ``#HttpOnly_`` Netscape prefix handling because the
session cookies that actually matter for claude.ai
(``sessionKey``), crunchyroll.com (``etp_rt`` / ``sess_id``) and
chatgpt.com (``__Secure-next-auth.session-token``) are exported with
that prefix by curl / Chrome / yt-dlp.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import patch

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


# ── detect_site coverage for roblox + blackbox ────────────────────────


def test_detect_site_roblox_from_domain() -> None:
    cookies = [
        {"domain": ".roblox.com", "name": ".ROBLOSECURITY", "value": "x"},
        {"domain": ".www.roblox.com", "name": "RBXEventTrackerV2", "value": "y"},
    ]
    assert cookie_checker.detect_site(cookies, "www_roblox_com_cookies.txt") == "roblox.com"


def test_detect_site_roblox_from_known_cookie_alone() -> None:
    """Even without a roblox.com domain, a ``.ROBLOSECURITY`` cookie name is enough."""
    cookies = [{"domain": "", "name": ".ROBLOSECURITY", "value": "x"}]
    assert cookie_checker.detect_site(cookies, "") == "roblox.com"


def test_detect_site_blackbox_from_domain() -> None:
    cookies = [
        {"domain": "app.blackbox.ai", "name": "sessionId", "value": "x"},
        {"domain": ".blackbox.ai", "name": "next-auth.session-token", "value": "y"},
    ]
    assert cookie_checker.detect_site(cookies, "app_blackbox_ai_cookies.txt") == "blackbox.ai"


# ── HTTP error surfacing in check_claude / check_crunchyroll ─────────


_CF_CHALLENGE_BODY = (
    "<!DOCTYPE html><html lang='en-US'><head><title>Just a moment...</title>"
    "<div class='challenge-platform'></div></head></html>"
)


def _minimal_claude_cookies() -> list[dict]:
    return [
        {"domain": "claude.ai", "name": "sessionKey", "value": "sk-ant-sid01-fake", "secure": True, "path": "/"},
    ]


def _minimal_crunchy_cookies() -> list[dict]:
    return [
        {"domain": "crunchyroll.com", "name": "etp_rt", "value": "fake-etp", "secure": True, "path": "/"},
    ]


def test_check_claude_reports_cloudflare_challenge() -> None:
    """A 403 + Cloudflare challenge body must NOT look like a dead cookie."""
    resp = {"status": 403, "text": _CF_CHALLENGE_BODY, "json": None, "via": "cffi"}
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        r = cookie_checker.check_claude(_minimal_claude_cookies())
    assert r["alive"] is False
    assert r.get("error"), "must surface an error so dead-vs-blocked is distinguishable"
    err = r["error"].lower()
    assert "cloudflare" in err
    assert "403" in err


def test_check_claude_reports_unauthorized() -> None:
    resp = {"status": 401, "text": "{}", "json": {}, "via": "requests"}
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        r = cookie_checker.check_claude(_minimal_claude_cookies())
    assert r["alive"] is False
    assert "401" in r["error"]
    assert "dead" in r["error"].lower() or "unauthorized" in r["error"].lower()


def test_check_claude_alive_on_200() -> None:
    payload = [{
        "uuid": "abc-org",
        "name": "Akaza\u2019s Organization",
        "capabilities": ["claude_pro"],
        "billing_type": "stripe",
    }]
    resp = {"status": 200, "text": "...", "json": payload, "via": "cffi"}
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        r = cookie_checker.check_claude(_minimal_claude_cookies())
    assert r["alive"] is True
    assert r.get("error") is None
    assert r["info"]["organization"] == "Akaza\u2019s Organization"
    assert r["info"]["plan"] == "Pro"
    # Email fallback should pull from "<name>'s Organization" -> "<name>".
    assert r["info"].get("email") == "Akaza"


def test_check_crunchyroll_reports_cloudflare_challenge() -> None:
    resp = {"status": 403, "text": _CF_CHALLENGE_BODY, "json": None, "via": "cffi"}
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        r = cookie_checker.check_crunchyroll(_minimal_crunchy_cookies())
    assert r["alive"] is False
    assert "cloudflare" in r["error"].lower()


def test_check_crunchyroll_reports_unauthorized() -> None:
    resp = {"status": 401, "text": '{"error":"invalid_grant"}', "json": {"error": "invalid_grant"}, "via": "requests"}
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        r = cookie_checker.check_crunchyroll(_minimal_crunchy_cookies())
    assert r["alive"] is False
    assert "401" in r["error"]


def test_check_crunchyroll_missing_etp_rt() -> None:
    """No ``etp_rt`` cookie -> clear early error, no HTTP attempted."""
    r = cookie_checker.check_crunchyroll([{"domain": "crunchyroll.com", "name": "device_id", "value": "x"}])
    assert r["alive"] is False
    assert "etp_rt" in r.get("error", "")


def test_http_error_message_helper_distinguishes_states() -> None:
    """The error-message helper must phrase each failure mode distinctly."""
    cf = cookie_checker._http_error_message(
        {"status": 403, "text": _CF_CHALLENGE_BODY, "via": "cffi"}, "x"
    )
    bare_403 = cookie_checker._http_error_message(
        {"status": 403, "text": '{"error":"forbidden"}', "via": "cffi"}, "x"
    )
    unauth = cookie_checker._http_error_message(
        {"status": 401, "text": "", "via": "requests"}, "x"
    )
    rate = cookie_checker._http_error_message(
        {"status": 429, "text": "", "via": "cffi"}, "x"
    )
    netfail = cookie_checker._http_error_message(
        {"status": 0, "text": "ConnectionError: dns", "via": "cffi"}, "x"
    )
    assert "cloudflare" in cf.lower()
    assert "cloudflare" not in bare_403.lower()
    assert "401" in unauth and "dead" in unauth.lower()
    assert "429" in rate
    assert "network error" in netfail.lower()


def test_cf_challenge_marker_matches_real_body() -> None:
    """The CF detector must catch the page Cloudflare actually serves."""
    assert cookie_checker._looks_like_cf_challenge(_CF_CHALLENGE_BODY)
    assert not cookie_checker._looks_like_cf_challenge('{"organizations":[]}')
    assert not cookie_checker._looks_like_cf_challenge("")


# ── Crunchyroll OAuth body / client_id (live web SPA shape) ───────────


def test_crunchyroll_token_body_uses_device_id_from_cookie() -> None:
    """The token body must include the device_id from the cookie jar.

    Without ``device_id`` + ``device_type`` the live token endpoint
    returns ``invalid_request / missing_required_field`` — see the
    diagnostic capture in the PR description.
    """
    body = cookie_checker._crunchyroll_token_body({"device_id": "abc-123", "etp_rt": "rt"})
    assert "grant_type=etp_rt_cookie" in body
    assert "device_id=abc-123" in body
    assert "device_type=" in body


def test_crunchyroll_token_body_fallback_device_id_when_cookie_absent() -> None:
    body = cookie_checker._crunchyroll_token_body({"etp_rt": "rt"})
    # Must still include a (non-empty) device_id so the endpoint accepts it.
    assert "device_id=" in body
    assert "device_id=&" not in body and not body.endswith("device_id=")


def test_check_crunchyroll_uses_cr_web_client_id() -> None:
    """The Authorization header must base64 the live ``noaihdevm_6iyg0a8l0q``
    client id with an empty secret (PKCE-style)."""
    captured: dict = {}

    def fake_request_json(s, url, headers, cd, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = kwargs.get("data", "")
        return {
            "status": 200,
            "json": {
                "access_token": "atok",
                "country": "US",
                "token_type": "Bearer",
                "scope": "account",
                "expires_in": 300,
            },
            "text": "",
            "via": "cffi",
        }

    with patch.object(cookie_checker, "_request_json", side_effect=fake_request_json):
        cookie_checker.check_crunchyroll(_minimal_crunchy_cookies() + [
            {"domain": "crunchyroll.com", "name": "device_id", "value": "dev-uuid", "path": "/", "secure": True},
        ])

    assert captured["url"].endswith("/auth/v1/token")
    auth = captured["headers"]["Authorization"]
    assert auth.startswith("Basic ")
    decoded = base64.b64decode(auth.removeprefix("Basic ")).decode()
    assert decoded == "noaihdevm_6iyg0a8l0q:", f"expected the cr_web client_id with empty secret, got {decoded!r}"
    assert "device_id=dev-uuid" in captured["body"]
    assert "device_type=" in captured["body"]


def test_check_crunchyroll_alive_on_200_with_access_token() -> None:
    """Successful token exchange must flip alive=True and surface country
    even when the downstream account/profile calls aren't mocked (the
    follow-up GETs go through ``_safe_get`` which is independent)."""
    resp = {
        "status": 200,
        "json": {
            "access_token": "the-token",
            "country": "JP",
            "token_type": "Bearer",
            "scope": "account",
            "expires_in": 300,
        },
        "text": "",
        "via": "cffi",
    }
    with patch.object(cookie_checker, "_request_json", return_value=resp):
        # ``_safe_get`` is what fetches accounts/profile/subscriptions; the
        # test doesn't need them populated, just needs alive=True.
        with patch.object(cookie_checker, "_safe_get", side_effect=Exception("skip")):
            r = cookie_checker.check_crunchyroll(_minimal_crunchy_cookies())
    assert r["alive"] is True
    assert r["info"]["country"] == "JP"
    assert r.get("error") is None
