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
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from bson import ObjectId
from bson.errors import InvalidId

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
    "notifications",
}

# Collections whose field changes are recorded on the timeline (audit trail).
# activities/notifications/ai_decisions are event streams — never tracked.
_TRACKED_COLLECTIONS = {
    "accounts", "contacts", "leads", "opportunities", "projects",
    "invoices", "tasks",
}
_UNTRACKED_FIELDS = {"updated_at", "created_at", "metadata", "name_normalized"}

# Default win probability per stage (forecast weighting; an opportunity's own
# `probability` field overrides these when set).
STAGE_PROBABILITY = {
    "new": 0.10, "rfq": 0.20, "qualified": 0.40, "proposal": 0.60,
    "negotiation": 0.80, "won": 1.0, "lost": 0.0,
}
OPPORTUNITY_STAGES = list(STAGE_PROBABILITY)

# Activity link field per linkable object type (the central timeline layer).
_TIMELINE_FIELDS = {
    "account": "account_id",
    "contact": "contact_id",
    "opportunity": "opportunity_id",
    "project": "project_id",
    "lead": "lead_id",
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

# Sentinel for "caller did not supply this field", so an explicit None can mean
# "clear this field" (TOR-16). update() used to strip every None, which made it
# impossible to null anything through the API — and silently broke the service's
# own set_opportunity_stage(), where clearing loss_reason on a reopened deal
# just vanished.
class _Unset:
    def __repr__(self):  # pragma: no cover - debug aid
        return "<unset>"


UNSET = _Unset()


def create(collection: str, data: Dict[str, Any]) -> dict:
    data = {k: v for k, v in data.items() if v is not None and v is not UNSET}
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


def update(collection: str, id_str: str, data: Dict[str, Any],
           changed_by: Optional[str] = None) -> Optional[dict]:
    """
    Patch a document. A key present with value None CLEARS that field; use the
    UNSET sentinel (or simply omit the key) to leave a field alone. Before
    TOR-16 every None was stripped, so nothing could ever be cleared.
    """
    update_data = {k: v for k, v in data.items() if v is not UNSET}
    update_data["updated_at"] = datetime.utcnow()

    # Field-change history: diff before/after and put the changes on the
    # timeline, so amount/stage/owner edits leave an audit trail.
    old = None
    if collection in _TRACKED_COLLECTIONS:
        old = _col(collection).find_one({"_id": _oid(id_str)})

    to_set = {k: v for k, v in update_data.items() if v is not None}
    to_unset = {k: "" for k, v in update_data.items() if v is None}
    ops: Dict[str, Any] = {"$set": to_set}
    if to_unset:
        ops["$unset"] = to_unset
    result = _col(collection).update_one({"_id": _oid(id_str)}, ops)
    if result.matched_count == 0:
        return None

    if old is not None:
        changes = {}
        for k, v in update_data.items():
            if k in _UNTRACKED_FIELDS or k.startswith("metadata."):
                continue
            before = old.get(k)
            if before != v:
                changes[k] = {"from": _jsonable(before), "to": _jsonable(v)}
        if changes:
            singular = collection[:-1] if collection.endswith("s") else collection
            link_field = _TIMELINE_FIELDS.get(singular)
            activity = {
                "type": "record_updated",
                "subject": f"{singular} updated: {', '.join(changes)}",
                "description": None,
                "author": changed_by,
                "object_type": singular,
                "object_id": id_str,
                "changes": changes,
            }
            if link_field:
                activity[link_field] = id_str
            # keep account context on linked objects for the account timeline
            if old.get("account_id") and singular != "account":
                activity["account_id"] = old["account_id"]
            try:
                log_activity(activity)
            except Exception:
                pass  # history must never break the write

    return get(collection, id_str)


def _jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, ObjectId):
        return str(v)
    return v


def delete(collection: str, id_str: str, changed_by: Optional[str] = None) -> bool:
    """
    SOFT delete: flag the document and hide it from lists, keep the row.

    A hard delete_one() here orphaned every reference to the document —
    contacts, opportunities, invoices, projects and activities kept a dangling
    account_id, disappeared from the account view, and still counted in every
    report (TOR-18). The spine's own nightly reconcile already refuses to hard
    delete for exactly this reason ("they anchor historical activities"), so
    the API handing out a hard delete contradicted it.

    Use purge() for a genuine, cascading removal.
    """
    result = _col(collection).update_one(
        {"_id": _oid(id_str)},
        {"$set": {"status": "deleted",
                  "deleted_at": datetime.utcnow(),
                  "deleted_by": changed_by,
                  "updated_at": datetime.utcnow()}},
    )
    return result.matched_count > 0


def purge(collection: str, id_str: str) -> Dict[str, Any]:
    """
    Hard delete WITH reference cleanup. Admin-only path; `delete` is what the
    generic API exposes.

    Re-points nothing — there is nothing to re-point to — so referencing docs
    have the dead id cleared rather than left dangling.
    """
    ref_field = {"accounts": "account_id", "contacts": "contact_id",
                 "opportunities": "opportunity_id", "projects": "project_id",
                 "leads": "lead_id"}.get(collection)
    cleared: Dict[str, int] = {}
    if ref_field:
        for other in _ACCOUNT_REF_COLLECTIONS:
            if other == collection:
                continue
            res = _col(other).update_many(
                {ref_field: id_str}, {"$set": {ref_field: None}})
            if res.modified_count:
                cleared[other] = res.modified_count
    result = _col(collection).delete_one({"_id": _oid(id_str)})
    return {"deleted": result.deleted_count > 0, "references_cleared": cleared}


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


def find_contact_by_email(email: str) -> Optional[dict]:
    """Find a contact by lowercased email (dedupe helper)."""
    if not email:
        return None
    return serialize(_col("contacts").find_one({"email": email.strip().lower()}))


def get_or_create_contact(email: str, defaults: Optional[Dict[str, Any]] = None) -> Tuple[dict, bool]:
    """Return (contact, created). Reuses an existing contact matched by email."""
    existing = find_contact_by_email(email)
    if existing:
        return existing, False
    data = dict(defaults or {})
    data["email"] = (email or "").strip().lower()
    return create("contacts", data), True


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
    """
    Opportunity Won — the ONLY path that converts a lead/RFQ into a client.

    Side effects (Finance + Operations):
      1. Opportunity stage/status → won, closed_at set
      2. Linked project activated (or created)
      3. Draft invoice stub created
      4. Linked lead stage → won (stops outreach/nurture)
    """
    opportunity = get("opportunities", opp_id)
    if not opportunity:
        return None

    now = datetime.utcnow()
    update("opportunities", opp_id,
           {"stage": "won", "status": "won", "closed_at": now})

    project_id = opportunity.get("project_id")
    project = None
    if project_id:
        update("projects", project_id, {
            "status": "active",
            "activated_at": now,
            "customer_id": opportunity.get("account_id"),
        })
        project = get("projects", project_id)
    else:
        project = create(
            "projects",
            {
                "name": opportunity.get("title") or "Project",
                "account_id": opportunity.get("account_id"),
                "opportunity_id": opp_id,
                "status": "active",
                "activated_at": now,
                "source": "rfq_won",
            },
        )
        project_id = project.get("_id") if project else None
        if project_id:
            update("opportunities", opp_id, {"project_id": project_id})

    invoice = create(
        "invoices",
        {
            "account_id": opportunity.get("account_id"),
            "project_id": project_id,
            "amount": opportunity.get("amount", 0),
            "status": "draft",
            "payment_terms": opportunity.get("payment_terms") or "Net 30",
            "source": "rfq_won",
            "created_at": now,
        },
    )

    lead_id = opportunity.get("lead_id")
    if lead_id:
        try:
            from db_pools import get_background_db
            from bson import ObjectId
            db = get_background_db()
            db["leads"].update_one(
                {"_id": ObjectId(str(lead_id))},
                {"$set": {
                    "stage": "won",
                    "engagement_status": "converted",
                    "converted_at": now,
                    "opportunity_id": opp_id,
                    "project_id": project_id,
                    "updated_at": now,
                }},
            )
        except Exception:
            pass

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
        "project": project or (get("projects", project_id) if project_id else None),
        "invoice": invoice,
    }


def set_opportunity_stage(opp_id: str, stage: str,
                          loss_reason: Optional[str] = None,
                          changed_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Move an opportunity through the pipeline. "won" delegates to
    mark_opportunity_won (project activation + invoice stub); "lost" requires
    a loss_reason so losses stay analyzable. Every move logs a stage_changed
    activity.
    """
    if stage not in STAGE_PROBABILITY:
        raise ValueError(f"Unknown stage: {stage}. Valid: {OPPORTUNITY_STAGES}")
    opportunity = get("opportunities", opp_id)
    if not opportunity:
        return None
    old_stage = opportunity.get("stage")
    if stage == old_stage:
        return {"opportunity": opportunity}

    if stage == "won":
        return mark_opportunity_won(opp_id)

    fields: Dict[str, Any] = {"stage": stage}
    if stage == "lost":
        if not (loss_reason or "").strip():
            raise ValueError("loss_reason is required when marking an opportunity lost")
        fields["status"] = "lost"
        fields["loss_reason"] = loss_reason.strip()
        fields["closed_at"] = datetime.utcnow()
    elif opportunity.get("status") in ("won", "lost"):
        fields["status"] = "open"       # reopening a closed deal
        # Explicit None now genuinely clears these (TOR-16) — a reopened deal
        # used to keep showing the reason it was lost.
        fields["loss_reason"] = None
        fields["closed_at"] = None

    update("opportunities", opp_id, fields, changed_by=changed_by)
    log_activity({
        "type": "stage_changed",
        "subject": f"{opportunity.get('title')}: {old_stage} → {stage}"
                   + (f" ({loss_reason})" if stage == "lost" else ""),
        "author": changed_by,
        "account_id": opportunity.get("account_id"),
        "opportunity_id": opp_id,
    })
    if stage == "lost":
        notify("opportunity_lost",
               f"Opportunity lost: {opportunity.get('title')} — {loss_reason}",
               link_object_type="opportunity", link_object_id=opp_id)
    return {"opportunity": get("opportunities", opp_id)}


def convert_lead(lead_id: str, opportunity: Optional[Dict[str, Any]] = None,
                 changed_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Lead conversion: dedupe/create the Account (from company) and Contact
    (from email), link them back onto the lead, optionally open an
    Opportunity, and mark the lead converted.
    """
    lead = get("leads", lead_id)
    if not lead:
        return None
    if lead.get("status") == "converted":
        raise ValueError("Lead is already converted")

    name = (lead.get("name")
            or f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip()
            or lead.get("email") or "")

    account_id = lead.get("account_id")
    if not account_id and (lead.get("company") or "").strip():
        account, _ = get_or_create_account(
            lead["company"].strip(),
            defaults={"owner": lead.get("owner"),
                      "metadata": {"source": "lead_conversion"}})
        account_id = account["_id"]

    contact_id = lead.get("contact_id")
    if not contact_id and (lead.get("email") or "").strip():
        contact, _ = get_or_create_contact(
            lead["email"].strip().lower(),
            defaults={"name": name or None, "title": lead.get("title"),
                      "phone": lead.get("phone"), "account_id": account_id,
                      "owner": lead.get("owner"),
                      "metadata": {"source": "lead_conversion"}})
        contact_id = contact["_id"]

    opportunity_doc = None
    if opportunity is not None:
        opportunity_doc = create("opportunities", {
            "title": opportunity.get("title") or f"Opportunity: {name or lead.get('company', 'lead')}",
            "account_id": account_id,
            "contact_id": contact_id,
            "amount": float(opportunity.get("amount") or 0),
            "stage": opportunity.get("stage") or "qualified",
            "status": "open",
            "owner": opportunity.get("owner") or lead.get("owner"),
            "expected_close_date": opportunity.get("expected_close_date"),
            "metadata": {"source": "lead_conversion", "lead_id": lead_id},
        })

    update("leads", lead_id, {
        "status": "converted",
        "account_id": account_id,
        "contact_id": contact_id,
        "converted_at": datetime.utcnow(),
        "converted_opportunity_id": opportunity_doc["_id"] if opportunity_doc else None,
    }, changed_by=changed_by)

    log_activity({
        "type": "lead_converted",
        "subject": f"Lead converted: {name or lead.get('email') or lead_id}",
        "author": changed_by,
        "lead_id": lead_id,
        "account_id": account_id,
        "contact_id": contact_id,
        "opportunity_id": opportunity_doc["_id"] if opportunity_doc else None,
    })
    return {
        "lead": get("leads", lead_id),
        "account": get("accounts", account_id) if account_id else None,
        "contact": get("contacts", contact_id) if contact_id else None,
        "opportunity": opportunity_doc,
    }


# ------------------------- duplicate management ----------------------

_LEGAL_SUFFIXES = re.compile(
    r"\b(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|"
    r"gmbh|co|company|plc|sa|bv|ag)\b\.?", re.IGNORECASE)


def _dedupe_key(name: str) -> str:
    """Aggressive company-name key: normalized, legal suffixes stripped."""
    n = _normalize_name(name)
    n = _LEGAL_SUFFIXES.sub("", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def find_duplicate_accounts() -> List[Dict[str, Any]]:
    """Group non-merged accounts whose names collapse to the same dedupe key
    (e.g. 'Acme Corp' / 'Acme Corporation' / 'acme corp.')."""
    groups: Dict[str, List[dict]] = {}
    # Project only the fields the dedupe key and the UI row need. This used to
    # pull every field of every account into memory to compute a name key
    # (TOR-20).
    projection = {"name": 1, "status": 1, "owner": 1, "account_type": 1,
                  "created_at": 1}
    for doc in _col("accounts").find({"status": {"$ne": "merged"}}, projection):
        key = _dedupe_key(doc.get("name", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(serialize(doc))
    return [{"key": k, "accounts": v} for k, v in groups.items() if len(v) > 1]


_ACCOUNT_REF_COLLECTIONS = ("contacts", "leads", "opportunities",
                            "activities", "invoices", "projects")


def merge_accounts(primary_id: str, duplicate_ids: List[str],
                   changed_by: Optional[str] = None) -> Dict[str, Any]:
    """
    Merge duplicate accounts into a primary: re-point every account_id
    reference, union tags, fill blank primary fields from the duplicates,
    then mark the duplicates status='merged' (kept for provenance, hidden
    from lists). Timelines of the duplicates flow into the primary.
    """
    primary = get("accounts", primary_id)
    if not primary:
        raise ValueError("Primary account not found")
    duplicate_ids = [d for d in duplicate_ids if d != primary_id]
    if not duplicate_ids:
        raise ValueError("No duplicate ids to merge")

    repointed: Dict[str, int] = {}
    fill_fields = {}
    all_tags = set(primary.get("tags") or [])
    for dup_id in duplicate_ids:
        dup = get("accounts", dup_id)
        if not dup:
            continue
        for coll in _ACCOUNT_REF_COLLECTIONS:
            res = _db()[coll].update_many({"account_id": dup_id},
                                          {"$set": {"account_id": primary_id}})
            repointed[coll] = repointed.get(coll, 0) + res.modified_count
        _col("tasks").update_many(
            {"linked_object_type": "account", "linked_object_id": dup_id},
            {"$set": {"linked_object_id": primary_id}})
        all_tags.update(dup.get("tags") or [])
        for f in ("email", "phone", "website", "owner"):
            if not primary.get(f) and dup.get(f) and f not in fill_fields:
                fill_fields[f] = dup[f]
        _col("accounts").update_one(
            {"_id": _oid(dup_id)},
            {"$set": {"status": "merged", "merged_into": primary_id,
                      "merged_at": datetime.utcnow(),
                      "updated_at": datetime.utcnow()}})

    if all_tags != set(primary.get("tags") or []):
        fill_fields["tags"] = sorted(all_tags)
    if fill_fields:
        update("accounts", primary_id, fill_fields, changed_by=changed_by)

    log_activity({
        "type": "accounts_merged",
        "subject": f"Merged {len(duplicate_ids)} duplicate(s) into {primary.get('name')}",
        "author": changed_by,
        "account_id": primary_id,
        "merged_ids": duplicate_ids,
        "repointed": repointed,
    })
    return {"account": get("accounts", primary_id),
            "merged": duplicate_ids, "repointed": repointed}


# ------------------------------- search ------------------------------

def search(q: str, limit: int = 10) -> Dict[str, List[dict]]:
    """Global CRM search across accounts, contacts, leads, opportunities."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"accounts": [], "contacts": [], "leads": [], "opportunities": []}
    rx = {"$regex": re.escape(q), "$options": "i"}
    return {
        "accounts": list_docs("accounts",
                              {"name": rx, "status": {"$ne": "merged"}}, limit=limit),
        "contacts": list_docs("contacts",
                              {"$or": [{"name": rx}, {"email": rx}]}, limit=limit),
        "leads": list_docs("leads",
                           {"$or": [{"name": rx}, {"email": rx}, {"company": rx}]},
                           limit=limit),
        "opportunities": list_docs("opportunities", {"title": rx}, limit=limit),
    }


# ------------------------------ reports ------------------------------

def pipeline_report() -> Dict[str, Any]:
    """
    Pipeline value by stage, win rate, weighted forecast, velocity.

    Computed with a $group aggregation rather than by pulling every
    opportunity into Python (TOR-20). The old loop read the whole collection
    on every dashboard load — unbounded memory, and under a 1 GB cgroup on a
    single-worker event loop it blocked every other request while it ran.
    """
    stages: Dict[str, Dict[str, Any]] = {
        s: {"stage": s, "count": 0, "value": 0.0, "weighted": 0.0}
        for s in OPPORTUNITY_STAGES
    }

    # Weighted forecast uses the opportunity's own probability when set,
    # otherwise the stage default — expressed as a $switch so Mongo does it.
    prob_expr = {
        "$ifNull": [
            "$probability",
            {"$switch": {
                "branches": [{"case": {"$eq": ["$stage", st]}, "then": pr}
                             for st, pr in STAGE_PROBABILITY.items()],
                "default": 0.1,
            }},
        ]
    }

    pipeline = [
        {"$group": {
            "_id": {"$ifNull": ["$stage", "new"]},
            "count": {"$sum": 1},
            "value": {"$sum": {"$ifNull": [{"$toDouble": "$amount"}, 0]}},
            "weighted": {"$sum": {"$cond": [
                {"$eq": ["$status", "open"]},
                {"$multiply": [{"$ifNull": [{"$toDouble": "$amount"}, 0]}, prob_expr]},
                0,
            ]}},
        }},
    ]
    for row in _col("opportunities").aggregate(pipeline):
        stage = row["_id"] or "new"
        stages.setdefault(
            stage, {"stage": stage, "count": 0, "value": 0.0, "weighted": 0.0})
        stages[stage].update(
            count=row["count"],
            value=float(row.get("value") or 0),
            weighted=float(row.get("weighted") or 0),
        )

    won = stages.get("won", {}).get("count", 0)
    lost = stages.get("lost", {}).get("count", 0)

    # Velocity: measured from created_at to closed_at, the timestamp stamped
    # when the deal actually closed. Previously this used updated_at, so any
    # later edit to a won deal inflated the average forever (TOR-17). Rows
    # closed before closed_at existed simply don't contribute.
    velocity = list(_col("opportunities").aggregate([
        {"$match": {"stage": "won",
                    "closed_at": {"$ne": None},
                    "created_at": {"$ne": None}}},
        {"$group": {"_id": None, "avg_ms": {"$avg": {
            "$subtract": ["$closed_at", "$created_at"]}}}},
    ]))
    avg_days = (round(velocity[0]["avg_ms"] / 86_400_000, 1)
                if velocity and velocity[0].get("avg_ms") else None)

    open_rows = [r for st, r in stages.items() if st not in ("won", "lost")]
    return {
        "stages": [stages[s] for s in OPPORTUNITY_STAGES if s in stages]
                  + [r for s, r in stages.items() if s not in OPPORTUNITY_STAGES],
        "open_count": sum(r["count"] for r in open_rows),
        "open_value": round(sum(r["value"] for r in open_rows), 2),
        "forecast": round(sum(r["weighted"] for r in stages.values()), 2),
        "won_count": won,
        "lost_count": lost,
        "win_rate": round(won / (won + lost), 3) if (won + lost) else None,
        "avg_days_to_close": avg_days,
    }


def activity_report(days: int = 30) -> Dict[str, Any]:
    """Activity volume by type over the trailing window."""
    since = datetime.utcnow() - timedelta(days=days)
    counts: Dict[str, int] = {}
    for doc in _col("activities").aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]):
        counts[doc["_id"] or "unknown"] = doc["n"]
    return {"days": days, "by_type": counts, "total": sum(counts.values())}


# --------------------------- notifications ---------------------------

def notify(type_: str, message: str, link_object_type: Optional[str] = None,
           link_object_id: Optional[str] = None, owner: Optional[str] = None,
           dedupe_key: Optional[str] = None) -> Optional[dict]:
    """Create a CRM notification. With dedupe_key, at most one unread
    notification per key exists (repeat alerts don't pile up)."""
    try:
        if dedupe_key:
            existing = _col("notifications").find_one(
                {"dedupe_key": dedupe_key, "read": False})
            if existing:
                return serialize(existing)
        return create("notifications", {
            "type": type_, "message": message,
            "link_object_type": link_object_type,
            "link_object_id": link_object_id,
            "owner": owner, "read": False, "dedupe_key": dedupe_key,
        })
    except Exception:
        return None  # notifications are best-effort
