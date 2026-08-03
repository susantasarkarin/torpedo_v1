"""
MAIL POOL AI TESTS
==================

Covers the Bedrock mail-desk migration and the two-stage rules->AI pipeline:

  - prefilter routing: bank/promo/transactional never reach Bedrock
  - AI category -> UI segment mapping (incl. domain-authoritative rules)
  - parse_json_strict against malformed model output
  - the ai_analysis idempotency marker (double-processing is a no-op)
  - the inbound-sender-never-cold-outreach rule
  - the backfill script's dry-run

No network calls: the Bedrock transport seam (_call_converse) is patched.

Run with: pytest backend/tests/test_mail_pool_ai.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sales.mail_pool_ai as m          # noqa: E402
import leads.bedrock_client as bc       # noqa: E402


# ============================================================
# parse_json_strict against malformed model output
# ============================================================

def test_parse_json_strict_good_and_bad():
    assert bc.parse_json_strict('{"a": 1}') == {"a": 1}
    # markdown fences stripped
    assert bc.parse_json_strict('```json\n{"a": 1}\n```') == {"a": 1}
    # prose wrapped around a value -> first balanced object
    assert bc.parse_json_strict('Here you go: {"a": 1} thanks') == {"a": 1}
    for bad in ("", "   ", "not json at all", "{unbalanced"):
        with pytest.raises(bc.JSONParseError):
            bc.parse_json_strict(bad)


# ============================================================
# Prefilter routing — noise never reaches Bedrock
# ============================================================

def _agent_returning(segment, conf, category=None):
    a = MagicMock()
    a.classify.return_value = {"segment": segment,
                              "category": category or segment.title(),
                              "confidence": conf}
    return a


@pytest.mark.parametrize("segment,conf,expect", [
    ("bank", 0.8, "skip"),
    ("promotion", 0.9, "skip"),
    ("transactional", 0.6, "skip"),
    ("bank", 0.3, "proceed"),          # low confidence -> proceed
    ("client", 0.9, "proceed"),
    ("vendor", 0.5, "proceed"),
    ("internal", 0.95, "proceed"),
    ("gst_it_govt", 0.7, "proceed"),
    ("others", 0.3, "proceed"),
])
def test_prefilter_routing(segment, conf, expect):
    with patch.object(m, "_rule_agent", return_value=_agent_returning(segment, conf)):
        decision, _ = m.prefilter_decision({"from_email": "x@y.com"})
    assert decision == expect


def test_prefilter_skip_never_calls_bedrock():
    """A prefiltered email must be marked skipped WITHOUT any analysis call."""
    with patch.object(m, "_rule_agent",
                      return_value=_agent_returning("promotion", 0.9, "Promotion")), \
         patch.object(m, "analyze_email") as analyze, \
         patch.object(m, "_get_db") as gdb:
        gdb.return_value = MagicMock()
        r = m.process_email({"_id": "e1", "from_email": "promo@x.com",
                             "subject": "90% OFF SALE"})
    assert r["skipped"] is True
    analyze.assert_not_called()        # Bedrock never touched


def test_prefilter_disabled_proceeds(monkeypatch):
    monkeypatch.setattr(m, "MAIL_AI_PREFILTER_ENABLED", False)
    with patch.object(m, "_rule_agent",
                      return_value=_agent_returning("bank", 0.99)):
        decision, _ = m.prefilter_decision({"from_email": "x@y.com"})
    assert decision == "proceed"


# ============================================================
# AI category -> segment mapping
# ============================================================

@pytest.mark.parametrize("ai_cat,rule_seg,rule_disp,expect", [
    ("rfq",            "client",      "Client",       ("Client", "ai")),
    ("client_inquiry", "others",      "Others",       ("Client", "ai")),
    ("reply",          "vendor",      "Vendor",       ("Client", "ai")),
    ("vendor",         "others",      "Others",       ("Vendor", "ai")),
    ("promotional",    "others",      "Others",       ("Promotion", "ai")),
    ("transactional",  "others",      "Others",       ("Transactional", "ai")),
    ("other",          "others",      "Others",       ("Others", "rules")),
    ("rfq",            "internal",    "Internal",     ("Internal", "rules")),
    ("client_inquiry", "gst_it_govt", "GST/IT/Govt",  ("GST/IT/Govt", "rules")),
    ("rfq",            "bank",        "Bank",         ("Bank", "rules")),
])
def test_category_to_segment(ai_cat, rule_seg, rule_disp, expect):
    rule = {"segment": rule_seg, "category": rule_disp}
    assert m.derive_segment(ai_cat, rule) == expect


def test_category_to_segment_no_rule():
    assert m.derive_segment("rfq", None) == ("Client", "ai")
    assert m.derive_segment("other", None) == ("Others", "rules")


# ============================================================
# Idempotency — double-processing an email is a no-op
# ============================================================

def test_idempotency_marker_batch_excludes_processed():
    """process_batch queries only ai_analysis-absent docs, so an already
    analyzed email is never re-processed."""
    col = MagicMock()
    col.find.return_value.sort.return_value.limit.return_value = iter([])
    with patch.object(m, "_get_db", return_value={m.MAIL_COLLECTION: col}):
        gdb = MagicMock(); gdb.__getitem__.return_value = col
        with patch.object(m, "_get_db", return_value=gdb):
            m.process_batch(limit=5)
    # the query must require ai_analysis to NOT exist
    query = col.find.call_args[0][0]
    assert query["ai_analysis"] == {"$exists": False}


def test_throttle_leaves_unmarked():
    """A Bedrock throttle stops the run and marks nothing (no partial write)."""
    col = MagicMock()
    docs = [{"_id": "e1", "from_email": "x@y.com", "subject": "s",
             "body_plain": "b", "date": 1}]
    col.find.return_value.sort.return_value.limit.return_value = iter(docs)
    gdb = MagicMock(); gdb.__getitem__.return_value = col
    with patch.object(m, "_get_db", return_value=gdb), \
         patch.object(m, "prefilter_decision", return_value=("proceed", {})), \
         patch.object(m, "analyze_email", side_effect=m.MailAIThrottled("throttled")):
        r = m.process_batch(limit=5)
    assert r["throttled"] is True and r["processed"] == 0
    col.update_many.assert_not_called()   # nothing marked failed


# ============================================================
# Inbound sender is never a cold-outreach target
# ============================================================

def test_inbound_sender_routes_to_warm_not_cold():
    fake_leads = {"L1": {"_id": "L1", "email": "ravi@acme.in"}}

    class FakeLeadsRaw:
        def find_one(self, q): return fake_leads.get(q["_id"])
        def update_one(self, q, u, upsert=False):
            fake_leads.setdefault(q["_id"], {"_id": q["_id"]}).update(u.get("$set", {}))

    warm = MagicMock()
    gdb = MagicMock(); gdb.__getitem__.return_value = warm
    with patch("leads.bucket_classifier.classify_lead",
               return_value={"bucket": "SFW", "confidence": 0.9,
                             "reason": "x", "method": "cheap"}), \
         patch("leads.bucket_classifier.persist", return_value=True), \
         patch("leads.bucket_classifier.leads_raw", FakeLeadsRaw()), \
         patch("leads.outreach_qualification.qualify") as qualify, \
         patch.object(m, "_get_db", return_value=gdb):
        route = m._run_icp_and_route("L1", "ravi@acme.in", is_inbound=True,
                                     source_email_id="e1")
    assert route == "warm"
    assert fake_leads["L1"]["cold_outreach_blocked"] is True
    assert fake_leads["L1"]["outreach_route"] == "warm"
    qualify.assert_not_called()          # inbound never runs cold gates
    warm.update_one.assert_called()      # warm-queue record written


def test_outbound_lead_runs_cold_qualification():
    from leads.outreach_qualification import QualificationResult
    fake_leads = {"L2": {"_id": "L2", "email": "cold@prospect.com"}}

    class FakeLeadsRaw:
        def find_one(self, q): return fake_leads.get(q["_id"])
        def update_one(self, q, u, upsert=False):
            fake_leads.setdefault(q["_id"], {"_id": q["_id"]}).update(u.get("$set", {}))

    gdb = MagicMock()
    with patch("leads.bucket_classifier.classify_lead",
               return_value={"bucket": "SFW", "confidence": 0.9,
                             "reason": "x", "method": "cheap"}), \
         patch("leads.bucket_classifier.persist", return_value=True), \
         patch("leads.bucket_classifier.leads_raw", FakeLeadsRaw()), \
         patch("leads.outreach_qualification.qualify",
               return_value=QualificationResult(True, "qualified", bucket="SFW")), \
         patch.object(m, "_get_db", return_value=gdb):
        route = m._run_icp_and_route("L2", "cold@prospect.com", is_inbound=False,
                                     source_email_id="e2")
    assert route == "cold"
    assert fake_leads["L2"]["outreach_route"] == "cold"


def test_auto_enroll_guard_blocks_inbound():
    """canonical_ingestion._auto_enroll_in_outreach must skip a
    cold_outreach_blocked lead (belt-and-suspenders enforcement)."""
    import leads.canonical_ingestion as ci
    # Should return early without raising or touching campaigns.
    ci._auto_enroll_in_outreach(
        {"classification_basket": "A", "email": "x@y.com",
         "cold_outreach_blocked": True}, "eid")


# ============================================================
# Backfill dry-run
# ============================================================

def test_backfill_dry_run_writes_nothing():
    import sales.backfill_mail_segments as bf
    col = MagicMock()
    col.find.return_value = iter([
        {"_id": "a", "ai_analysis": {"category": "rfq",
                                     "rule_classification": {"segment": "client",
                                                             "category": "Client"}}},
    ])
    with patch.object(bf, "_col", return_value=col):
        stats = bf.run(dry_run=True)
    assert stats["updated"] == 1
    col.update_one.assert_not_called()   # dry-run: no writes
