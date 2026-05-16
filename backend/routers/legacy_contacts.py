"""
Legacy Contacts Routes
======================
Contacts (qualified leads with stages) CRUD — POST, GET all, PUT, DELETE,
bulk-delete. Auto-syncs company data to finance_db.customers.
Extracted from main.py to keep the app entry-point lean.
"""

import logging
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, Depends, HTTPException

try:
    from .session_state import verify_session
except ImportError:
    from session_state import verify_session

try:
    from .database import get_client, get_database
except ImportError:
    from database import get_client, get_database

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

        contact_data["stage"] = contact_data.get("stage", "RFQ")
        contact_data["createdAt"] = datetime.utcnow()
        contact_data["updatedAt"] = datetime.utcnow()

        linked_customer_id = None
        if contact_data.get("companyName"):
            customers_col = _customers()
            existing_customer = customers_col.find_one({"company_name": contact_data["companyName"]})
            if existing_customer:
                linked_customer_id = str(existing_customer["_id"])
                update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
                if contact_data.get("companyEmail"):
                    update_fields["email"] = contact_data["companyEmail"]
                if contact_data.get("companyHeadquarters"):
                    update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
                    update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
                customers_col.update_one({"_id": existing_customer["_id"]}, {"$set": update_fields})
            else:
                customer_data = {
                    "name": contact_data["companyName"],
                    "customer_type": "business",
                    "company_name": contact_data["companyName"],
                    "email": contact_data.get("companyEmail", ""),
                    "phone": "",
                    "gst_treatment": "unregistered",
                    "gstin": "",
                    "pan": "",
                    "billing_address": {
                        "line1": contact_data.get("companyHeadquarters", ""),
                        "line2": "",
                        "city": "",
                        "state": "",
                        "pincode": "",
                        "country": "India",
                    },
                    "shipping_address": {
                        "line1": contact_data.get("companyHeadquarters", ""),
                        "line2": "",
                        "city": "",
                        "state": "",
                        "pincode": "",
                        "country": "India",
                    },
                    "same_as_billing": True,
                    "payment_terms": 30,
                    "credit_limit": 0,
                    "currency": "INR",
                    "opening_balance": 0,
                    "notes": "",
                    "status": "active",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
                result_customer = customers_col.insert_one(customer_data)
                linked_customer_id = str(result_customer.inserted_id)

        contact_data["linked_customer_id"] = linked_customer_id
        result = _contacts().insert_one(contact_data)
        contact_data["_id"] = str(result.inserted_id)
        return {"message": "Contact created successfully", "contact": contact_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Contact creation error: {str(e)}")


@router.get("/contacts/", dependencies=[Depends(verify_session)])
async def get_contacts():
    try:
        contacts = list(_contacts().find())
        all_customers = {str(c["_id"]): c for c in _customers().find()}

        for contact in contacts:
            contact["_id"] = str(contact["_id"])
            for date_field in ["createdAt", "updatedAt", "movedFromLeadAt", "addedOn"]:
                if date_field in contact:
                    contact[date_field] = contact[date_field].isoformat() if isinstance(contact[date_field], datetime) else str(contact[date_field])

            linked_customer_id = contact.get("linked_customer_id")
            if linked_customer_id and linked_customer_id in all_customers:
                customer = all_customers[linked_customer_id]
                contact["linked_customer"] = {
                    "_id": str(customer["_id"]),
                    "name": customer.get("name", ""),
                    "company_name": customer.get("company_name", ""),
                    "email": customer.get("email", ""),
                    "status": customer.get("status", "active"),
                }
            elif contact.get("companyName"):
                for cid, customer in all_customers.items():
                    if customer.get("company_name") == contact["companyName"]:
                        contact["linked_customer_id"] = cid
                        contact["linked_customer"] = {
                            "_id": cid,
                            "name": customer.get("name", ""),
                            "company_name": customer.get("company_name", ""),
                            "email": customer.get("email", ""),
                            "status": customer.get("status", "active"),
                        }
                        _contacts().update_one(
                            {"_id": ObjectId(contact["_id"])},
                            {"$set": {"linked_customer_id": cid}},
                        )
                        break

        return {"contacts": contacts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch contacts error: {str(e)}")


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, contact_data: Dict[str, Any] = Body(...)):
    try:
        contact_data = {k: v for k, v in contact_data.items() if k not in ["_id", "createdAt", "movedFromLeadAt"]}
        if "email" in contact_data and (not contact_data["email"] or not contact_data["email"].strip()):
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        contact_data["updatedAt"] = datetime.utcnow()
        result = _contacts().update_one({"_id": ObjectId(contact_id)}, {"$set": contact_data})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Contact not found")

        if contact_data.get("companyName"):
            customers_col = _customers()
            existing_customer = customers_col.find_one({"company_name": contact_data["companyName"]})
            if existing_customer:
                linked_customer_id = str(existing_customer["_id"])
                update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
                if contact_data.get("companyEmail"):
                    update_fields["email"] = contact_data["companyEmail"]
                if contact_data.get("companyHeadquarters"):
                    update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
                    update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
                customers_col.update_one({"_id": existing_customer["_id"]}, {"$set": update_fields})
                _contacts().update_one({"_id": ObjectId(contact_id)}, {"$set": {"linked_customer_id": linked_customer_id}})

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
