"""
Unit test for the 2026-09-27 P1 follow-up: GET /api/rfq/stats must forward
spine_rfq.get_stats()'s per-currency breakdown to the frontend, not just the
deprecated cross-currency blended sum (RFQ.jsx previously had nothing else to
render, so it kept showing one misleading total across mixed currencies).
"""
import asyncio

from app.services import spine_rfq
from routers.rfq import get_rfq_stats


def test_stats_endpoint_forwards_value_by_currency(monkeypatch):
    fake_stats = {
        "by_state": {"open": 2, "won": 1, "lost": 0, "closed": 0},
        "by_stage": {"rfq": 2, "won": 1},
        "pipeline_value": 5000.0,
        "won_value": 3000.0,
        "total": 3,
        "value_by_currency": [
            {"currency": "USD", "pipeline_value": 5000.0, "won_value": 0.0},
            {"currency": "INR", "pipeline_value": 0.0, "won_value": 3000.0},
        ],
    }
    monkeypatch.setattr(spine_rfq, "get_stats", lambda direction=None: fake_stats)

    result = asyncio.run(get_rfq_stats(direction=None))

    assert result["value_by_currency"] == fake_stats["value_by_currency"]
    # Deprecated fields stay for old clients, but must never be the only thing
    # a caller can render.
    assert result["total_value"] == 8000.0
