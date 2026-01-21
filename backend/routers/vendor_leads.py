"""
Vendor Leads Router
Handles transfer of contacts from AI Database to Vendor Leads
and conversion of qualified leads to full Vendors (Panel/Billing)
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List
from bson import ObjectId
from datetime import datetime
from pymongo import MongoClient
import os

router = APIRouter(prefix="/vendor-leads", tags=["Vendor Leads"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["email_automation"]

# Collections
vendor_leads_collection = db["vendor_leads"]
ai_classified_leads_collection = db["ai_classified_leads"]
leads_enriched_collection = db["leads_enriched"]

# Ensure indexes
try:
    vendor_leads_collection.create_index("email")
    vendor_leads_collection.create_index("status")
    vendor_leads_collection.create_index("created_at")
    vendor_leads_collection.create_index("source_lead_id")
    print("✅ Vendor leads indexes created")
except Exception as e:
    print(f"Warning: Could not create vendor_leads indexes: {e}")


def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    if "source_lead_id" in doc and doc["source_lead_id"]:
        doc["source_lead_id"] = str(doc["source_lead_id"])
    return doc


# ========================
# Vendor Leads CRUD
# ========================

@router.get("")
async def get_vendor_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    search: Optional[str] = None
):
    """Get all vendor leads with pagination"""
    query = {}
    
    if status:
        query["status"] = status
    
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
            {"title": {"$regex": search, "$options": "i"}}
        ]
    
    skip = (page - 1) * limit
    total = vendor_leads_collection.count_documents(query)
    
    leads = list(vendor_leads_collection.find(query)
                 .sort("created_at", -1)
                 .skip(skip)
                 .limit(limit))
    
    return {
        "leads": [serialize_doc(l) for l in leads],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit if total > 0 else 1
    }


@router.get("/stats")
async def get_vendor_leads_stats():
    """Get vendor leads statistics"""
    total = vendor_leads_collection.count_documents({})
    new = vendor_leads_collection.count_documents({"status": "new"})
    contacted = vendor_leads_collection.count_documents({"status": "contacted"})
    qualified = vendor_leads_collection.count_documents({"status": "qualified"})
    rejected = vendor_leads_collection.count_documents({"status": "rejected"})
    converted = vendor_leads_collection.count_documents({"status": "converted"})
    
    return {
        "total": total,
        "new": new,
        "contacted": contacted,
        "qualified": qualified,
        "rejected": rejected,
        "converted": converted
    }


@router.get("/{lead_id}")
async def get_vendor_lead(lead_id: str):
    """Get a single vendor lead by ID"""
    try:
        obj_id = ObjectId(lead_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid lead ID")
    
    lead = vendor_leads_collection.find_one({"_id": obj_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return serialize_doc(lead)


@router.post("")
async def create_vendor_lead(lead_data: dict = Body(...)):
    """Create a new vendor lead manually"""
    lead = {
        "name": lead_data.get("name", ""),
        "email": lead_data.get("email", ""),
        "title": lead_data.get("title", ""),
        "company": lead_data.get("company", ""),
        "phone": lead_data.get("phone", ""),
        "status": lead_data.get("status", "new"),
        "notes": lead_data.get("notes", ""),
        "source": "manual",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = vendor_leads_collection.insert_one(lead)
    lead["_id"] = str(result.inserted_id)
    
    return {"success": True, "lead": lead}


@router.put("/{lead_id}")
async def update_vendor_lead(lead_id: str, lead_data: dict = Body(...)):
    """Update a vendor lead"""
    try:
        obj_id = ObjectId(lead_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid lead ID")
    
    update = {k: v for k, v in lead_data.items() if k != "_id"}
    update["updated_at"] = datetime.utcnow()
    
    result = vendor_leads_collection.update_one(
        {"_id": obj_id},
        {"$set": update}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return {"success": True, "modified": result.modified_count}


@router.delete("/{lead_id}")
async def delete_vendor_lead(lead_id: str):
    """Delete a vendor lead"""
    try:
        obj_id = ObjectId(lead_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid lead ID")
    
    result = vendor_leads_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return {"success": True, "deleted": True}


@router.post("/bulk-delete")
async def bulk_delete_vendor_leads(data: dict = Body(...)):
    """Delete multiple vendor leads"""
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    
    obj_ids = []
    for id in ids:
        try:
            obj_ids.append(ObjectId(id))
        except:
            pass
    
    result = vendor_leads_collection.delete_many({"_id": {"$in": obj_ids}})
    
    return {"success": True, "deleted": result.deleted_count}


# ========================
# Transfer from AI Database
# ========================

@router.post("/transfer-from-ai-database")
async def transfer_from_ai_database(data: dict = Body(...)):
    """
    Transfer a single lead from AI Database to Vendor Leads.
    
    Body:
    {
        "lead_id": "...",  # ObjectId of the lead in AI Database
        "source_collection": "leads_enriched" | "ai_classified_leads"
    }
    """
    lead_id = data.get("lead_id")
    source_collection = data.get("source_collection", "leads_enriched")
    
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")
    
    try:
        obj_id = ObjectId(lead_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid lead_id")
    
    # Get source collection
    if source_collection == "ai_classified_leads":
        source = ai_classified_leads_collection
    else:
        source = leads_enriched_collection
    
    # Find the lead
    lead = source.find_one({"_id": obj_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found in AI Database")
    
    # Check if already transferred
    if lead.get("transferred_to_vendor_leads"):
        raise HTTPException(status_code=400, detail="Lead already transferred to Vendor Leads")
    
    # Extract email
    email = lead.get("email") or lead.get("work_email") or lead.get("personal_email") or ""
    
    # Check if already exists in vendor leads by email
    if email:
        existing = vendor_leads_collection.find_one({"email": email})
        if existing:
            raise HTTPException(status_code=400, detail=f"Lead with email {email} already exists in Vendor Leads")
    
    # Map fields from AI Database lead to vendor lead
    vendor_lead = {
        "name": lead.get("name") or lead.get("full_name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Unknown",
        "email": email,
        "title": lead.get("title") or lead.get("job_title") or "",
        "company": lead.get("company_name") or lead.get("company") or "",
        "phone": lead.get("phone") or lead.get("phone_number") or "",
        "linkedin_url": lead.get("linkedin_url") or "",
        "website": lead.get("company_website") or lead.get("company_domain") or "",
        "industry": lead.get("industry") or lead.get("company_industry") or "",
        "location": lead.get("location") or lead.get("company_headquarters") or "",
        "status": "new",
        "notes": f"Transferred from AI Database on {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        "source": "ai_database",
        "source_lead_id": str(obj_id),
        "source_collection": source_collection,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = vendor_leads_collection.insert_one(vendor_lead)
    vendor_lead["_id"] = str(result.inserted_id)
    
    # Update the original lead to mark it as transferred
    source.update_one(
        {"_id": obj_id},
        {"$set": {
            "transferred_to_vendor_leads": True,
            "transferred_at": datetime.utcnow(),
            "vendor_lead_id": str(result.inserted_id)
        }}
    )
    
    return {
        "success": True,
        "lead": vendor_lead,
        "message": "Lead transferred to Vendor Leads successfully"
    }


@router.post("/bulk-transfer-from-ai-database")
async def bulk_transfer_from_ai_database(data: dict = Body(...)):
    """
    Transfer multiple leads from AI Database to Vendor Leads.
    
    Body:
    {
        "lead_ids": ["...", "..."],
        "source_collection": "leads_enriched" | "ai_classified_leads"
    }
    """
    lead_ids = data.get("lead_ids", [])
    source_collection = data.get("source_collection", "leads_enriched")
    
    if not lead_ids:
        raise HTTPException(status_code=400, detail="lead_ids is required")
    
    # Get source collection
    if source_collection == "ai_classified_leads":
        source = ai_classified_leads_collection
    else:
        source = leads_enriched_collection
    
    transferred = 0
    skipped = 0
    errors = []
    
    for lead_id in lead_ids:
        try:
            obj_id = ObjectId(lead_id)
            lead = source.find_one({"_id": obj_id})
            
            if not lead:
                skipped += 1
                errors.append(f"Lead {lead_id} not found")
                continue
            
            # Skip if already transferred
            if lead.get("transferred_to_vendor_leads"):
                skipped += 1
                errors.append(f"Lead {lead_id} already transferred")
                continue
            
            email = lead.get("email") or lead.get("work_email") or lead.get("personal_email") or ""
            
            # Check for duplicates by email
            if email:
                existing = vendor_leads_collection.find_one({"email": email})
                if existing:
                    skipped += 1
                    errors.append(f"Email {email} already exists")
                    continue
            
            # Create vendor lead
            vendor_lead = {
                "name": lead.get("name") or lead.get("full_name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Unknown",
                "email": email,
                "title": lead.get("title") or lead.get("job_title") or "",
                "company": lead.get("company_name") or lead.get("company") or "",
                "phone": lead.get("phone") or lead.get("phone_number") or "",
                "linkedin_url": lead.get("linkedin_url") or "",
                "status": "new",
                "notes": f"Bulk transferred from AI Database on {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                "source": "ai_database",
                "source_lead_id": str(obj_id),
                "source_collection": source_collection,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            result = vendor_leads_collection.insert_one(vendor_lead)
            
            # Mark original as transferred
            source.update_one(
                {"_id": obj_id},
                {"$set": {
                    "transferred_to_vendor_leads": True,
                    "transferred_at": datetime.utcnow(),
                    "vendor_lead_id": str(result.inserted_id)
                }}
            )
            
            transferred += 1
            
        except Exception as e:
            skipped += 1
            errors.append(f"Error with {lead_id}: {str(e)}")
    
    return {
        "success": True,
        "transferred": transferred,
        "skipped": skipped,
        "errors": errors[:10],
        "message": f"Transferred {transferred} leads to Vendor Leads"
    }


# ========================
# Convert to Vendor
# ========================

@router.post("/{lead_id}/convert-to-vendor")
async def convert_to_vendor(lead_id: str, data: dict = Body(...)):
    """
    Convert a qualified vendor lead to a full vendor (Panel or Billing).
    
    Body:
    {
        "vendor_type": "panel" | "billing",
        "additional_data": { ... }
    }
    """
    vendor_type = data.get("vendor_type", "panel")
    additional_data = data.get("additional_data", {})
    
    try:
        obj_id = ObjectId(lead_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid lead_id")
    
    # Find the vendor lead
    lead = vendor_leads_collection.find_one({"_id": obj_id})
    if not lead:
        raise HTTPException(status_code=404, detail="Vendor lead not found")
    
    # Check if already converted
    if lead.get("status") == "converted":
        raise HTTPException(status_code=400, detail="Lead already converted to vendor")
    
    # Create vendor in appropriate collection
    if vendor_type == "billing":
        # Billing vendor goes to finance_db.vendors
        finance_db = client["finance_db"]
        billing_vendors = finance_db["vendors"]
        
        # Generate vendor number
        last_vendor = billing_vendors.find_one(sort=[("vendor_number", -1)])
        if last_vendor and last_vendor.get("vendor_number"):
            try:
                num = int(last_vendor["vendor_number"].replace("VEND-", ""))
                new_num = f"VEND-{num + 1:05d}"
            except:
                new_num = "VEND-00001"
        else:
            new_num = "VEND-00001"
        
        vendor = {
            "name": lead.get("name", ""),
            "vendor_number": new_num,
            "vendor_type": additional_data.get("vendor_subtype", "supplier"),
            "company_name": lead.get("company", ""),
            "email": lead.get("email", ""),
            "phone": lead.get("phone", ""),
            "status": "active",
            "gst_treatment": additional_data.get("gst_treatment", ""),
            "payment_terms": additional_data.get("payment_terms", 30),
            "source_vendor_lead_id": str(obj_id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            **{k: v for k, v in additional_data.items() if k not in ["vendor_subtype", "gst_treatment", "payment_terms"]}
        }
        
        result = billing_vendors.insert_one(vendor)
        vendor["_id"] = str(result.inserted_id)
        
    else:
        # Panel vendor goes to email_automation.panel_vendors
        panel_vendors = db["panel_vendors"]
        
        vendor = {
            "vendor_name": lead.get("name", "") or lead.get("company", ""),
            "name": lead.get("name", ""),
            "email": lead.get("email", ""),
            "phone": lead.get("phone", ""),
            "vendorType": additional_data.get("vendor_subtype", "Panel"),
            "status": "Active",
            "completeRD": additional_data.get("completeRD", []),
            "terminateRD": additional_data.get("terminateRD", []),
            "quotaFullRD": additional_data.get("quotaFullRD", []),
            "source_vendor_lead_id": str(obj_id),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            **{k: v for k, v in additional_data.items() if k not in ["vendor_subtype", "completeRD", "terminateRD", "quotaFullRD"]}
        }
        
        result = panel_vendors.insert_one(vendor)
        vendor["_id"] = str(result.inserted_id)
    
    # Update vendor lead status to converted
    vendor_leads_collection.update_one(
        {"_id": obj_id},
        {"$set": {
            "status": "converted",
            "converted_to_vendor_type": vendor_type,
            "converted_vendor_id": str(result.inserted_id),
            "converted_at": datetime.utcnow()
        }}
    )
    
    return {
        "success": True,
        "vendor": vendor,
        "vendor_type": vendor_type,
        "message": f"Lead converted to {vendor_type} vendor successfully"
    }
