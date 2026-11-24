"""Marketing > Newsletter (marketing/newsletter.py).

router         signed-in users: create / edit / preview / audience / test send; approving (send now or
               schedule) needs the approve capability. Every state change is audit-logged.
public_router  what recipients hit: the unsubscribe page, the RFC 8058 one-click target, and images
               picked from the media library (served by their unguessable stored name, images only).
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.security import require
from marketing import newsletter as N
from marketing.schema import stamp, utcnow
from session_state import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketing/newsletter", tags=["Marketing"])
public_router = APIRouter(prefix="/api/marketing/newsletter", tags=["Marketing (public)"])
require_approve = require("approve")


def _gd(name):
    from database import get_database
    return get_database(name)


def _col():
    return _gd(N.DB)[N.NEWSLETTERS]


def _out(d: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(d)
    d["_id"] = str(d["_id"])
    return d


def _get(nl_id: str) -> Dict[str, Any]:
    nl = _col().find_one({"_id": ObjectId(nl_id)}) if ObjectId.is_valid(nl_id) else None
    if not nl:
        raise HTTPException(404, "newsletter not found")
    return nl


def _audit(user: str, nl_id: str, reason: str) -> None:
    try:
        from platform_core.audit import log_action
        log_action(actor=user, action="update", entity_type="newsletter", entity_id=nl_id, reason=reason,
                   source="marketing_newsletter")
    except Exception:
        pass


def _bad(e: ValueError):
    raise HTTPException(400, str(e))


# ------------------------------------------------------------------------------------- reference data
@router.get("/meta")
async def meta(user: str = Depends(verify_session)):
    cfg = N._cfg()
    boxes = N.mailboxes(_gd)
    today = utcnow()
    for m in boxes:
        m["sent_today"] = N.sent_today(_gd, m["email"], today)
    return {"brands": {bu: N.brand(bu, cfg) for bu in N.BRANDS}, "sources": N.SOURCES, "block_types": N.BLOCK_TYPES,
            "tokens": N.TOKENS, "mailboxes": boxes, "limits": {k: cfg.get(k) for k in ("daily_cap_per_mailbox",
                                                                                     "per_tick_per_mailbox")},
            "send_blocker": N.send_blocker()}


# ------------------------------------------------------------------------------------- newsletters
@router.get("")
async def list_newsletters(status: Optional[str] = None, user: str = Depends(verify_session)):
    q = {"status": status} if status in N.STATUSES else {}
    rows = []
    for d in _col().find(q, {"blocks": 0, "history": 0}).sort("updated_at", -1).limit(200):
        d = _out(d)
        if d.get("status") in ("sending", "paused", "sent", "cancelled"):
            d["stats"] = N.stats(_gd, ObjectId(d["_id"]))
        rows.append(d)
    return {"newsletters": rows}


@router.post("")
async def create(body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    try:
        doc = N.clean(body)
    except ValueError as e:
        _bad(e)
    doc.setdefault("blocks", [])
    doc.setdefault("bus", [])
    doc.setdefault("senders", {})
    doc.setdefault("audience", {})
    doc.update(status="draft", created_by=user, history=[{"at": utcnow(), "by": user, "action": "created"}])
    doc = stamp(doc, bu=None, source="newsletter")
    doc["_id"] = _col().insert_one(doc).inserted_id
    _audit(user, str(doc["_id"]), "created")
    return _out(doc)


@router.get("/{nl_id}")
async def get_one(nl_id: str, user: str = Depends(verify_session)):
    nl = _get(nl_id)
    out = _out(nl)
    out["problems"] = N.problems(nl, _gd)
    out["test_is_current"] = bool((nl.get("test") or {}).get("ok")) and nl["test"].get("hash") == N.design_hash(nl)
    if nl["status"] not in ("draft", "scheduled"):
        out["stats"] = N.stats(_gd, nl["_id"])
    return out


@router.put("/{nl_id}")
async def edit(nl_id: str, body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    nl = _get(nl_id)
    if nl["status"] not in N.EDITABLE:
        raise HTTPException(400, f"a {nl['status']} newsletter can no longer be edited; duplicate it instead")
    try:
        upd = N.clean(body, partial=True)
    except ValueError as e:
        _bad(e)
    upd["updated_at"] = utcnow()
    push = None
    if nl["status"] == "scheduled":                       # a change needs a new test and a new approval
        upd["status"] = "draft"
        push = {"history": {"at": upd["updated_at"], "by": user, "action": "edited while scheduled: back to draft"}}
    _col().update_one({"_id": nl["_id"]}, {"$set": upd, **({"$push": push} if push else {})})
    return await get_one(nl_id, user)


@router.delete("/{nl_id}")
async def delete(nl_id: str, user: str = Depends(verify_session)):
    nl = _get(nl_id)
    if nl["status"] != "draft":
        raise HTTPException(400, "only drafts can be deleted; cancel it instead")
    _col().delete_one({"_id": nl["_id"]})
    _audit(user, nl_id, "deleted")
    return {"ok": True}


@router.post("/{nl_id}/duplicate")
async def duplicate(nl_id: str, user: str = Depends(verify_session)):
    nl = _get(nl_id)
    body = {k: nl.get(k) for k in ("subject", "preheader", "blocks", "bus", "senders", "audience")}
    body["name"] = f"{nl.get('name') or 'Newsletter'} (copy)"
    return await create(body, user)


@router.post("/{nl_id}/preview")
async def preview(nl_id: str, bu: str = Query(...), body: Dict[str, Any] = Body(default={}),
                  user: str = Depends(verify_session)):
    """Render one BU's edition. The body may carry unsaved edits (subject / preheader / blocks) to preview live."""
    if bu not in N.BRANDS:
        raise HTTPException(400, "unknown business unit")
    nl = _get(nl_id)
    try:
        nl = {**nl, **N.clean({k: body[k] for k in ("subject", "preheader", "blocks") if k in body}, partial=True)}
    except ValueError as e:
        _bad(e)
    subject, html, _ = N.render(nl, bu, {"first_name": "Priya", "name": "Priya Sharma", "company": "Acme Insights"})
    return {"subject": subject, "html": html}


@router.get("/{nl_id}/audience")
async def audience(nl_id: str, bu: str = Query(...), sample: int = Query(25, ge=0, le=500),
                   user: str = Depends(verify_session)):
    if bu not in N.BRANDS:
        raise HTTPException(400, "unknown business unit")
    a = N.audience(_gd, _get(nl_id), bu)
    a["sample"] = sorted(a.pop("recipients"), key=lambda r: r["email"])[:sample]
    return a


@router.post("/{nl_id}/test")
async def test_send(nl_id: str, body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    nl = _get(nl_id)
    if nl["status"] != "draft":
        raise HTTPException(400, "test sends are for drafts")
    try:
        out = N.send_test(_gd, nl, body.get("to") or [], actor=user, sender=N.workspace_sender())
    except ValueError as e:
        _bad(e)
    _audit(user, nl_id, f"test sent to {', '.join(body.get('to') or [])}: {'ok' if out['ok'] else 'failed'}")
    return out


@router.post("/{nl_id}/approve")
async def approve(nl_id: str, body: Dict[str, Any] = Body(default={}), user: str = Depends(require_approve)):
    """Send now (no scheduled_for) or at scheduled_for (ISO, UTC unless it carries an offset)."""
    nl = _get(nl_id)
    when = None
    if body.get("scheduled_for"):
        try:
            when = datetime.fromisoformat(str(body["scheduled_for"]).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "scheduled_for must be an ISO date-time")
        if when.tzinfo is not None:
            from datetime import timezone
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        N.approve(_gd, nl, actor=user, when=when)
    except ValueError as e:
        _bad(e)
    _audit(user, nl_id, f"approved, sending from {(when or utcnow()):%Y-%m-%d %H:%M} UTC")
    return await get_one(nl_id, user)


@router.post("/{nl_id}/status/{action}")
async def change_status(nl_id: str, action: str, user: str = Depends(verify_session)):
    if action not in ("pause", "resume", "cancel", "unschedule"):
        raise HTTPException(404, "unknown action")
    try:
        to = N.set_status(_gd, _get(nl_id), action, actor=user)
    except ValueError as e:
        _bad(e)
    _audit(user, nl_id, f"{action} -> {to}")
    return await get_one(nl_id, user)


@router.get("/{nl_id}/recipients")
async def recipients(nl_id: str, bu: Optional[str] = None, status: Optional[str] = None,
                     limit: int = Query(200, ge=1, le=1000), user: str = Depends(verify_session)):
    nl = _get(nl_id)
    q: Dict[str, Any] = {"newsletter_id": nl["_id"]}
    if bu:
        q["bu"] = bu
    if status:
        q["status"] = status
    rows = [_out({k: r.get(k) for k in ("_id", "bu", "email", "name", "company", "status", "mailbox", "sent_at",
                                         "error", "reason", "sources")})
            for r in _gd(N.DB)[N.RECIPIENTS].find(q).sort("email", 1).limit(limit)]
    return {"recipients": rows, "stats": N.stats(_gd, nl["_id"])}


# ------------------------------------------------------------------------------------- mailbox contacts
@router.get("/contacts/list")
async def contacts(search: Optional[str] = None, bu: Optional[str] = None, limit: int = Query(100, ge=1, le=1000),
                   user: str = Depends(verify_session)):
    import re
    q: Dict[str, Any] = {}
    if bu in N.BRANDS:
        q["bus"] = bu
    if search:
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        q["$or"] = [{"email": rx}, {"name": rx}]
    ea = _gd(N.DB)
    rows = [_out(c) for c in ea[N.CONTACTS].find(q).sort("last_seen", -1).limit(limit)]
    m = ea[N.META].find_one({"_id": "harvest"}) or {}
    return {"contacts": rows, "total": ea[N.CONTACTS].count_documents(q),
            "harvest": {"ran_at": m.get("ran_at"), "running": bool(m.get("running"))}}


def _harvest_job():
    ea = _gd(N.DB)
    try:
        logger.info("[newsletter] harvest %s", N.harvest(_gd))
    except Exception as e:
        logger.error("[newsletter] harvest failed: %s", e)
    finally:
        ea[N.META].update_one({"_id": "harvest"}, {"$set": {"running": False}}, upsert=True)


@router.post("/contacts/harvest")
async def harvest(tasks: BackgroundTasks, user: str = Depends(verify_session)):
    """Pick up external addresses from mail synced since the last run (runs in the background)."""
    ea = _gd(N.DB)
    m = ea[N.META].find_one({"_id": "harvest"}) or {}
    if m.get("running") and m.get("started_at") and (utcnow() - m["started_at"]).total_seconds() < 3600:
        return {"started": False, "detail": "already running"}
    ea[N.META].update_one({"_id": "harvest"}, {"$set": {"running": True, "started_at": utcnow()}}, upsert=True)
    tasks.add_task(_harvest_job)
    return {"started": True}


# ------------------------------------------------------------------------------------- public
_UNSUB_PAGE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Unsubscribed</title><div style=\"font:16px/1.6 Arial,sans-serif;max-width:32rem;margin:12vh auto;"
    "padding:0 1.25rem;color:#1a1a1a\"><h1 style='font-size:1.35rem;margin:0 0 .75rem'>You've been unsubscribed</h1>"
    "<p style='margin:0;color:#555'>You won't receive our newsletters or other emails again. Nothing else is needed "
    "from you.</p></div>"
)


def _optout(token: str, source: str) -> None:
    from services.outreach_unsubscribe import read_token, record_optout
    email = read_token(token)
    if email:
        record_optout(email, source=source)


@public_router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(token: str):
    """Acts on GET, like the outreach link: a confirm step loses real opt-outs. Same page whatever the token."""
    try:
        _optout(token, "newsletter_link")
    except Exception as e:
        logger.error("[newsletter-unsub] %s", e)
    return HTMLResponse(_UNSUB_PAGE)


@public_router.post("/unsubscribe/{token}/one-click")
async def unsubscribe_one_click(token: str):
    """RFC 8058 target. Always 200: a non-200 makes the mailbox provider treat our unsubscribe as broken."""
    try:
        _optout(token, "newsletter_one_click")
    except Exception as e:
        logger.error("[newsletter-unsub] one-click: %s", e)
    return {"status": "unsubscribed"}


@public_router.get("/img/{stored_name}")
async def image(stored_name: str):
    m = _gd("marketing_db")["media"].find_one({"stored_name": stored_name})
    if not m or not str(m.get("mime_type") or "").startswith("image/") or not os.path.isfile(m.get("path") or ""):
        return Response(status_code=404)
    return FileResponse(m["path"], media_type=m["mime_type"], headers={"Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff",
                                  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})
