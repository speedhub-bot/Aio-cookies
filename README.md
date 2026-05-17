# AIO Cookies

All-in-one cookie validity + account info checker for:

- **claude.ai**, **chatgpt.com**, **cursor.com**, **devin.ai**, **crunchyroll.com**
  (via `cookie_checker.py`)
- **blackbox.ai**, **manus.im**, **perplexity.ai**
  (via the `cookiescanner` package — also shipped as `cookie-scanner.zip`)

Three ways to use it:

1. `cookie_checker.py` — interactive / CLI cookie checker for the 5 legacy sites.
2. `cookiescanner` — installable Python package for the 3 newer sites
   (`pip install -e .` exposes a `cookie-scanner` console script).
3. `tgbot/` — **Telegram bot** that wires both together behind a
   per-site button menu.

---

## Telegram bot

### Features

- **Site-picker keyboard** — tap a button, send your cookies, get back
  ALIVE / DEAD plus every account field the site exposes (email, plan,
  renewal, credits, JWT claims, organisation membership, …).
- **No auto-detect guesswork** — the site you picked is the site we run.
- **Multiple input formats** — EditThisCookie / Cookie-Editor `.json`,
  Netscape `cookies.txt`, raw `Cookie:` header, or a `.zip` of any of
  those.
- **Hit notifications** — toggle in `/settings`. When ON, every ALIVE
  result also fires a hit alert with the cookies attached back as a
  Netscape `cookies.txt` (ready for yt-dlp / curl).
- **Per-user JSON-backed settings** stored under `bot_data/`.

### Setup

```bash
git clone https://github.com/speedhub-bot/AIO-COOKIES.git
cd AIO-COOKIES
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: at minimum, set BOT_TOKEN. API_ID/API_HASH default to
# Telegram Desktop's public values and work out of the box.

python bot.py
```

### Commands

| Command     | What it does                                  |
| ----------- | --------------------------------------------- |
| `/start`    | Site picker keyboard                          |
| `/check`    | Alias of `/start`                             |
| `/sites`    | List supported sites                          |
| `/settings` | Toggle hit notifications                      |
| `/help`     | Usage guide                                   |
| `/about`    | Credits                                       |

### Environment variables

See [`.env.example`](.env.example) for the full list with defaults.
Required: `BOT_TOKEN`. Everything else has a sensible default.

---

## Legacy CLI (`cookie_checker.py`)

Standalone interactive checker for claude.ai / chatgpt.com / cursor.com /
devin.ai / crunchyroll.com:

```bash
python cookie_checker.py                # interactive mode
python cookie_checker.py -f cookies.json
python cookie_checker.py -f cookies/    # folder of cookie files
python cookie_checker.py -f cookies.zip
```

---

## `cookiescanner` package

The package's own README lives at [`cookiescanner/README.md`](cookiescanner/README.md).

Install + use:

```bash
pip install -e .
cookie-scanner scan cookies.json
cookie-scanner scan -c perplexity.json -c blackbox.json -c manus.json
```

---

## Project layout

```
bot.py                       # top-level Telegram bot launcher
tgbot/
  __init__.py
  bot.py                     # Application builder + main()
  config.py                  # env-based config
  handlers.py                # commands, callbacks, document upload
  formatting.py              # HTML formatter + Netscape exporter helpers
  scanner.py                 # unified per-site dispatcher
  storage.py                 # tiny JSON-backed per-user settings

cookie_checker.py            # legacy interactive CLI (5 sites)
cookie-scanner.zip           # original distribution of the scanner package
cookiescanner/               # extracted package (3 sites)
  cli.py
  cookies.py
  http.py
  scanner.py
  types.py
  sites/
    base.py
    blackbox.py
    manus.py
    perplexity.py
examples/
tests/
```

Bot wiring by akaza ([@akaza_isnt](https://t.me/akaza_isnt)).
