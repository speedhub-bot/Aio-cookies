"""Base class for site adapters."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ..cookies import CookieJar
from ..http import HttpClient
from ..types import ScanResult


class SiteAdapter:
    """Subclass and set ``SITE``, ``HOST`` (cookie-domain), ``BASE_URL``.

    Override ``scan()`` to define the probing flow.
    """

    SITE: str = ""
    HOST: str = ""
    BASE_URL: str = ""
    # Common cookies the site uses. Used to give a useful warning when none
    # of the expected cookies are present in the jar.
    KNOWN_COOKIES: tuple[str, ...] = ()

    def __init__(self, jar: CookieJar, proxy: str | None = None) -> None:
        self.jar = jar
        self.proxy = proxy

    # ----- helpers ------------------------------------------------------

    def host_cookies(self) -> dict[str, str]:
        return self.jar.for_host(self.HOST)

    def make_client(self, extra_headers: dict[str, str] | None = None) -> HttpClient:
        return HttpClient(
            cookies=self.host_cookies(),
            proxy=self.proxy,
            extra_headers=extra_headers,
        )

    def referer(self) -> str:
        return self.BASE_URL.rstrip("/") + "/"

    def common_headers(self) -> dict[str, str]:
        host = urlparse(self.BASE_URL).netloc
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": f"https://{host}",
            "Referer": self.referer(),
        }

    @staticmethod
    def try_json(resp) -> Any:
        """Return parsed JSON or ``None``."""
        try:
            text = resp.text
            return json.loads(text)
        except Exception:
            return None

    # ----- entrypoint ---------------------------------------------------

    def scan(self) -> ScanResult:  # pragma: no cover — must override
        raise NotImplementedError

    # ----- diagnostics --------------------------------------------------

    def cookies_warning(self) -> str | None:
        """Return a string warning if none of the well-known cookies are present."""
        if not self.KNOWN_COOKIES:
            return None
        host_cookies = self.host_cookies()
        if not any(name in host_cookies for name in self.KNOWN_COOKIES):
            return (
                f"No expected cookies for {self.SITE} were found "
                f"(looked for: {', '.join(self.KNOWN_COOKIES)})."
            )
        return None
