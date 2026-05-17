"""roblox.com adapter.

Auth model: single session cookie ``.ROBLOSECURITY`` set on
``.roblox.com``. Roblox ships a clean public web-API which only needs
that cookie (plus a CSRF token, which is only required for POSTs).

Endpoints we use:

    GET https://users.roblox.com/v1/users/authenticated
        -> {id, name, displayName}  — primary alive check

    GET https://accountinformation.roblox.com/v1/email
        -> {email, verified, emailAddress}

    GET https://accountinformation.roblox.com/v1/phone
        -> {countryCode, prefix, phone, isVerified}

    GET https://accountinformation.roblox.com/v1/birthdate
        -> {birthMonth, birthDay, birthYear}

    GET https://economy.roblox.com/v1/users/{id}/currency
        -> {robux}

    GET https://premiumfeatures.roblox.com/v1/users/{id}/validate-membership
        -> raw boolean ``true`` / ``false``

    GET https://accountsettings.roblox.com/v1/email
        -> {verified, emailAddress}   (used as a fallback)
"""

from __future__ import annotations

from typing import Any

from ..types import ScanResult
from .base import SiteAdapter


class RobloxAdapter(SiteAdapter):
    SITE = "roblox.com"
    HOST = "www.roblox.com"
    BASE_URL = "https://www.roblox.com"
    KNOWN_COOKIES = (".ROBLOSECURITY",)

    USERS_API = "https://users.roblox.com"
    ACCOUNT_INFO_API = "https://accountinformation.roblox.com"
    ACCOUNT_SETTINGS_API = "https://accountsettings.roblox.com"
    ECONOMY_API = "https://economy.roblox.com"
    PREMIUM_API = "https://premiumfeatures.roblox.com"

    # Cookies live on ``.roblox.com``; explicitly merge across subdomains
    # so the api.* hosts get the cookie too.
    SUBDOMAIN_HOSTS = (
        "www.roblox.com",
        "users.roblox.com",
        "accountinformation.roblox.com",
        "accountsettings.roblox.com",
        "economy.roblox.com",
        "premiumfeatures.roblox.com",
        ".roblox.com",
    )

    def host_cookies(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for host in self.SUBDOMAIN_HOSTS:
            merged.update(self.jar.for_host(host))
        return merged

    def scan(self) -> ScanResult:
        result = ScanResult(site=self.SITE, alive=False)

        warning = self.cookies_warning()
        if warning:
            result.error = warning
            return result

        headers = self.common_headers()
        with self.make_client(extra_headers=headers) as http:
            # 1) Authenticated user — alive check.
            url = self.USERS_API + "/v1/users/authenticated"
            r = http.get(url)
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            if r.status_code == 401:
                result.error = "/v1/users/authenticated returned 401 (cookie dead)"
                return result
            if r.status_code != 200:
                result.error = f"/v1/users/authenticated returned HTTP {r.status_code}"
                return result
            data = self.try_json(r)
            if not isinstance(data, dict) or not data.get("id"):
                result.error = "authenticated endpoint returned no user id"
                return result

            user_id = data.get("id")
            result.alive = True
            result.info["user_id"] = user_id
            if data.get("name"):
                result.info["username"] = data["name"]
            if data.get("displayName"):
                result.info["name"] = data["displayName"]

            # 2) Email + verification.
            for url in (
                self.ACCOUNT_INFO_API + "/v1/email",
                self.ACCOUNT_SETTINGS_API + "/v1/email",
            ):
                r = http.get(url)
                result.endpoints_tried.append(
                    {"url": url, "status": r.status_code, "len": len(r.text)}
                )
                payload = self.try_json(r)
                if isinstance(payload, dict):
                    email = payload.get("emailAddress") or payload.get("email")
                    if email and not result.info.get("email"):
                        result.info["email"] = email
                    if payload.get("verified") is not None and result.info.get("email_verified") is None:
                        result.info["email_verified"] = bool(payload["verified"])

            # 3) Phone number.
            url = self.ACCOUNT_INFO_API + "/v1/phone"
            r = http.get(url)
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            phone_payload = self.try_json(r)
            if isinstance(phone_payload, dict) and phone_payload.get("phone"):
                cc = phone_payload.get("countryCode") or ""
                prefix = phone_payload.get("prefix") or ""
                phone = phone_payload.get("phone")
                result.info["phone"] = f"{cc}{prefix}{phone}".strip()
                if phone_payload.get("isVerified") is not None:
                    result.info["phone_verified"] = bool(phone_payload["isVerified"])

            # 4) Birthdate.
            url = self.ACCOUNT_INFO_API + "/v1/birthdate"
            r = http.get(url)
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            bd = self.try_json(r)
            if isinstance(bd, dict) and bd.get("birthYear"):
                year = bd["birthYear"]
                month = bd.get("birthMonth") or 1
                day = bd.get("birthDay") or 1
                result.info["birthdate"] = f"{year:04d}-{int(month):02d}-{int(day):02d}"

            # 5) Robux balance.
            url = f"{self.ECONOMY_API}/v1/users/{user_id}/currency"
            r = http.get(url)
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            cur = self.try_json(r)
            if isinstance(cur, dict) and cur.get("robux") is not None:
                result.info["robux"] = cur["robux"]

            # 6) Premium membership.
            url = f"{self.PREMIUM_API}/v1/users/{user_id}/validate-membership"
            r = http.get(url)
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            try:
                is_premium = r.text.strip().lower() == "true"
            except Exception:  # noqa: BLE001
                is_premium = False
            result.info["is_premium"] = is_premium

        _finalise(result.info)
        return result


# ----- helpers ---------------------------------------------------------


def _finalise(info: dict[str, Any]) -> None:
    if info.get("is_premium"):
        info["plan"] = "Premium"
        info["is_pro"] = True
    else:
        info["plan"] = "Free"
        info["is_pro"] = False
