"""Marketing > Content: calendar, drafts, review, brand voice, UTM links (MARKETING_PLAN 3.6, 3.5.4).

Reads need a session; approving / scheduling content and approving a brand voice
need the approve capability. Every change is logged on the item and audit-logged.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.security import require
from marketing import content as C, schema
from session_state import verify_session

router = APIRouter(prefix="/api/marketing/content", tags=["Marketing"])
require_approve = require("approve")


def _ea():
    from database import get_database
    return get_database(schema.DB)


def _gd(name):
    from database import get_database
    return get_database(name)


def _out(d):
    d["_id"] = str(d["_id"])
    return d


def _audit(user, item_id, reason):
    try:
        from platform_core.audit import log_action
        log_action(actor=user, action="update", entity_type="content_item", entity_id=item_id, reason=reason, source="marketing_content")
    except Exception:
        pass


@router.get("")
async def list_items(bu: Optional[str] = None, channel: Optional[str] = None, status: Optional[str] = None,
                     weeks: int = Query(6, ge=1, le=26), user: str = Depends(verify_session)) -> Dict[str, Any]:
    q: Dict[str, Any] = {}
    if bu:
        q["bu"] = bu
    if channel:
        q["channel"] = channel
    if status:
        q["status"] = status
    rows = [_out(r) for r in _ea()["content_items"].find(q).sort("updated_at", -1).limit(500)]
    horizon = datetime.utcnow() + timedelta(weeks=weeks)
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"items": [r for r in rows if not r.get("scheduled_for") or r["scheduled_for"] <= horizon], "counts": counts,
            "channels": list(C.CHANNELS), "flow": {k: sorted(v) for k, v in C.FLOW.items()}}


@router.post("")
async def create_item(body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    if body.get("bu") not in schema.BUS or body.get("channel") not in C.CHANNELS:
        raise HTTPException(400, f"bu must be one of {schema.BUS}, channel one of {C.CHANNELS}")
    doc = {k: body.get(k) for k in ("title", "topic", "body", "channel", "link", "utm_content")}
    doc.update(status="draft" if (body.get("body") or "").strip() else "idea", history=[], created_by=user)
    if body.get("scheduled_for"):
        doc["scheduled_for"] = datetime.fromisoformat(str(body["scheduled_for"]).replace("Z", "+00:00")).replace(tzinfo=None)
    doc = schema.stamp(doc, bu=body["bu"], source="content_calendar")
    doc["claim_problems"] = C.claims_for(_gd, doc)
    doc["_id"] = _ea()["content_items"].insert_one(doc).inserted_id
    _audit(user, str(doc["_id"]), "created")
    return _out(doc)


@router.put("/{item_id}")
async def edit_item(item_id: str, body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    col = _ea()["content_items"]
    it = col.find_one({"_id": ObjectId(item_id)}) if ObjectId.is_valid(item_id) else None
    if not it:
        raise HTTPException(404, "not found")
    if it["status"] in ("approved", "scheduled", "published"):
        raise HTTPException(400, "approved content is locked: move it back to draft first")
    upd = {k: body[k] for k in ("title", "topic", "body", "link", "utm_content", "hashtags") if k in body}
    if "scheduled_for" in body:
        upd["scheduled_for"] = (datetime.fromisoformat(str(body["scheduled_for"]).replace("Z", "+00:00")).replace(tzinfo=None)
                                if body["scheduled_for"] else None)
    merged = {**it, **upd}
    upd["claim_problems"] = C.claims_for(_gd, merged)
    if it["status"] == "idea" and (merged.get("body") or "").strip():
        upd["status"] = "draft"
    upd["updated_at"] = datetime.utcnow()
    col.update_one({"_id": it["_id"]}, {"$set": upd})
    _audit(user, item_id, "edited")
    return _out(col.find_one({"_id": it["_id"]}))


def _move(item_id, to, user):
    col = _ea()["content_items"]
    it = col.find_one({"_id": ObjectId(item_id)}) if ObjectId.is_valid(item_id) else None
    if not it:
        raise HTTPException(404, "not found")
    it["claim_problems"] = C.claims_for(_gd, it)
    try:
        upd = C.transition(it, to, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    upd["claim_problems"] = it["claim_problems"]
    col.update_one({"_id": it["_id"]}, {"$set": upd})
    _audit(user, item_id, f"{it['status']} -> {to}")
    return _out(col.find_one({"_id": it["_id"]}))


@router.post("/{item_id}/move/{to}")
async def move_item(item_id: str, to: str, user: str = Depends(verify_session)):
    if to in ("approved", "scheduled"):
        raise HTTPException(403, "approving / scheduling needs the approve endpoint")
    return _move(item_id, to, user)


@router.post("/{item_id}/approve")
async def approve_item(item_id: str, schedule: bool = False, user: str = Depends(require_approve)):
    out = _move(item_id, "approved", user)
    return _move(item_id, "scheduled", user) if schedule else out


@router.post("/{item_id}/draft")
async def draft_item(item_id: str, user: str = Depends(verify_session)):
    """Ask Qwen for a draft now (P3 lane: outside 22:00-07:00 IST the gateway defers it)."""
    col = _ea()["content_items"]
    it = col.find_one({"_id": ObjectId(item_id)}) if ObjectId.is_valid(item_id) else None
    if not it:
        raise HTTPException(404, "not found")
    upd = C.draft(it, _gd)
    if upd.get("body"):
        upd["claim_problems"] = C.claims_for(_gd, {**it, **upd})
        if it["status"] == "idea":
            upd["status"] = "draft"
    col.update_one({"_id": it["_id"]}, {"$set": upd})
    return _out(col.find_one({"_id": it["_id"]}))


@router.get("/brand-voice")
async def brand_voice(user: str = Depends(verify_session)):
    C.seed_brand_voice()
    return {"voices": [_out(v) for v in _ea()["brand_voice"].find({})]}


@router.put("/brand-voice/{bu}")
async def save_brand_voice(bu: str, body: Dict[str, Any] = Body(...), user: str = Depends(require_approve)):
    if bu not in schema.BUS:
        raise HTTPException(404, bu)
    upd = {k: body[k] for k in ("voice", "tone", "do", "dont", "banned_claims") if k in body}
    upd.update(status="approved" if body.get("approve") else "proposed", updated_at=datetime.utcnow(), updated_by=user)
    _ea()["brand_voice"].update_one({"bu": bu}, {"$set": upd}, upsert=True)
    _audit(user, f"brand_voice:{bu}", f"saved ({upd['status']})")
    return _out(_ea()["brand_voice"].find_one({"bu": bu}))


@router.post("/check")
async def check(body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    return {"problems": C.claims_for(_gd, body)}


@router.post("/utm-link")
async def utm(body: Dict[str, Any] = Body(...), user: str = Depends(verify_session)):
    if not body.get("url") or body.get("bu") not in schema.BUS:
        raise HTTPException(400, "url and bu required")
    return {"url": C.utm_link(body["url"], bu=body["bu"], channel=body.get("channel") or "quora",
                              campaign=body.get("campaign") or "answers", content=body.get("content"))}


@router.get("/performance")
async def perf(days: int = Query(90, ge=7, le=365), user: str = Depends(verify_session)):
    return {"items": C.performance(_gd, days=days)}
