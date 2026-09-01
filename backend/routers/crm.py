"""
CRM SPINE ROUTER  (/api/crm/*)

Clean canonical CRM API layer. Does NOT replace legacy routes (sales_accounts,
leads, finance, ...) — those stay untouched. This is the new unified surface
that modules and AI agents link through.

Generic CRUD is exposed per canonical collection, plus the cross-object flows
(timeline, RFQ, opportunity-won). Create payloads are validated against the
canonical Pydantic models in app/models/crm_objects.py.
"""

from fastapi import APIRouter, HTTPException, Body, Query, Depends
from typing import Optional, Dict, Any

try:
    from ..middleware.rate_limit import web_lead_rate_limit
    from ..app.services import crm_service
    from ..app.models import crm_objects
    from ..app.security import require
except ImportError:  # pragma: no cover - absolute import fallback
    from middleware.rate_limit import web_lead_rate_limit
    from app.services import crm_service
    from app.models import crm_objects
    from app.security import require

router = APIRouter(prefix="/api/crm", tags=["CRM Spine"])

# Coarse capability gates (enforced only when RBAC_ENABLED=true).
require_read = require("read")
require_write = require("write")
require_approve = require("approve")

# Map a URL resource to its canonical Pydantic model for create-time validation.
_MODELS = {
    "accounts": crm_objects.Account,
    "contacts": crm_objects.Contact,
    "leads": crm_objects.Lead,
    "opportunities": crm_objects.Opportunity,
    "activities": crm_objects.Activity,
    "tasks": crm_objects.Task,
    "projects": crm_objects.Project,
    "invoices": crm_objects.Invoice,
    "ai_decisions": crm_objects.AIDecision,
}


def _check_resource(resource: str):
    if resource not in crm_service.COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown CRM resource: {resource}")


# ----------------------- cross-object flows (specific first) -----------------------

@router.get("/timeline/{object_type}/{object_id}")
def get_timeline(object_type: str, object_id: str, _user: str = Depends(require_read)):
    """Activities + tasks linked to one canonical object (account/contact/opportunity/project)."""
    try:
        return crm_service.timeline(object_type, object_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rfq")
def create_rfq(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_write)):
    """RFQ -> creates an Opportunity and a Project stub, cross-linked."""
    return crm_service.create_rfq(payload)


@router.post("/opportunities/{opp_id}/win")
def win_opportunity(opp_id: str, _user: str = Depends(require_write)):
    """Mark Opportunity Won -> activate Project and create Invoice stub."""
    result = crm_service.mark_opportunity_won(opp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return result


@router.post("/opportunities/{opp_id}/stage")
def move_opportunity_stage(
    opp_id: str,
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_write),
):
    """Move an opportunity to another stage. 'lost' requires loss_reason;
    'won' triggers the full win flow."""
    try:
        result = crm_service.set_opportunity_stage(
            opp_id, payload.get("stage", ""),
            loss_reason=payload.get("loss_reason"),
            changed_by=str(_user) if _user else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return result


@router.post("/leads/{lead_id}/convert")
def convert_lead(
    lead_id: str,
    payload: Dict[str, Any] = Body(default={}),
    _user: str = Depends(require_write),
):
    """Convert a lead into Account + Contact (and optionally an Opportunity
    when payload.opportunity is provided)."""
    try:
        result = crm_service.convert_lead(
            lead_id, opportunity=payload.get("opportunity"),
            changed_by=str(_user) if _user else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return result


@router.get("/search")
def global_search(q: str = Query(..., min_length=2),
                        limit: int = Query(10, le=50),
                        _user: str = Depends(require_read)):
    """Global search across accounts, contacts, leads and opportunities."""
    return crm_service.search(q, limit=limit)


@router.get("/reports/pipeline")
def report_pipeline(_user: str = Depends(require_read)):
    """Pipeline value by stage, weighted forecast, win rate, velocity."""
    return crm_service.pipeline_report()


@router.get("/reports/activity")
def report_activity(days: int = Query(30, ge=1, le=365),
                          _user: str = Depends(require_read)):
    """Activity volume by type over the trailing window."""
    return crm_service.activity_report(days=days)


@router.get("/spine-health")
def spine_health(_user: str = Depends(require_read)):
    """
    Mirror health (TOR-13).

    Every spine_connector mirror swallows its exceptions so a mirror failure
    can never break the legacy write that triggered it. That is the right call
    for availability and the wrong one for visibility: a mirror failing all day
    was indistinguishable from one never invoked. `failed` should be 0 — a
    non-zero value means legacy records exist with no spine counterpart, and
    the nightly reconcile only re-converges what it explicitly handles.
    """
    try:
        from app.services.spine_connector import mirror_stats
    except ImportError:
        from backend.app.services.spine_connector import mirror_stats
    return mirror_stats()


@router.get("/duplicates/accounts")
def duplicate_accounts(_user: str = Depends(require_read)):
    """Groups of accounts whose names collapse to the same dedupe key."""
    return crm_service.find_duplicate_accounts()


@router.post("/accounts/merge")
def merge_accounts(payload: Dict[str, Any] = Body(...),
                         _user: str = Depends(require_write)):
    """Merge duplicate accounts into a primary; re-points all references."""
    try:
        return crm_service.merge_accounts(
            payload.get("primary_id", ""),
            payload.get("duplicate_ids") or [],
            changed_by=str(_user) if _user else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notifications/{notif_id}/read")
def mark_notification_read(notif_id: str, _user: str = Depends(require_write)):
    doc = crm_service.update("notifications", notif_id, {"read": True})
    if not doc:
        raise HTTPException(status_code=404, detail="Notification not found")
    return doc


@router.post("/contacts/{contact_id}/draft-email")
def draft_email_for_contact(
    contact_id: str,
    payload: Dict[str, Any] = Body(default={}),
    _user: str = Depends(require_write),
):
    """AI-draft an outbound email to this contact (stored in
    mail_followup_drafts for review — nothing is sent)."""
    contact = crm_service.get("contacts", contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not contact.get("email"):
        raise HTTPException(status_code=400, detail="Contact has no email address")
    try:
        try:
            from ai_governance.ai_gateway import get_ai_gateway
            from db_pools import get_db
        except ImportError:
            from backend.ai_governance.ai_gateway import get_ai_gateway
            from backend.db_pools import get_db
        account = crm_service.get("accounts", contact["account_id"]) \
            if contact.get("account_id") else None
        draft = get_ai_gateway().generate_email_draft(
            system_prompt=(
                "You draft concise, professional B2B emails for a market-research "
                "company. Return ONLY JSON: {\"subject\": \"...\", \"body\": \"...\"}. "
                "No invented prices or commitments."),
            user_prompt=(
                f"Draft an email to {contact.get('name') or contact['email']} "
                f"({contact.get('title') or 'unknown title'}"
                f"{', ' + account['name'] if account else ''}).\n"
                f"Goal/context from the sender: "
                f"{payload.get('context') or 'a friendly business check-in'}"))
        if not draft:
            raise HTTPException(status_code=502, detail="AI draft generation failed")
        from datetime import datetime as _dt
        ins = get_db("email_automation")["mail_followup_drafts"].insert_one({
            "source": "crm_contact_page",
            "contact_id": contact_id,
            "account_id": contact.get("account_id"),
            "to_email": contact["email"],
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "status": "draft",
            "requested_by": str(_user) if _user else None,
            "created_at": _dt.utcnow(),
        })
        crm_service.log_activity({
            "type": "email_drafted",
            "subject": f"AI draft prepared: {draft.get('subject')}",
            "author": str(_user) if _user else None,
            "contact_id": contact_id,
            "account_id": contact.get("account_id"),
        })
        return {"draft_id": str(ins.inserted_id), **draft,
                "to_email": contact["email"], "status": "draft"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/web-to-lead", dependencies=[Depends(web_lead_rate_limit)])
def web_to_lead(payload: Dict[str, Any] = Body(...)):
    """
    Public inbound lead capture for website forms.

    Three gates, because this is the one endpoint that writes to the database
    with no session (TOR-10):
      1. rate limit (5/hour per source IP) — see middleware/rate_limit.py
      2. honeypot field `website_hp` must be empty
      3. WEB_LEAD_TOKEN shared secret

    The token used to be optional and defaulted to empty, which skipped the
    check entirely — so in practice the honeypot was the only protection and
    anyone could write unbounded documents into crm_db.leads, each firing a
    notification. It is REQUIRED now: with no token configured the endpoint
    refuses rather than accepting anonymous writes.
    """
    import os as _os
    if (payload.get("website_hp") or "").strip():
        return {"ok": True}  # bot fell in the honeypot; pretend success
    expected = _os.getenv("WEB_LEAD_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Web lead capture is not configured (WEB_LEAD_TOKEN unset).")
    if payload.get("token") != expected:
        raise HTTPException(status_code=403, detail="Invalid token")
    email = (payload.get("email") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    if not email and not name:
        raise HTTPException(status_code=422, detail="name or email required")
    lead = crm_service.create("leads", {
        "email": email or None,
        "name": name or None,
        "company": (payload.get("company") or "").strip() or None,
        "phone": (payload.get("phone") or "").strip() or None,
        "source": "webform",
        "status": "new",
        "metadata": {"source": "web_to_lead",
                     "message": (payload.get("message") or "")[:2000]},
    })
    crm_service.log_activity({
        "type": "lead_ingested",
        "subject": f"Web form lead: {name or email}",
        "lead_id": lead["_id"],
    })
    crm_service.notify(
        "web_lead_received",
        f"New website lead: {name or email}"
        + (f" ({payload.get('company')})" if payload.get("company") else ""),
        link_object_type="lead", link_object_id=lead["_id"])
    return {"ok": True, "lead_id": lead["_id"]}


# ------------------------------- generic CRUD -------------------------------

def _build_list_query(resource: str, account_id, contact_id, owner, stage,
                      status, unread, linked_object_type, linked_object_id,
                      q) -> Dict[str, Any]:
    import re as _re
    query: Dict[str, Any] = {}
    if account_id:
        query["account_id"] = account_id
    if contact_id:
        query["contact_id"] = contact_id
    if owner:
        query["$or"] = [{"owner": owner}, {"owner_id": owner}]
    if stage:
        query["stage"] = stage
    if status:
        query["status"] = status
    elif resource == "accounts":
        # hide merged dupes AND soft-deleted rows by default
        query["status"] = {"$nin": ["merged", "deleted"]}
    else:
        # Soft-deleted docs stay in the collection so they keep anchoring
        # historical activities (TOR-18), but they must not appear in lists.
        query["status"] = {"$ne": "deleted"}
    if unread is not None and resource == "notifications":
        query["read"] = not unread
    if linked_object_type:
        query["linked_object_type"] = linked_object_type
    if linked_object_id:
        query["linked_object_id"] = linked_object_id
    if q:
        rx = {"$regex": _re.escape(q), "$options": "i"}
        text_or = [{"name": rx}, {"title": rx}, {"email": rx}, {"company": rx}]
        if "$or" in query:
            query = {"$and": [{"$or": query.pop("$or")}, {**query, "$or": text_or}]}
        else:
            query["$or"] = text_or
    return query


@router.get("/{resource}/export.csv")
def export_resource_csv(resource: str,
                              limit: int = Query(100000, ge=1, le=1000000),
                              _user: str = Depends(require_read)):
    """
    Export a canonical collection as CSV (flat top-level fields).

    Genuinely streamed (TOR-20): the previous version materialised every
    document AND the entire rendered file as one string before handing it to
    StreamingResponse, so a large export was a single unbounded allocation
    that also blocked the event loop for its duration.

    The header needs a stable column set, so a bounded first pass samples the
    field names; rows are then streamed straight off the cursor.
    """
    import csv
    import io as _io
    import re as _re
    from fastapi.responses import StreamingResponse
    _check_resource(resource)

    preferred = ["_id", "name", "title", "email", "company", "stage", "status",
                 "amount", "owner", "account_id", "contact_id", "created_at"]

    # Header discovery: sample rather than scan. Documents in a canonical
    # collection are homogeneous enough that 500 rows settle the columns.
    keys: list = []
    for d in crm_service.list_docs(resource, limit=500):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                continue
            if k not in keys:
                keys.append(k)
    keys.sort(key=lambda k: preferred.index(k) if k in preferred else 999)

    def _rows():
        buf = _io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0), buf.truncate(0)

        CHUNK = 1000
        sent = 0
        while sent < limit:
            batch = crm_service.list_docs(
                resource, limit=min(CHUNK, limit - sent), skip=sent)
            if not batch:
                break
            for d in batch:
                writer.writerow({k: v for k, v in d.items()
                                 if not isinstance(v, (dict, list))})
            yield buf.getvalue()
            buf.seek(0), buf.truncate(0)
            sent += len(batch)
            if len(batch) < CHUNK:
                break

    fname = _re.sub(r"[^A-Za-z0-9_-]", "", resource) or "export"
    return StreamingResponse(
        _rows(), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=crm_{fname}.csv"})


@router.get("/{resource}")
def list_resource(
    resource: str,
    limit: int = Query(200, le=1000),
    skip: int = Query(0, ge=0),
    account_id: Optional[str] = Query(None),
    contact_id: Optional[str] = Query(None),
    owner: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    unread: Optional[bool] = Query(None),
    linked_object_type: Optional[str] = Query(None),
    linked_object_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    _user: str = Depends(require_read),
):
    _check_resource(resource)
    query = _build_list_query(resource, account_id, contact_id, owner, stage,
                              status, unread, linked_object_type,
                              linked_object_id, q)
    return crm_service.list_docs(resource, query=query, limit=limit, skip=skip)


@router.post("/{resource}")
def create_resource(
    resource: str,
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_write),
):
    _check_resource(resource)
    model = _MODELS.get(resource)
    try:
        # Validate + coerce against the canonical schema, dropping unset fields.
        data = model(**payload).model_dump(exclude_none=True) if model else payload
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    return crm_service.create(resource, data)


@router.get("/{resource}/{doc_id}")
def get_resource(resource: str, doc_id: str, _user: str = Depends(require_read)):
    _check_resource(resource)
    try:
        doc = crm_service.get(resource, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return doc


@router.put("/{resource}/{doc_id}")
def update_resource(
    resource: str,
    doc_id: str,
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_write),
):
    _check_resource(resource)
    try:
        doc = crm_service.update(resource, doc_id, payload,
                                 changed_by=str(_user) if _user else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not doc:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return doc


@router.delete("/{resource}/{doc_id}")
def delete_resource(resource: str, doc_id: str, _user: str = Depends(require_write)):
    """Soft delete: the row is flagged and hidden, not removed (TOR-18)."""
    _check_resource(resource)
    try:
        ok = crm_service.delete(resource, doc_id,
                                changed_by=str(_user) if _user else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return {"message": "deleted", "soft": True}


@router.post("/{resource}/{doc_id}/purge")
def purge_resource(resource: str, doc_id: str,
                         _user: str = Depends(require_approve)):
    """
    Permanently remove a document and clear references to it.

    Deliberately separate from DELETE and behind the stronger 'approve'
    capability: this is the operation that cannot be undone.
    """
    _check_resource(resource)
    try:
        result = crm_service.purge(resource, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    return result
