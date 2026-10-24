"""Service Delivery API (CRM plan 3.13): projects, milestones, status, sign-off."""
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

from app.security import require
from service_delivery import rules

router = APIRouter(prefix="/api/service-delivery", tags=["service-delivery"])
require_read = require("read")
require_write = require("write")


def _col():
    from database import get_database
    return get_database("crm_db")["service_projects"]


def _out(p: Dict[str, Any]) -> Dict[str, Any]:
    return {**p, "_id": str(p["_id"])}


def _get(pid: str) -> Dict[str, Any]:
    try:
        p = _col().find_one({"_id": ObjectId(pid)})
    except Exception:
        p = None
    if not p:
        raise HTTPException(404, "service project not found")
    return p


def _audit(user, pid, reason, changes=None):
    from platform_core.audit import log_action
    log_action(actor=user, action="update", entity_type="service_project", entity_id=pid, reason=reason,
               changes=changes, source="service_delivery")


@router.get("/projects")
def list_projects(status: str = None, bu: str = None, _user: str = Depends(require_read)):
    q = {k: v for k, v in (("status", status), ("bu", bu)) if v}
    return {"projects": [_out(p) for p in _col().find(q).sort("updated_at", -1).limit(500)]}


@router.get("/projects/{pid}")
def get_project(pid: str, _user: str = Depends(require_read)):
    return _out(_get(pid))


@router.post("/projects")
def create_project(body: Dict[str, Any] = Body(...), user: str = Depends(require_write)):
    now = datetime.utcnow()
    try:
        p = rules.new_project(bu=body.get("bu"), account_id=body.get("account_id"), contact_id=body.get("contact_id"),
                              title=body.get("title") or "Service project", scope=body.get("scope") or "",
                              deliverables=body.get("deliverables") or [], value=float(body.get("value") or 0),
                              currency=body.get("currency") or "INR",
                              start=datetime.fromisoformat(body["start"]) if body.get("start") else now,
                              end=datetime.fromisoformat(body["end"]) if body.get("end") else now,
                              owner=body.get("owner"), opportunity_id=body.get("opportunity_id") or "", now=now)
    except (rules.SDError, ValueError) as e:
        raise HTTPException(400, str(e))
    if body.get("opportunity_id") and _col().find_one({"opportunity_id": body["opportunity_id"]}, {"_id": 1}):
        raise HTTPException(409, "a service project already exists for this RFQ")
    pid = str(_col().insert_one(p).inserted_id)
    _audit(user, pid, "service project created")
    return {"_id": pid}


@router.put("/projects/{pid}/milestones")
def set_milestones(pid: str, body: Dict[str, Any] = Body(...), user: str = Depends(require_write)):
    p = _get(pid)
    ms = body.get("milestones") or []
    for m in ms:
        if isinstance(m.get("due"), str):
            m["due"] = datetime.fromisoformat(m["due"])
    if any(m.get("signed_off_at") for m in p.get("milestones") or []):
        raise HTTPException(409, "milestones are fixed once one is signed off")
    probs = rules.validate_milestones(ms)
    if probs:
        raise HTTPException(400, "; ".join(probs))
    _col().update_one({"_id": p["_id"]}, {"$set": {"milestones": ms, "updated_at": datetime.utcnow()}})
    _audit(user, pid, "milestones set", {"count": len(ms)})
    return {"ok": True}


@router.post("/projects/{pid}/status")
def move_status(pid: str, body: Dict[str, Any] = Body(...), user: str = Depends(require_write)):
    p, to = _get(pid), body.get("to")
    try:
        rules.move(p, to)
    except rules.SDError as e:
        raise HTTPException(400, str(e))
    now = datetime.utcnow()
    _col().update_one({"_id": p["_id"]}, {"$set": {"status": to, "updated_at": now},
                                          "$push": {"history": {"from": p["status"], "to": to, "at": now, "by": user,
                                                                "reason": body.get("reason") or ""}}})
    _audit(user, pid, f"status {p['status']} -> {to}", {"status": {"from": p["status"], "to": to}})
    return {"ok": True}


@router.post("/projects/{pid}/milestones/{idx}/sign-off")
def sign_off(pid: str, idx: int, user: str = Depends(require_write)):
    p = _get(pid)
    if idx < 0 or idx >= len(p.get("milestones") or []):
        raise HTTPException(404, "milestone not found")
    try:
        res = rules.sign_off(p, idx, by=user, now=datetime.utcnow())
    except rules.SDError as e:
        raise HTTPException(409, str(e))
    upd = {"milestones": p["milestones"], "updated_at": datetime.utcnow()}
    if res["close_project"]:
        upd["status"] = "closed"
    _col().update_one({"_id": p["_id"]}, {"$set": upd})
    from platform_core import review_queue
    # Invoice is raised by Finance from this request (reviewed while finance is in shadow).
    review_queue.enqueue(type="invoice_request", module="service_delivery",
                         ref={"collection": "crm_db.service_projects", "id": f"{pid}:{idx}"},
                         reason="milestone signed off: raise its invoice", suggested=res["invoice"],
                         value_inr=res["invoice"]["amount"] if res["invoice"]["currency"] == "INR" else None)
    _audit(user, pid, f"milestone {idx} signed off", {"close_project": res["close_project"]})
    return res
