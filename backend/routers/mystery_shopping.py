from fastapi import APIRouter, Request, HTTPException, Body
from typing import Dict, Any
from datetime import datetime, timezone
from bson import ObjectId
import os
from motor.motor_asyncio import AsyncIOMotorClient

router = APIRouter(prefix="/api/mystery-shopping", tags=["Mystery Shopping"])

_MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
_client = AsyncIOMotorClient(_MONGO_URI)
_col = _client["operations_db"]["mystery_shopping_audits"]


def _serialize(doc):
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    return doc


def _require_auth(request: Request):
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/audits")
async def list_audits(request: Request):
    _require_auth(request)
    audits = []
    async for doc in _col.find().sort("created_at", -1).limit(500):
        audits.append(_serialize(doc))
    return audits


@router.post("/audits")
async def create_audit(request: Request, payload: Dict[str, Any] = Body(...)):
    _require_auth(request)
    now = datetime.now(timezone.utc).isoformat()
    doc = {**payload, "status": payload.get("status", "draft"), "created_at": now, "updated_at": now}
    result = await _col.insert_one(doc)
    created = await _col.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.get("/audits/{audit_id}")
async def get_audit(audit_id: str, request: Request):
    _require_auth(request)
    try:
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.put("/audits/{audit_id}")
async def update_audit(audit_id: str, request: Request, payload: Dict[str, Any] = Body(...)):
    _require_auth(request)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await _col.update_one({"_id": ObjectId(audit_id)}, {"$set": payload})
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.delete("/audits/{audit_id}")
async def delete_audit(audit_id: str, request: Request):
    _require_auth(request)
    try:
        result = await _col.delete_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Audit not found")
    return {"ok": True}


# ── Public endpoints (no auth — accessed by field shoppers via live link) ─────

@router.get("/public/{audit_id}")
async def get_audit_public(audit_id: str):
    try:
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)


@router.put("/public/{audit_id}/submit")
async def field_submit(audit_id: str, payload: Dict[str, Any] = Body(...)):
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload.setdefault("status", "submitted")
    try:
        await _col.update_one({"_id": ObjectId(audit_id)}, {"$set": payload})
        doc = await _col.find_one({"_id": ObjectId(audit_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid audit ID")
    if not doc:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize(doc)
