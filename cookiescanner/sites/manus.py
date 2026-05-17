"""manus.im adapter.

Manus's web app at ``manus.im`` calls a private API at ``api.manus.im``
through an APISIX edge that returns generic 503s on undocumented paths
and rejects clients lacking the ``x-client-type: web`` header. There is
no public, stable ``/me`` endpoint.

Auth is held in cookie ``session_id`` (sometimes ``__Secure-session_id``).
That cookie value **is** a JWT — Manus signs it themselves and the
payload contains everything we need:

    {
      "email": "...",
      "name": "...",
      "user_id": "...",
      "team_uid": "...",
      "type": "user",
      "iat": <issued_at>,
      "exp": <expiry>
    }

The adapter does two things:

    1. **Alive check** — decode the JWT (no signature check; we don't
       have Manus's key) and confirm ``exp`` is in the future.
    2. **Account info** — surface email / name / user_id / team_uid /
       issued / expires from the JWT. Then best-effort probe a list
       of candidate ``api.manus.im`` paths for subscription / credit
       data. The probe list is configurable via ``PROBE_PATHS`` so you
       can extend it as Manus exposes new endpoints.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any

from ..types import ScanResult
from .base import SiteAdapter


class ManusAdapter(SiteAdapter):
    SITE = "manus.im"
    HOST = "manus.im"
    BASE_URL = "https://manus.im"
    API_BASE = "https://api.manus.im"
    KNOWN_COOKIES = (
        "session_id",
        "__Secure-session_id",
    )

    # Required custom headers — without these APISIX returns 503.
    EXTRA_HEADERS = {
        "x-client-type": "web",
        "x-client-locale": "en",
        "x-client-timezone": "UTC",
    }

    # Candidate paths we probe for additional account info.
    # Manus does not document a "me" endpoint; extend this as you find
    # new ones in DevTools.
    PROBE_PATHS: tuple[str, ...] = (
        "/api/user/info",
        "/api/user/profile",
        "/api/users/me",
        "/api/me",
        "/api/account/info",
        "/api/subscription/info",
        "/api/billing/info",
        "/api/credit/balance",
        "/api/credit/get",
        "/api/credits/get",
        "/api/membership/info",
    )

    def scan(self) -> ScanResult:
        result = ScanResult(site=self.SITE, alive=False)

        host_cookies = self.host_cookies()
        token = (
            host_cookies.get("session_id")
            or host_cookies.get("__Secure-session_id")
        )
        if not token:
            result.error = (
                f"No expected cookies for {self.SITE} were found "
                f"(looked for: {', '.join(self.KNOWN_COOKIES)})."
            )
            return result

        # 1) Decode the JWT payload (no signature verification — we don't
        #    have Manus's secret, but exp is enforced by their API).
        claims = _decode_jwt_payload(token)
        if not isinstance(claims, dict):
            result.error = "session_id cookie is not a JWT we can decode"
            return result

        exp = claims.get("exp")
        if isinstance(exp, (int, float)) and exp < time.time():
            iso = datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
            result.error = f"session_id JWT expired at {iso}"
            return result

        # JWT is alive.
        result.alive = True
        if claims.get("email"):
            result.info["email"] = claims["email"]
        if claims.get("name"):
            result.info["name"] = claims["name"]
        if claims.get("user_id"):
            result.info["user_id"] = claims["user_id"]
        if claims.get("team_uid"):
            result.info["team_uid"] = claims["team_uid"]
        if claims.get("type"):
            result.info["user_type"] = claims["type"]
        if isinstance(exp, (int, float)):
            result.info["session_expires"] = datetime.fromtimestamp(
                int(exp), tz=timezone.utc
            ).isoformat()
        iat = claims.get("iat")
        if isinstance(iat, (int, float)):
            result.info["session_issued"] = datetime.fromtimestamp(
                int(iat), tz=timezone.utc
            ).isoformat()

        # 2) Best-effort probe of candidate account API paths.
        headers = {
            **self.common_headers(),
            **self.EXTRA_HEADERS,
            "Origin": "https://manus.im",
            "Referer": "https://manus.im/app",
        }
        with self.make_client(extra_headers=headers) as http:
            for path in self.PROBE_PATHS:
                url = self.API_BASE + path
                try:
                    resp = http.get(url)
                except Exception as e:
                    result.endpoints_tried.append(
                        {"url": url, "status": "ERR", "error": f"{type(e).__name__}: {e}"}
                    )
                    continue
                entry: dict[str, Any] = {
                    "url": url,
                    "status": resp.status_code,
                    "len": len(resp.text),
                }
                payload = self.try_json(resp)
                if isinstance(payload, dict):
                    # APISIX 404 envelope.
                    status_msg = str(payload.get("status") or "").lower()
                    if status_msg in {"not found", "404", ""} and "data" not in payload:
                        entry["note"] = "endpoint not found"
                    else:
                        entry["json_keys"] = sorted(list(payload.keys()))[:25]
                        _harvest(payload, result.info)
                result.endpoints_tried.append(entry)

        _finalise(result.info)
        return result


# ----- JWT decode ------------------------------------------------------


def _b64decode_url(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode a JWT's payload segment without verifying the signature."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        raw = _b64decode_url(parts[1])
        return json.loads(raw)
    except Exception:
        return None


# ----- harvest + finalise ---------------------------------------------


_KEYS = {
    "plan",
    "plan_name",
    "planName",
    "tier",
    "subscription",
    "subscription_status",
    "subscriptionStatus",
    "membership",
    "membership_type",
    "isPro",
    "is_pro",
    "is_premium",
    "isPremium",
    "credits",
    "credit",
    "credit_balance",
    "creditBalance",
    "remaining_credits",
    "remainingCredits",
    "monthly_credits",
    "monthlyCredits",
    "renewal_date",
    "renewalDate",
    "renews_at",
    "current_period_end",
    "currentPeriodEnd",
    "expires_at",
    "expiresAt",
    "cancel_at",
    "canceled_at",
    "auto_renew",
    "autoRenew",
}


def _harvest(payload: dict[str, Any], out: dict[str, Any]) -> None:
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _KEYS and out.get(k) in (None, "", [], {}):
                    if isinstance(v, (str, int, float, bool)):
                        out[k] = v
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)


def _finalise(info: dict[str, Any]) -> None:
    if "plan" not in info:
        for k in (
            "plan_name",
            "planName",
            "tier",
            "membership",
            "membership_type",
            "subscription_status",
            "subscriptionStatus",
        ):
            if info.get(k):
                info["plan"] = info[k]
                break
    if "plan" not in info:
        # We couldn't pull a plan from the API; the JWT alone doesn't carry
        # subscription state. Default to "unknown".
        info["plan"] = "unknown (no API endpoint returned subscription data)"

    pro = False
    plan_str = str(info.get("plan") or "").lower()
    if plan_str in {"pro", "plus", "premium", "team", "starter", "max", "ultra", "active"} or "pro" in plan_str or "premium" in plan_str:
        pro = True
    for k in ("isPro", "is_pro", "is_premium", "isPremium"):
        if info.get(k) is True:
            pro = True
            break
    info["is_pro"] = pro

    if "renewal" not in info:
        for k in (
            "renewal_date",
            "renewalDate",
            "renews_at",
            "current_period_end",
            "currentPeriodEnd",
            "expires_at",
            "expiresAt",
        ):
            if info.get(k):
                info["renewal"] = info[k]
                break
