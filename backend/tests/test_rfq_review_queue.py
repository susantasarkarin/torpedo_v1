"""
Covers sales/rfq_review_queue.py -- the staging area RFQs proposed by the
local-Qwen extraction sit in until a human approves them (see
sales/mail_pool_ai.py's module docstring for why: the bucket_classifier
incident showed this model's confidence carries no information about
correctness on real data).

Mocks the module-level Mongo collection -- no live Mongo needed.
"""
from unittest.mock import MagicMock, patch

from bson import ObjectId

import sales.rfq_review_queue as q


def test_stage_inserts_pending_review_doc():
    fake_col = MagicMock()
    fake_col.insert_one.return_value = MagicMock(inserted_id=ObjectId())

    with patch.object(q, "_col", return_value=fake_col):
        queue_id = q.stage(
            {"title": "RFQ"}, source_email_id="e1",
            sender_email="a@b.com", sender_name="A B", confidence="medium")

    assert isinstance(queue_id, str)
    inserted = fake_col.insert_one.call_args.args[0]
    assert inserted["status"] == "pending_review"
    assert inserted["payload"] == {"title": "RFQ"}
    assert inserted["sender_email"] == "a@b.com"
    assert inserted["model_confidence"] == "medium"


def test_list_pending_filters_and_serializes_id():
    doc_id = ObjectId()
    fake_cursor = MagicMock()
    fake_cursor.sort.return_value = fake_cursor
    fake_cursor.limit.return_value = [{"_id": doc_id, "status": "pending_review"}]
    fake_col = MagicMock()
    fake_col.find.return_value = fake_cursor

    with patch.object(q, "_col", return_value=fake_col):
        items = q.list_pending(limit=10)

    fake_col.find.assert_called_once_with({"status": "pending_review"})
    assert items == [{"_id": str(doc_id), "status": "pending_review"}]


def test_get_returns_none_for_invalid_id():
    assert q.get("not-an-objectid") is None


def test_get_returns_none_when_not_found():
    fake_col = MagicMock()
    fake_col.find_one.return_value = None
    with patch.object(q, "_col", return_value=fake_col):
        assert q.get(str(ObjectId())) is None


def test_get_returns_serialized_doc():
    doc_id = ObjectId()
    fake_col = MagicMock()
    fake_col.find_one.return_value = {"_id": doc_id, "status": "pending_review"}
    with patch.object(q, "_col", return_value=fake_col):
        doc = q.get(str(doc_id))
    assert doc["_id"] == str(doc_id)


def test_mark_approved_sets_status_and_ids():
    fake_col = MagicMock()
    queue_id = str(ObjectId())
    with patch.object(q, "_col", return_value=fake_col):
        q.mark_approved(queue_id, opportunity_id="opp1", project_id="proj1")

    call_filter, call_update = fake_col.update_one.call_args.args
    assert call_filter == {"_id": ObjectId(queue_id)}
    assert call_update["$set"]["status"] == "approved"
    assert call_update["$set"]["opportunity_id"] == "opp1"
    assert call_update["$set"]["project_id"] == "proj1"


def test_mark_rejected_sets_status_and_reason():
    fake_col = MagicMock()
    queue_id = str(ObjectId())
    with patch.object(q, "_col", return_value=fake_col):
        q.mark_rejected(queue_id, reason="not a real RFQ")

    call_filter, call_update = fake_col.update_one.call_args.args
    assert call_filter == {"_id": ObjectId(queue_id)}
    assert call_update["$set"]["status"] == "rejected"
    assert call_update["$set"]["reject_reason"] == "not a real RFQ"
