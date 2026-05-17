"""Tiny JSON-backed per-user settings store.

Keeps the dependency surface small — a single file under ``DATA_DIR``
is enough for the bot's only stateful concept (the hit-notification
toggle). Reads are in-process and writes are atomic via a rename.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from . import config


_LOCK = asyncio.Lock()
_CACHE: dict[str, dict[str, Any]] | None = None


def _settings_path() -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / "settings.json"


def _load_sync() -> dict[str, dict[str, Any]]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_sync(data: dict[str, dict[str, Any]]) -> None:
    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


async def _ensure_loaded() -> dict[str, dict[str, Any]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = await asyncio.to_thread(_load_sync)
    return _CACHE


async def get_user_settings(user_id: int) -> dict[str, Any]:
    """Return the full settings dict for a user (creates defaults)."""
    async with _LOCK:
        cache = await _ensure_loaded()
        key = str(user_id)
        entry = cache.get(key)
        if entry is None:
            entry = {
                "hit_notifications": config.HIT_NOTIFICATIONS_DEFAULT,
            }
            cache[key] = entry
            await asyncio.to_thread(_save_sync, cache)
        else:
            # Backfill any newly-added keys without erasing existing ones.
            if "hit_notifications" not in entry:
                entry["hit_notifications"] = config.HIT_NOTIFICATIONS_DEFAULT
        return dict(entry)


async def set_setting(user_id: int, key: str, value: Any) -> dict[str, Any]:
    async with _LOCK:
        cache = await _ensure_loaded()
        ukey = str(user_id)
        entry = cache.setdefault(ukey, {})
        entry[key] = value
        await asyncio.to_thread(_save_sync, cache)
        return dict(entry)


async def toggle_bool(user_id: int, key: str, default: bool = False) -> bool:
    async with _LOCK:
        cache = await _ensure_loaded()
        ukey = str(user_id)
        entry = cache.setdefault(ukey, {})
        current = bool(entry.get(key, default))
        entry[key] = not current
        await asyncio.to_thread(_save_sync, cache)
        return not current


async def get_hit_notifications(user_id: int) -> bool:
    settings = await get_user_settings(user_id)
    return bool(settings.get("hit_notifications", config.HIT_NOTIFICATIONS_DEFAULT))
