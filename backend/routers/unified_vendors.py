"""
Unified Vendors Router
Provides a combined view of panel vendors (Operations) and billing vendors (Finance)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime
from pymongo import MongoClient
import os

router = APIRouter(prefix="/vendors", tags=["Unified Vendors"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# Panel vendors are in email_automation database
operations_db = client["email_automation"]
panel_vendors_collection = operations_db["panel_vendors"]

# Billing vendors are in finance_db database
finance_db = client["finance_db"]
billing_vendors_collection = finance_db["vendors"]

def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

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
