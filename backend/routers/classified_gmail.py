"""
Classified Gmail Router
Handles classified email management and moves to leads
Integrates with email_processor.py for classification and enrichment
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

# Import name extraction utility
from leads.gmail_leads_service import extract_name_from_email

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/classified-gmail",
    tags=["classified-gmail"]
)

# MongoDB connections
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# Databases
email_db = mongo_client["email_automation"]
leads_db = mongo_client["email_automation"]

# Collections
classified_gmail_collection = email_db["classified_gmail"]
mail_pool_collection = email_db["mail_pool"]
leads_raw_collection = leads_db["leads_raw"]
vendor_leads_collection = leads_db["vendor_leads"]
enrichment_logs_collection = email_db["enrichment_logs"]
email_leads_collection = email_db["email_leads"]

# Gmail workspace database for sent email tracking
torpedo_gmail_db = mongo_client["torpedo_gmail"]
email_metadata_collection = torpedo_gmail_db["email_metadata"]


# ============== HELPER: CHECK IF WE'VE REPLIED TO SENDER ==============

def has_sent_email_to(email_address: str) -> bool:
    """
    Check if we have previously sent an email to this address.
    Used to determine if a classified email should be auto-moved to leads.
    Contacts we've interacted with are higher quality leads.
    """
    if not email_address:
        return False
    
    email_lower = email_address.lower().strip()
    
    # Check torpedo_gmail.email_metadata for sent emails to this address
    sent_to_contact = email_metadata_collection.find_one({
        "direction": "sent",
        "$or": [
            {"to_email": email_lower},
            {"to_email": {"$regex": email_lower, "$options": "i"}},
            {"recipients": {"$elemMatch": {"$regex": email_lower, "$options": "i"}}}
        ]
    })
    
    return sent_to_contact is not None


# ============== MODELS ==============

class ClassifiedEmailSegment(str):
    """Email segment types"""
    CLIENT = "CLIENT"
    VENDOR = "VENDOR"
    RECRUITER = "RECRUITER"
    INTERNAL = "INTERNAL"
    SPAM = "SPAM"
    UNKNOWN = "UNKNOWN"


class ClassifiedEmail(BaseModel):
    """Classified email document"""
    email_id: str = Field(..., description="Original email_id from mail_pool")
    segment: str = Field(..., description="Email segment (CLIENT, VENDOR, RECRUITER, INTERNAL, SPAM)")
    priority: int = Field(default=0, ge=0, le=10, description="Priority score 0-10")
    sender_email: str
    sender_name: Optional[str] = None
    subject: str
    body_preview: str
    summary: Optional[str] = None
    contacts: List[Dict] = Field(default_factory=list)
    sentiment: Optional[str] = None  # positive, neutral, negative
    category: Optional[str] = None
    confidence_score: float = Field(default=0.5, ge=0, le=1)
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    moved_to_leads: bool = Field(default=False)
    moved_at: Optional[datetime] = None
    moved_by: Optional[str] = None
    lead_id: Optional[str] = None  # Reference to created lead
    notes: str = Field(default="")


class MoveToLeadsRequest(BaseModel):
    """Request to move classified email to leads"""
    segment: str = Field(..., description="Target segment: CLIENT, VENDOR, or INTERNAL")
    category: Optional[str] = None
    stage: str = Field(default="lead_generation")
    notes: Optional[str] = None


class ClassifiedEmailResponse(BaseModel):
    """Response with classified email details"""
    id: str
    email_id: str
    segment: str
    priority: int
    sender_email: str
    subject: str
    summary: Optional[str]
    sentiment: Optional[str]
    category: Optional[str]
    confidence_score: float
    processed_at: str
    moved_to_leads: bool
    moved_at: Optional[str]
    lead_id: Optional[str]
    notes: str


# ============== UTILITY FUNCTIONS ==============

def get_session_user(authorization: Optional[str] = None) -> str:
    """Extract user from session (simplified)"""
    # In production, validate session token
    return authorization or "system"


def ensure_indexes():
    """Create necessary indexes"""
    try:
        classified_gmail_collection.create_index([("email_id", 1)], unique=True)
        classified_gmail_collection.create_index([("segment", 1)])
        classified_gmail_collection.create_index([("priority", -1)])
        classified_gmail_collection.create_index([("processed_at", -1)])
        classified_gmail_collection.create_index([("moved_to_leads", 1)])
        classified_gmail_collection.create_index([("created_at", -1)])
        logger.info("Indexes ensured for classified_gmail")
    except Exception as e:
        logger.warning(f"Failed to create indexes: {e}")


# Ensure indexes on startup
ensure_indexes()


# ============== ENDPOINTS ==============

@router.get("/stats", summary="Get classified emails statistics")
async def get_stats(days: int = Query(7, ge=1, le=90)) -> Dict:
    """
    Get statistics on classified emails
    - Total classified by segment
    - Success rate by segment
    - Pending moves to leads
    - Average priority by segment
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get segment breakdown
        segment_stats = list(classified_gmail_collection.aggregate([
            {"$match": {"processed_at": {"$gte": cutoff_date}}},
            {
                "$group": {
                    "_id": "$segment",
                    "count": {"$sum": 1},
                    "avg_priority": {"$avg": "$priority"},
                    "avg_confidence": {"$avg": "$confidence_score"},
                    "moved_count": {
                        "$sum": {"$cond": ["$moved_to_leads", 1, 0]}
                    }
                }
            },
            {"$sort": {"count": -1}}
        ]))
        
        # Get total stats
        total = classified_gmail_collection.count_documents(
            {"processed_at": {"$gte": cutoff_date}}
        )
        moved_total = classified_gmail_collection.count_documents(
            {"processed_at": {"$gte": cutoff_date}, "moved_to_leads": True}
        )
        
        # Get pending (not moved) count
        pending = total - moved_total
        
        return {
            "period_days": days,
            "total_classified": total,
            "total_moved_to_leads": moved_total,
            "pending_moves": pending,
            "move_success_rate": (moved_total / total * 100) if total > 0 else 0,
            "by_segment": [
                {
                    "segment": stat["_id"],
                    "count": stat["count"],
                    "moved": stat["moved_count"],
                    "move_rate": (stat["moved_count"] / stat["count"] * 100) if stat["count"] > 0 else 0,
                    "avg_priority": round(stat["avg_priority"], 2),
                    "avg_confidence": round(stat["avg_confidence"], 2)
                }
                for stat in segment_stats
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", summary="List classified emails with pagination")
async def list_classified(
    segment: Optional[str] = Query(None, description="Filter by segment"),
    moved: Optional[bool] = Query(None, description="Filter by moved status"),
    priority_min: int = Query(0, ge=0, le=10),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("processed_at", enum=["processed_at", "priority", "confidence_score"])
) -> Dict:
    """
    List classified emails with filters and pagination
    """
    try:
        # Build filter
        filter_dict = {}
        if segment:
            filter_dict["segment"] = segment
        if moved is not None:
            filter_dict["moved_to_leads"] = moved
        if priority_min > 0:
            filter_dict["priority"] = {"$gte": priority_min}
        
        # Count total
        total = classified_gmail_collection.count_documents(filter_dict)
        
        # Get page
        skip = (page - 1) * limit
        sort_order = -1 if sort_by == "processed_at" else 1
        
        emails = list(classified_gmail_collection.find(filter_dict)
            .sort(sort_by, sort_order)
            .skip(skip)
            .limit(limit))
        
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
            "emails": [
                {
                    "id": str(email["_id"]),
                    "email_id": email.get("email_id"),
                    "segment": email.get("segment"),
                    "priority": email.get("priority", 0),
                    "sender_email": email.get("sender_email"),
                    "subject": email.get("subject"),
                    "summary": email.get("summary"),
                    "sentiment": email.get("sentiment"),
                    "confidence_score": email.get("confidence_score", 0),
                    "processed_at": email.get("processed_at", datetime.utcnow()).isoformat(),
                    "moved_to_leads": email.get("moved_to_leads", False),
                    "notes": email.get("notes", "")
                }
                for email in emails
            ]
        }
    except Exception as e:
        logger.error(f"Error listing classified emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{email_id}", summary="Get classified email details")
async def get_classified_email(email_id: str) -> Dict:
    """
    Get full details of a classified email including:
    - Classification results
    - Extracted contacts
    - Summary and sentiment
    - Move history
    """
    try:
        email = classified_gmail_collection.find_one({"_id": ObjectId(email_id)})
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return {
            "id": str(email["_id"]),
            "email_id": email.get("email_id"),
            "segment": email.get("segment"),
            "priority": email.get("priority", 0),
            "sender_email": email.get("sender_email"),
            "sender_name": email.get("sender_name"),
            "subject": email.get("subject"),
            "body_preview": email.get("body_preview"),
            "summary": email.get("summary"),
            "sentiment": email.get("sentiment"),
            "category": email.get("category"),
            "confidence_score": email.get("confidence_score", 0),
            "contacts": email.get("contacts", []),
            "processed_at": email.get("processed_at", datetime.utcnow()).isoformat(),
            "moved_to_leads": email.get("moved_to_leads", False),
            "moved_at": email.get("moved_at", "").isoformat() if email.get("moved_at") else None,
            "moved_by": email.get("moved_by"),
            "lead_id": email.get("lead_id"),
            "notes": email.get("notes", "")
        }
    except Exception as e:
        logger.error(f"Error fetching email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{email_id}/move-to-leads", summary="Move classified email to leads")
async def move_to_leads(
    email_id: str,
    request: MoveToLeadsRequest,
    authorization: Optional[str] = None
) -> Dict:
    """
    Move a classified email to leads collection
    Creates a new lead with enriched data from classification
    """
    try:
        # Get classified email
        classified = classified_gmail_collection.find_one({"_id": ObjectId(email_id)})
        if not classified:
            raise HTTPException(status_code=404, detail="Classified email not found")
        
        if classified.get("moved_to_leads"):
            raise HTTPException(status_code=400, detail="Email already moved to leads")
        
        # Extract name properly - use display name first, fallback to email parsing
        sender_email = classified.get("sender_email", "")
        sender_name = classified.get("sender_name", "")
        
        # Use extract_name_from_email to properly parse names from email format
        # This handles cases like "john.doe@company.com" → "John", "Doe"
        full_name, first_name, last_name = extract_name_from_email(sender_email, sender_name)
        
        # Create lead document
        lead_doc = {
            "source": "classified_gmail",
            "email": sender_email,
            "full_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "title": next(
                (c.get("title") for c in classified.get("contacts", []) if c.get("title")),
                ""
            ),
            "company_name": next(
                (c.get("company") for c in classified.get("contacts", []) if c.get("company")),
                ""
            ),
            "segment": request.segment,
            "category": request.category or classified.get("category"),
            "confidence_score": classified.get("confidence_score", 0),
            "email_summary": classified.get("summary"),
            "email_sentiment": classified.get("sentiment"),
            "classification_segment": classified.get("segment"),
            "classified_email_id": classified.get("email_id"),
            "contacts": classified.get("contacts", []),
            "stage": request.stage,
            "created_at": datetime.utcnow(),
            "created_from": "classified_gmail",
            "notes": request.notes or ""
        }
        
        # Determine which collection to insert into
        if request.segment == "VENDOR":
            result = vendor_leads_collection.insert_one(lead_doc)
        else:
            result = leads_raw_collection.insert_one(lead_doc)
        
        lead_id = str(result.inserted_id)
        
        # Update classified email with move info
        user = get_session_user(authorization)
        classified_gmail_collection.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "moved_to_leads": True,
                    "moved_at": datetime.utcnow(),
                    "moved_by": user,
                    "lead_id": lead_id
                }
            }
        )
        
        # Log enrichment
        enrichment_logs_collection.insert_one({
            "email_id": classified.get("email_id"),
            "classified_id": email_id,
            "lead_id": lead_id,
            "segment": request.segment,
            "timestamp": datetime.utcnow(),
            "action": "moved_to_leads",
            "user": user
        })
        
        return {
            "success": True,
            "lead_id": lead_id,
            "segment": request.segment,
            "message": f"Email moved to {request.segment} leads"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving to leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{email_id}/mark-spam", summary="Mark email as spam")
async def mark_spam(email_id: str, reason: str = "") -> Dict:
    """Mark classified email as spam and skip future similar emails"""
    try:
        classified = classified_gmail_collection.find_one({"_id": ObjectId(email_id)})
        if not classified:
            raise HTTPException(status_code=404, detail="Email not found")
        
        classified_gmail_collection.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "segment": "SPAM",
                    "updated_at": datetime.utcnow(),
                    "spam_reason": reason
                }
            }
        )
        
        return {"success": True, "message": "Email marked as spam"}
    except Exception as e:
        logger.error(f"Error marking spam: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{email_id}/add-notes", summary="Add notes to classified email")
async def add_notes(email_id: str, notes: str) -> Dict:
    """Add or update notes on a classified email"""
    try:
        result = classified_gmail_collection.update_one(
            {"_id": ObjectId(email_id)},
            {"$set": {"notes": notes, "updated_at": datetime.utcnow()}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return {"success": True, "message": "Notes updated"}
    except Exception as e:
        logger.error(f"Error updating notes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{email_id}", summary="Delete classified email")
async def delete_classified(email_id: str) -> Dict:
    """Delete a classified email (soft delete recommended)"""
    try:
        result = classified_gmail_collection.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "deleted": True,
                    "deleted_at": datetime.utcnow()
                }
            }
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return {"success": True, "message": "Email deleted"}
    except Exception as e:
        logger.error(f"Error deleting email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch/process", summary="Process batch of emails from torpedo_gmail.email_metadata")
async def process_batch(
    limit: int = Query(50, ge=1, le=500),
    priority_only: bool = Query(False, description="Unused — kept for API compatibility"),
    auto_move: bool = Query(True, description="Auto-move high-confidence CLIENT/VENDOR emails to leads"),
) -> Dict:
    """
    Classify a batch of inbound emails from torpedo_gmail.email_metadata
    using AI and auto-move high-confidence CLIENT/VENDOR emails to sales leads.

    Supersedes the legacy mail_pool-based batch processor.
    """
    try:
        try:
            from leads.email_processor import EmailProcessor
        except ImportError:
            from backend.leads.email_processor import EmailProcessor

        processor = EmailProcessor()

        # since_hours=2 keeps the classifier focused on recent mail;
        # a separate backfill job handles older emails.
        stats = processor.process_batch_from_metadata(limit=limit, since_hours=2)

        return {
            "processed": stats.get("total_processed", 0),
            "auto_moved_to_leads": stats.get("auto_moved_to_leads", 0) if auto_move else 0,
            "by_segment": stats.get("by_segment", {}),
            "duration_seconds": stats.get("duration_seconds", 0),
            "errors": stats.get("errors", [])[:5],
            "message": (
                f"Classified {stats.get('total_processed', 0)} emails, "
                f"added {stats.get('auto_moved_to_leads', 0)} to Sales Leads"
            ),
        }
    except Exception as e:
        logger.error(f"[ClassifiedGmail] batch/process error: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/analytics/segment-flow", summary="Get segment flow analytics")
async def get_segment_flow(days: int = Query(30, ge=1, le=365)) -> Dict:
    """
    Analyze segment flow:
    - How many emails classified as CLIENT, VENDOR, etc.
    - How many moved to leads
    - Conversion rates by segment
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        segments = ["CLIENT", "VENDOR", "RECRUITER", "INTERNAL", "SPAM"]
        flow_data = []
        
        for segment in segments:
            classified = classified_gmail_collection.count_documents({
                "segment": segment,
                "processed_at": {"$gte": cutoff_date}
            })
            
            moved = classified_gmail_collection.count_documents({
                "segment": segment,
                "moved_to_leads": True,
                "processed_at": {"$gte": cutoff_date}
            })
            
            conversion_rate = (moved / classified * 100) if classified > 0 else 0
            
            flow_data.append({
                "segment": segment,
                "total_classified": classified,
                "moved_to_leads": moved,
                "pending": classified - moved,
                "conversion_rate": round(conversion_rate, 2)
            })
        
        return {
            "period_days": days,
            "segments": flow_data,
            "total": sum(s["total_classified"] for s in flow_data),
            "total_moved": sum(s["moved_to_leads"] for s in flow_data)
        }
    except Exception as e:
        logger.error(f"Error in segment flow analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))
