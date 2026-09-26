"""
Unit tests for the 2026-09-26 RFQ page P1 fixes in app/services/spine_rfq.py:
- received_date prefers the backfilled real email date over the import
  timestamp (created_at).
- currency is never defaulted to INR when unset.
- get_stats() reports value per currency instead of one blended sum.

opportunity_to_rfq() makes no DB call when account_id/contact_id are both
absent, so these are pure-function tests -- no mocking needed.
"""
from datetime import datetime
from unittest.mock import MagicMock

from app.services import spine_rfq


def opp(**rfq_overrides):
    rfq_payload = {"title": "T", "budget": 100, "currency": None}
    rfq_payload.update(rfq_overrides)
    return {"_id": "o1", "title": "T", "stage": "rfq", "status": "open",
            "created_at": datetime(2026, 8, 3, 14, 0, 0),
            "metadata": {"rfq": rfq_payload}}


def test_received_date_prefers_the_backfilled_real_date():
    real_date = datetime(2021, 12, 17, 10, 16, 37)
    row = spine_rfq.opportunity_to_rfq(opp(received_at=real_date))
    assert row["received_date"] == real_date.isoformat()


def test_received_date_falls_back_to_created_at_when_not_backfilled():
    row = spine_rfq.opportunity_to_rfq(opp())
    assert row["received_date"] == datetime(2026, 8, 3, 14, 0, 0).isoformat()


def test_currency_is_never_defaulted_to_inr():
    row = spine_rfq.opportunity_to_rfq(opp(currency=None))
    assert row["extracted_currency"] is None
    assert row["final_currency"] is None


def test_currency_passes_through_when_actually_set():
    row = spine_rfq.opportunity_to_rfq(opp(currency="IDR"))
    assert row["extracted_currency"] == "IDR"
    assert row["final_currency"] == "IDR"


def test_get_stats_reports_value_per_currency_not_a_blended_sum(monkeypatch):
    docs_by_state = {
        "open": [{"currency": "IDR", "amount": 2_880_000_000}, {"currency": None, "amount": 500}],
        "won": [{"currency": "USD", "amount": 1000}],
    }

    class FakeCol:
        def count_documents(self, match):
            return 0

        def aggregate(self, pipeline):
            state = pipeline[0]["$match"]["state"]
            group = {}
            for d in docs_by_state.get(state, []):
                group[d["currency"]] = group.get(d["currency"], 0) + d["amount"]
            return [{"_id": k, "total": v} for k, v in group.items()]

    monkeypatch.setattr(spine_rfq.crm_service, "_col", lambda name: FakeCol())
    monkeypatch.setattr(spine_rfq, "_rfq_query",
                        lambda state=None, direction=None: {"state": state} if state else {})

    stats = spine_rfq.get_stats()
    by_cur = {row["currency"]: row for row in stats["value_by_currency"]}
    assert by_cur["IDR"]["pipeline_value"] == 2_880_000_000
    assert by_cur["unknown"]["pipeline_value"] == 500
    assert by_cur["USD"]["won_value"] == 1000
    # No entry mixes IDR and unknown/USD into one number.
    assert len(by_cur) == 3
