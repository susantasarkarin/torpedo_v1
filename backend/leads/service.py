"""
AGENT 4 — BACKEND SERVICE LAYER
Lead management service with async processing

Cost Optimization:
    - Deduplication index to prevent duplicate leads
    - Tracks dedup index for fast lookups
"""

import os
from datetime import datetime
from typing import Optional, List, Tuple
from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

from .models import (
    LeadInput, LeadRaw, LeadEnriched, AIClassificationLog,
    LeadImportResponse, LeadFilterParams, ClassificationStatus,
    SeniorityLevel, Department, Persona, CompanySize, Region,
    BuyingRole, Gender, EmailStatus
)
from .ai_classifier import classify_lead
from .deduplication import (
    check_duplicate,
    add_to_dedup_index,
    log_rejected_duplicate
)

load_dotenv()

# ============== DATABASE CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Collections
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']
leads_collection = db['leads']  # Legacy leads collection (used by main.py)
classification_logs_collection = db['lead_ai_classification_logs']
campaigns_collection = db['campaigns']

# ============== ENSURE INDEXES ==============

def ensure_indexes():
    """Create necessary indexes for performance"""
    # leads_raw indexes
    leads_raw_collection.create_index("linkedin_url", unique=True)
    leads_raw_collection.create_index("created_at")
    leads_raw_collection.create_index("classification_status")
    leads_raw_collection.create_index([("classification_status", ASCENDING), ("classification_attempts", ASCENDING)])
    
    # leads_enriched indexes
    leads_enriched_collection.create_index("raw_lead_id")
    leads_enriched_collection.create_index("linkedin_url", unique=True)
    leads_enriched_collection.create_index("seniority_level")
    leads_enriched_collection.create_index("department")
    leads_enriched_collection.create_index("persona")
    leads_enriched_collection.create_index("industry")
    leads_enriched_collection.create_index("region")
    leads_enriched_collection.create_index("confidence_score")
    leads_enriched_collection.create_index("campaign_ids")
    leads_enriched_collection.create_index("stage")  # For lead_stage filtering
    
    # classification_logs indexes
    classification_logs_collection.create_index("raw_lead_id")
    classification_logs_collection.create_index("created_at")
    classification_logs_collection.create_index("success")

# Run on module load
try:
    ensure_indexes()
except Exception as e:
    print(f"Warning: Could not create indexes: {e}")


# ============== IMPORT SERVICE ==============

def import_leads(leads: List[LeadInput], skip_dedup_check: bool = False) -> LeadImportResponse:
    """
    Import raw leads with idempotent behavior (skip duplicates).
    
    Args:
        leads: List of LeadInput objects to import
        skip_dedup_check: Skip pre-import deduplication check (faster but may hit DB errors)
        
    Returns:
        LeadImportResponse with import stats
    """
    imported = 0
    duplicates = 0
    errors = 0
    lead_ids = []
    
    for lead_input in leads:
        try:
            # Pre-import deduplication check (optional but recommended)
            if not skip_dedup_check:
                dedup_result = check_duplicate(
                    linkedin_url=lead_input.linkedin_url,
                    email=lead_input.email,
                    name=lead_input.name,
                    company_name=lead_input.company_name
                )
                if dedup_result.is_duplicate:
                    log_rejected_duplicate(
                        lead=lead_input.model_dump() if hasattr(lead_input, 'model_dump') else dict(lead_input),
                        reason=dedup_result.reason,
                        source=lead_input.source or "import"
                    )
                    if dedup_result.existing_lead_id:
                        lead_ids.append(dedup_result.existing_lead_id)
                    duplicates += 1
                    continue
            
            lead_raw = LeadRaw(
                name=lead_input.name,
                title=lead_input.title,
                linkedin_url=lead_input.linkedin_url,
                snippet=lead_input.snippet or "",
                source=lead_input.source,
                first_name=lead_input.first_name,
                last_name=lead_input.last_name,
                email=lead_input.email,
                email_status=lead_input.email_status,
                location=lead_input.location,
                company_name=lead_input.company_name,
                company_domain=lead_input.company_domain,
                company_website=lead_input.company_website,
                company_employee_count=lead_input.company_employee_count,
                company_employee_count_range=lead_input.company_employee_count_range,
                company_founded=lead_input.company_founded,
                company_industry=lead_input.company_industry,
                company_type=lead_input.company_type,
                company_headquarters=lead_input.company_headquarters,
                company_revenue_range=lead_input.company_revenue_range,
                company_linkedin_url=lead_input.company_linkedin_url,
                created_at=datetime.utcnow(),
                classification_status=ClassificationStatus.PENDING
            )
            
            result = leads_raw_collection.insert_one(lead_raw.model_dump())
            lead_id = str(result.inserted_id)
            lead_ids.append(lead_id)
            imported += 1
            
            # Add to deduplication index for future lookups
            add_to_dedup_index(
                lead_id=lead_id,
                linkedin_url=lead_input.linkedin_url,
                email=lead_input.email,
                name=lead_input.name,
                company_name=lead_input.company_name
            )
            
        except DuplicateKeyError:
            # Lead already exists - this is expected for idempotent imports
            existing = leads_raw_collection.find_one({"linkedin_url": lead_input.linkedin_url})
            if existing:
                lead_ids.append(str(existing["_id"]))
            duplicates += 1
            
        except Exception as e:
            print(f"Error importing lead {lead_input.linkedin_url}: {e}")
            errors += 1
    
    return LeadImportResponse(
        imported=imported,
        duplicates=duplicates,
        errors=errors,
        lead_ids=lead_ids
    )


# ============== CLASSIFICATION SERVICE ==============

def get_pending_leads(limit: Optional[int] = None) -> List[dict]:
    """Get leads pending classification with retry limit. If limit is None, get ALL pending."""
    query = {
        "classification_status": {"$in": [ClassificationStatus.PENDING.value, ClassificationStatus.FAILED.value]},
        "classification_attempts": {"$lt": 3}  # Max 3 retries
    }
    if limit:
        return list(leads_raw_collection.find(query).limit(limit))
    return list(leads_raw_collection.find(query))


def classify_single_lead(raw_lead_id: str) -> Tuple[bool, Optional[str]]:
    """
    Classify a single lead and store results.
    Returns: (success, error_message)
    """
    # Get raw lead
    raw_lead = leads_raw_collection.find_one({"_id": ObjectId(raw_lead_id)})
    if not raw_lead:
        return False, "Lead not found"
    
    # Mark as processing
    leads_raw_collection.update_one(
        {"_id": ObjectId(raw_lead_id)},
        {
            "$set": {
                "classification_status": ClassificationStatus.PROCESSING.value,
                "last_classification_attempt": datetime.utcnow()
            },
            "$inc": {"classification_attempts": 1}
        }
    )
    
    # Create LeadRaw model with all available context for AI classification
    lead = LeadRaw(
        name=raw_lead["name"],
        title=raw_lead["title"],
        linkedin_url=raw_lead["linkedin_url"],
        snippet=raw_lead.get("snippet", ""),
        source=raw_lead.get("source", "linkedin"),
        first_name=raw_lead.get("first_name"),
        last_name=raw_lead.get("last_name"),
        email=raw_lead.get("email"),
        email_status=raw_lead.get("email_status"),
        location=raw_lead.get("location"),
        company_name=raw_lead.get("company_name"),
        company_domain=raw_lead.get("company_domain"),
        company_website=raw_lead.get("company_website"),
        company_industry=raw_lead.get("company_industry"),
    )
    
    # Classify
    result, log = classify_lead(lead)
    
    # Store classification log
    log.raw_lead_id = raw_lead_id
    classification_logs_collection.insert_one(log.model_dump())
    
    if result:
        # Create enriched lead with all fields
        # Use AI-inferred data, fallback to raw data from import
        
        # Determine email and status - prefer raw email, fallback to AI predicted
        raw_email = raw_lead.get("email")
        predicted_email = getattr(result, 'predicted_email', None)
        final_email = raw_email or predicted_email
        
        # Set email status based on source
        if raw_email:
            email_status = EmailStatus(raw_lead.get("email_status", "Unknown")) if raw_lead.get("email_status") else EmailStatus.UNKNOWN
        elif predicted_email:
            email_status = EmailStatus.PREDICTED
        else:
            email_status = EmailStatus.UNKNOWN
        
        enriched = LeadEnriched(
            raw_lead_id=raw_lead_id,
            # Personal Info
            name=lead.name,
            first_name=result.first_name or raw_lead.get("first_name", ""),
            last_name=result.last_name or raw_lead.get("last_name", ""),
            email=final_email,
            email_status=email_status,
            title=lead.title,
            linkedin_url=lead.linkedin_url,
            location=result.inferred_location or raw_lead.get("location"),
            # Metadata
            added_on=datetime.utcnow(),
            source=lead.source,
            snippet=lead.snippet,
            # AI Classification
            seniority_level=result.seniority_level,
            buying_role=result.buying_role,
            department=result.department,
            persona=result.persona,
            gender=result.gender,
            company_size=result.company_size,
            region=result.region,
            confidence_score=result.confidence_score,
            # Company Info - prefer AI inferred, fallback to raw import data
            company_name=result.company_name or raw_lead.get("company_name"),
            company_domain=result.company_domain or raw_lead.get("company_domain"),
            company_website=result.company_website or raw_lead.get("company_website"),
            company_employee_count=result.company_employee_count or raw_lead.get("company_employee_count"),
            company_employee_count_range=result.company_employee_count_range or raw_lead.get("company_employee_count_range"),
            company_founded=result.company_founded or raw_lead.get("company_founded"),
            company_industry=result.company_industry or raw_lead.get("company_industry"),
            company_type=result.company_type or raw_lead.get("company_type"),
            company_headquarters=result.company_headquarters or raw_lead.get("company_headquarters"),
            company_revenue_range=result.company_revenue_range or raw_lead.get("company_revenue_range"),
            company_linkedin_url=result.company_linkedin_url or raw_lead.get("company_linkedin_url"),
            classified_at=datetime.utcnow()
        )
        
        # Upsert enriched lead
        leads_enriched_collection.update_one(
            {"linkedin_url": lead.linkedin_url},
            {"$set": enriched.model_dump()},
            upsert=True
        )
        
        # Get enriched lead ID
        enriched_doc = leads_enriched_collection.find_one({"linkedin_url": lead.linkedin_url})
        enriched_id = str(enriched_doc["_id"]) if enriched_doc else None
        
        # Update raw lead status
        leads_raw_collection.update_one(
            {"_id": ObjectId(raw_lead_id)},
            {"$set": {
                "classification_status": ClassificationStatus.CLASSIFIED.value,
                "enriched_lead_id": enriched_id
            }}
        )
        
        # P1.6: Queue low-confidence classifications for human review
        try:
            from .review_queue import get_review_queue_service
            review_service = get_review_queue_service()
            review_service.add_to_queue(
                entity_type="lead",
                entity_id=enriched_id or raw_lead_id,
                ai_classification=result.model_dump(),
                confidence_score=result.confidence_score,
                metadata={
                    "raw_lead_id": raw_lead_id,
                    "name": lead.name,
                    "linkedin_url": lead.linkedin_url
                }
            )
        except Exception as e:
            # Non-fatal - log and continue
            pass
        
        return True, None
    else:
        # Mark as failed
        leads_raw_collection.update_one(
            {"_id": ObjectId(raw_lead_id)},
            {"$set": {"classification_status": ClassificationStatus.FAILED.value}}
        )
        return False, log.error_message


def classify_pending_leads(batch_size: Optional[int] = None) -> Tuple[int, int]:
    """
    Process pending leads in batch.
    If batch_size is None, process ALL pending leads.
    Returns: (success_count, failure_count)
    """
    pending = get_pending_leads(batch_size)
    success = 0
    failure = 0
    
    for lead in pending:
        ok, error = classify_single_lead(str(lead["_id"]))
        if ok:
            success += 1
        else:
            failure += 1
    
    return success, failure


# ============== QUERY SERVICE ==============

# Stage mappings matching frontend salesPipeline.js
# Leads section: Early-stage leads not yet in active sales process
LEAD_STAGES = ["lead_generation", "outreach"]
# Contacts section: Active deals from discovery call onwards (moved from Leads)
CONTACT_STAGES = ["discovery_call", "presentation", "rfq_pricing", "negotiation", "won", "lost", "onboarding", "project_execution", "payment", "retention"]

def get_leads(filters: LeadFilterParams) -> Tuple[List[dict], int]:
    """
    Get enriched leads with filtering and pagination.
    Returns: (leads, total_count)
    """
    query = {}
    
    # Filter by lead_stage if provided
    # Maps 'leads' -> early-stage leads, 'contacts' -> active deals (discovery_call onwards)
    if filters.lead_stage:
        if filters.lead_stage == "leads":
            # Show leads in early stages OR have no stage (default to leads)
            query["$or"] = [
                {"stage": {"$in": LEAD_STAGES}},
                {"stage": {"$exists": False}},
                {"stage": None},
                {"stage": ""}
            ]
        elif filters.lead_stage == "contacts":
            # Show leads that have been moved to contacts (discovery_call onwards)
            query["stage"] = {"$in": CONTACT_STAGES}
        else:
            # Allow filtering by specific stage
            query["stage"] = filters.lead_stage
    
    if filters.seniority_level:
        query["seniority_level"] = filters.seniority_level.value
    
    if filters.department:
        query["department"] = filters.department.value
    
    if filters.persona:
        query["persona"] = filters.persona.value
    
    if filters.company_size:
        query["company_size"] = filters.company_size.value
    
    if filters.industry:
        query["industry"] = {"$regex": filters.industry, "$options": "i"}
    
    if filters.region:
        query["region"] = filters.region.value
    
    if filters.min_confidence:
        query["confidence_score"] = {"$gte": filters.min_confidence}
    
    if filters.source:
        # Support comma-separated sources for multi-source filtering
        sources = [s.strip() for s in filters.source.split(",")]
        if len(sources) == 1:
            query["source"] = sources[0]
        else:
            query["source"] = {"$in": sources}
    
    if filters.search:
        query["$or"] = [
            {"name": {"$regex": filters.search, "$options": "i"}},
            {"title": {"$regex": filters.search, "$options": "i"}},
            {"industry": {"$regex": filters.search, "$options": "i"}}
        ]
    
    total = leads_enriched_collection.count_documents(query)
    
    skip = (filters.page - 1) * filters.limit
    leads = list(leads_enriched_collection.find(query)
                 .sort("classified_at", DESCENDING)
                 .skip(skip)
                 .limit(filters.limit))
    
    # Convert ObjectId to string
    for lead in leads:
        lead["_id"] = str(lead["_id"])
    
    return leads, total


def get_raw_leads_with_status(limit: int = 100, skip: int = 0) -> List[dict]:
    """Get raw leads with their status for UI display (paginated for performance)"""
    leads = list(leads_raw_collection.find().sort("created_at", DESCENDING).skip(skip).limit(limit))
    for lead in leads:
        lead["_id"] = str(lead["_id"])
    return leads


# ============== CAMPAIGN ATTACHMENT SERVICE ==============

def attach_leads_to_campaign(campaign_id: str, lead_ids: List[str]) -> Tuple[int, str]:
    """
    Attach enriched leads to a campaign.
    Returns: (attached_count, message)
    """
    # Verify campaign exists
    campaign = campaigns_collection.find_one({"_id": ObjectId(campaign_id)})
    if not campaign:
        return 0, "Campaign not found"
    
    attached = 0
    for lead_id in lead_ids:
        try:
            result = leads_enriched_collection.update_one(
                {"_id": ObjectId(lead_id)},
                {"$addToSet": {"campaign_ids": campaign_id}}
            )
            if result.modified_count > 0:
                attached += 1
        except Exception as e:
            print(f"Error attaching lead {lead_id}: {e}")
    
    return attached, f"Attached {attached} leads to campaign"


# ============== STATISTICS SERVICE ==============

# Source groupings for statistics
CSV_SOURCES = ["csv", "csv_import", "google_sheets", "json_import"]
WEBSEARCH_SOURCES = ["web_search", "google_search", "linkedin"]
GMAIL_SOURCES = ["gmail", "email", "imap"]

def get_lead_statistics() -> dict:
    """Get overview statistics for dashboard"""
    raw_total = leads_raw_collection.count_documents({})
    pending = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.PENDING.value})
    processing = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.PROCESSING.value})
    classified = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.CLASSIFIED.value})
    failed = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.FAILED.value})
    
    # Failed leads that can be retried (< 3 attempts)
    failed_retryable = leads_raw_collection.count_documents({
        "classification_status": ClassificationStatus.FAILED.value,
        "classification_attempts": {"$lt": 3}
    })
    # Failed leads that have exhausted retries (>= 3 attempts)
    failed_permanent = leads_raw_collection.count_documents({
        "classification_status": ClassificationStatus.FAILED.value,
        "classification_attempts": {"$gte": 3}
    })
    
    enriched_total = leads_enriched_collection.count_documents({})
    high_confidence = leads_enriched_collection.count_documents({"confidence_score": {"$gte": 0.8}})
    low_confidence = leads_enriched_collection.count_documents({"confidence_score": {"$lt": 0.5}})
    
    # Source-based counts for raw leads
    raw_csv = leads_raw_collection.count_documents({"source": {"$in": CSV_SOURCES}})
    raw_websearch = leads_raw_collection.count_documents({"source": {"$in": WEBSEARCH_SOURCES}})
    raw_gmail = leads_raw_collection.count_documents({"source": {"$in": GMAIL_SOURCES}})
    
    # CSV with email (auto-classified)
    raw_csv_with_email = leads_raw_collection.count_documents({
        "source": {"$in": CSV_SOURCES},
        "email": {"$exists": True, "$ne": "", "$ne": None}
    })
    
    # Source-based counts for enriched leads
    enriched_csv = leads_enriched_collection.count_documents({"source": {"$in": CSV_SOURCES}})
    enriched_websearch = leads_enriched_collection.count_documents({"source": {"$in": WEBSEARCH_SOURCES}})
    enriched_gmail = leads_enriched_collection.count_documents({"source": {"$in": GMAIL_SOURCES}})
    
    # Department breakdown
    department_pipeline = [
        {"$group": {"_id": "$department", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    departments = list(leads_enriched_collection.aggregate(department_pipeline))
    
    # Seniority breakdown
    seniority_pipeline = [
        {"$group": {"_id": "$seniority_level", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    seniorities = list(leads_enriched_collection.aggregate(seniority_pipeline))
    
    return {
        "raw": {
            "total": raw_total,
            "pending": pending,
            "processing": processing,
            "classified": classified,
            "failed": failed,
            "failed_retryable": failed_retryable,
            "failed_permanent": failed_permanent
        },
        "by_source": {
            "csv": {
                "raw": raw_csv,
                "raw_with_email": raw_csv_with_email,
                "enriched": enriched_csv,
                "classified_count": enriched_csv + raw_csv_with_email  # CSV with email = auto-classified
            },
            "websearch": {
                "raw": raw_websearch,
                "enriched": enriched_websearch,
                "classified_count": enriched_websearch
            },
            "gmail": {
                "raw": raw_gmail,
                "enriched": enriched_gmail,
                "classified_count": enriched_gmail
            }
        },
        "enriched": {
            "total": enriched_total,
            "high_confidence": high_confidence,
            "low_confidence": low_confidence
        },
        "by_department": {d["_id"]: d["count"] for d in departments},
        "by_seniority": {s["_id"]: s["count"] for s in seniorities}
    }


# ============== DELETE LEADS ==============

def delete_leads_by_source(source: str) -> dict:
    """
    Delete all leads imported from a specific source.
    Returns count of deleted leads from raw and enriched collections.
    """
    # Get IDs of raw leads to delete
    raw_leads_to_delete = list(leads_raw_collection.find(
        {"source": {"$in": [source, "google_search", "web_search"]} if source == "web_search" else {"source": source}},
        {"_id": 1, "enriched_lead_id": 1}
    ))
    
    raw_ids = [str(lead["_id"]) for lead in raw_leads_to_delete]
    enriched_ids = [lead.get("enriched_lead_id") for lead in raw_leads_to_delete if lead.get("enriched_lead_id")]
    
    # Delete from enriched collection
    enriched_deleted = 0
    if enriched_ids:
        enriched_result = leads_enriched_collection.delete_many({
            "$or": [
                {"raw_lead_id": {"$in": raw_ids}},
                {"_id": {"$in": [ObjectId(eid) for eid in enriched_ids if eid]}}
            ]
        })
        enriched_deleted = enriched_result.deleted_count
    
    # Delete from raw collection - include both web_search and google_search sources
    if source == "web_search":
        raw_result = leads_raw_collection.delete_many({
            "source": {"$in": ["web_search", "google_search"]}
        })
    else:
        raw_result = leads_raw_collection.delete_many({"source": source})
    
    raw_deleted = raw_result.deleted_count
    
    # Also delete any classification logs
    if raw_ids:
        classification_logs_collection.delete_many({"raw_lead_id": {"$in": raw_ids}})
    
    return {
        "raw_deleted": raw_deleted,
        "enriched_deleted": enriched_deleted,
        "total_deleted": raw_deleted + enriched_deleted
    }


def delete_all_leads() -> dict:
    """
    Delete ALL leads from both raw and enriched collections.
    Returns count of deleted leads.
    """
    # Delete all from enriched collection
    enriched_result = leads_enriched_collection.delete_many({})
    enriched_deleted = enriched_result.deleted_count
    
    # Delete all from raw collection
    raw_result = leads_raw_collection.delete_many({})
    raw_deleted = raw_result.deleted_count
    
    # Delete all classification logs
    classification_logs_collection.delete_many({})
    
    return {
        "raw_deleted": raw_deleted,
        "enriched_deleted": enriched_deleted,
        "total_deleted": raw_deleted + enriched_deleted
    }


# ============== GET SINGLE ENRICHED LEAD ==============

def get_enriched_lead_by_id(lead_id: str) -> Optional[dict]:
    """
    Get a single lead by ID.
    Searches in multiple collections with fallback:
    1. leads_enriched (primary for AI-classified leads)
    2. leads (legacy collection from main.py)
    3. leads_raw (raw imported leads)
    """
    try:
        # Validate ObjectId format first
        try:
            obj_id = ObjectId(lead_id)
        except Exception as e:
            print(f"Invalid ObjectId format '{lead_id}': {e}")
            return None
        
        # 1. Try leads_enriched first (primary collection for AI Database)
        lead = leads_enriched_collection.find_one({"_id": obj_id})
        if lead:
            lead["_id"] = str(lead["_id"])
            if "raw_lead_id" in lead:
                lead["raw_lead_id"] = str(lead["raw_lead_id"])
            lead["_source_collection"] = "leads_enriched"
            return lead
        
        # 2. Fallback to legacy leads collection (used by main.py)
        lead = leads_collection.find_one({"_id": obj_id})
        if lead:
            lead["_id"] = str(lead["_id"])
            lead["_source_collection"] = "leads"
            return lead
        
        # 3. Fallback to leads_raw collection
        lead = leads_raw_collection.find_one({"_id": obj_id})
        if lead:
            lead["_id"] = str(lead["_id"])
            lead["_source_collection"] = "leads_raw"
            return lead
        
        print(f"Lead not found in any collection: {lead_id}")
        return None
    except Exception as e:
        print(f"Error getting lead {lead_id}: {e}")
        return None


# ============== DUPLICATE EMAIL HANDLING ==============

def find_duplicate_emails() -> dict:
    """
    Find leads with duplicate emails.
    Returns a dictionary with duplicate emails and their lead IDs.
    """
    # Aggregate to find emails that appear more than once
    pipeline = [
        {"$match": {"email": {"$ne": None, "$ne": ""}}},
        {"$group": {
            "_id": "$email",
            "count": {"$sum": 1},
            "leads": {"$push": {"id": "$_id", "name": "$name", "created_at": "$created_at"}}
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    duplicates = list(leads_enriched_collection.aggregate(pipeline))
    
    return {
        "duplicate_count": len(duplicates),
        "duplicates": [
            {
                "email": d["_id"],
                "count": d["count"],
                "leads": [{"id": str(l["id"]), "name": l["name"], "created_at": l.get("created_at")} for l in d["leads"]]
            }
            for d in duplicates
        ]
    }


def delete_duplicate_emails() -> dict:
    """
    Delete duplicate leads keeping only the oldest one per email.
    Uses email as the unique identifier.
    Returns count of deleted duplicates.
    """
    # Find duplicates
    pipeline = [
        {"$match": {"email": {"$ne": None, "$ne": ""}}},
        {"$sort": {"created_at": 1}},  # Sort by creation date (oldest first)
        {"$group": {
            "_id": "$email",
            "count": {"$sum": 1},
            "leads": {"$push": "$_id"},
            "first_lead": {"$first": "$_id"}  # Keep the oldest
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    
    duplicates = list(leads_enriched_collection.aggregate(pipeline))
    
    deleted_count = 0
    for dup in duplicates:
        # Get all lead IDs except the first one (oldest)
        leads_to_delete = [lead_id for lead_id in dup["leads"] if lead_id != dup["first_lead"]]
        
        if leads_to_delete:
            # Delete the duplicate leads
            result = leads_enriched_collection.delete_many({"_id": {"$in": leads_to_delete}})
            deleted_count += result.deleted_count
            
            # Also delete corresponding raw leads if linked
            for lead_id in leads_to_delete:
                leads_raw_collection.delete_many({"enriched_lead_id": str(lead_id)})
    
    return {
        "duplicates_found": len(duplicates),
        "leads_deleted": deleted_count
    }
