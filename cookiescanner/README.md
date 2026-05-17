# cookie-scanner

Cookie-based session scanner for **blackbox.ai**, **manus.im**, and **perplexity.ai**.

For each site it:

1. Validates whether your stored cookies are still **alive** or **dead**.
2. If alive, scrapes whatever the authenticated browser endpoints expose:
   email, plan / pro / premium flag, renewal date, credits, etc.

No API keys involved — this hits the same internal endpoints the
browser UI uses, with your cookies attached.

---

## Install

```bash
cd cookie-scanner
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

That installs the `cookie-scanner` console script.

> Uses `curl_cffi` to impersonate Chrome's TLS / JA3 fingerprint, which is
> what gets past Cloudflare on perplexity.ai without a residential IP.
> If you ever do need a resi proxy, pass `--proxy`.

---

## Quick start

Export your cookies from the browser (any of these works):

- **EditThisCookie / Cookie-Editor JSON** export
- **`cookies.txt`** (Netscape format, what `yt-dlp --cookies` uses)
- A raw `Cookie:` header copied out of DevTools
- A plain `{"name": "value", ...}` JSON dict

Then:

```bash
cookie-scanner scan cookies.json
# or merge several sources at once:
cookie-scanner scan -c perplexity.json -c blackbox.json -c manus.json
```

Output looks like:

```
──────────── blackbox.ai  —  ALIVE ────────────
email                  you@example.com
hasActiveSubscription  False
id                     c45f56e2-9c12-420c-...
is_pro                 False
plan                   free
provider               stripe
session_expires        2026-06-14T06:15:26.887Z

──────────── manus.im  —  ALIVE ────────────
email            you@example.com
name             your_name
user_id          310519663662422955
user_type        user
session_issued   2026-05-15T06:04:34+00:00
session_expires  2026-08-13T06:04:34+00:00

──────────── perplexity.ai  —  ALIVE ────────────
email                you@example.com
plan                 free
is_pro               False
payment_tier         none
subscription_tier    none
subscription_status  none
session_expires      2026-06-14T06:15:46Z

──────────── blackbox.ai  —  DEAD ────────────
note: /api/auth/session returned null/no user (cookie dead)
```

### Useful flags

| flag | what it does |
| -- | -- |
| `--only perplexity.ai` | run a single site only |
| `--proxy http://user:pass@host:port` | route all traffic through a proxy |
| `--json` | emit machine-readable JSON instead of the table |
| `--verbose` / `-v` | print every endpoint that was probed |

### Python API

```python
from cookiescanner import load_cookies, scan_all

jar = load_cookies("cookies.json")
for result in scan_all(jar):
    print(result.site, "alive" if result.alive else "dead", result.info)
```

---

## What each adapter checks

### perplexity.ai

- **Alive check**: `GET /api/auth/session` returns a `user` object.
- **Account info**: `/api/user` — returns `email`, `username`,
  `payment_tier`, `subscription_tier`, `subscription_status`,
  `subscription_source`, `is_in_organization`.
- **Cookie of record**: `__Secure-next-auth.session-token` (on
  `www.perplexity.ai`).
- **Note on `/rest/*`**: the `/rest/user/settings` and
  `/rest/billing/sub_data_v2` endpoints are gated by a `cf_clearance`
  cookie that is fingerprint-locked to the user's browser. From a
  non-browser TLS client they always come back as a Cloudflare 403
  challenge, so we don't bother with them — `/api/user` already has
  the same data.

### blackbox.ai

- **Alive check**: `GET /api/auth/session` returns a `user` object.
- **Account info**: 
  - `GET /api/account/current` — `userEmail`, `availableAccounts`.
  - `POST /api/check-subscription` with `{email}` — full subscription
    block (`hasActiveSubscription`, `expiryTimestamp`, `customerId`,
    `isTeam`, `numSeats`, `previouslySubscribed`, `provider`,
    `isTrialSubscription`, `activeInsuffientCredits`).
  - `GET /api/v0/credits` / `/api/credits/get` — best-effort credit
    balance (often `400 No customer ID` for free accounts).
- **Cookie of record**: `next-auth.session-token` (domain
  `.blackbox.ai`). The companion per-host `sessionId` /
  `__Host-authjs.csrf-token` cookies are also forwarded.

### manus.im

Manus is the odd one out — there is **no public `/me` endpoint**.
The API on `api.manus.im` sits behind an APISIX edge that returns 503
on anything it doesn't whitelist, and rejects clients lacking the
`x-client-type: web` header. Their public JS bundles only reference
`/api/chat/*`, `/api/internal/*` and `/api/user_behavior/*` paths.

We sidestep all of that:

- **Alive check**: the `session_id` cookie value **is a JWT** signed
  by Manus. We decode the payload (no signature check — we don't have
  their secret) and verify `exp` is in the future.
- **Account info from JWT**: `email`, `name`, `user_id`, `team_uid`,
  `type`, `iat`, `exp` (we surface these as
  `session_issued` / `session_expires`).
- **Best-effort subscription probe**: walks `PROBE_PATHS` on
  `api.manus.im` with the required headers and harvests any
  recognised plan / credit / renewal fields. Run with `-v` to see
  which paths returned data.
- **Cookie of record**: `session_id` (or `__Secure-session_id`).

If you find a new manus endpoint via DevTools, drop it into
`PROBE_PATHS` inside `cookiescanner/sites/manus.py` — it'll be picked
up automatically.

---

## Extending

To add a new site, drop a file under `cookiescanner/sites/` that
subclasses `SiteAdapter` and register it in `sites/__init__.py`. See
`blackbox.py` for the shape — there's nothing special about it.

---

## Notes / gotchas

- **Cloudflare**: perplexity is behind CF with bot challenges. We use
  `curl_cffi` with a Chrome TLS profile to get through. If you start
  getting `403` HTML challenge responses anyway, pass a resi proxy
  with `--proxy`.
- **Cookie freshness**: Next-auth tokens are JWTs with rolling
  expiry — if you stop hitting the site for ~30 days the token
  invalidates server-side even if its `expires` field hasn't elapsed.
- **No retries**: every probe is one-shot. If you want retries / a
  scheduled run, wrap `scan_all()` in your own loop.
- **No state-changing writes**: the only `POST` is
  `blackbox.ai/api/check-subscription` with `{email}` (Blackbox
  requires it as POST). Everything else is a GET; nothing modifies
  account state.
