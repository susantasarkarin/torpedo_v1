"""
Covers the 2026-09-19 RFQ review-gate change to sales/mail_pool_ai.py:

  - _log_rfq_and_estimate() now STAGES a proposed RFQ (sales/rfq_review_queue)
    instead of calling crm_service.create_rfq() directly -- per the
    bucket_classifier incident, this model's confidence can't gate a live
    CRM write on its own.
  - finalize_approved_rfq() is the only path that still calls
    crm_service.create_rfq(), and only once a human has approved.
  - _derive_priority() is deterministic (deadline-based), not AI-derived.
  - process_sender_batch()'s single-flight lock skips a tick if the
    previous one is still marked running.

No network/Mongo calls: every collection/service touchpoint is mocked.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import sales.mail_pool_ai as m


# ============================================================
# _derive_priority — deterministic, deadline-based
# ============================================================

def test_priority_high_when_deadline_within_3_days():
    deadline = (datetime.utcnow() + timedelta(days=2)).isoformat()
    assert m._derive_priority({"deadline": deadline}) == "high"


def test_priority_medium_when_deadline_within_2_weeks():
    deadline = (datetime.utcnow() + timedelta(days=10)).isoformat()
    assert m._derive_priority({"deadline": deadline}) == "medium"


def test_priority_low_when_deadline_far_out():
    deadline = (datetime.utcnow() + timedelta(days=30)).isoformat()
    assert m._derive_priority({"deadline": deadline}) == "low"


def test_priority_medium_when_no_deadline():
    assert m._derive_priority({}) == "medium"


def test_priority_medium_when_deadline_unparseable():
    assert m._derive_priority({"deadline": "not a date"}) == "medium"


# ============================================================
# _log_rfq_and_estimate — stages, never calls create_rfq directly
# ============================================================

def test_non_rfq_analysis_stages_nothing():
    result = m._log_rfq_and_estimate({"rfq": {"is_rfq": False}}, {"_id": "e1"})
    assert result == {}


def test_rfq_stages_full_payload_and_never_touches_crm_service():
    analysis = {
        "summary": "They want a quote for a CATI study.",
        "contacts": [{"company": "Acme Research", "title": "Procurement Lead"}],
        "rfq": {
            "is_rfq": True, "title": "CATI Study RFQ", "budget": 5000,
            "currency": "USD", "description": "500 completes, urban India",
            "deadline": (datetime.utcnow() + timedelta(days=5)).isoformat(),
            "methodology": "CATI", "loi": 12, "ir": 30, "sample_size": 500,
            "country": "India", "study_type": "B2C",
            "target_audience": "urban women 25-40", "timeline": "3 weeks",
            "items": [{"description": "CATI interviews", "quantity": 500, "rate": 10}],
        },
    }
    email_doc = {"_id": "e1", "from_email": "buyer@acme.example",
                "from_name": "Jane Buyer", "subject": "RFQ: CATI study"}

    with patch("sales.rfq_review_queue.stage", return_value="queue123") as stage, \
         patch("app.services.crm_service.create_rfq") as create_rfq:
        result = m._log_rfq_and_estimate(analysis, email_doc)

    create_rfq.assert_not_called()
    assert result == {"queue_id": "queue123"}
    payload, kwargs = stage.call_args.args[0], stage.call_args.kwargs
    assert payload["title"] == "CATI Study RFQ"
    assert payload["sender_company"] == "Acme Research"
    assert payload["sender_title"] == "Procurement Lead"
    assert payload["target_audience"] == "urban women 25-40"
    assert payload["timeline"] == "3 weeks"
    assert payload["ai_summary"] == analysis["summary"]
    assert payload["priority"] == "medium"   # deadline in 5 days
    assert payload["items"] == analysis["rfq"]["items"]
    assert kwargs["sender_email"] == "buyer@acme.example"


# ============================================================
# finalize_approved_rfq — the only path that creates a live Opportunity
# ============================================================

def _fake_queue_doc(payload_overrides=None):
    payload = {
        "title": "CATI Study RFQ", "budget": 5000, "currency": "USD",
        "description": "500 completes", "deadline": None,
        "source_email_id": "e1", "sender_company": "Acme Research",
        "sender_title": "Procurement Lead", "from_email": "buyer@acme.example",
        "from_name": "Jane Buyer", "items": [], "ai_summary": "summary",
    }
    payload.update(payload_overrides or {})
    return {"_id": "queue123", "status": "pending_review", "payload": payload}


def test_finalize_raises_for_unknown_queue_id():
    with patch("sales.rfq_review_queue.get", return_value=None):
        try:
            m.finalize_approved_rfq("missing")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_finalize_raises_if_already_resolved():
    doc = _fake_queue_doc()
    doc["status"] = "approved"
    with patch("sales.rfq_review_queue.get", return_value=doc):
        try:
            m.finalize_approved_rfq("queue123")
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_finalize_creates_opportunity_and_marks_approved():
    doc = _fake_queue_doc()
    fake_create_rfq_result = {
        "opportunity": {"_id": "opp1"}, "project": {"_id": "proj1"},
    }

    with patch("sales.rfq_review_queue.get", return_value=doc), \
         patch("sales.rfq_review_queue.mark_approved") as mark_approved, \
         patch.object(m, "_resolve_account_and_contact", return_value=("acc1", "contact1")), \
         patch("app.services.crm_service.create_rfq", return_value=fake_create_rfq_result) as create_rfq, \
         patch.object(m, "_get_db") as get_db, \
         patch("app.services.crm_service.notify"):
        fake_mail_col = MagicMock()
        fake_mail_col.find_one.return_value = None  # source email long gone; must not crash
        fake_finance_db = MagicMock()
        fake_finance_db.__getitem__.side_effect = lambda name: {
            "customers": MagicMock(find_one=MagicMock(return_value={"_id": "cust1"})),
            "estimates": MagicMock(
                estimated_document_count=MagicMock(return_value=0),
                insert_one=MagicMock(return_value=MagicMock(inserted_id="est1")),
            ),
        }[name]
        get_db.side_effect = lambda name: fake_mail_col if name == m.MAIL_DB else fake_finance_db

        result = m.finalize_approved_rfq("queue123")

    create_rfq.assert_called_once()
    called_payload = create_rfq.call_args.args[0]
    assert called_payload["account_id"] == "acc1"
    assert called_payload["contact_id"] == "contact1"
    assert result["opportunity_id"] == "opp1"
    assert result["project_id"] == "proj1"
    mark_approved.assert_called_once_with("queue123", "opp1", "proj1")


# ============================================================
# process_sender_batch — single-flight lock
# ============================================================

def test_process_sender_batch_skips_when_already_running():
    with patch.object(m, "_acquire_batch_lock", return_value=False), \
         patch.object(m, "_process_sender_batch_locked") as locked_impl:
        result = m.process_sender_batch(limit=5)

    locked_impl.assert_not_called()
    assert result["skipped_already_running"] is True
    assert result["senders_processed"] == 0


def test_process_sender_batch_runs_and_releases_lock_on_success():
    with patch.object(m, "_acquire_batch_lock", return_value=True), \
         patch.object(m, "_release_batch_lock") as release, \
         patch.object(m, "_process_sender_batch_locked",
                      return_value={"senders_processed": 3}) as locked_impl:
        result = m.process_sender_batch(limit=5)

    locked_impl.assert_called_once_with(5)
    release.assert_called_once()
    assert result == {"senders_processed": 3}


# ============================================================
# deep_scan_sender_rfqs — ledger dedup keys off queue_id, not
# opportunity_id (which no longer gets set directly), and self-heals once
# a human approves a staged item
# ============================================================

def _cursor(docs):
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = docs
    return cursor


def test_deep_scan_stages_a_new_ledger_entry_once():
    """A ledger entry with neither queue_id nor opportunity_id gets staged
    exactly once; re-running with the same ledger state must not re-stage
    it (the real bug this dedup key exists to prevent — the old code keyed
    dedup off opportunity_id, which _log_rfq_and_estimate() no longer sets
    at all now that it stages instead of creating)."""
    one_doc = [{"_id": "e1", "subject": "RFQ", "date": "2026-01-01", "body_plain": "please quote"}]
    fake_col = MagicMock()
    fake_sender_col = MagicMock()
    fake_sender_col.find_one.return_value = {
        "rfq_scan": {"ledger": [{"ref": "r1", "status": "open"}],
                    "last_scanned_date": "2026-01-01"}}
    fake_col.find.return_value = _cursor(one_doc)

    with patch.object(m, "_scan_chunk", return_value={"new_rfqs": [], "rfq_updates": []}), \
         patch.object(m, "_log_rfq_and_estimate", return_value={"queue_id": "q1"}) as stage_call:
        result = m.deep_scan_sender_rfqs("a@b.com", "A", fake_col, fake_sender_col)

    stage_call.assert_called_once()
    assert result["rfqs_logged"] == 1

    # Persisted ledger now carries queue_id — re-running must not re-stage.
    persisted_ledger = fake_sender_col.update_one.call_args.args[1]["$set"]["rfq_scan.ledger"]
    assert persisted_ledger[0]["queue_id"] == "q1"

    stage_call.reset_mock()
    fake_sender_col.find_one.return_value = {
        "rfq_scan": {"ledger": persisted_ledger, "last_scanned_date": "2026-01-01"}}
    fake_col.find.return_value = _cursor(one_doc)
    with patch.object(m, "_scan_chunk", return_value={"new_rfqs": [], "rfq_updates": []}), \
         patch.object(m, "_log_rfq_and_estimate") as stage_call2, \
         patch("sales.rfq_review_queue.get", return_value={"status": "pending_review"}):
        m.deep_scan_sender_rfqs("a@b.com", "A", fake_col, fake_sender_col)

    stage_call2.assert_not_called()


def test_deep_scan_adopts_opportunity_once_approved_and_applies_stage():
    """Once a human approves a staged RFQ, the next scan must adopt the
    resulting opportunity_id and apply the ledger's current status to it."""
    ledger = [{"ref": "r1", "status": "won", "queue_id": "q1", "stage_applied": None}]
    fake_col = MagicMock()
    fake_col.find.return_value = _cursor(
        [{"_id": "e1", "subject": "thanks", "date": "2026-01-02", "body_plain": "confirmed"}])
    fake_sender_col = MagicMock()
    fake_sender_col.find_one.return_value = {
        "rfq_scan": {"ledger": ledger, "last_scanned_date": "2026-01-01"}}

    with patch.object(m, "_scan_chunk", return_value={"new_rfqs": [], "rfq_updates": []}), \
         patch("sales.rfq_review_queue.get",
              return_value={"status": "approved", "opportunity_id": "opp1",
                           "estimate_id": "est1"}), \
         patch.object(m, "_apply_rfq_stage") as apply_stage:
        result = m.deep_scan_sender_rfqs("a@b.com", "A", fake_col, fake_sender_col)

    apply_stage.assert_called_once()
    applied_entry = apply_stage.call_args.args[0]
    assert applied_entry["opportunity_id"] == "opp1"
    assert result["rfqs_won"] == 1


def test_process_sender_batch_releases_lock_even_on_exception():
    with patch.object(m, "_acquire_batch_lock", return_value=True), \
         patch.object(m, "_release_batch_lock") as release, \
         patch.object(m, "_process_sender_batch_locked", side_effect=RuntimeError("boom")):
        try:
            m.process_sender_batch(limit=5)
            assert False, "expected RuntimeError to propagate"
        except RuntimeError:
            pass

    release.assert_called_once()
