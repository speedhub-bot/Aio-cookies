"""Tests for the Roblox ``.ROBLOSECURITY`` refresh flow.

Roblox rotates ``.ROBLOSECURITY`` server-side any time it sees the
same token used from a different IP than where it was minted.
``RobloxAdapter._refresh_roblosecurity`` proactively triggers that
rotation through the public ``/v1/authentication-ticket`` →
``/v1/authentication-ticket/redeem`` flow so the account survives
imports through a scanner / bot.

These tests fake the HTTP layer end-to-end (no network) so they can
exercise each branch of the refresh flow deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Make the repo root importable so ``cookiescanner`` resolves.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cookiescanner.cookies import Cookie, CookieJar  # noqa: E402
from cookiescanner.sites.roblox import RobloxAdapter  # noqa: E402


# ---------- Fake HTTP layer ----------


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


class _FakeHttp:
    """Stand-in for ``cookiescanner.http.HttpClient``.

    The adapter calls ``http.get``, ``http.post`` and ``http.session_cookies``;
    we record every call and return scripted responses keyed by URL.
    """

    def __init__(
        self,
        *,
        get_handlers: dict[str, _FakeResponse] | None = None,
        post_script: list[_FakeResponse] | None = None,
        cookies_after: list[dict[str, str]] | None = None,
    ) -> None:
        self.get_handlers = dict(get_handlers or {})
        # Post responses are returned in order so we can simulate the
        # ticket → ticket-with-csrf → redeem progression.
        self.post_script = list(post_script or [])
        self.cookies_timeline = list(cookies_after or [{".ROBLOSECURITY": "OLD_VALUE"}])
        self.calls: list[dict[str, Any]] = []
        self._cookie_call_idx = 0

    def __enter__(self) -> "_FakeHttp":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def get(self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers, "kwargs": kwargs})
        return self.get_handlers.get(url, _FakeResponse(status_code=404, text=""))

    def post(self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "headers": headers, "kwargs": kwargs})
        if not self.post_script:
            return _FakeResponse(status_code=500, text="ran out of fake responses")
        return self.post_script.pop(0)

    def session_cookies(self) -> dict[str, str]:
        # Step through the timeline so the adapter sees the cookie value
        # change *after* the redeem call returns.
        idx = min(self._cookie_call_idx, len(self.cookies_timeline) - 1)
        self._cookie_call_idx += 1
        return dict(self.cookies_timeline[idx])


def _jar_with_roblosecurity(value: str = "OLD_VALUE") -> CookieJar:
    return CookieJar([Cookie(name=".ROBLOSECURITY", value=value, domain=".roblox.com")])


def _adapter_with_fake(http: _FakeHttp) -> RobloxAdapter:
    a = RobloxAdapter(jar=_jar_with_roblosecurity())
    a.make_client = lambda extra_headers=None: http  # type: ignore[assignment]
    return a


# ---------- Scripts for the standard auth-ticket dance ----------


_CSRF_HEADER = "v1-CSRF-FOR-TEST"
_TICKET = "TICKET-FOR-TEST"
_FRESH_COOKIE = "NEW_REFRESHED_VALUE"


def _successful_refresh_post_script() -> list[_FakeResponse]:
    return [
        # 1) First POST -> 403 + x-csrf-token
        _FakeResponse(status_code=403, headers={"x-csrf-token": _CSRF_HEADER}),
        # 2) Retry with CSRF -> 200 + rbx-authentication-ticket header
        _FakeResponse(status_code=200, headers={"rbx-authentication-ticket": _TICKET}),
        # 3) Redeem -> 200 (curl_cffi will pretend to set the new cookie)
        _FakeResponse(status_code=200, headers={"Set-Cookie": f".ROBLOSECURITY={_FRESH_COOKIE}; Path=/"}, text=""),
    ]


_USER_OK = _FakeResponse(
    status_code=200,
    text='{"id": 4256729542, "name": "awemetk", "displayName": "XENO"}',
)


# ---------- Tests ----------


def test_refresh_rotates_cookie_and_marks_alive() -> None:
    """Happy path: 3-step dance succeeds, alive=True, refreshed_cookies populated."""
    http = _FakeHttp(
        get_handlers={
            RobloxAdapter.USERS_API + "/v1/users/authenticated": _USER_OK,
        },
        post_script=_successful_refresh_post_script(),
        # ``_refresh_roblosecurity`` calls ``session_cookies()`` exactly
        # twice — once to snapshot the OLD value right before the redeem
        # POST, once to read the NEW value right after.
        cookies_after=[
            {".ROBLOSECURITY": "OLD_VALUE"},
            {".ROBLOSECURITY": _FRESH_COOKIE},
        ],
    )
    adapter = _adapter_with_fake(http)
    result = adapter.scan()

    assert result.alive is True
    assert result.refreshed_cookies.get(".ROBLOSECURITY") == _FRESH_COOKIE
    assert result.info.get("cookie_refreshed") is True
    assert result.info.get("user_id") == 4256729542
    # The CSRF retry must carry the X-CSRF-TOKEN header.
    csrf_retries = [
        c for c in http.calls
        if c["method"] == "POST" and c["url"].endswith("/authentication-ticket")
        and (c.get("headers") or {}).get("X-CSRF-TOKEN") == _CSRF_HEADER
    ]
    assert csrf_retries, "expected at least one POST with X-CSRF-TOKEN set after the 403"
    # The redeem POST must carry the negotiation header.
    redeem_calls = [
        c for c in http.calls
        if c["method"] == "POST" and c["url"].endswith("/authentication-ticket/redeem")
    ]
    assert len(redeem_calls) == 1
    assert (redeem_calls[0].get("headers") or {}).get("RBXAuthenticationNegotiation") == "1"


def test_refresh_reports_dead_cookie_on_initial_401() -> None:
    """A 401 from the first authentication-ticket POST means the cookie is dead."""
    http = _FakeHttp(
        post_script=[_FakeResponse(status_code=401, text="")],
        cookies_after=[{".ROBLOSECURITY": "OLD_VALUE"}],
    )
    adapter = _adapter_with_fake(http)
    result = adapter.scan()

    assert result.alive is False
    assert result.error and "401" in result.error and "dead" in result.error
    assert not result.refreshed_cookies


def test_refresh_no_csrf_falls_back_to_alive_check() -> None:
    """If the endpoint never returns ``x-csrf-token``, we fall back to the read-only
    alive check rather than failing the whole scan."""
    http = _FakeHttp(
        get_handlers={
            RobloxAdapter.USERS_API + "/v1/users/authenticated": _USER_OK,
        },
        post_script=[
            # 403 but no x-csrf-token at all.
            _FakeResponse(status_code=403, headers={}),
        ],
        cookies_after=[{".ROBLOSECURITY": "OLD_VALUE"}],
    )
    adapter = _adapter_with_fake(http)
    result = adapter.scan()

    assert result.alive is True
    # No refresh happened — the bot reply shouldn't claim one.
    assert not result.refreshed_cookies
    assert result.info.get("cookie_refreshed") is not True


def test_refresh_no_ticket_in_retry_falls_back() -> None:
    """If the CSRF retry succeeds but doesn't include the ticket header,
    fall back to the read-only alive check."""
    http = _FakeHttp(
        get_handlers={
            RobloxAdapter.USERS_API + "/v1/users/authenticated": _USER_OK,
        },
        post_script=[
            _FakeResponse(status_code=403, headers={"x-csrf-token": _CSRF_HEADER}),
            _FakeResponse(status_code=200, headers={}),  # no rbx-authentication-ticket
        ],
        cookies_after=[{".ROBLOSECURITY": "OLD_VALUE"}],
    )
    adapter = _adapter_with_fake(http)
    result = adapter.scan()

    assert result.alive is True
    assert not result.refreshed_cookies


def test_refresh_cookie_unchanged_after_redeem_is_not_reported_as_rotated() -> None:
    """If for any reason the Set-Cookie didn't actually change the value
    in the session jar, don't lie to the user about a refresh."""
    http = _FakeHttp(
        get_handlers={
            RobloxAdapter.USERS_API + "/v1/users/authenticated": _USER_OK,
        },
        post_script=_successful_refresh_post_script(),
        # Every snapshot returns the same value.
        cookies_after=[{".ROBLOSECURITY": "OLD_VALUE"}],
    )
    adapter = _adapter_with_fake(http)
    result = adapter.scan()

    assert result.alive is True
    assert not result.refreshed_cookies
    assert result.info.get("cookie_refreshed") is not True


# ---------- ScanOutcome / formatting wiring ----------


def test_scan_outcome_carries_refreshed_cookies_through_legacy_adapter() -> None:
    """``_scan_legacy`` must pass ``refreshed_cookies`` from the inner checker
    onto the ``ScanOutcome``."""
    from tgbot import scanner as tg_scanner

    # Pretend claude.ai returned a refreshed cookie too (not real, just wiring).
    def fake_checker(cookies: list[dict[str, Any]], proxy: Any = None) -> dict[str, Any]:
        return {
            "alive": True,
            "info": {"email": "x@y.z"},
            "refreshed_cookies": {"sessionKey": "rotated-sk"},
        }

    with patch.object(tg_scanner.legacy, "CHECKERS", {"claude.ai": fake_checker}):
        out = tg_scanner.scan_one_sync(
            "claude.ai",
            [{"name": "sessionKey", "value": "old", "domain": "claude.ai"}],
            "cookies.txt",
        )
    assert out.alive is True
    assert out.refreshed_cookies == {"sessionKey": "rotated-sk"}


def test_format_outcome_renders_refreshed_cookies_block() -> None:
    """Bot replies must surface the fresh cookie so the user can copy it back."""
    from tgbot.formatting import format_outcome
    from tgbot.scanner import ScanOutcome

    out = ScanOutcome(
        site="roblox.com",
        filename="www_roblox_com_cookies.txt",
        alive=True,
        info={"user_id": 1, "username": "u", "cookie_refreshed": True},
        elapsed_s=1.0,
        refreshed_cookies={".ROBLOSECURITY": "FRESHFRESHFRESH"},
    )
    body = format_outcome(out)
    assert "Refreshed cookies" in body
    assert ".ROBLOSECURITY" in body
    assert "FRESHFRESHFRESH" in body
