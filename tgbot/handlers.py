"""Telegram handlers — commands, site-picker callbacks, document upload."""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
from pathlib import Path
from typing import Iterable

from loguru import logger
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config, storage
from .formatting import format_hit, format_outcome, format_summary
from .scanner import ScanOutcome, dump_netscape, scan_site


# ── Inline keyboards ─────────────────────────────────────────


def _sites_keyboard() -> InlineKeyboardMarkup:
    """Two-column grid of site buttons."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for site in config.SUPPORTED_SITES:
        row.append(
            InlineKeyboardButton(
                f"{site['emoji']} {site['label']}",
                callback_data=f"site:{site['id']}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("\u2699\ufe0f Settings", callback_data="settings"),
            InlineKeyboardButton("\u2139\ufe0f Help", callback_data="help"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _settings_keyboard(hit_on: bool) -> InlineKeyboardMarkup:
    toggle_label = (
        "\U0001f514 Hit notifications: ON"
        if hit_on
        else "\U0001f515 Hit notifications: OFF"
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(toggle_label, callback_data="toggle:hit_notifications")],
            [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="home")],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="home")]]
    )


# ── Static copy ──────────────────────────────────────────────


_START_TEXT = (
    "\U0001f36a <b>AIO Cookies Bot</b>\n"
    "Cookie validity + account info checker.\n\n"
    "Pick a site below, then send me your cookies "
    "(<code>.json</code> / <code>.txt</code> / <code>.zip</code>)."
)

_HELP_TEXT = (
    "<b>How to use</b>\n"
    "1. Tap a site button below (or use /check).\n"
    "2. Send me a cookie export for that site:\n"
    "   \u2022 EditThisCookie / Cookie-Editor <code>.json</code>\n"
    "   \u2022 Netscape <code>cookies.txt</code> (yt-dlp format)\n"
    "   \u2022 Raw <code>Cookie:</code> header text\n"
    "   \u2022 A <code>.zip</code> of any of the above\n"
    "3. I run the matching checker and reply with ALIVE / DEAD plus "
    "every account field the site exposes.\n\n"
    "<b>Commands</b>\n"
    "/start \u2014 Site picker\n"
    "/check \u2014 Same as /start\n"
    "/sites \u2014 List supported sites\n"
    "/settings \u2014 Toggle hit notifications\n"
    "/help \u2014 This message\n"
    "/about \u2014 Credits"
)

_ABOUT_TEXT = (
    "<b>AIO Cookies Bot</b>\n"
    "Built on top of <code>cookie_checker.py</code> and the "
    "<code>cookiescanner</code> package in this repo.\n"
    "Bot wiring by akaza (<a href=\"https://t.me/akaza_isnt\">@akaza_isnt</a>)."
)


def _sites_text() -> str:
    lines = ["<b>Supported sites</b>"]
    for s in config.SUPPORTED_SITES:
        lines.append(f"  {s['emoji']} {s['label']} \u2014 <code>{s['id']}</code>")
    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────


async def _reply_or_edit(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query:
        q = update.callback_query
        try:
            await q.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except BadRequest:
            # Message is unchanged or too old to edit — fall back to a new one.
            assert q.message is not None
            await q.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
    elif update.message is not None:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )


def _selected_site(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if context.user_data is None:
        return None
    site = context.user_data.get("selected_site")
    return str(site) if site else None


def _set_selected_site(context: ContextTypes.DEFAULT_TYPE, site_id: str) -> None:
    if context.user_data is not None:
        context.user_data["selected_site"] = site_id


# ── Commands ─────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_or_edit(update, _START_TEXT, _sites_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_or_edit(update, _HELP_TEXT, _back_keyboard())


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_or_edit(update, _ABOUT_TEXT, _back_keyboard())


async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_or_edit(update, _sites_text(), _sites_keyboard())


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    hit_on = await storage.get_hit_notifications(user.id)
    text = (
        "<b>Settings</b>\n\n"
        "When <i>hit notifications</i> is ON, every ALIVE result also "
        "triggers a hit-style alert in this chat with the cookies "
        "attached as a <code>cookies.txt</code> (Netscape format)."
    )
    await _reply_or_edit(update, text, _settings_keyboard(hit_on))


# ── Callback queries ────────────────────────────────────────


async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or q.data is None:
        return
    await q.answer()

    data = q.data
    user = update.effective_user
    if data == "home":
        await cmd_start(update, context)
        return
    if data == "help":
        await cmd_help(update, context)
        return
    if data == "settings":
        await cmd_settings(update, context)
        return
    if data.startswith("toggle:"):
        if user is None:
            return
        key = data.split(":", 1)[1]
        if key == "hit_notifications":
            new_val = await storage.toggle_bool(
                user.id, "hit_notifications", default=config.HIT_NOTIFICATIONS_DEFAULT
            )
            text = (
                "<b>Settings</b>\n\n"
                f"Hit notifications are now <b>{'ON' if new_val else 'OFF'}</b>."
            )
            await _reply_or_edit(update, text, _settings_keyboard(new_val))
        return
    if data.startswith("site:"):
        site_id = data.split(":", 1)[1]
        if site_id not in config.SUPPORTED_SITE_IDS:
            await _reply_or_edit(update, "\u274c Unknown site.", _sites_keyboard())
            return
        _set_selected_site(context, site_id)
        emoji = config.site_emoji(site_id)
        text = (
            f"{emoji} <b>{site_id}</b> selected.\n\n"
            "Now send me your cookie file:\n"
            "  \u2022 <code>.json</code> (EditThisCookie / Cookie-Editor)\n"
            "  \u2022 <code>.txt</code> (Netscape / yt-dlp <code>cookies.txt</code>)\n"
            "  \u2022 <code>.zip</code> of multiple cookie files"
        )
        await _reply_or_edit(update, text, _back_keyboard())
        return


# ── Document upload ──────────────────────────────────────────


_ALLOWED_EXTS = {".json", ".txt", ".cookie", ".cookies", ".zip", ".header"}


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user = update.effective_user
    if msg is None or msg.document is None or user is None:
        return

    site_id = _selected_site(context)
    if not site_id:
        await msg.reply_text(
            "\u2139\ufe0f Pick a site first \u2014 use /start or /check.",
            reply_markup=_sites_keyboard(),
        )
        return

    doc = msg.document
    filename = doc.file_name or "cookies"
    ext = Path(filename).suffix.lower()
    if ext and ext not in _ALLOWED_EXTS:
        await msg.reply_text(
            f"\u274c Unsupported file type: <code>{ext}</code>.\n"
            "Send a .json, .txt, or .zip.",
            parse_mode=ParseMode.HTML,
        )
        return

    if doc.file_size and doc.file_size > config.MAX_FILE_BYTES:
        await msg.reply_text(
            f"\u274c File too large ({doc.file_size} bytes). "
            f"Max: {config.MAX_FILE_BYTES} bytes.",
        )
        return

    status_msg = await msg.reply_text(
        f"\u23f3 Scanning <b>{filename}</b> against "
        f"<b>{config.site_label(site_id)}</b>\u2026",
        parse_mode=ParseMode.HTML,
    )

    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=ext or "",
        dir=str(config.TEMP_DIR),
    ) as tmp:
        tmp_path = tmp.name

    try:
        try:
            tg_file = await doc.get_file()
            await tg_file.download_to_drive(tmp_path)
        except Exception:
            logger.exception("Failed to download document for user {}", user.id)
            await status_msg.edit_text("\u274c Failed to download your file from Telegram.")
            return

        try:
            outcomes = await asyncio.wait_for(
                scan_site(site_id, tmp_path, filename),
                timeout=config.JOB_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await status_msg.edit_text(
                f"\u23f1\ufe0f Scan timed out after {config.JOB_TIMEOUT_SECONDS}s."
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scan failed for user {}", user.id)
            await status_msg.edit_text(f"\u274c Scan failed: {exc}")
            return

        try:
            await status_msg.delete()
        except BadRequest:
            pass

        await _deliver_outcomes(update, context, site_id, outcomes)

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def _deliver_outcomes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    site_id: str,
    outcomes: list[ScanOutcome],
) -> None:
    msg = update.message
    user = update.effective_user
    if msg is None or user is None:
        return

    if len(outcomes) > 1:
        await msg.reply_text(format_summary(outcomes), parse_mode=ParseMode.HTML)

    hit_on = await storage.get_hit_notifications(user.id)

    for outcome in outcomes:
        await msg.reply_text(
            format_outcome(outcome),
            parse_mode=ParseMode.HTML,
            reply_markup=_back_keyboard() if len(outcomes) == 1 else None,
        )

        if outcome.alive and hit_on:
            await _send_hit(update, outcome)


async def _send_hit(update: Update, outcome: ScanOutcome) -> None:
    msg = update.message
    if msg is None:
        return
    netscape = dump_netscape(outcome.cookies, default_domain=outcome.site)
    if not netscape.strip():
        return
    bio = io.BytesIO(netscape.encode("utf-8"))
    bio.name = f"{outcome.site}.cookies.txt"
    await msg.reply_document(
        document=InputFile(bio, filename=bio.name),
        caption=format_hit(outcome),
        parse_mode=ParseMode.HTML,
    )


# ── Catch-all ────────────────────────────────────────────────


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Friendly fallback for users who type instead of tapping/uploading."""
    if update.message is None:
        return
    site_id = _selected_site(context)
    if site_id:
        await update.message.reply_text(
            f"\u2139\ufe0f I'm waiting for your <b>{config.site_label(site_id)}</b> "
            "cookie file (.json / .txt / .zip).",
            parse_mode=ParseMode.HTML,
            reply_markup=_back_keyboard(),
        )
    else:
        await update.message.reply_text(
            "\u2139\ufe0f Pick a site first \u2014 use /start or /check.",
            reply_markup=_sites_keyboard(),
        )


# ── Registration ─────────────────────────────────────────────


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_start))
    app.add_handler(CommandHandler("sites", cmd_sites))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
