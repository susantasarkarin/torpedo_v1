"""
PAUSE ALREADY-ENROLLED AI-REJECTED LEADS
==========================================

Covers leads/ai_rejected_hold.py. find_ai_rejected_enrolled joins
outreach_leads_v2 (torpedo db) against leads_raw (email_automation db) by
lead_id, matching either leads_raw._id or its enriched_lead_id -- both link
paths enrollment actually uses. apply_pause writes nothing unless dry_run=False.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.ai_rejected_hold import PAUSE_STATUS, apply_pause, find_ai_rejected_enrolled


def _db(live_rows, raw_rows):
    olv = MagicMock()
    olv.find.return_value = live_rows
    raw = MagicMock()
    raw.find.return_value = raw_rows
    db = MagicMock()
    db.__getitem__.side_effect = lambda name: {"outreach_leads_v2": olv}[name]
    fake_router = MagicMock(get_leads_db=lambda: {"leads_raw": raw})
    return db, olv, raw, fake_router


def test_matches_by_raw_id_and_by_enriched_lead_id():
    live = [
        {"_id": "OL1", "lead_id": "RAW1"},        # matches leads_raw._id directly
        {"_id": "OL2", "lead_id": "ENR2"},        # matches via enriched_lead_id
        {"_id": "OL3", "lead_id": "UNRELATED"},   # no AI verdict at all
    ]
    raw = [
        {"_id": "RAW1", "outreach_bucket": "REJECT"},
        {"_id": "RAW2", "outreach_bucket": "REVIEW", "enriched_lead_id": "ENR2"},
    ]
    db, olv, raw_coll, fake_router = _db(live, raw)
    with patch.dict(sys.modules, {"routers.cold_outreach_router": fake_router}):
        out = find_ai_rejected_enrolled(db)
    ids = {r["_id"]: r["_ai_bucket"] for r in out}
    assert ids == {"OL1": "REJECT", "OL2": "REVIEW"}


def test_no_rejected_leads_at_all_short_circuits_without_querying_live():
    db, olv, raw_coll, fake_router = _db(live_rows=[{"_id": "OL1", "lead_id": "X"}], raw_rows=[])
    with patch.dict(sys.modules, {"routers.cold_outreach_router": fake_router}):
        out = find_ai_rejected_enrolled(db)
    assert out == []
    olv.find.assert_not_called()   # never even queried outreach_leads_v2


def test_only_live_workflow_statuses_are_queried():
    db, olv, raw_coll, fake_router = _db(live_rows=[], raw_rows=[{"_id": "R1", "outreach_bucket": "REJECT"}])
    with patch.dict(sys.modules, {"routers.cold_outreach_router": fake_router}):
        find_ai_rejected_enrolled(db)
    query = olv.find.call_args.args[0]
    assert set(query["workflow_status"]["$in"]) == {"not_started", "pending_scheduled", "in_sequence"}


def test_apply_pause_dry_run_writes_nothing():
    db = MagicMock()
    result = apply_pause(db, [{"_id": "OL1"}], dry_run=True)
    assert result == {"would_pause": 1, "applied": 0}
    db["outreach_leads_v2"].update_many.assert_not_called()


def test_apply_pause_sets_terminal_status_and_reason():
    db = MagicMock()
    db["outreach_leads_v2"].update_many.return_value.modified_count = 2
    result = apply_pause(db, [{"_id": "OL1"}, {"_id": "OL2"}], dry_run=False)
    assert result == {"would_pause": 2, "applied": 2}
    flt, update = db["outreach_leads_v2"].update_many.call_args.args
    assert flt == {"_id": {"$in": ["OL1", "OL2"]}}
    assert update["$set"]["workflow_status"] == PAUSE_STATUS
    assert "REJECT/REVIEW" in update["$set"]["last_send_error"]
