"""Thin HTTP helper around curl_cffi.

curl_cffi spoofs Chrome's TLS / JA3 fingerprint, which is what gets
us past Cloudflare on perplexity.ai and the Akamai-style edge in
front of manus.im without scraping HTML challenge pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from curl_cffi import requests as cr


# Stick to a recent Chrome impersonation. Bump this when curl_cffi
# adds newer profiles — the older ones eventually get fingerprinted.
DEFAULT_IMPERSONATE = "chrome"
DEFAULT_TIMEOUT = 20


@dataclass
class HttpClient:
    """Per-site HTTP client. Holds cookies, proxy, and a session."""

    cookies: dict[str, str]
    proxy: str | None = None
    impersonate: str = DEFAULT_IMPERSONATE
    timeout: int = DEFAULT_TIMEOUT
    extra_headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        proxies = None
        if self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}
        # curl_cffi.Session is what gives us connection reuse + cookie jar.
        self._session = cr.Session(impersonate=self.impersonate, proxies=proxies)
        # Seed cookies. We don't know the domain here, so we let the
        # caller pass already-host-filtered cookies via for_host(...).
        for name, value in self.cookies.items():
            self._session.cookies.set(name, value)

    def get(self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any):
        merged_headers = dict(self.extra_headers or {})
        if headers:
            merged_headers.update(headers)
        return self._session.get(
            url,
            headers=merged_headers,
            timeout=self.timeout,
            allow_redirects=False,
            **kwargs,
        )

    def post(self, url: str, *, headers: dict[str, str] | None = None, **kwargs: Any):
        merged_headers = dict(self.extra_headers or {})
        if headers:
            merged_headers.update(headers)
        return self._session.post(
            url,
            headers=merged_headers,
            timeout=self.timeout,
            allow_redirects=False,
            **kwargs,
        )

    def session_cookies(self) -> dict[str, str]:
        """Return the session's current cookie jar as a flat dict.

        Useful after a request whose ``Set-Cookie`` header rotates a
        session token (e.g. Roblox's ``.ROBLOSECURITY`` refresh flow) —
        the curl_cffi session jar is updated in place, so reading
        cookies back here gets the *refreshed* value, not the seeded one.
        """
        out: dict[str, str] = {}
        try:
            for c in self._session.cookies:
                name = getattr(c, "name", None)
                value = getattr(c, "value", None)
                if name and value is not None:
                    out[str(name)] = str(value)
        except TypeError:
            # Some curl_cffi versions expose ``cookies`` as a mapping.
            try:
                for name, value in dict(self._session.cookies).items():
                    if name and value is not None:
                        out[str(name)] = str(value)
            except Exception:
                pass
        return out

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
