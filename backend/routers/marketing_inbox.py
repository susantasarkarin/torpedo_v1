"""Marketing > Inbox (MARKETING_PLAN 3.7, 6.3): every inbound message across channels, with SLA."""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from marketing import inbox as I, schema
from session_state import verify_session

router = APIRouter(prefix="/api/marketing/inbox", tags=["Marketing"])


def _ea():
    from database import get_database
    return get_database(schema.DB)


@router.get("")
async def list_inbox(status: Optional[str] = "open", channel: Optional[str] = None, bu: Optional[str] = None,
                     limit: int = Query(200, le=1000), user: str = Depends(verify_session)) -> Dict[str, Any]:
    now = datetime.utcnow()
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if channel:
        q["channel"] = channel
    if bu:
        q["bu"] = bu
    rows = []
    for r in _ea()["inbox_items"].find(q).sort("due_at", 1).limit(limit):
        r["_id"] = str(r["_id"])
        r["breached"] = bool(r.get("status") == "open" and r.get("due_at") and r["due_at"] < now)
        rows.append(r)
    return {"items": rows, "channels": list(I.CHANNELS), "stats": stats(30)}


def stats(days: int = 30) -> Dict[str, Any]:
    """Response time vs SLA per channel (6.1 overview tile 6)."""
    since = datetime.utcnow() - timedelta(days=days)
    out: Dict[str, Dict[str, Any]] = {}
    for r in _ea()["inbox_items"].find({"at": {"$gte": since}, "status": {"$ne": "spam"}}):
        o = out.setdefault(r["channel"], {"received": 0, "replied": 0, "met": 0, "open_breached": 0, "minutes": []})
        o["received"] += 1
        if r.get("status") == "replied":
            o["replied"] += 1
            o["met"] += 1 if r.get("sla_met") else 0
            if r.get("response_minutes") is not None:
                o["minutes"].append(r["response_minutes"])
        elif r.get("status") == "open" and r.get("due_at") and r["due_at"] < datetime.utcnow():
            o["open_breached"] += 1
    for o in out.values():
        m = sorted(o.pop("minutes"))
        o["median_response_minutes"] = m[len(m) // 2] if m else None
        o["sla_met_pct"] = round(100 * o["met"] / o["replied"], 1) if o["replied"] else None
    return out


@router.post("/{item_id}/{action}")
async def act(item_id: str, action: str, user: str = Depends(verify_session)):
    if action not in ("replied", "close", "spam", "reopen") or not ObjectId.is_valid(item_id):
        raise HTTPException(400, "action must be replied | close | spam | reopen")
    from database import get_database
    if action == "replied":
        I.mark_replied(get_database, item_id, by=user)
    else:
        _ea()["inbox_items"].update_one({"_id": ObjectId(item_id)}, {"$set": {
            "status": {"close": "closed", "spam": "spam", "reopen": "open"}[action], "updated_at": datetime.utcnow(), "updated_by": user}})
    try:
        from platform_core.audit import log_action
        log_action(actor=user, action="update", entity_type="inbox_item", entity_id=item_id, reason=action, source="marketing_inbox")
    except Exception:
        pass
    r = _ea()["inbox_items"].find_one({"_id": ObjectId(item_id)})
    r["_id"] = str(r["_id"])
    return r


@router.get("/weekly-report")
async def weekly_report(rebuild: bool = False, user: str = Depends(verify_session)):
    """Latest weekly report (6.4); rebuild=true builds the last full week now."""
    from marketing import report
    if rebuild:
        r = report.build()
    else:
        r = _ea()["marketing_reports"].find_one({}, sort=[("week_start", -1)]) or report.build()
    r.pop("_id", None)
    return r
