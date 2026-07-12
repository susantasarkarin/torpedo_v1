"""
Unified Vendors Router
Provides a combined view of panel vendors (Operations) and billing vendors (Finance)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from bson import ObjectId
from datetime import datetime
from pymongo import MongoClient
from random import randint
import os

# Shared MongoDB serialization (ObjectId/datetime -> JSON) — consolidated
# from per-router copies into backend/utils.py.
try:
    from ..utils import serialize_doc, serialize_docs
except ImportError:  # pragma: no cover - flat import when run from backend/
    from utils import serialize_doc, serialize_docs

router = APIRouter(prefix="/api/vendors", tags=["Unified Vendors"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# Panel vendors are in email_automation database
operations_db = client["email_automation"]
panel_vendors_collection = operations_db["vendors"]

# Billing vendors are in finance_db database
finance_db = client["finance_db"]
billing_vendors_collection = finance_db["vendors"]

def _normalize_string(value) -> str:
    return str(value or "").strip()


def _generate_unique_vid() -> str:
    """Generate a unique 4-digit VID for legacy vendors missing one."""
    for _ in range(200):
        candidate = str(randint(1000, 9999))
        if not panel_vendors_collection.find_one({"vid": candidate}):
            return candidate

    # Deterministic fallback if random attempts collide repeatedly
    seed = int(datetime.utcnow().timestamp() * 1000)
    candidate = str((seed % 9000) + 1000)
    while panel_vendors_collection.find_one({"vid": candidate}):
        candidate = str(((int(candidate) - 1000 + 1) % 9000) + 1000)
    return candidate


def _ensure_vendor_identifiers(vendor: dict) -> dict:
    """
    Ensure vendors always have both vid and vendorNo/vendorNumber.
    This heals old records that were created before these fields were enforced.
    """
    if not vendor:
        return vendor

    updates = {}

    vid = _normalize_string(vendor.get("vid"))
    if not vid:
        vid = _generate_unique_vid()
        updates["vid"] = vid

    vendor_no = _normalize_string(vendor.get("vendorNo") or vendor.get("vendorNumber"))
    if not vendor_no:
        vendor_no = vid
        updates["vendorNo"] = vendor_no
        updates["vendorNumber"] = vendor_no
    else:
        if not _normalize_string(vendor.get("vendorNo")):
            updates["vendorNo"] = vendor_no
        if not _normalize_string(vendor.get("vendorNumber")):
            updates["vendorNumber"] = vendor_no

    if updates:
        updates["updatedAt"] = datetime.utcnow().isoformat()
        panel_vendors_collection.update_one({"_id": vendor["_id"]}, {"$set": updates})
        vendor.update(updates)

    return vendor

# ========================
# Panel Vendor CRUD (used by VendorsPage)
# ========================

@router.get("/")
def list_panel_vendors(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
):
    """List panel vendors, paginated"""
    query = {}
    if search:
        import re
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        query = {
            "$or": [
                {"vendorName": pattern},
                {"vendorEmail": pattern},
                {"vendorVariable": pattern},
                {"vendorType": pattern},
                {"vid": pattern},
                {"vendorNo": pattern},
                {"vendorNumber": pattern},
            ]
        }
    total = panel_vendors_collection.count_documents(query)
    skip = (page - 1) * page_size
    vendors = [
        serialize_doc(_ensure_vendor_identifiers(v))
        for v in panel_vendors_collection.find(query).skip(skip).limit(page_size)
    ]
    import math
    pages = math.ceil(total / page_size) if total > 0 else 1
    return {"vendors": vendors, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.post("/")
def create_panel_vendor(vendor_data: dict):
    """Create a new panel vendor"""
    if not _normalize_string(vendor_data.get("vid")):
        vendor_data["vid"] = _generate_unique_vid()

    vendor_no = _normalize_string(vendor_data.get("vendorNo") or vendor_data.get("vendorNumber"))
    if not vendor_no:
        vendor_no = vendor_data["vid"]
    vendor_data["vendorNo"] = vendor_no
    vendor_data["vendorNumber"] = vendor_no

    vendor_data["createdAt"] = datetime.utcnow().isoformat()
    result = panel_vendors_collection.insert_one(vendor_data)
    created = panel_vendors_collection.find_one({"_id": result.inserted_id})
    return serialize_doc(created)


@router.put("/{vendor_id}")
def update_panel_vendor(vendor_id: str, vendor_data: dict):
    """Update a panel vendor"""
    try:
        oid = ObjectId(vendor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid vendor ID")

    existing = panel_vendors_collection.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor_data.pop("_id", None)
    # Preserve existing identifiers unless explicitly changed to a non-empty value.
    if "vid" in vendor_data and not _normalize_string(vendor_data.get("vid")):
        vendor_data.pop("vid", None)
    if "vendorNo" in vendor_data and not _normalize_string(vendor_data.get("vendorNo")):
        vendor_data.pop("vendorNo", None)
    if "vendorNumber" in vendor_data and not _normalize_string(vendor_data.get("vendorNumber")):
        vendor_data.pop("vendorNumber", None)

    vendor_data["updatedAt"] = datetime.utcnow().isoformat()
    result = panel_vendors_collection.update_one({"_id": oid}, {"$set": vendor_data})

    # Safety for legacy records: fill any missing identifiers after update.
    updated = panel_vendors_collection.find_one({"_id": oid})
    updated = _ensure_vendor_identifiers(updated)
    return serialize_doc(updated)


@router.delete("/{vendor_id}")
def delete_panel_vendor(vendor_id: str):
    """Delete a panel vendor"""
    try:
        oid = ObjectId(vendor_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid vendor ID")
    result = panel_vendors_collection.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor deleted successfully"}


# ========================
# Unified Vendor Endpoints
# ========================

@router.get("/unified")
async def get_all_unified_vendors(
    vendor_type: Optional[str] = Query(None, description="Filter by type: panel, billing, or all"),
    search: Optional[str] = Query(None, description="Search by name/email")
):
    """Get all vendors from both panel and billing systems in a unified view"""
    try:
        vendors = []
        
        # Fetch panel vendors (if not filtered to billing only)
        if vendor_type != "billing":
            panel_query = {}
            if search:
                panel_query["$or"] = [
                    {"vendor_name": {"$regex": search, "$options": "i"}},
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}}
                ]
            
            panel_vendors = list(panel_vendors_collection.find(panel_query))
            for pv in panel_vendors:
                vendors.append({
                    "_id": str(pv["_id"]),
                    "source_id": str(pv["_id"]),
                    "vendor_type": "panel",
                    "display_name": pv.get("vendor_name") or pv.get("name") or "Unknown",
                    "email": pv.get("email") or pv.get("contact_email") or "",
                    "phone": pv.get("phone") or "",
                    "status": pv.get("status", "active"),
                    "linked_billing_vendor_id": pv.get("linked_billing_vendor_id"),
                    "created_at": pv.get("created_at"),
                    "original_data": serialize_doc(pv)
                })
        
        # Fetch billing vendors (if not filtered to panel only)
        if vendor_type != "panel":
            billing_query = {}
            if search:
                billing_query["$or"] = [
                    {"vendor_name": {"$regex": search, "$options": "i"}},
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}}
                ]
            
            billing_vendors = list(billing_vendors_collection.find(billing_query))
            for bv in billing_vendors:
                vendors.append({
                    "_id": str(bv["_id"]),
                    "source_id": str(bv["_id"]),
                    "vendor_type": "billing",
                    "display_name": bv.get("vendor_name") or bv.get("name") or "Unknown",
                    "email": bv.get("email") or bv.get("contact_email") or "",
                    "phone": bv.get("phone") or "",
                    "status": bv.get("status", "active"),
                    "linked_panel_vendor_id": bv.get("linked_panel_vendor_id"),
                    "created_at": bv.get("created_at"),
                    "original_data": serialize_doc(bv)
                })
        
        # Sort by display_name
        vendors.sort(key=lambda x: x.get("display_name", "").lower())
        
        return vendors
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/unified/stats")
async def get_vendor_stats():
    """Get statistics about vendors"""
    try:
        panel_count = panel_vendors_collection.count_documents({})
        billing_count = billing_vendors_collection.count_documents({})
        
        # Count linked vendors
        panel_linked = panel_vendors_collection.count_documents({"linked_billing_vendor_id": {"$exists": True, "$ne": None}})
        billing_linked = billing_vendors_collection.count_documents({"linked_panel_vendor_id": {"$exists": True, "$ne": None}})
        
        return {
            "total_vendors": panel_count + billing_count,
            "panel_vendors": panel_count,
            "billing_vendors": billing_count,
            "linked_panel_vendors": panel_linked,
            "linked_billing_vendors": billing_linked,
            "unlinked_vendors": (panel_count - panel_linked) + (billing_count - billing_linked)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/link-panel-to-billing")
async def link_panel_to_billing(panel_vendor_id: str, billing_vendor_id: str):
    """Link a panel vendor to a billing vendor (bidirectional)"""
    try:
        # Update panel vendor with billing link
        panel_result = panel_vendors_collection.update_one(
            {"_id": ObjectId(panel_vendor_id)},
            {"$set": {
                "linked_billing_vendor_id": billing_vendor_id,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Update billing vendor with panel link
        billing_result = billing_vendors_collection.update_one(
            {"_id": ObjectId(billing_vendor_id)},
            {"$set": {
                "linked_panel_vendor_id": panel_vendor_id,
                "updated_at": datetime.utcnow()
            }}
        )
        
        if panel_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Panel vendor not found")
        if billing_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Billing vendor not found")
        
        return {"message": "Vendors linked successfully"}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/unlink-panel-from-billing/{panel_vendor_id}")
async def unlink_panel_from_billing(panel_vendor_id: str):
    """Unlink a panel vendor from its linked billing vendor (bidirectional)"""
    try:
        # First find the panel vendor to get the linked billing vendor id
        panel_vendor = panel_vendors_collection.find_one({"_id": ObjectId(panel_vendor_id)})
        if not panel_vendor:
            raise HTTPException(status_code=404, detail="Panel vendor not found")
        
        billing_vendor_id = panel_vendor.get("linked_billing_vendor_id")
        
        # Remove link from panel vendor
        panel_vendors_collection.update_one(
            {"_id": ObjectId(panel_vendor_id)},
            {"$set": {
                "linked_billing_vendor_id": None,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Remove link from billing vendor (if it exists)
        if billing_vendor_id:
            billing_vendors_collection.update_one(
                {"_id": ObjectId(billing_vendor_id)},
                {"$set": {
                    "linked_panel_vendor_id": None,
                    "updated_at": datetime.utcnow()
                }}
            )
        
        return {"message": "Vendors unlinked successfully"}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


# ========================
# P1.5: Vendor Email Separation
# ========================

@router.get("/{vendor_id}/emails")
async def get_vendor_emails(vendor_id: str, vendor_type: str = Query("panel", description="panel or billing")):
    """
    P1.5: Get all emails associated with a vendor.
    Returns structured email data with types: primary, billing, internal, other.
    """
    try:
        collection = panel_vendors_collection if vendor_type == "panel" else billing_vendors_collection
        vendor = collection.find_one({"_id": ObjectId(vendor_id)})
        
        if not vendor:
            raise HTTPException(status_code=404, detail=f"{vendor_type.capitalize()} vendor not found")
        
        # Build emails list from various fields
        emails = []
        
        # Primary/contact email
        primary_email = vendor.get("email") or vendor.get("contact_email")
        if primary_email:
            emails.append({
                "email": primary_email,
                "type": "primary",
                "label": "Primary Contact",
                "is_primary": True
            })
        
        # Billing email (if different from primary)
        billing_email = vendor.get("billing_email")
        if billing_email and billing_email != primary_email:
            emails.append({
                "email": billing_email,
                "type": "billing",
                "label": "Billing",
                "is_primary": False
            })
        
        # Internal/operations email
        internal_email = vendor.get("internal_email") or vendor.get("operations_email")
        if internal_email and internal_email not in [primary_email, billing_email]:
            emails.append({
                "email": internal_email,
                "type": "internal",
                "label": "Internal/Operations",
                "is_primary": False
            })
        
        # Additional emails list
        additional_emails = vendor.get("additional_emails", [])
        for add_email in additional_emails:
            if isinstance(add_email, str):
                if add_email not in [e["email"] for e in emails]:
                    emails.append({
                        "email": add_email,
                        "type": "other",
                        "label": "Additional",
                        "is_primary": False
                    })
            elif isinstance(add_email, dict):
                if add_email.get("email") not in [e["email"] for e in emails]:
                    emails.append({
                        "email": add_email.get("email"),
                        "type": add_email.get("type", "other"),
                        "label": add_email.get("label", "Additional"),
                        "is_primary": False
                    })
        
        return {
            "vendor_id": vendor_id,
            "vendor_type": vendor_type,
            "vendor_name": vendor.get("vendor_name") or vendor.get("name"),
            "emails": emails
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{vendor_id}/emails")
async def update_vendor_emails(
    vendor_id: str,
    vendor_type: str = Query("panel", description="panel or billing"),
    primary_email: Optional[str] = None,
    billing_email: Optional[str] = None,
    internal_email: Optional[str] = None,
    additional_emails: Optional[List[str]] = None
):
    """
    P1.5: Update vendor emails with type separation.
    Allows setting different email addresses for different purposes.
    """
    try:
        collection = panel_vendors_collection if vendor_type == "panel" else billing_vendors_collection
        vendor = collection.find_one({"_id": ObjectId(vendor_id)})
        
        if not vendor:
            raise HTTPException(status_code=404, detail=f"{vendor_type.capitalize()} vendor not found")
        
        update_doc = {"updated_at": datetime.utcnow()}
        
        if primary_email is not None:
            update_doc["email"] = primary_email
            update_doc["contact_email"] = primary_email
        
        if billing_email is not None:
            update_doc["billing_email"] = billing_email
        
        if internal_email is not None:
            update_doc["internal_email"] = internal_email
        
        if additional_emails is not None:
            update_doc["additional_emails"] = additional_emails
        
        collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {"$set": update_doc}
        )
        
        return {
            "success": True,
            "vendor_id": vendor_id,
            "message": "Vendor emails updated"
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

