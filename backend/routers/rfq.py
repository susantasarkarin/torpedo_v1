"""
RFQ Router - Request for Quotation Management

Provides endpoints for:
- RFQ CRUD operations
- RFQ listing with filters
- Value override/update
- Link to leads
- Email thread association
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rfq",
    tags=["rfq"]
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["email_automation"]
rfqs_collection = db["rfqs"]
email_leads_collection = db["email_leads"]


# ============== PYDANTIC MODELS ==============

class RFQCreate(BaseModel):
    """Request model for creating RFQ manually"""
    contact_email: str = Field(..., description="Lead's email address")
    lead_id: Optional[str] = Field(None, description="ObjectId reference to lead")
    title: str = Field(..., description="RFQ title")
    description: str = Field("", description="RFQ description")
    manual_value: Optional[float] = Field(None, description="Manual value override")
    manual_currency: str = Field("USD", description="Currency code")
    priority: str = Field("medium", description="Priority: low, medium, high")
    due_date: Optional[str] = Field(None, description="Due date ISO string")


class RFQUpdate(BaseModel):
    """Request model for updating RFQ"""
    title: Optional[str] = None
    description: Optional[str] = None
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None


class RFQResponse(BaseModel):
    """Response model for RFQ"""
    rfq_id: str
    contact_email: str
    lead_id: Optional[str] = None
    lead_name: Optional[str] = None
    title: str
    description: str = ""
    extracted_value: Optional[float] = None
    extracted_currency: str = "USD"
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    final_value: Optional[float] = None
    final_currency: str = "USD"
    source_emails_count: int = 0
    status: str = "pending"
    priority: str = "medium"
    received_date: Optional[str] = None
    due_date: Optional[str] = None
    summary: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============== HELPER FUNCTIONS ==============

def generate_rfq_id() -> str:
    """Generate a unique RFQ ID in format RFQ-YYYY-NNNN"""
    year = datetime.utcnow().year
    
    # Find the highest RFQ number for this year
    latest = rfqs_collection.find_one(
        {"rfq_id": {"$regex": f"^RFQ-{year}-"}},
        sort=[("rfq_id", DESCENDING)]
    )
    
    if latest:
        try:
            last_num = int(latest["rfq_id"].split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1
    
    return f"RFQ-{year}-{new_num:04d}"


def rfq_to_response(rfq: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB RFQ document to response format"""
    # Calculate final value
    final_value = rfq.get("manual_value") if rfq.get("manual_value") is not None else rfq.get("extracted_value")
    final_currency = rfq.get("manual_currency") if rfq.get("manual_currency") else rfq.get("extracted_currency", "USD")
    
    # Get lead name if lead_id exists
    lead_name = None
    if rfq.get("lead_id"):
        lead = email_leads_collection.find_one({"_id": ObjectId(rfq["lead_id"])})
        if lead:
            lead_name = lead.get("name") or lead.get("email")
    
    # If no lead_id, try to find by contact_email
    if not lead_name and rfq.get("contact_email"):
        lead = email_leads_collection.find_one({"email": rfq["contact_email"]})
        if lead:
            lead_name = lead.get("name") or lead.get("email")
    
    return {
        "_id": str(rfq["_id"]),
        "rfq_id": rfq.get("rfq_id", ""),
        "contact_email": rfq.get("contact_email", ""),
        "lead_id": rfq.get("lead_id"),
        "lead_name": lead_name,
        "title": rfq.get("title", ""),
        "description": rfq.get("description", ""),
        "extracted_value": rfq.get("extracted_value"),
        "extracted_currency": rfq.get("extracted_currency", "USD"),
        "manual_value": rfq.get("manual_value"),
        "manual_currency": rfq.get("manual_currency"),
        "final_value": final_value,
        "final_currency": final_currency,
        "source_emails": rfq.get("source_emails", []),
        "source_emails_count": len(rfq.get("source_emails", [])),
        "status": rfq.get("status", "pending"),
        "priority": rfq.get("priority", "medium"),
        "received_date": rfq.get("received_date").isoformat() if rfq.get("received_date") else None,
        "due_date": rfq.get("due_date").isoformat() if rfq.get("due_date") else None,
        "quoted_date": rfq.get("quoted_date").isoformat() if rfq.get("quoted_date") else None,
        "closed_date": rfq.get("closed_date").isoformat() if rfq.get("closed_date") else None,
        "summary": rfq.get("summary", ""),
        "created_at": rfq.get("created_at").isoformat() if rfq.get("created_at") else None,
        "updated_at": rfq.get("updated_at").isoformat() if rfq.get("updated_at") else None,
        "created_by": rfq.get("created_by", "auto")
    }


# ============== ENDPOINTS ==============

@router.get("/")
async def list_rfqs(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    search: Optional[str] = Query(None, description="Search in title, contact_email"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page")
) -> Dict[str, Any]:
    """
    List all RFQs with optional filters and pagination.
    """
    query = {}
    
    if status:
        query["status"] = status
    
    if priority:
        query["priority"] = priority
    
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"contact_email": {"$regex": search, "$options": "i"}},
            {"rfq_id": {"$regex": search, "$options": "i"}}
        ]
    
    # Get total count
    total = rfqs_collection.count_documents(query)
    
    # Get paginated results
    skip = (page - 1) * limit
    rfqs = list(
        rfqs_collection.find(query)
        .sort("created_at", DESCENDING)
        .skip(skip)
        .limit(limit)
    )
    
    return {
        "success": True,
        "rfqs": [rfq_to_response(rfq) for rfq in rfqs],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


@router.get("/stats")
async def get_rfq_stats() -> Dict[str, Any]:
    """
    Get RFQ statistics by status.
    """
    pipeline = [
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "total_value": {
                    "$sum": {
                        "$ifNull": ["$manual_value", {"$ifNull": ["$extracted_value", 0]}]
                    }
                }
            }
        }
    ]
    
    results = list(rfqs_collection.aggregate(pipeline))
    
    stats = {
        "pending": {"count": 0, "total_value": 0},
        "quoted": {"count": 0, "total_value": 0},
        "negotiating": {"count": 0, "total_value": 0},
        "won": {"count": 0, "total_value": 0},
        "lost": {"count": 0, "total_value": 0}
    }
    
    for result in results:
        status = result["_id"]
        if status in stats:
            stats[status] = {
                "count": result["count"],
                "total_value": result["total_value"]
            }
    
    # Calculate totals
    total_count = sum(s["count"] for s in stats.values())
    total_value = sum(s["total_value"] for s in stats.values())
    
    return {
        "success": True,
        "stats": stats,
        "total_count": total_count,
        "total_value": total_value
    }


@router.get("/{rfq_id}")
async def get_rfq(rfq_id: str) -> Dict[str, Any]:
    """
    Get a single RFQ by ID (either rfq_id like RFQ-2025-0001 or MongoDB _id).
    """
    # Try to find by rfq_id first
    rfq = rfqs_collection.find_one({"rfq_id": rfq_id})
    
    # If not found, try by _id
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({"_id": ObjectId(rfq_id)})
        except:
            pass
    
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    return {
        "success": True,
        "rfq": rfq_to_response(rfq)
    }


@router.post("/")
async def create_rfq(rfq_data: RFQCreate) -> Dict[str, Any]:
    """
    Create a new RFQ manually.
    """
    # Generate RFQ ID
    rfq_id = generate_rfq_id()
    
    # Parse due date if provided
    due_date = None
    if rfq_data.due_date:
        try:
            due_date = datetime.fromisoformat(rfq_data.due_date.replace("Z", "+00:00"))
        except:
            pass
    
    rfq_doc = {
        "rfq_id": rfq_id,
        "contact_email": rfq_data.contact_email,
        "lead_id": rfq_data.lead_id,
        "title": rfq_data.title,
        "description": rfq_data.description,
        "extracted_value": None,
        "extracted_currency": "USD",
        "manual_value": rfq_data.manual_value,
        "manual_currency": rfq_data.manual_currency,
        "source_emails": [],
        "status": "pending",
        "priority": rfq_data.priority,
        "received_date": datetime.utcnow(),
        "due_date": due_date,
        "quoted_date": None,
        "closed_date": None,
        "summary": "",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": "manual"
    }
    
    result = rfqs_collection.insert_one(rfq_doc)
    
    # Link RFQ to lead if contact_email exists
    if rfq_data.contact_email:
        email_leads_collection.update_one(
            {"email": rfq_data.contact_email},
            {"$addToSet": {"rfq_ids": rfq_id}}
        )
    
    rfq_doc["_id"] = result.inserted_id
    
    return {
        "success": True,
        "message": f"RFQ {rfq_id} created successfully",
        "rfq": rfq_to_response(rfq_doc)
    }


@router.put("/{rfq_id}")
async def update_rfq(rfq_id: str, rfq_data: RFQUpdate) -> Dict[str, Any]:
    """
    Update an existing RFQ.
    """
    # Find the RFQ
    rfq = rfqs_collection.find_one({"rfq_id": rfq_id})
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({"_id": ObjectId(rfq_id)})
        except:
            pass
    
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    # Build update document
    update_doc = {"updated_at": datetime.utcnow()}
    
    if rfq_data.title is not None:
        update_doc["title"] = rfq_data.title
    if rfq_data.description is not None:
        update_doc["description"] = rfq_data.description
    if rfq_data.manual_value is not None:
        update_doc["manual_value"] = rfq_data.manual_value
    if rfq_data.manual_currency is not None:
        update_doc["manual_currency"] = rfq_data.manual_currency
    if rfq_data.priority is not None:
        update_doc["priority"] = rfq_data.priority
    
    if rfq_data.status is not None:
        update_doc["status"] = rfq_data.status
        # Set closed_date if status is won or lost
        if rfq_data.status in ["won", "lost"]:
            update_doc["closed_date"] = datetime.utcnow()
        elif rfq_data.status == "quoted":
            update_doc["quoted_date"] = datetime.utcnow()
    
    if rfq_data.due_date is not None:
        try:
            update_doc["due_date"] = datetime.fromisoformat(rfq_data.due_date.replace("Z", "+00:00"))
        except:
            pass
    
    rfqs_collection.update_one(
        {"_id": rfq["_id"]},
        {"$set": update_doc}
    )
    
    # Get updated document
    updated_rfq = rfqs_collection.find_one({"_id": rfq["_id"]})
    
    return {
        "success": True,
        "message": "RFQ updated successfully",
        "rfq": rfq_to_response(updated_rfq)
    }


@router.delete("/{rfq_id}")
async def delete_rfq(rfq_id: str) -> Dict[str, Any]:
    """
    Delete an RFQ.
    """
    # Find the RFQ
    rfq = rfqs_collection.find_one({"rfq_id": rfq_id})
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({"_id": ObjectId(rfq_id)})
        except:
            pass
    
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    # Remove RFQ ID from lead
    if rfq.get("contact_email"):
        email_leads_collection.update_one(
            {"email": rfq["contact_email"]},
            {"$pull": {"rfq_ids": rfq["rfq_id"]}}
        )
    
    # Delete RFQ
    rfqs_collection.delete_one({"_id": rfq["_id"]})
    
    return {
        "success": True,
        "message": f"RFQ {rfq.get('rfq_id')} deleted successfully"
    }


@router.get("/by-lead/{lead_id}")
async def get_rfqs_by_lead(lead_id: str) -> Dict[str, Any]:
    """
    Get all RFQs for a specific lead.
    """
    # First try to find by lead_id
    rfqs = list(rfqs_collection.find({"lead_id": lead_id}).sort("created_at", DESCENDING))
    
    # If no results, try to find by contact_email
    if not rfqs:
        # Check if lead_id is actually an email
        if "@" in lead_id:
            rfqs = list(rfqs_collection.find({"contact_email": lead_id}).sort("created_at", DESCENDING))
        else:
            # Try to get the lead's email first
            try:
                lead = email_leads_collection.find_one({"_id": ObjectId(lead_id)})
                if lead and lead.get("email"):
                    rfqs = list(rfqs_collection.find({"contact_email": lead["email"]}).sort("created_at", DESCENDING))
            except:
                pass
    
    return {
        "success": True,
        "rfqs": [rfq_to_response(rfq) for rfq in rfqs],
        "count": len(rfqs)
    }


@router.post("/{rfq_id}/link-email")
async def link_email_to_rfq(
    rfq_id: str,
    message_id: str = Body(..., embed=True),
    subject: str = Body("", embed=True),
    inbox: str = Body("", embed=True)
) -> Dict[str, Any]:
    """
    Link an email to an existing RFQ.
    """
    # Find the RFQ
    rfq = rfqs_collection.find_one({"rfq_id": rfq_id})
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({"_id": ObjectId(rfq_id)})
        except:
            pass
    
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    # Add email to source_emails
    source_email = {
        "message_id": message_id,
        "subject": subject,
        "inbox": inbox,
        "date": datetime.utcnow(),
        "extracted_amount": None
    }
    
    rfqs_collection.update_one(
        {"_id": rfq["_id"]},
        {
            "$push": {"source_emails": source_email},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    
    return {
        "success": True,
        "message": "Email linked to RFQ successfully"
    }
