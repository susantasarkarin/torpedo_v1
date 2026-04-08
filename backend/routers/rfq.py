"""
RFQ Router - Request for Quotation Management

Provides endpoints for:
- RFQ CRUD operations
- RFQ listing with filters
- Value override/update
- Link to leads
- Email thread association
- Convert to Estimate/Invoice
"""

import os
import logging
from datetime import datetime, timedelta
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

# Gmail API database (torpedo_gmail)
gmail_db = mongo_client["torpedo_gmail"]
email_metadata_collection = gmail_db["email_metadata"]

# Finance database for estimates and invoices
finance_db = mongo_client["finance_db"]
customers_collection = finance_db["customers"]
estimates_collection = finance_db["estimates"]
invoices_collection = finance_db["invoices"]

# Contacts collection for CRM
contacts_collection = db["contacts"]


# ============== RFQ STATE MACHINE ==============

# P1.3: Valid status transitions
VALID_STATUS_TRANSITIONS = {
    "pending": ["quoted", "lost"],
    "quoted": ["negotiating", "won", "lost"],
    "negotiating": ["quoted", "won", "lost"],
    "won": [],  # Terminal state
    "lost": ["pending"],  # Can reopen lost RFQs
}

def validate_status_transition(current_status: str, new_status: str) -> tuple[bool, str]:
    """
    P1.3: Validate RFQ status transition.
    Returns (is_valid, error_message).
    """
    if current_status == new_status:
        return True, ""
    
    allowed = VALID_STATUS_TRANSITIONS.get(current_status, [])
    if new_status in allowed:
        return True, ""
    
    return False, f"Cannot transition from '{current_status}' to '{new_status}'. Allowed: {allowed}"


def create_or_update_contact_on_win(rfq: Dict[str, Any]) -> Optional[str]:
    """
    P1.2: Auto-create or update contact when RFQ is won.
    Returns contact_id if created/updated, None on error.
    """
    try:
        email = rfq.get("contact_email", "").lower().strip()
        if not email:
            logger.warning(f"RFQ {rfq.get('rfq_id')} won but no contact_email")
            return None
        
        # Check if contact already exists
        existing = contacts_collection.find_one({"email": email})
        
        # Extract sender info from RFQ
        sender_name = rfq.get("sender_name", "")
        sender_company = rfq.get("sender_company", "")
        
        # Parse first/last name
        first_name, last_name = "", ""
        if sender_name:
            parts = sender_name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
        
        now = datetime.utcnow()
        
        if existing:
            # Update existing contact with won RFQ info
            update_data = {
                "updated_at": now,
                "last_won_rfq_id": rfq.get("rfq_id"),
                "last_won_rfq_date": now,
            }
            # Only update fields if they're empty
            if not existing.get("firstName") and first_name:
                update_data["firstName"] = first_name
            if not existing.get("lastName") and last_name:
                update_data["lastName"] = last_name
            if not existing.get("company") and sender_company:
                update_data["company"] = sender_company
            
            # Add 'won-rfq' tag if not present
            existing_tags = existing.get("tags", [])
            if "won-rfq" not in existing_tags:
                update_data["tags"] = existing_tags + ["won-rfq"]
            
            contacts_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": update_data}
            )
            logger.info(f"Updated contact {email} with won RFQ {rfq.get('rfq_id')}")
            return str(existing["_id"])
        else:
            # Create new contact
            contact_data = {
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "company": sender_company,
                "phone": "",
                "tags": ["won-rfq", "auto-created"],
                "customFields": {
                    "source": "rfq-win",
                    "source_rfq_id": rfq.get("rfq_id")
                },
                "last_won_rfq_id": rfq.get("rfq_id"),
                "last_won_rfq_date": now,
                "created_at": now,
                "updated_at": now,
            }
            result = contacts_collection.insert_one(contact_data)
            logger.info(f"Created contact {email} from won RFQ {rfq.get('rfq_id')}")
            return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error creating/updating contact on RFQ win: {e}")
        return None


def promote_lead_to_contacts_on_quoted(rfq: Dict[str, Any]) -> Optional[str]:
    """
    Auto-promote lead to Contacts stage when RFQ status changes to 'quoted'.
    This moves the lead into the active sales pipeline in Contacts section.
    Returns lead_id if updated, None on error.
    """
    try:
        email = rfq.get("contact_email", "").lower().strip()
        lead_id = rfq.get("lead_id")
        
        lead = None
        
        # Try to find lead by lead_id first
        if lead_id:
            try:
                lead = email_leads_collection.find_one({"_id": ObjectId(lead_id)})
            except:
                pass
        
        # Fallback to contact_email
        if not lead and email:
            lead = email_leads_collection.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
        
        if not lead:
            logger.warning(f"RFQ {rfq.get('rfq_id')} quoted but no linked lead found for {email}")
            return None
        
        now = datetime.utcnow()
        
        # Only promote if not already in contacts or a more advanced stage
        current_stage = lead.get("lead_stage", "leads")
        if current_stage == "contacts":
            # Already in contacts, just add tag
            existing_tags = lead.get("tags", [])
            if "rfq-quoted" not in existing_tags:
                email_leads_collection.update_one(
                    {"_id": lead["_id"]},
                    {"$addToSet": {"tags": "rfq-quoted"}, "$set": {"updated_at": now}}
                )
            logger.info(f"Lead {lead['_id']} already in contacts, added rfq-quoted tag")
            return str(lead["_id"])
        
        # Promote to contacts stage
        update_data = {
            "lead_stage": "contacts",
            "stage": "discovery_call",  # Default contact stage
            "updated_at": now,
            "promoted_to_contacts_at": now,
            "promoted_from_rfq": rfq.get("rfq_id"),
        }
        
        # Add rfq-quoted tag
        existing_tags = lead.get("tags", [])
        if "rfq-quoted" not in existing_tags:
            update_data["tags"] = existing_tags + ["rfq-quoted"]
        
        email_leads_collection.update_one(
            {"_id": lead["_id"]},
            {"$set": update_data}
        )
        
        logger.info(f"Promoted lead {lead['_id']} to contacts from RFQ {rfq.get('rfq_id')} quote")
        return str(lead["_id"])
        
    except Exception as e:
        logger.error(f"Error promoting lead to contacts on RFQ quoted: {e}")
        return None


# ============== PYDANTIC MODELS ==============

class RFQCreate(BaseModel):
    """Request model for creating RFQ manually"""
    contact_email: str = Field(..., description="Lead's email address")
    lead_id: Optional[str] = Field(None, description="ObjectId reference to lead")
    title: str = Field(..., description="RFQ title")
    description: str = Field("", description="RFQ description")
    manual_value: Optional[float] = Field(None, description="Manual value override")
    manual_currency: str = Field("USD", description="Currency code (USD, INR, EUR, GBP)")
    priority: str = Field("medium", description="Priority: low, medium, high")
    due_date: Optional[str] = Field(None, description="Due date ISO string")
    # New fields for enhanced RFQ
    methodology: Optional[str] = Field(None, description="Research methodology (CATI, CAWI, F2F, etc.)")
    loi: Optional[int] = Field(None, description="Length of Interview in minutes")
    ir: Optional[float] = Field(None, description="Incidence Rate percentage")
    country: Optional[str] = Field(None, description="Target country for the study")
    sample_size: Optional[int] = Field(None, description="Required sample size")


class RFQUpdate(BaseModel):
    """Request model for updating RFQ"""
    title: Optional[str] = None
    description: Optional[str] = None
    manual_value: Optional[float] = None
    manual_currency: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    # New fields for enhanced RFQ
    methodology: Optional[str] = None
    loi: Optional[int] = None
    ir: Optional[float] = None
    country: Optional[str] = None
    sample_size: Optional[int] = None
    target_audience: Optional[str] = None
    timeline: Optional[str] = None
    study_type: Optional[str] = None
    budget: Optional[float] = None
    additional_requirements: Optional[str] = None


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
    # New fields for enhanced RFQ (AI extracted)
    methodology: Optional[str] = None
    loi: Optional[int] = None
    ir: Optional[float] = None
    country: Optional[str] = None
    sample_size: Optional[int] = None
    target_audience: Optional[str] = None
    timeline: Optional[str] = None
    study_type: Optional[str] = None
    budget: Optional[float] = None
    additional_requirements: Optional[str] = None
    ai_summary: Optional[str] = None
    # Email body and sender details
    email_body: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_company: Optional[str] = None
    sender_title: Optional[str] = None


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


def rfq_to_response(rfq: Dict[str, Any], leads_cache: Optional[Dict] = None) -> Dict[str, Any]:
    """Convert MongoDB RFQ document to response format.
    
    Args:
        rfq: The RFQ document from MongoDB
        leads_cache: Optional pre-fetched leads dict with keys:
            - "by_id": {str(lead_id): lead_doc, ...}
            - "by_email": {email_lower: lead_doc, ...}
            If provided, skips per-RFQ DB queries (batch optimization).
    """
    # Calculate final value
    final_value = rfq.get("manual_value") if rfq.get("manual_value") is not None else rfq.get("extracted_value")
    final_currency = rfq.get("manual_currency") if rfq.get("manual_currency") else rfq.get("extracted_currency", "USD")
    
    # Get lead_id and lead_name - ensure lead_id is always populated if possible
    lead_id = rfq.get("lead_id")
    lead_name = None
    lead = None
    
    if leads_cache is not None:
        # Use pre-fetched leads (batch mode - no DB queries)
        by_id = leads_cache.get("by_id", {})
        by_email = leads_cache.get("by_email", {})
        
        if lead_id and str(lead_id) in by_id:
            lead = by_id[str(lead_id)]
            lead_name = lead.get("name") or ((lead.get("first_name", "") + " " + lead.get("last_name", "")).strip()) or lead.get("email")
            lead_name = lead_name.strip() if lead_name else None
        
        if not lead and rfq.get("contact_email"):
            contact_email = rfq.get("contact_email", "").lower().strip()
            lead = by_email.get(contact_email)
            if lead:
                lead_id = str(lead["_id"])
                lead_name = lead.get("name") or ((lead.get("first_name", "") + " " + lead.get("last_name", "")).strip()) or lead.get("email")
                lead_name = lead_name.strip() if lead_name else None
        
        if not lead and rfq.get("sender_email") and rfq.get("sender_email") != rfq.get("contact_email"):
            sender_email = rfq.get("sender_email", "").lower().strip()
            lead = by_email.get(sender_email)
            if lead:
                lead_id = str(lead["_id"])
                lead_name = lead.get("name") or ((lead.get("first_name", "") + " " + lead.get("last_name", "")).strip()) or lead.get("email")
                lead_name = lead_name.strip() if lead_name else None
    else:
        # Original per-RFQ DB lookup (used for single-RFQ endpoints)
        if lead_id:
            try:
                lead = email_leads_collection.find_one({"_id": ObjectId(lead_id)})
                if lead:
                    lead_name = lead.get("name") or lead.get("first_name", "") + " " + lead.get("last_name", "") or lead.get("email")
                    lead_name = lead_name.strip() if lead_name else None
            except:
                pass
        
        if not lead and rfq.get("contact_email"):
            contact_email = rfq.get("contact_email", "").lower().strip()
            lead = email_leads_collection.find_one({"email": {"$regex": f"^{contact_email}$", "$options": "i"}})
            if lead:
                lead_id = str(lead["_id"])
                lead_name = lead.get("name") or lead.get("first_name", "") + " " + lead.get("last_name", "") or lead.get("email")
                lead_name = lead_name.strip() if lead_name else None
                try:
                    rfqs_collection.update_one({"_id": rfq["_id"]}, {"$set": {"lead_id": lead_id}})
                except Exception as e:
                    logger.warning(f"Failed to backfill lead_id for RFQ {rfq.get('rfq_id')}: {e}")
        
        if not lead and rfq.get("sender_email") and rfq.get("sender_email") != rfq.get("contact_email"):
            sender_email = rfq.get("sender_email", "").lower().strip()
            lead = email_leads_collection.find_one({"email": {"$regex": f"^{sender_email}$", "$options": "i"}})
            if lead:
                lead_id = str(lead["_id"])
                lead_name = lead.get("name") or lead.get("first_name", "") + " " + lead.get("last_name", "") or lead.get("email")
                lead_name = lead_name.strip() if lead_name else None
    
    return {
        "_id": str(rfq["_id"]),
        "rfq_id": rfq.get("rfq_id", ""),
        "contact_email": rfq.get("contact_email", ""),
        "lead_id": lead_id,
        "lead_name": lead_name or rfq.get("sender_name") or rfq.get("contact_email"),
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
        "created_by": rfq.get("created_by", "auto"),
        # New enhanced RFQ fields from AI extraction
        "methodology": rfq.get("methodology"),
        "loi": rfq.get("loi"),
        "ir": rfq.get("ir"),
        "country": rfq.get("country"),
        "sample_size": rfq.get("sample_size"),
        "target_audience": rfq.get("target_audience"),
        "timeline": rfq.get("timeline"),
        "study_type": rfq.get("study_type"),
        "budget": rfq.get("budget"),
        "additional_requirements": rfq.get("additional_requirements"),
        "ai_summary": rfq.get("ai_summary"),
        # Email body and sender details (for RFQ detail view)
        "email_body": rfq.get("email_body"),
        "sender_name": rfq.get("sender_name"),
        "sender_email": rfq.get("sender_email") or rfq.get("contact_email"),
        "sender_company": rfq.get("sender_company"),
        "sender_title": rfq.get("sender_title")
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
    Excludes soft-deleted RFQs.
    """
    # P0.18: Exclude soft-deleted RFQs
    query = {"is_deleted": {"$ne": True}}
    
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
    
    # PERF: Batch-fetch all referenced leads in 2 queries instead of N+1
    lead_ids = []
    emails = set()
    for r in rfqs:
        if r.get("lead_id"):
            try:
                lead_ids.append(ObjectId(r["lead_id"]))
            except Exception:
                pass
        if r.get("contact_email"):
            emails.add(r["contact_email"].lower().strip())
        if r.get("sender_email"):
            emails.add(r["sender_email"].lower().strip())
    
    leads_by_id = {}
    leads_by_email = {}
    if lead_ids:
        for lead in email_leads_collection.find({"_id": {"$in": lead_ids}}):
            leads_by_id[str(lead["_id"])] = lead
            if lead.get("email"):
                leads_by_email[lead["email"].lower().strip()] = lead
    if emails:
        remaining_emails = [e for e in emails if e not in leads_by_email]
        if remaining_emails:
            for lead in email_leads_collection.find({"email": {"$in": remaining_emails}}):
                leads_by_email[lead["email"].lower().strip()] = lead
                leads_by_id[str(lead["_id"])] = lead
    
    leads_cache = {"by_id": leads_by_id, "by_email": leads_by_email}
    
    return {
        "success": True,
        "rfqs": [rfq_to_response(rfq, leads_cache) for rfq in rfqs],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


@router.get("/stats")
async def get_rfq_stats() -> Dict[str, Any]:
    """
    Get RFQ statistics by status.
    Excludes soft-deleted RFQs.
    """
    pipeline = [
        # P0.18: Exclude soft-deleted RFQs
        {"$match": {"is_deleted": {"$ne": True}}},
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
    Excludes soft-deleted RFQs.
    """
    # P0.18: Exclude soft-deleted RFQs
    base_filter = {"is_deleted": {"$ne": True}}
    
    # Try to find by rfq_id first
    rfq = rfqs_collection.find_one({**base_filter, "rfq_id": rfq_id})
    
    # If not found, try by _id
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({**base_filter, "_id": ObjectId(rfq_id)})
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
        "created_by": "manual",
        # New enhanced RFQ fields
        "methodology": rfq_data.methodology,
        "loi": rfq_data.loi,
        "ir": rfq_data.ir,
        "country": rfq_data.country,
        "sample_size": rfq_data.sample_size
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
    
    P1.3: Validates status transitions via state machine.
    P1.2: Auto-creates/updates contact when status changes to 'won'.
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
    
    current_status = rfq.get("status", "pending")
    
    # P1.3: Validate status transition
    if rfq_data.status is not None and rfq_data.status != current_status:
        is_valid, error_msg = validate_status_transition(current_status, rfq_data.status)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition: {error_msg}"
            )
    
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
    # New enhanced RFQ fields
    if rfq_data.methodology is not None:
        update_doc["methodology"] = rfq_data.methodology
    if rfq_data.loi is not None:
        update_doc["loi"] = rfq_data.loi
    if rfq_data.ir is not None:
        update_doc["ir"] = rfq_data.ir
    if rfq_data.country is not None:
        update_doc["country"] = rfq_data.country
    if rfq_data.sample_size is not None:
        update_doc["sample_size"] = rfq_data.sample_size
    if rfq_data.target_audience is not None:
        update_doc["target_audience"] = rfq_data.target_audience
    if rfq_data.timeline is not None:
        update_doc["timeline"] = rfq_data.timeline
    if rfq_data.study_type is not None:
        update_doc["study_type"] = rfq_data.study_type
    if rfq_data.budget is not None:
        update_doc["budget"] = rfq_data.budget
    if rfq_data.additional_requirements is not None:
        update_doc["additional_requirements"] = rfq_data.additional_requirements
    
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
    
    # P1.2: Auto-create/update contact when RFQ is won
    contact_id = None
    promoted_lead_id = None
    
    if rfq_data.status == "won" and current_status != "won":
        contact_id = create_or_update_contact_on_win(updated_rfq)
    
    # Auto-promote lead to Contacts when RFQ is quoted
    # This moves the lead into the active sales pipeline for follow-up
    if rfq_data.status == "quoted" and current_status != "quoted":
        promoted_lead_id = promote_lead_to_contacts_on_quoted(updated_rfq)
    
    response = {
        "success": True,
        "message": "RFQ updated successfully",
        "rfq": rfq_to_response(updated_rfq)
    }
    
    if contact_id:
        response["contact_created"] = True
        response["contact_id"] = contact_id
    
    if promoted_lead_id:
        response["lead_promoted_to_contacts"] = True
        response["promoted_lead_id"] = promoted_lead_id
        response["message"] = "RFQ updated and lead promoted to Contacts"
    
    return response


@router.delete("/{rfq_id}")
async def delete_rfq(rfq_id: str) -> Dict[str, Any]:
    """
    Soft delete an RFQ.
    P0.18: Guards against deletion if linked estimates or invoices exist.
    """
    # P0.18: Exclude already soft-deleted RFQs
    base_filter = {"is_deleted": {"$ne": True}}
    
    # Find the RFQ
    rfq = rfqs_collection.find_one({**base_filter, "rfq_id": rfq_id})
    if not rfq:
        try:
            rfq = rfqs_collection.find_one({**base_filter, "_id": ObjectId(rfq_id)})
        except:
            pass
    
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    
    # P0.18: Guard - Check for linked estimates
    if rfq.get("estimate_id"):
        linked_estimate = estimates_collection.find_one({"_id": ObjectId(rfq["estimate_id"])})
        if linked_estimate:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete RFQ: linked to estimate {linked_estimate.get('estimate_number', rfq['estimate_id'])}. Delete the estimate first."
            )
    
    # P0.18: Guard - Check for linked invoices
    if rfq.get("invoice_id"):
        linked_invoice = invoices_collection.find_one({"_id": ObjectId(rfq["invoice_id"])})
        if linked_invoice:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete RFQ: linked to invoice {linked_invoice.get('invoice_number', rfq['invoice_id'])}. Delete the invoice first."
            )
    
    # Remove RFQ ID from lead (keep this for data consistency)
    if rfq.get("contact_email"):
        email_leads_collection.update_one(
            {"email": rfq["contact_email"]},
            {"$pull": {"rfq_ids": rfq["rfq_id"]}}
        )
    
    # P0.18: Soft delete instead of hard delete
    rfqs_collection.update_one(
        {"_id": rfq["_id"]},
        {"$set": {
            "is_deleted": True,
            "deleted_at": datetime.utcnow(),
            "deleted_by": "api_user"  # TODO: Replace with actual user from auth
        }}
    )
    
    logger.info(f"Soft deleted RFQ {rfq.get('rfq_id')}")
    
    return {
        "success": True,
        "message": f"RFQ {rfq.get('rfq_id')} deleted successfully"
    }


@router.post("/bulk-delete")
async def bulk_delete_rfqs(data: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Soft delete multiple RFQs by their IDs.
    P0.18: Guards against deletion if linked estimates or invoices exist.
    """
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    
    # P0.18: Exclude already soft-deleted RFQs
    base_filter = {"is_deleted": {"$ne": True}}
    
    deleted_count = 0
    skipped = []  # Track RFQs that couldn't be deleted
    
    for rfq_id in ids:
        # Find the RFQ
        rfq = rfqs_collection.find_one({**base_filter, "rfq_id": rfq_id})
        if not rfq:
            try:
                rfq = rfqs_collection.find_one({**base_filter, "_id": ObjectId(rfq_id)})
            except:
                continue
        
        if rfq:
            # P0.18: Guard - Check for linked estimates
            if rfq.get("estimate_id"):
                skipped.append({"rfq_id": rfq.get("rfq_id", rfq_id), "reason": "linked to estimate"})
                continue
            
            # P0.18: Guard - Check for linked invoices
            if rfq.get("invoice_id"):
                skipped.append({"rfq_id": rfq.get("rfq_id", rfq_id), "reason": "linked to invoice"})
                continue
            
            # Remove RFQ ID from lead
            if rfq.get("contact_email"):
                email_leads_collection.update_one(
                    {"email": rfq["contact_email"]},
                    {"$pull": {"rfq_ids": rfq.get("rfq_id")}}
                )
            
            # P0.18: Soft delete instead of hard delete
            rfqs_collection.update_one(
                {"_id": rfq["_id"]},
                {"$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": "api_user"  # TODO: Replace with actual user from auth
                }}
            )
            deleted_count += 1
    
    response = {
        "success": True,
        "message": f"Successfully deleted {deleted_count} RFQs",
        "deleted_count": deleted_count
    }
    
    if skipped:
        response["skipped"] = skipped
        response["message"] += f", skipped {len(skipped)} with linked documents"
    
    return response


@router.get("/by-lead/{lead_id}")
async def get_rfqs_by_lead(lead_id: str) -> Dict[str, Any]:
    """
    Get all RFQs for a specific lead.
    Excludes soft-deleted RFQs.
    """
    # P0.18: Exclude soft-deleted RFQs
    base_filter = {"is_deleted": {"$ne": True}}
    
    # First try to find by lead_id
    rfqs = list(rfqs_collection.find({**base_filter, "lead_id": lead_id}).sort("created_at", DESCENDING))
    
    # If no results, try to find by contact_email
    if not rfqs:
        # Check if lead_id is actually an email
        if "@" in lead_id:
            rfqs = list(rfqs_collection.find({**base_filter, "contact_email": lead_id}).sort("created_at", DESCENDING))
        else:
            # Try to get the lead's email first
            try:
                lead = email_leads_collection.find_one({"_id": ObjectId(lead_id)})
                if lead and lead.get("email"):
                    rfqs = list(rfqs_collection.find({**base_filter, "contact_email": lead["email"]}).sort("created_at", DESCENDING))
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


# =============================================================================
# RFQ Conversion Endpoints - Convert RFQ to Estimate or Invoice
# =============================================================================

class RFQConversionRequest(BaseModel):
    """Request model for RFQ conversion."""
    customer_id: Optional[str] = Field(None, description="Customer ID to bill. If not provided, will try to match from RFQ client info")
    unit_price: Optional[float] = Field(None, description="Price per complete. If not provided, calculated from RFQ value / sample_size")
    discount_percent: float = Field(0, description="Discount percentage to apply")
    tax_percent: float = Field(18, description="Tax/GST percentage")
    notes: Optional[str] = Field(None, description="Additional notes for estimate/invoice")
    due_days: int = Field(30, description="Payment due in days")
    line_items: Optional[List[Dict[str, Any]]] = Field(None, description="Custom line items. If not provided, auto-generated from RFQ")


class ConversionResponse(BaseModel):
    """Response model for RFQ conversion."""
    success: bool
    message: str
    document_type: str
    document_id: str
    document_number: str
    rfq_id: str
    total_amount: float


def _generate_line_items_from_rfq(rfq: Dict[str, Any], unit_price: Optional[float] = None) -> List[Dict[str, Any]]:
    """Generate invoice line items from RFQ data."""
    sample_size = rfq.get("sample_size", 0) or 0
    rfq_value = rfq.get("manual_value") or rfq.get("extracted_value") or 0
    
    # Calculate unit price if not provided
    if unit_price is None and sample_size > 0:
        unit_price = rfq_value / sample_size
    elif unit_price is None:
        unit_price = rfq_value
    
    items = []
    
    # Main survey line item
    methodology = rfq.get("methodology", "Online Survey")
    country = rfq.get("country", "")
    loi = rfq.get("loi", 0)
    ir = rfq.get("ir", 0)
    
    description = f"{methodology}"
    if country:
        description += f" - {country}"
    if loi:
        description += f" | LOI: {loi} mins"
    if ir:
        description += f" | IR: {ir}%"
    
    items.append({
        "description": description,
        "quantity": sample_size if sample_size > 0 else 1,
        "unit": "completes" if sample_size > 0 else "project",
        "unit_price": round(unit_price, 2),
        "amount": round(unit_price * (sample_size if sample_size > 0 else 1), 2)
    })
    
    return items


def _find_or_create_customer(rfq: Dict[str, Any]) -> Optional[str]:
    """Find existing customer or return None."""
    client_name = rfq.get("client_name", "").strip()
    client_email = rfq.get("client_email", "").strip()
    
    if not client_name and not client_email:
        return None
    
    # Try to find by email first
    if client_email:
        customer = customers_collection.find_one({"email": {"$regex": client_email, "$options": "i"}})
        if customer:
            return str(customer["_id"])
    
    # Try to find by name
    if client_name:
        customer = customers_collection.find_one({"name": {"$regex": f"^{client_name}$", "$options": "i"}})
        if customer:
            return str(customer["_id"])
    
    return None


def _get_next_document_number(collection, prefix: str) -> str:
    """Generate next document number."""
    today = datetime.utcnow()
    year_month = today.strftime("%Y%m")
    
    # Find the highest number for this month
    pattern = f"^{prefix}-{year_month}-"
    last_doc = collection.find_one(
        {"document_number": {"$regex": pattern}},
        sort=[("document_number", DESCENDING)]
    )
    
    if last_doc:
        try:
            last_num = int(last_doc["document_number"].split("-")[-1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1
    
    return f"{prefix}-{year_month}-{next_num:04d}"


@router.post("/{rfq_id}/convert-to-estimate", response_model=ConversionResponse)
async def convert_rfq_to_estimate(
    rfq_id: str,
    request: RFQConversionRequest
) -> ConversionResponse:
    """
    Convert an RFQ to an Estimate.
    
    This creates an estimate document in the finance system based on the RFQ details.
    The RFQ status is updated to 'quoted'.
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
    
    # Determine customer
    customer_id = request.customer_id
    if not customer_id:
        customer_id = _find_or_create_customer(rfq)
    
    if not customer_id:
        raise HTTPException(
            status_code=400, 
            detail="Customer not found. Please provide customer_id or ensure RFQ has valid client information."
        )
    
    # Verify customer exists
    try:
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")
    
    # Generate line items
    if request.line_items:
        line_items = request.line_items
    else:
        line_items = _generate_line_items_from_rfq(rfq, request.unit_price)
    
    # Calculate totals
    subtotal = sum(item.get("amount", 0) for item in line_items)
    discount_amount = subtotal * (request.discount_percent / 100)
    taxable_amount = subtotal - discount_amount
    tax_amount = taxable_amount * (request.tax_percent / 100)
    total = taxable_amount + tax_amount
    
    # Generate estimate number
    estimate_number = _get_next_document_number(estimates_collection, "EST")
    
    # Create estimate document
    now = datetime.utcnow()
    estimate = {
        "document_number": estimate_number,
        "estimate_number": estimate_number,
        "customer_id": customer_id,
        "customer_name": customer.get("name", ""),
        "rfq_id": rfq.get("rfq_id") or str(rfq["_id"]),
        "rfq_object_id": str(rfq["_id"]),
        "project_name": rfq.get("project_name", ""),
        "status": "draft",
        "date": now,
        "expiry_date": now + timedelta(days=request.due_days),
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "discount_percent": request.discount_percent,
        "discount_amount": round(discount_amount, 2),
        "tax_percent": request.tax_percent,
        "tax_amount": round(tax_amount, 2),
        "total": round(total, 2),
        "notes": request.notes or f"Estimate generated from RFQ: {rfq.get('project_name', rfq_id)}",
        "terms": f"Valid for {request.due_days} days from date of issue.",
        "created_at": now,
        "updated_at": now
    }
    
    result = estimates_collection.insert_one(estimate)
    estimate_id = str(result.inserted_id)
    
    # Update RFQ status and link
    rfqs_collection.update_one(
        {"_id": rfq["_id"]},
        {
            "$set": {
                "status": "quoted",
                "estimate_id": estimate_id,
                "estimate_number": estimate_number,
                "quoted_at": now,
                "quoted_value": total,
                "updated_at": now
            }
        }
    )
    
    logger.info(f"Converted RFQ {rfq_id} to Estimate {estimate_number}")
    
    return ConversionResponse(
        success=True,
        message=f"RFQ converted to estimate successfully",
        document_type="estimate",
        document_id=estimate_id,
        document_number=estimate_number,
        rfq_id=rfq.get("rfq_id") or str(rfq["_id"]),
        total_amount=round(total, 2)
    )


@router.post("/{rfq_id}/convert-to-invoice", response_model=ConversionResponse)
async def convert_rfq_to_invoice(
    rfq_id: str,
    request: RFQConversionRequest
) -> ConversionResponse:
    """
    Convert an RFQ directly to an Invoice.
    
    This creates an invoice document in the finance system based on the RFQ details.
    The RFQ status is updated to 'won'.
    Use this when a deal is confirmed and you want to skip the estimate stage.
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
    
    # Determine customer
    customer_id = request.customer_id
    if not customer_id:
        customer_id = _find_or_create_customer(rfq)
    
    if not customer_id:
        raise HTTPException(
            status_code=400, 
            detail="Customer not found. Please provide customer_id or ensure RFQ has valid client information."
        )
    
    # Verify customer exists
    try:
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")
    
    # Generate line items
    if request.line_items:
        line_items = request.line_items
    else:
        line_items = _generate_line_items_from_rfq(rfq, request.unit_price)
    
    # Calculate totals
    subtotal = sum(item.get("amount", 0) for item in line_items)
    discount_amount = subtotal * (request.discount_percent / 100)
    taxable_amount = subtotal - discount_amount
    tax_amount = taxable_amount * (request.tax_percent / 100)
    total = taxable_amount + tax_amount
    
    # Generate invoice number
    invoice_number = _get_next_document_number(invoices_collection, "INV")
    
    # Create invoice document
    now = datetime.utcnow()
    invoice = {
        "invoice_number": invoice_number,
        "customer_id": customer_id,
        "customer_name": customer.get("name", ""),
        "rfq_id": rfq.get("rfq_id") or str(rfq["_id"]),
        "rfq_object_id": str(rfq["_id"]),
        "project_name": rfq.get("project_name", ""),
        "project_id": rfq.get("project_id"),  # Link to project if exists
        "status": "pending",
        "date": now,
        "due_date": now + timedelta(days=request.due_days),
        "line_items": line_items,
        "subtotal": round(subtotal, 2),
        "discount_percent": request.discount_percent,
        "discount_amount": round(discount_amount, 2),
        "tax_percent": request.tax_percent,
        "tax_amount": round(tax_amount, 2),
        "total": round(total, 2),
        "amount_paid": 0,
        "balance_due": round(total, 2),
        "notes": request.notes or f"Invoice generated from RFQ: {rfq.get('project_name', rfq_id)}",
        "terms": f"Payment due within {request.due_days} days.",
        "created_at": now,
        "updated_at": now
    }
    
    result = invoices_collection.insert_one(invoice)
    invoice_id = str(result.inserted_id)
    
    # Update customer receivables
    customers_collection.update_one(
        {"_id": ObjectId(customer_id)},
        {
            "$inc": {"total_receivables": round(total, 2)},
            "$set": {"updated_at": now}
        }
    )
    
    # Update RFQ status and link
    rfqs_collection.update_one(
        {"_id": rfq["_id"]},
        {
            "$set": {
                "status": "won",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "invoiced_at": now,
                "invoiced_value": total,
                "won_at": now,
                "updated_at": now
            }
        }
    )
    
    logger.info(f"Converted RFQ {rfq_id} to Invoice {invoice_number}")
    
    return ConversionResponse(
        success=True,
        message=f"RFQ converted to invoice successfully",
        document_type="invoice",
        document_id=invoice_id,
        document_number=invoice_number,
        rfq_id=rfq.get("rfq_id") or str(rfq["_id"]),
        total_amount=round(total, 2)
    )


@router.post("/estimate/{estimate_id}/convert-to-invoice", response_model=ConversionResponse)
async def convert_estimate_to_invoice(
    estimate_id: str,
    due_days: int = Query(30, description="Payment due in days")
) -> ConversionResponse:
    """
    Convert an Estimate to an Invoice.
    
    This creates an invoice from an existing estimate and updates the linked RFQ status to 'won'.
    """
    # Find the estimate
    try:
        estimate = estimates_collection.find_one({"_id": ObjectId(estimate_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid estimate_id format")
    
    if not estimate:
        raise HTTPException(status_code=404, detail="Estimate not found")
    
    # Generate invoice number
    invoice_number = _get_next_document_number(invoices_collection, "INV")
    
    now = datetime.utcnow()
    
    # Create invoice from estimate
    invoice = {
        "invoice_number": invoice_number,
        "customer_id": estimate.get("customer_id"),
        "customer_name": estimate.get("customer_name", ""),
        "rfq_id": estimate.get("rfq_id"),
        "rfq_object_id": estimate.get("rfq_object_id"),
        "estimate_id": estimate_id,
        "estimate_number": estimate.get("estimate_number"),
        "project_name": estimate.get("project_name", ""),
        "status": "pending",
        "date": now,
        "due_date": now + timedelta(days=due_days),
        "line_items": estimate.get("line_items", []),
        "subtotal": estimate.get("subtotal", 0),
        "discount_percent": estimate.get("discount_percent", 0),
        "discount_amount": estimate.get("discount_amount", 0),
        "tax_percent": estimate.get("tax_percent", 18),
        "tax_amount": estimate.get("tax_amount", 0),
        "total": estimate.get("total", 0),
        "amount_paid": 0,
        "balance_due": estimate.get("total", 0),
        "notes": estimate.get("notes", ""),
        "terms": f"Payment due within {due_days} days.",
        "created_at": now,
        "updated_at": now
    }
    
    result = invoices_collection.insert_one(invoice)
    invoice_id = str(result.inserted_id)
    total = estimate.get("total", 0)
    
    # Update estimate status
    estimates_collection.update_one(
        {"_id": ObjectId(estimate_id)},
        {
            "$set": {
                "status": "accepted",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "converted_at": now,
                "updated_at": now
            }
        }
    )
    
    # Update customer receivables
    customer_id = estimate.get("customer_id")
    if customer_id:
        try:
            customers_collection.update_one(
                {"_id": ObjectId(customer_id)},
                {
                    "$inc": {"total_receivables": round(total, 2)},
                    "$set": {"updated_at": now}
                }
            )
        except:
            pass
    
    # Update linked RFQ if exists
    rfq_object_id = estimate.get("rfq_object_id")
    if rfq_object_id:
        try:
            rfqs_collection.update_one(
                {"_id": ObjectId(rfq_object_id)},
                {
                    "$set": {
                        "status": "won",
                        "invoice_id": invoice_id,
                        "invoice_number": invoice_number,
                        "invoiced_at": now,
                        "invoiced_value": total,
                        "won_at": now,
                        "updated_at": now
                    }
                }
            )
        except:
            pass
    
    logger.info(f"Converted Estimate {estimate_id} to Invoice {invoice_number}")
    
    return ConversionResponse(
        success=True,
        message=f"Estimate converted to invoice successfully",
        document_type="invoice",
        document_id=invoice_id,
        document_number=invoice_number,
        rfq_id=estimate.get("rfq_id", ""),
        total_amount=round(total, 2)
    )


# =============================================================================
# Gmail Email to RFQ Sync - Convert classified Gmail emails to RFQs
# =============================================================================

def generate_rfq_id_for_sync() -> str:
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


def extract_rfq_details_from_summary(summary: str, subject: str) -> Dict[str, Any]:
    """Extract RFQ details from AI summary and subject"""
    import re
    
    details = {
        "loi": None,
        "ir": None,
        "sample_size": None,
        "country": None,
        "methodology": None,
        "study_type": None
    }
    
    text = f"{subject} {summary}".lower()
    
    # Extract LOI
    loi_patterns = [
        r'(\d+)\s*(?:min(?:ute)?s?)\s*(?:loi|interview)',
        r'loi[:\s]+(\d+)',
        r'(\d+)\s*min\b'
    ]
    for pattern in loi_patterns:
        match = re.search(pattern, text)
        if match:
            details["loi"] = int(match.group(1))
            break
    
    # Extract IR
    ir_patterns = [
        r'(\d+(?:\.\d+)?)\s*%\s*(?:ir|incidence)',
        r'ir[:\s]+(\d+(?:\.\d+)?)',
        r'incidence[:\s]+(\d+(?:\.\d+)?)'
    ]
    for pattern in ir_patterns:
        match = re.search(pattern, text)
        if match:
            details["ir"] = float(match.group(1))
            break
    
    # Extract sample size
    n_patterns = [
        r'n\s*[=:]\s*(\d+)',
        r'(\d+)\s*(?:completes?|respondents?|sample)',
        r'sample\s*(?:size)?[:\s]*(\d+)'
    ]
    for pattern in n_patterns:
        match = re.search(pattern, text)
        if match:
            details["sample_size"] = int(match.group(1))
            break
    
    # Extract country
    countries = ["us", "usa", "uk", "india", "germany", "france", "brazil", "canada", "australia", "japan", "china", "global", "multi-country", "apac", "emea", "latam"]
    for country in countries:
        if country in text:
            details["country"] = country.upper()
            break
    
    # Extract methodology
    methodologies = ["cati", "cawi", "f2f", "face to face", "online", "phone", "web", "panel", "idi", "focus group"]
    for method in methodologies:
        if method in text:
            details["methodology"] = method.upper()
            break
    
    # Extract study type
    if "healthcare" in text or "hcp" in text or "physician" in text:
        details["study_type"] = "Healthcare"
    elif "b2b" in text or "business" in text:
        details["study_type"] = "B2B"
    elif "it " in text or "technology" in text:
        details["study_type"] = "IT"
    elif "consumer" in text or "b2c" in text:
        details["study_type"] = "Consumer"
    
    return details


@router.post("/sync-from-gmail")
async def sync_rfqs_from_gmail(
    limit: int = Query(100, description="Maximum emails to process"),
    categories: List[str] = Query(["client", "rfq"], description="AI categories to include")
) -> Dict[str, Any]:
    """
    Sync classified Gmail emails to RFQs.
    
    Converts emails with ai_category='client' or 'rfq' from torpedo_gmail.email_metadata
    to RFQs in email_automation.rfqs collection.
    """
    try:
        # Find classified emails that haven't been synced to RFQs yet
        query = {
            "ai_category": {"$in": categories},
            "rfq_synced": {"$ne": True}  # Not already synced
        }
        
        emails = list(email_metadata_collection.find(query).limit(limit))
        
        if not emails:
            return {
                "success": True,
                "message": "No new emails to sync",
                "synced": 0,
                "skipped": 0
            }
        
        synced = 0
        skipped = 0
        errors = []
        
        for email in emails:
            try:
                # Get sender email (external party)
                from_email = email.get("from_email", "")
                to_emails = email.get("to_emails", [])
                
                # Determine the client email (the external party)
                # If from_email is internal, use to_email as contact
                internal_domains = ["cogentixresearch.com", "surveyfieldwork.com"]
                from_domain = from_email.split("@")[-1].lower() if "@" in from_email else ""
                
                if from_domain in internal_domains:
                    # Outbound email - find external recipient
                    contact_email = None
                    for to_email in to_emails:
                        to_domain = to_email.split("@")[-1].lower() if "@" in to_email else ""
                        if to_domain not in internal_domains:
                            contact_email = to_email
                            break
                    if not contact_email:
                        skipped += 1
                        continue
                else:
                    # Inbound email - sender is the client
                    contact_email = from_email
                
                if not contact_email:
                    skipped += 1
                    continue
                
                # Skip noreply, bounce, etc.
                skip_patterns = ["noreply", "no-reply", "mailer-daemon", "postmaster", "bounce"]
                if any(p in contact_email.lower() for p in skip_patterns):
                    skipped += 1
                    continue
                
                # Check if RFQ already exists for this thread
                thread_id = email.get("gmail_thread_id", "")
                if thread_id:
                    existing = rfqs_collection.find_one({"gmail_thread_id": thread_id})
                    if existing:
                        # Mark as synced but skip
                        email_metadata_collection.update_one(
                            {"_id": email["_id"]},
                            {"$set": {"rfq_synced": True, "rfq_id": existing["rfq_id"]}}
                        )
                        skipped += 1
                        continue
                
                # Extract RFQ details from AI summary
                summary = email.get("ai_summary", "")
                subject = email.get("subject", "")
                rfq_details = extract_rfq_details_from_summary(summary, subject)
                
                # Get sender info
                sender_info = email.get("sender_info", {})
                
                # Generate RFQ ID
                rfq_id = generate_rfq_id_for_sync()
                
                # Create RFQ document
                rfq_doc = {
                    "rfq_id": rfq_id,
                    "contact_email": contact_email,
                    "title": subject or "RFQ Request",
                    "description": summary[:2000] if summary else "",
                    "extracted_value": None,
                    "extracted_currency": "USD",
                    "manual_value": None,
                    "manual_currency": None,
                    # AI-extracted fields
                    "methodology": rfq_details.get("methodology"),
                    "loi": rfq_details.get("loi"),
                    "ir": rfq_details.get("ir"),
                    "sample_size": rfq_details.get("sample_size"),
                    "country": rfq_details.get("country"),
                    "study_type": rfq_details.get("study_type"),
                    "target_audience": None,
                    "timeline": None,
                    # Sender info
                    "sender_name": sender_info.get("name", email.get("from_name", "")),
                    "sender_company": sender_info.get("company_name", ""),
                    "sender_title": sender_info.get("title", ""),
                    # AI summary
                    "ai_summary": summary,
                    # Source tracking
                    "gmail_thread_id": thread_id,
                    "gmail_message_id": email.get("gmail_message_id", ""),
                    "source_emails": [{
                        "message_id": email.get("gmail_message_id", ""),
                        "subject": subject,
                        "date": email.get("timestamp"),
                        "from": from_email
                    }],
                    # Standard fields
                    "status": "pending",
                    "priority": "high" if email.get("ai_urgency") == "high" else "medium",
                    "received_date": email.get("timestamp", datetime.utcnow()),
                    "due_date": None,
                    "summary": "",
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_by": "gmail_sync"
                }
                
                rfqs_collection.insert_one(rfq_doc)
                
                # Mark email as synced
                email_metadata_collection.update_one(
                    {"_id": email["_id"]},
                    {"$set": {"rfq_synced": True, "rfq_id": rfq_id}}
                )
                
                synced += 1
                logger.info(f"Created RFQ {rfq_id} from Gmail thread {thread_id}")
                
            except Exception as e:
                errors.append(str(e))
                logger.error(f"Error syncing email {email.get('_id')}: {e}")
        
        return {
            "success": True,
            "message": f"Synced {synced} emails to RFQs, skipped {skipped}",
            "synced": synced,
            "skipped": skipped,
            "errors": errors[:10] if errors else None
        }
        
    except Exception as e:
        logger.error(f"Error syncing Gmail to RFQs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync-status")
async def get_sync_status() -> Dict[str, Any]:
    """Get Gmail to RFQ sync status"""
    try:
        # Count emails by category
        pipeline = [
            {"$match": {"ai_category": {"$in": ["client", "rfq"]}}},
            {"$group": {
                "_id": {
                    "category": "$ai_category",
                    "synced": {"$ifNull": ["$rfq_synced", False]}
                },
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(email_metadata_collection.aggregate(pipeline))
        
        stats = {
            "client_total": 0,
            "client_synced": 0,
            "rfq_total": 0,
            "rfq_synced": 0,
            "total_rfqs": rfqs_collection.count_documents({"is_deleted": {"$ne": True}})
        }
        
        for r in results:
            cat = r["_id"]["category"]
            synced = r["_id"]["synced"]
            count = r["count"]
            
            if cat == "client":
                stats["client_total"] += count
                if synced:
                    stats["client_synced"] = count
            elif cat == "rfq":
                stats["rfq_total"] += count
                if synced:
                    stats["rfq_synced"] = count
        
        stats["pending_sync"] = (stats["client_total"] - stats["client_synced"]) + (stats["rfq_total"] - stats["rfq_synced"])
        
        return {
            "success": True,
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
