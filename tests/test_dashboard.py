from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tgbot import config, storage
from tgbot.dashboard import format_start_dashboard


def test_plan_label_is_service_specific() -> None:
    assert storage.plan_label("claude.ai", {"plan": "Max"}, True) == "Max"
    assert storage.plan_label("claude.ai", {"plan": "Team/Enterprise"}, True) == "Team/Enterprise"
    assert storage.plan_label("chatgpt.com", {"plan": "Plus"}, True) == "Plus"
    assert storage.plan_label("roblox.com", {"is_premium": True}, True) == "Premium"
    assert storage.plan_label("claude.ai", {"plan": "Pro"}, False) is None


def test_record_scan_outcomes_updates_live_dashboard(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    storage._STATS_CACHE = None

    async def run() -> dict:
        await storage.record_scan_outcomes(
            [
                SimpleNamespace(site="claude.ai", alive=True, info={"plan": "Max"}),
                SimpleNamespace(site="claude.ai", alive=True, info={"plan": "Pro"}),
                SimpleNamespace(site="chatgpt.com", alive=True, info={"plan": "Plus"}),
                SimpleNamespace(site="chatgpt.com", alive=False, info={}),
            ]
        )
        return await storage.get_dashboard_stats()

    stats = asyncio.run(run())

    assert stats["total"] == 4
    assert stats["alive"] == 3
    assert stats["dead"] == 1
    assert stats["sites"]["claude.ai"]["plans"] == {"Max": 1, "Pro": 1}
    assert stats["sites"]["chatgpt.com"]["plans"] == {"Plus": 1}


def test_format_start_dashboard_shows_counts_and_every_service() -> None:
    stats = {
        "total": 3,
        "alive": 2,
        "dead": 1,
        "sites": {
            "claude.ai": {
                "total": 2,
                "alive": 2,
                "dead": 0,
                "plans": {"Max": 1, "Pro": 1},
            },
            "chatgpt.com": {
                "total": 1,
                "alive": 0,
                "dead": 1,
                "plans": {},
            },
        },
    }

    body = format_start_dashboard(stats)

    assert "Live dashboard" in body
    assert "Total: <b>3</b>" in body
    assert "Claude.ai" in body
    assert "Max <b>1</b>" in body
    assert "Pro <b>1</b>" in body
    assert "ChatGPT" in body
    assert "❌ <b>1</b>" in body
    assert "Perplexity" in body
