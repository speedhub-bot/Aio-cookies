"""spotify.com adapter.

Auth model: long-lived session cookies (``sp_dc``, ``sp_key``, ``sp_t``)
set on ``.spotify.com``. The web account dashboard at
``www.spotify.com/account/`` exposes a handful of authenticated REST
endpoints that take just the session cookies — no OAuth bearer needed.

Endpoints we use:

    GET /api/account-settings/v1/profile
        -> {profile: {email, country, displayName, ...}}

    GET /account/overview/
        -> HTML containing an embedded JSON blob with the user's
           ``currentPlan`` (premium / family_premium_v2 / duo_premium /
           student_premium / free / ...), ``isSubAccount``,
           ``inviteToken`` (family owners only), billing country, etc.

    GET /api/family/v1/family/home   (only succeeds for Family plans)
        -> family roster + remaining seats

Strategy: profile endpoint is the alive check. Overview HTML gives plan
+ billing. Family endpoint is best-effort.
"""

from __future__ import annotations

import re
from typing import Any

from ..types import ScanResult
from .base import SiteAdapter


class SpotifyAdapter(SiteAdapter):
    SITE = "spotify.com"
    HOST = "www.spotify.com"
    BASE_URL = "https://www.spotify.com"
    KNOWN_COOKIES = ("sp_dc", "sp_key", "sp_t")

    def scan(self) -> ScanResult:
        result = ScanResult(site=self.SITE, alive=False)

        warning = self.cookies_warning()
        if warning:
            result.error = warning
            return result

        headers = {
            **self.common_headers(),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        with self.make_client(extra_headers=headers) as http:
            # 1) Profile = alive check (JSON, requires session)
            url = self.BASE_URL + "/api/account-settings/v1/profile"
            r = http.get(url, headers={"Accept": "application/json"})
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            if r.status_code != 200:
                result.error = (
                    f"/api/account-settings/v1/profile returned "
                    f"{r.status_code} (cookie dead or wrong jar)"
                )
                return result
            data = self.try_json(r)
            if not isinstance(data, dict):
                result.error = "profile endpoint returned non-JSON"
                return result

            profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
            email = profile.get("email") or data.get("email")
            country = profile.get("country") or data.get("country")
            # ``/api/account-settings/v1/profile`` returns 200 with a stub
            # body for some logged-out edge cases; require *both* the email
            # and country fields to land before calling the cookie alive.
            if not email or not country:
                result.error = "profile payload missing email/country (cookie likely dead)"
                return result

            result.alive = True
            if email:
                result.info["email"] = email
            if country:
                result.info["country"] = str(country).upper()
            if profile.get("displayName"):
                result.info["name"] = profile["displayName"]
            if profile.get("birthdate"):
                result.info["birthdate"] = profile["birthdate"]
            if profile.get("phoneNumber") or data.get("phoneNumber"):
                result.info["phone"] = profile.get("phoneNumber") or data.get("phoneNumber")
            if profile.get("createdAt"):
                result.info["member_since"] = profile["createdAt"]

            # 2) Account overview HTML — has currentPlan + billing details.
            url = self.BASE_URL + "/account/overview/"
            r = http.get(
                url,
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,*/*;q=0.8"
                    )
                },
            )
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            if r.status_code == 200 and r.text:
                _absorb_overview(r.text, result.info)

            # 3) Family home — owner gets the invite link + roster.
            url = self.BASE_URL + "/api/family/v1/family/home"
            r = http.get(url, headers={"Accept": "application/json"})
            result.endpoints_tried.append(
                {"url": url, "status": r.status_code, "len": len(r.text)}
            )
            if r.status_code == 200:
                fam = self.try_json(r)
                if isinstance(fam, dict):
                    _absorb_family(fam, result.info)

        _finalise(result.info)
        return result


# ----- helpers ---------------------------------------------------------


_PLAN_KEY_PATTERNS = (
    re.compile(r'"currentPlan"\s*:\s*"([^"]+)"'),
    re.compile(r'"current_plan"\s*:\s*"([^"]+)"'),
)
_OWNER_PATTERN = re.compile(r'"isSubAccount"\s*:\s*(true|false)', re.IGNORECASE)
_INVITE_TOKEN_PATTERN = re.compile(r'"inviteToken"\s*:\s*"([0-9a-fA-F]+)"')
_NEXT_PAYMENT_PATTERN = re.compile(r'"nextPaymentDate"\s*:\s*"([^"]+)"')
_AUTOPAY_PATTERN = re.compile(r'"autopayStatus"\s*:\s*"([^"]+)"', re.IGNORECASE)


def _absorb_overview(html: str, info: dict[str, Any]) -> None:
    """Extract whatever account fields we can find in the overview HTML."""
    plan = None
    for pat in _PLAN_KEY_PATTERNS:
        m = pat.search(html)
        if m:
            plan = m.group(1).strip()
            break
    if plan:
        info["currentPlan"] = plan
        info["plan"] = _PLAN_LABELS.get(plan, plan)

    m = _OWNER_PATTERN.search(html)
    if m:
        # ``isSubAccount`` == True means non-owner (member).
        info["isSubAccount"] = m.group(1).lower() == "true"

    m = _INVITE_TOKEN_PATTERN.search(html)
    if m:
        token = m.group(1)
        info["inviteToken"] = token
        info["inviteLink"] = f"https://www.spotify.com/family/join/invite/{token}/"

    m = _NEXT_PAYMENT_PATTERN.search(html)
    if m:
        info["renewal"] = m.group(1)

    m = _AUTOPAY_PATTERN.search(html)
    if m:
        info["autopayStatus"] = m.group(1)


def _absorb_family(payload: dict[str, Any], info: dict[str, Any]) -> None:
    members = payload.get("members")
    if isinstance(members, list):
        info["familyMembers"] = [
            (m.get("nickname") or m.get("name") or m.get("memberId") or "?")
            for m in members
            if isinstance(m, dict)
        ]
        info["familySize"] = len(members)

    plan = payload.get("plan") or payload.get("planType")
    if plan and not info.get("plan"):
        info["plan"] = str(plan)

    address = payload.get("address")
    if isinstance(address, dict):
        joined = " ".join(
            str(v) for v in address.values() if v and isinstance(v, (str, int))
        ).strip()
        if joined:
            info["address"] = joined

    # ``invitations`` carries unused slots; presence of ``inviteCode`` /
    # ``inviteToken`` here means the caller is the family owner.
    for k in ("inviteCode", "inviteToken"):
        if payload.get(k) and not info.get("inviteToken"):
            info["inviteToken"] = payload[k]
            info["inviteLink"] = (
                f"https://www.spotify.com/family/join/invite/{payload[k]}/"
            )


_PLAN_LABELS = {
    "premium": "Premium",
    "premium_mini": "Premium Mini",
    "basic_premium": "Premium Basic",
    "duo_premium": "Duo Premium",
    "family_premium_v2": "Family Premium",
    "family_basic": "Family Basic",
    "student_premium": "Student Premium",
    "student_premium_hulu": "Student Premium-Hulu",
    "free": "Free",
}


def _finalise(info: dict[str, Any]) -> None:
    plan_raw = info.get("plan") or info.get("currentPlan") or "free"
    plan = str(plan_raw).lower()
    info["is_pro"] = "premium" in plan or "family" in plan or "duo" in plan or "student" in plan
    if not info.get("plan"):
        info["plan"] = plan_raw
