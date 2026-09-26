"""
SPINE RFQ ADAPTER
Presents crm_db opportunities (stage/source = rfq) in the RFQ response shape
the /rfq router and the Sales RFQ page have always spoken.

Why this exists
---------------
Three code paths used to create RFQs, into two different collections:

  * backend/sales/mail_pool_ai.py  -> crm_service.create_rfq() -> crm_db.opportunities
    (LIVE: celery beat every 10 min over torpedo_gmail.email_metadata)
  * backend/email_crm_pipeline/crm_populator.py -> email_automation.rfqs (monthly)
  * backend/routers/rfq.py /sync-from-gmail     -> email_automation.rfqs (manual)

The RFQ page read email_automation.rfqs, which the live pipeline never wrote,
so mailbox RFQs never appeared. crm_db.opportunities is now the single source
of truth; the other two writers are retired. This module is the read model.

Legacy rows still sitting in email_automation.rfqs are folded in by
`list_rfqs`/`get_rfq` so nothing that was hand-created there disappears; they
are migrated onto the spine by scripts/backfill_spine_rfqs.py.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

try:
    from . import crm_service
except ImportError:  # pragma: no cover - flat import when run from backend/
    from app.services import crm_service


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------
# The spine tracks a fine-grained `stage` plus a coarse `status`. The Sales page
# asks for open / won / lost / closed, so we derive a `state` from both and keep
# `status` carrying the detailed stage for the pipeline column.
#
#   open   -> live deal, still moving (new, rfq, qualified, proposal, negotiation)
#   won    -> opportunity.status == "won"
#   lost   -> opportunity.status == "lost"
#   closed -> explicitly closed with no win/loss recorded (abandoned, withdrawn)

OPEN_STAGES = ("new", "rfq", "qualified", "proposal", "negotiation")

# Detailed stage -> the legacy `status` values the RFQ page's filters use.
_STAGE_TO_LEGACY_STATUS = {
    "new": "pending",
    "rfq": "pending",
    "qualified": "pending",
    "proposal": "quoted",
    "negotiation": "negotiating",
    "won": "won",
    "lost": "lost",
}

# Reverse map, for translating an inbound status filter/update into a spine stage.
_LEGACY_STATUS_TO_STAGE = {
    "pending": "rfq",
    "quoted": "proposal",
    "negotiating": "negotiation",
    "won": "won",
    "lost": "lost",
}


def legacy_status_to_stage(status: str) -> Optional[str]:
    """Translate an RFQ-page status into a spine opportunity stage."""
    return _LEGACY_STATUS_TO_STAGE.get((status or "").strip().lower())


def derive_state(opportunity: Dict[str, Any]) -> str:
    """Coarse open/won/lost/closed state for a spine opportunity."""
    status = (opportunity.get("status") or "").strip().lower()
    stage = (opportunity.get("stage") or "").strip().lower()

    if status == "won" or stage == "won":
        return "won"
    if status == "lost" or stage == "lost":
        return "lost"
    if status == "closed" or opportunity.get("closed_at"):
        return "closed"
    return "open"


# ---------------------------------------------------------------------------
# Opportunity -> RFQ response shape
# ---------------------------------------------------------------------------

def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _rfq_display_id(opportunity: Dict[str, Any]) -> str:
    """
    Stable, human-readable id. Opportunities created before this adapter have no
    rfq_id of their own, so derive one from the creation year + the ObjectId tail
    rather than renumbering (which would break links people have already shared).
    """
    existing = (opportunity.get("metadata") or {}).get("rfq", {}).get("rfq_id")
    if existing:
        return existing
    if opportunity.get("rfq_id"):
        return opportunity["rfq_id"]

    created = opportunity.get("created_at")
    year = created.year if isinstance(created, datetime) else datetime.utcnow().year
    return f"RFQ-{year}-{str(opportunity.get('_id', ''))[-6:].upper()}"


def opportunity_to_rfq(
    opportunity: Dict[str, Any],
    accounts_cache: Optional[Dict[str, dict]] = None,
    contacts_cache: Optional[Dict[str, dict]] = None,
) -> Dict[str, Any]:
    """
    Map one spine opportunity onto the RFQ response contract.

    accounts_cache / contacts_cache are {id: doc} maps pre-fetched by the caller
    so a list of N RFQs costs 3 queries, not 2N+1.
    """
    meta = opportunity.get("metadata") or {}
    rfq_payload = meta.get("rfq") or {}

    account_id = opportunity.get("account_id")
    contact_id = opportunity.get("contact_id")

    account = (accounts_cache or {}).get(str(account_id)) if account_id else None
    contact = (contacts_cache or {}).get(str(contact_id)) if contact_id else None

    if account is None and account_id:
        account = crm_service.get("accounts", str(account_id))
    if contact is None and contact_id:
        contact = crm_service.get("contacts", str(contact_id))

    contact_email = (contact or {}).get("email") or rfq_payload.get("contact_email") or ""
    contact_name = (contact or {}).get("name") or ""
    account_name = (account or {}).get("name") or rfq_payload.get("account_name") or ""
    # No account/company was ever linked or extracted for a lot of mail-pool
    # RFQs (the sender's email just never mentions their company name) — fall
    # back to the email domain so the Account column reads e.g. "greenbook.org"
    # instead of a bare "—" for every RFQ that has no linked account.
    if not account_name and contact_email and "@" in contact_email:
        account_name = contact_email.split("@", 1)[1]

    state = derive_state(opportunity)
    stage = (opportunity.get("stage") or "rfq").strip().lower()

    amount = opportunity.get("amount")
    if amount in (None, 0):
        amount = rfq_payload.get("budget") or None

    return {
        "_id": str(opportunity.get("_id", "")),
        "rfq_id": _rfq_display_id(opportunity),
        # --- who ---
        "contact_email": contact_email,
        "contact_id": str(contact_id) if contact_id else None,
        "account_id": str(account_id) if account_id else None,
        "account_name": account_name,
        "lead_id": str(contact_id) if contact_id else None,
        "lead_name": contact_name or account_name or contact_email,
        # --- what ---
        "title": opportunity.get("title") or rfq_payload.get("title") or "",
        "description": opportunity.get("description") or rfq_payload.get("description") or "",
        "summary": rfq_payload.get("summary") or rfq_payload.get("description") or "",
        "ai_summary": rfq_payload.get("ai_summary"),
        # --- money ---
        # No currency default: a missing currency must read as unknown, never
        # INR (2026-09-26 -- a real ~$180K IDR fieldwork quote defaulting to
        # INR is most of why the page's "Total Value" read ~INR 468 crore).
        "extracted_value": rfq_payload.get("budget"),
        "extracted_currency": rfq_payload.get("currency"),
        "manual_value": opportunity.get("amount") if opportunity.get("amount") else None,
        "manual_currency": opportunity.get("currency"),
        "final_value": amount,
        "final_currency": opportunity.get("currency") or rfq_payload.get("currency"),
        "budget": rfq_payload.get("budget"),
        # --- direction: inbound (client -> us, the historical default — every
        # record before this field existed has no metadata.rfq.direction and
        # reads as inbound) vs outbound (us -> a vendor, asking for pricing) ---
        "direction": rfq_payload.get("direction") or "inbound",
        "client_name": rfq_payload.get("client_name"),
        # --- status ---
        "state": state,                                   # open | won | lost | closed
        "status": _STAGE_TO_LEGACY_STATUS.get(stage, "pending"),
        "stage": stage,
        "probability": crm_service.STAGE_PROBABILITY.get(stage),
        "loss_reason": opportunity.get("loss_reason"),
        "priority": opportunity.get("priority") or rfq_payload.get("priority") or "medium",
        # --- dates ---
        # received_at (backfilled from the source email's own date, see
        # scripts/backfill_rfq_received_dates.py) is the true date a client
        # sent the RFQ. created_at is only when this record was written to
        # the CRM (a 2026-08-03 bulk migration for most legacy rows), which
        # is not something a user asked about.
        "received_date": _iso(rfq_payload.get("received_at") or opportunity.get("created_at")),
        "due_date": _iso(rfq_payload.get("deadline") or opportunity.get("due_date")),
        "quoted_date": _iso(opportunity.get("quoted_at")),
        "closed_date": _iso(opportunity.get("closed_at")),
        "created_at": _iso(opportunity.get("created_at")),
        "updated_at": _iso(opportunity.get("updated_at")),
        "created_by": meta.get("source") or opportunity.get("created_by") or "mail_pool_ai",
        # --- research-brief fields the AI extracts ---
        "methodology": rfq_payload.get("methodology"),
        "loi": rfq_payload.get("loi"),
        "ir": rfq_payload.get("ir"),
        "country": rfq_payload.get("country") or rfq_payload.get("geography"),
        "sample_size": rfq_payload.get("sample_size"),
        "target_audience": rfq_payload.get("target_audience"),
        "timeline": rfq_payload.get("timeline"),
        "study_type": rfq_payload.get("study_type") or rfq_payload.get("project_type"),
        "additional_requirements": rfq_payload.get("additional_requirements"),
        # --- provenance ---
        "source_email_id": rfq_payload.get("source_email_id"),
        "source_emails": rfq_payload.get("source_emails", []),
        "source_emails_count": len(rfq_payload.get("source_emails", []) or []),
        "email_body": rfq_payload.get("email_body"),
        "sender_name": contact_name or rfq_payload.get("sender_name"),
        "sender_email": contact_email,
        "sender_company": account_name,
        "sender_title": (contact or {}).get("title") or rfq_payload.get("sender_title"),
        # --- spine cross-links ---
        "opportunity_id": str(opportunity.get("_id", "")),
        "project_id": str(opportunity["project_id"]) if opportunity.get("project_id") else None,
        "estimate_id": rfq_payload.get("estimate_id"),
        "invoice_id": opportunity.get("invoice_id"),
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _rfq_query(
    state: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    direction: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the opportunities filter for RFQ-sourced deals.

    An opportunity counts as an RFQ if it entered at the rfq stage or was logged
    by an RFQ flow — matching on stage alone would drop every RFQ that has since
    advanced to proposal/won.
    """
    query: Dict[str, Any] = {
        "$or": [
            {"stage": "rfq"},
            {"metadata.source": "rfq"},
            {"metadata.rfq": {"$exists": True}},
        ],
        "is_deleted": {"$ne": True},
    }

    conditions: List[Dict[str, Any]] = []

    if state:
        state = state.strip().lower()
        if state == "open":
            conditions.append({
                "status": {"$nin": ["won", "lost", "closed"]},
                "stage": {"$in": list(OPEN_STAGES)},
            })
        elif state in ("won", "lost"):
            conditions.append({"$or": [{"status": state}, {"stage": state}]})
        elif state == "closed":
            conditions.append({
                "$or": [{"status": "closed"}, {"closed_at": {"$exists": True, "$ne": None}}],
            })

    if status:
        stage = legacy_status_to_stage(status)
        if stage:
            conditions.append({"stage": stage})

    if direction:
        direction = direction.strip().lower()
        if direction == "outbound":
            conditions.append({"metadata.rfq.direction": "outbound"})
        elif direction == "inbound":
            # No direction stamped == inbound (every record predates this
            # field), so "inbound" matches absent OR explicitly "inbound".
            conditions.append({
                "$or": [
                    {"metadata.rfq.direction": {"$exists": False}},
                    {"metadata.rfq.direction": "inbound"},
                ]
            })

    if account_id:
        conditions.append({"account_id": account_id})

    if search:
        conditions.append({
            "$or": [
                {"title": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
                {"metadata.rfq.description": {"$regex": search, "$options": "i"}},
            ]
        })

    if conditions:
        query["$and"] = conditions

    return query


def _hydrate(opportunities: List[dict]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """Batch-fetch the accounts and contacts referenced by a page of opportunities."""
    account_ids, contact_ids = set(), set()
    for opp in opportunities:
        if opp.get("account_id"):
            account_ids.add(str(opp["account_id"]))
        if opp.get("contact_id"):
            contact_ids.add(str(opp["contact_id"]))

    def _fetch(collection: str, ids: set) -> Dict[str, dict]:
        if not ids:
            return {}
        oids = []
        for i in ids:
            try:
                oids.append(ObjectId(i))
            except Exception:
                continue
        if not oids:
            return {}
        docs = crm_service.list_docs(collection, {"_id": {"$in": oids}}, limit=len(oids))
        return {str(d["_id"]): d for d in docs}

    return _fetch("accounts", account_ids), _fetch("contacts", contact_ids)


def list_rfqs(
    state: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    direction: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
) -> Dict[str, Any]:
    """Paginated RFQ list read off crm_db.opportunities."""
    query = _rfq_query(state=state, status=status, account_id=account_id, search=search, direction=direction)
    col = crm_service._col("opportunities")

    total = col.count_documents(query)
    skip = (page - 1) * limit
    opportunities = list(
        col.find(query).sort("created_at", -1).skip(skip).limit(limit)
    )

    accounts_cache, contacts_cache = _hydrate(opportunities)

    return {
        "success": True,
        "rfqs": [
            opportunity_to_rfq(o, accounts_cache, contacts_cache) for o in opportunities
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
    }


def get_rfq(rfq_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one RFQ by opportunity _id or by its derived RFQ-YYYY-XXXXXX id."""
    col = crm_service._col("opportunities")

    opportunity = None
    try:
        opportunity = col.find_one({"_id": ObjectId(rfq_id)})
    except Exception:
        pass

    if not opportunity:
        opportunity = col.find_one({
            "$or": [
                {"rfq_id": rfq_id},
                {"metadata.rfq.rfq_id": rfq_id},
            ]
        })

    if not opportunity:
        return None
    return opportunity_to_rfq(opportunity)


def get_stats(direction: Optional[str] = None) -> Dict[str, Any]:
    """RFQ counts and pipeline value grouped by the coarse open/won/lost/closed state."""
    col = crm_service._col("opportunities")
    base = _rfq_query(direction=direction)

    stats = {
        "total": col.count_documents(base),
        "by_state": {},
        "by_stage": {},
        "pipeline_value": 0.0,
        "won_value": 0.0,
    }

    for state in ("open", "won", "lost", "closed"):
        stats["by_state"][state] = col.count_documents(
            _rfq_query(state=state, direction=direction)
        )

    for stage in crm_service.OPPORTUNITY_STAGES:
        stats["by_stage"][stage] = col.count_documents({**base, "stage": stage})

    def _sum(match: Dict[str, Any]) -> float:
        cursor = col.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ])
        docs = list(cursor)
        return float(docs[0]["total"]) if docs else 0.0

    def _sum_by_currency(match: Dict[str, Any]) -> Dict[str, float]:
        cursor = col.aggregate([
            {"$match": match},
            {"$group": {"_id": "$currency", "total": {"$sum": "$amount"}}},
        ])
        # An unset currency must read as "unknown", never assume a currency
        # (2026-09-26: this is exactly how a real ~$180K IDR fieldwork quote
        # got displayed as ~INR 288 crore -- see docs/RFQ_PAGE_P1_AUDIT.md).
        return {(doc["_id"] or "unknown"): float(doc["total"]) for doc in cursor}

    # Kept for callers that only want a single headline number -- but that
    # number mixes currencies (see the module docstring's warning) and MUST
    # NOT be shown as a single amount on the RFQ page; use value_by_currency.
    stats["pipeline_value"] = _sum(_rfq_query(state="open", direction=direction))
    stats["won_value"] = _sum(_rfq_query(state="won", direction=direction))

    pipeline_by_cur = _sum_by_currency(_rfq_query(state="open", direction=direction))
    won_by_cur = _sum_by_currency(_rfq_query(state="won", direction=direction))
    currencies = sorted(set(pipeline_by_cur) | set(won_by_cur))
    stats["value_by_currency"] = [
        {"currency": cur, "pipeline_value": pipeline_by_cur.get(cur, 0.0),
         "won_value": won_by_cur.get(cur, 0.0)}
        for cur in currencies
    ]

    return stats
