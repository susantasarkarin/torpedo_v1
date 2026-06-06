"""
CRM SPINE SERVICE
Canonical CRUD + cross-object flows for the unified CRM layer.

All canonical objects live in a dedicated `crm_db` database (override with
CRM_DB_NAME) so the spine stays cleanly separated from the legacy
`email_automation` collections while we migrate modules onto it.

Design notes:
- Uses the shared sync MongoClient from database.get_database (singleton pool).
- `activities` is the central linking layer: every activity carries optional
  account_id / contact_id / opportunity_id / project_id links.
- Cross-object flows (RFQ, Opportunity-Won) are implemented here, not in the
  router, so agents and other services can reuse them.
"""

import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from bson import ObjectId
from bson.errors import InvalidId

try:
    from ...database import get_database
except ImportError:  # pragma: no cover - absolute import fallback
    from database import get_database

CRM_DB_NAME = os.getenv("CRM_DB_NAME", "crm_db")

# Canonical collections exposed through the generic CRUD layer.
COLLECTIONS = {
    "accounts",
    "contacts",
    "leads",
    "opportunities",
    "activities",
    "tasks",
    "projects",
    "invoices",
    "ai_decisions",
}

# Activity link field per linkable object type (the central timeline layer).
_TIMELINE_FIELDS = {
    "account": "account_id",
    "contact": "contact_id",
    "opportunity": "opportunity_id",
    "project": "project_id",
}


# ----------------------------- internals -----------------------------

def _db():
    return get_database(CRM_DB_NAME)


def _col(collection: str):
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown CRM collection: {collection}")
    return _db()[collection]


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        raise ValueError(f"Invalid id: {id_str}")


def serialize(doc: Optional[dict]) -> Optional[dict]:
    """Make a Mongo document JSON-serializable (stringify _id)."""
    if not doc:
        return None
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


# --------------------------- generic CRUD ----------------------------

def create(collection: str, data: Dict[str, Any]) -> dict:
    data = {k: v for k, v in data.items() if v is not None}
    now = datetime.utcnow()
    data.setdefault("created_at", now)
    data["updated_at"] = now
    result = _col(collection).insert_one(data)
    data["_id"] = str(result.inserted_id)
    return data


def get(collection: str, id_str: str) -> Optional[dict]:
    return serialize(_col(collection).find_one({"_id": _oid(id_str)}))


def list_docs(
    collection: str,
    query: Optional[dict] = None,
    limit: int = 200,
    skip: int = 0,
    sort_field: str = "created_at",
    sort_dir: int = -1,
) -> List[dict]:
    cursor = (
        _col(collection)
        .find(query or {})
        .sort(sort_field, sort_dir)
        .skip(skip)
        .limit(limit)
    )
    return [serialize(d) for d in cursor]


def update(collection: str, id_str: str, data: Dict[str, Any]) -> Optional[dict]:
    update_data = {k: v for k, v in data.items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    result = _col(collection).update_one({"_id": _oid(id_str)}, {"$set": update_data})
    if result.matched_count == 0:
        return None
    return get(collection, id_str)


def delete(collection: str, id_str: str) -> bool:
    result = _col(collection).delete_one({"_id": _oid(id_str)})
    return result.deleted_count > 0


# --------------------------- account dedupe --------------------------

def _normalize_name(name: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def find_account_by_name(name: str) -> Optional[dict]:
    """Find an account by case-insensitive normalized name (dedupe helper)."""
    norm = _normalize_name(name)
    if not norm:
        return None
    col = _col("accounts")
    doc = col.find_one({"name_normalized": norm})
    if not doc:
        # Fallback for accounts created outside the dedupe path (no normalized field).
        doc = col.find_one({"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}})
    return serialize(doc)


def get_or_create_account(name: str, defaults: Optional[Dict[str, Any]] = None) -> Tuple[dict, bool]:
    """
    Return (account, created). Reuses an existing account matched by normalized
    name, otherwise creates one. Stores `name_normalized` for fast future dedupe.
    """
    existing = find_account_by_name(name)
    if existing:
        return existing, False
    data = dict(defaults or {})
    data["name"] = name
    data["name_normalized"] = _normalize_name(name)
    return create("accounts", data), True


# ------------------------ central linking layer ----------------------

def log_activity(data: Dict[str, Any]) -> dict:
    """Write an activity record (the central timeline entry)."""
    data.setdefault("type", "note")
    return create("activities", data)


def timeline(object_type: str, object_id: str) -> Dict[str, List[dict]]:
    """Aggregate activities + tasks linked to one canonical object."""
    field = _TIMELINE_FIELDS.get(object_type)
    if not field:
        raise ValueError(f"Unsupported timeline object type: {object_type}")
    activities = list_docs("activities", {field: object_id})
    tasks = list_docs(
        "tasks",
        {"linked_object_type": object_type, "linked_object_id": object_id},
        sort_field="due_date",
        sort_dir=1,
    )
    return {"activities": activities, "tasks": tasks}


def log_ai_decision(data: Dict[str, Any]) -> dict:
    """Record an AI decision (every agent action must call this)."""
    data.setdefault("status", "pending")
    data.setdefault("autonomy_mode", "observe")
    return create("ai_decisions", data)


# --------------------------- cross-object flows ----------------------

def create_rfq(payload: Dict[str, Any]) -> Dict[str, Any]:
    """RFQ -> create both an Opportunity and a Project stub, cross-linked."""
    account_id = payload.get("account_id")
    title = payload.get("title") or "RFQ Opportunity"
    budget = payload.get("budget", 0)

    opportunity = create(
        "opportunities",
        {
            "title": title,
            "account_id": account_id,
            "contact_id": payload.get("contact_id"),
            "amount": budget,
            "stage": "rfq",
            "status": "open",
            "metadata": {"source": "rfq", "rfq": payload},
        },
    )
    project = create(
        "projects",
        {
            "name": title,
            "account_id": account_id,
            "status": "stub",
            "budget": budget,
            "opportunity_id": opportunity["_id"],
        },
    )
    update("opportunities", opportunity["_id"], {"project_id": project["_id"]})

    log_activity(
        {
            "type": "rfq_created",
            "subject": title,
            "account_id": account_id,
            "contact_id": payload.get("contact_id"),
            "opportunity_id": opportunity["_id"],
            "project_id": project["_id"],
        }
    )
    return {
        "opportunity": get("opportunities", opportunity["_id"]),
        "project": project,
    }


def mark_opportunity_won(opp_id: str) -> Optional[Dict[str, Any]]:
    """Opportunity Won -> activate Project (if any) and create an Invoice stub."""
    opportunity = get("opportunities", opp_id)
    if not opportunity:
        return None

    update("opportunities", opp_id, {"stage": "won", "status": "won"})

    project_id = opportunity.get("project_id")
    if project_id:
        update("projects", project_id, {"status": "active"})

    invoice = create(
        "invoices",
        {
            "account_id": opportunity.get("account_id"),
            "project_id": project_id,
            "amount": opportunity.get("amount", 0),
            "status": "draft",
        },
    )

    log_activity(
        {
            "type": "opportunity_won",
            "subject": opportunity.get("title"),
            "account_id": opportunity.get("account_id"),
            "opportunity_id": opp_id,
            "project_id": project_id,
        }
    )
    return {
        "opportunity": get("opportunities", opp_id),
        "project": get("projects", project_id) if project_id else None,
        "invoice": invoice,
    }
