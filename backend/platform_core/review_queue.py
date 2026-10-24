"""One Review Queue for everything waiting on a person (CRM plan 3.1).

Collection: email_automation.review_queue_items. Every item says what it is
about (ref), why it is here (reason), what the system proposes (suggested)
and how the workflow continues once a person decides (resume handler).

  enqueue(type, module, ref, reason, ...)   idempotent per (type, ref) while pending
  resolve(item_id, action, actor, correction=None, assignee=None)
        action: approve | correct | reject | reassign
        approve/correct call the item's resume handler with the decision, so
        the workflow continues where it stopped; corrections to AI output are
        stored as labelled examples (ai_governance.labelled_examples) and are
        reused as few-shot examples by the Qwen gateway.

Resume handlers are registered by name (register_handler) so the queue never
imports feature modules directly.
"""
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from bson import ObjectId

from .audit import log_action

logger = logging.getLogger(__name__)

ACTIONS = ("approve", "correct", "reject", "reassign")
TYPES = ("ai_low_confidence", "ai_invalid_output", "rfq_extraction", "entity_link", "rfq_missing_data",
         "unusual_price", "finance_mismatch", "vendor_bid", "mailbox_paused", "positive_reply_draft",
         "neutral_reply", "invoice_request", "other")
_HANDLERS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Any]] = {}


def register_handler(name: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], Any]) -> None:
    _HANDLERS[name] = fn


def _db(name="email_automation"):
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database(name)


def _col(db=None):
    return (db or _db())["review_queue_items"]


def enqueue(*, type: str, module: str, ref: Dict[str, Any], reason: str,
            payload: Optional[Dict[str, Any]] = None, suggested: Optional[Dict[str, Any]] = None,
            resume: Optional[Dict[str, Any]] = None, bu: Optional[str] = None,
            value_inr: Optional[float] = None, owner: Optional[str] = None, db=None) -> str:
    """Add an item, or return the pending one already open for this (type, ref)."""
    if type not in TYPES:
        raise ValueError(f"unknown review type {type!r}")
    col = _col(db)
    key = {"type": type, "ref.collection": ref.get("collection"), "ref.id": str(ref.get("id")), "status": "pending"}
    existing = col.find_one(key, {"_id": 1})
    if existing:
        return str(existing["_id"])
    now = datetime.utcnow()
    doc = {"type": type, "module": module, "ref": {**ref, "id": str(ref.get("id"))}, "reason": reason,
           "payload": payload or {}, "suggested": suggested or {}, "resume": resume or {},
           "bu": bu, "value_inr": value_inr, "owner": owner, "status": "pending",
           "created_at": now, "updated_at": now}
    item_id = str(col.insert_one(doc).inserted_id)
    log_action(actor="system", action="create", entity_type="review_queue_item", entity_id=item_id,
               reason=reason, source=module, metadata={"type": type, "ref": doc["ref"]})
    return item_id


def list_items(status: str = "pending", module: Optional[str] = None, type: Optional[str] = None,
               bu: Optional[str] = None, limit: int = 200, db=None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"status": status}
    if module:
        q["module"] = module
    if type:
        q["type"] = type
    if bu:
        q["bu"] = bu
    out = []
    for d in _col(db).find(q).sort([("created_at", 1)]).limit(limit):
        d["_id"] = str(d["_id"])
        out.append(d)
    return out


def counts(db=None) -> Dict[str, Any]:
    by = {}
    for r in _col(db).aggregate([{"$match": {"status": "pending"}},
                                 {"$group": {"_id": "$module", "n": {"$sum": 1}, "oldest": {"$min": "$created_at"}}}]):
        by[r["_id"] or "other"] = {"pending": r["n"], "oldest": r["oldest"]}
    return {"pending_total": sum(v["pending"] for v in by.values()), "by_module": by,
            "legacy_pending": legacy_counts()}


# Older queues still hold undecided items until Phase 4 folds them in (items
# <= 90 days old move here; older ones are flagged archived_backlog). Their
# counts are shown so nothing waiting is hidden from the one page.
LEGACY_QUEUES = (
    ("email_automation", "ai_review_queue", {"status": "pending"}, "/admin/review-queue (old AI queue)"),
    ("email_automation", "rfq_review_queue", {"status": "pending"}, "/admin/sales/rfq/review-queue"),
    ("crm_db", "ai_decisions", {"status": "recommended"}, "/admin/ai/approvals"),
)


def legacy_counts() -> List[Dict[str, Any]]:
    out = []
    for dbname, col, q, page in LEGACY_QUEUES:
        try:
            n = _db(dbname)[col].count_documents(q)
        except Exception:
            n = None
        out.append({"queue": f"{dbname}.{col}", "pending": n, "page": page})
    return out


def resolve(item_id: str, action: str, actor: str, correction: Optional[Dict[str, Any]] = None,
            assignee: Optional[str] = None, note: str = "", db=None) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    col = _col(db)
    item = col.find_one({"_id": ObjectId(item_id)})
    if not item:
        raise KeyError(item_id)
    if item["status"] != "pending":
        return {"ok": False, "error": f"already {item['status']}"}
    now = datetime.utcnow()
    if action == "reassign":
        col.update_one({"_id": item["_id"]}, {"$set": {"owner": assignee, "updated_at": now}})
        log_action(actor=actor, action="update", entity_type="review_queue_item", entity_id=item_id,
                   reason=f"reassigned to {assignee}", changes={"owner": {"before": item.get("owner"), "after": assignee}})
        return {"ok": True, "status": "pending", "owner": assignee}

    decision = {"action": action, "by": actor, "at": now, "note": note,
                "value": correction if action == "correct" else item.get("suggested")}
    status = {"approve": "approved", "correct": "corrected", "reject": "rejected"}[action]
    resumed = None
    if action in ("approve", "correct"):
        handler = _HANDLERS.get((item.get("resume") or {}).get("handler", ""))
        if handler:
            try:
                resumed = handler(item, decision)
            except Exception as e:
                logger.exception("resume handler failed for review item %s", item_id)
                col.update_one({"_id": item["_id"]}, {"$set": {"resume_error": str(e)[:300], "updated_at": now}})
                return {"ok": False, "error": f"resume failed: {e}"}
    if action == "correct" and item["type"].startswith(("ai_", "rfq_extraction", "vendor_bid")):
        _db("ai_governance")["labelled_examples"].insert_one({
            "task": (item.get("payload") or {}).get("task"), "input_hash": (item.get("payload") or {}).get("input_hash"),
            "input": (item.get("payload") or {}).get("clean_input"), "model_output": item.get("suggested"),
            "label": correction, "by": actor, "at": now, "source_item": item_id})
    col.update_one({"_id": item["_id"]}, {"$set": {"status": status, "decision": decision, "resolved_at": now,
                                                  "resolved_by": actor, "updated_at": now}})
    log_action(actor=actor, action="update", entity_type="review_queue_item", entity_id=item_id,
               reason=f"{action}: {note}"[:200], changes={"status": {"before": "pending", "after": status}},
               metadata={"ref": item.get("ref"), "resumed": bool(resumed)})
    return {"ok": True, "status": status, "resumed": resumed}
