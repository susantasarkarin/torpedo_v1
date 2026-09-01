"""
Legacy Contacts Routes
======================
Contacts (qualified leads with stages) CRUD — POST, GET all, PUT, DELETE,
bulk-delete. Auto-syncs company data to finance_db.customers.
Extracted from main.py to keep the app entry-point lean.
"""

import logging
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

from session_state import verify_session

from database import get_client, get_database

from services import contact_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-contacts"])

# ---------------------------------------------------------------------------
# Lazy accessors
# ---------------------------------------------------------------------------
_db = None
_finance_db = None


def _get_db():
    global _db
    if _db is None:
        _db = get_database("email_automation")
    return _db


def _get_finance_db():
    global _finance_db
    if _finance_db is None:
        client = get_client()
        _finance_db = client["finance_db"]
    return _finance_db


def _contacts():
    return _get_db()["contacts"]


def _customers():
    return _get_finance_db()["customers"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/contacts/")
async def create_contact(contact_data: Dict[str, Any] = Body(...)):
    try:
        if not contact_data.get("email") or not contact_data["email"].strip():
            raise HTTPException(status_code=400, detail="Email is required")
        result = contact_service.create_contact(contact_data, _contacts(), _customers())
        return {"message": "Contact created successfully", "contact": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact creation error: {str(e)}")


@router.get("/contacts/", dependencies=[Depends(verify_session)])
async def get_contacts():
    try:
        contacts = contact_service.get_all_contacts(_contacts(), _customers())
        return {"contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, contact_data: Dict[str, Any] = Body(...)):
    try:
        contact_data = {k: v for k, v in contact_data.items() if k not in ["_id", "createdAt", "movedFromLeadAt"]}
        if "email" in contact_data and (not contact_data["email"] or not contact_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        matched = contact_service.update_contact(contact_id, contact_data, _contacts(), _customers())
        if matched == 0:
            raise HTTPException(status_code=404, detail="Contact not found")
        return {"message": "Contact updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact update error: {str(e)}")


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    try:
        result = _contacts().delete_one({"_id": ObjectId(contact_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Contact not found")
        return {"message": "Contact deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact delete error: {str(e)}")


@router.post("/contacts/bulk-delete")
async def bulk_delete_contacts(data: Dict[str, Any] = Body(...)):
    try:
        ids = data.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        object_ids = [ObjectId(id) for id in ids]
        result = _contacts().delete_many({"_id": {"$in": object_ids}})
        return {"message": f"Successfully deleted {result.deleted_count} contacts", "deleted_count": result.deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete error: {str(e)}")
