"""
Staging area for RFQs proposed by sales/mail_pool_ai.py's local-Qwen
extraction.

Per the bucket_classifier incident (docs/AI_MIGRATION_STATUS.md), this
model's self-reported confidence carries no information about correctness
on real, messy data -- and RFQ extraction is a harder, higher-stakes task
than that incident's simple single-category classifier, since it writes
live CRM records. So nothing here becomes a real Opportunity until a human
approves it via routers/rfq.py's review-queue endpoints, which call
sales.mail_pool_ai.finalize_approved_rfq() -- the same crm_service.create_rfq()
path the pipeline used to call directly, unchanged.

Pure data-access layer, deliberately dependency-free of mail_pool_ai.py, so
the import direction stays one-way: routers -> mail_pool_ai -> this module,
and routers -> this module directly for reads.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

COLLECTION = "rfq_review_queue"


def _get_db(name: str):
    from db_pools import get_db
    return get_db(name)


def _col():
    return _get_db("email_automation")[COLLECTION]


def stage(
    payload: Dict[str, Any],
    source_email_id: str,
    sender_email: str,
    sender_name: Optional[str] = None,
    confidence: Optional[str] = None,
) -> str:
    """Record a proposed RFQ for human review. Returns the queue doc id."""
    now = datetime.utcnow()
    doc = {
        "payload": payload,
        "source_email_id": source_email_id,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "model_confidence": confidence,
        "status": "pending_review",
        "created_at": now,
        "updated_at": now,
    }
    result = _col().insert_one(doc)
    return str(result.inserted_id)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def list_pending(limit: int = 100) -> List[Dict[str, Any]]:
    docs = list(_col().find({"status": "pending_review"})
                .sort("created_at", -1).limit(limit))
    return [_serialize(d) for d in docs]


def get(queue_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(queue_id)
    except (InvalidId, TypeError):
        return None
    doc = _col().find_one({"_id": oid})
    return _serialize(doc) if doc else None


def mark_approved(queue_id: str, opportunity_id: str, project_id: Optional[str]) -> None:
    _col().update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {
            "status": "approved",
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "reviewed_at": datetime.utcnow(),
        }},
    )


def mark_rejected(queue_id: str, reason: Optional[str] = None) -> None:
    _col().update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {
            "status": "rejected",
            "reject_reason": reason,
            "reviewed_at": datetime.utcnow(),
        }},
    )
