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
from .openai_rotator import SEGMENT_PIPELINE_MAP
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
torpedo_gmail_db = client['torpedo_gmail']  # Gmail Workspace emails database

# Collections
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']
leads_collection = db['leads']  # Legacy leads collection (used by main.py)
classification_logs_collection = db['lead_ai_classification_logs']
campaigns_collection = db['campaigns']
email_metadata_collection = torpedo_gmail_db['email_metadata']  # Synced emails

# ============== ENSURE INDEXES ==============

def ensure_indexes():
    """Create necessary indexes for performance"""
    # leads_raw indexes — sparse=True so NULL values don't violate uniqueness
    # (email-only leads have linkedin_url=None; linkedin-only leads have email=None)
    leads_raw_collection.create_index("linkedin_url", unique=True, sparse=True)
    leads_raw_collection.create_index("created_at")
    leads_raw_collection.create_index("classification_status")
    leads_raw_collection.create_index([("classification_status", ASCENDING), ("classification_attempts", ASCENDING)])

    # leads_enriched indexes — sparse=True on linkedin_url for same reason
    leads_enriched_collection.create_index("raw_lead_id")
    leads_enriched_collection.create_index("linkedin_url", unique=True, sparse=True)
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

def import_leads(leads: List[LeadInput], skip_dedup_check: bool = False, auto_classify: bool = False, icp_segment: Optional[str] = None) -> LeadImportResponse:
    """
    Import raw leads using CANONICAL INGESTION PIPELINE.
    
    ALL leads pass through the same pipeline:
    - normalize_payload
    - deduplicate_by_email (EMAIL is the ONLY dedup key)
    - validate_fields
    - conditional_enrichment
    - AI_classification (if auto_classify=True)
    - insert_into_leads_raw
    
    Args:
        leads: List of LeadInput objects to import
        skip_dedup_check: Ignored (canonical pipeline always deduplicates)
        auto_classify: Run AI classification immediately
        
    Returns:
        LeadImportResponse with import stats
    """
    from .canonical_ingestion import ingest_lead
    
    imported = 0
    updated = 0
    duplicates = 0
    errors = 0
    lead_ids = []
    
    for lead_input in leads:
        try:
            # Build canonical payload
            payload = {
                'email': lead_input.email,
                'name': lead_input.name,
                'first_name': lead_input.first_name,
                'last_name': lead_input.last_name,
                'title': lead_input.title,
                'linkedin_url': lead_input.linkedin_url,
                'location': lead_input.location,
                'company': lead_input.company_name,
                'company_domain': lead_input.company_domain,
                'phone': getattr(lead_input, 'phone', None),
            }
            
            # Determine source
            source = 'websearch'  # Default for web search leads
            if hasattr(lead_input, 'source') and lead_input.source:
                if 'csv' in str(lead_input.source).lower():
                    source = 'csv'
                elif 'gmail' in str(lead_input.source).lower():
                    source = 'gmail'
            
            source_detail = lead_input.source or 'openai_search'
            
            # Use CANONICAL ingestion
            result = ingest_lead(
                payload=payload,
                source=source,
                source_detail=source_detail,
                skip_classification=not auto_classify,
                icp_segment=icp_segment,
            )
            
            if result['success']:
                if result['lead_id']:
                    lead_ids.append(result['lead_id'])
                
                if result['action'] == 'inserted':
                    imported += 1
                elif result['action'] == 'updated':
                    updated += 1
                elif result['action'] == 'skipped':
                    duplicates += 1
            else:
                if result.get('error') and 'email' in result['error'].lower():
                    duplicates += 1  # Treat missing/invalid email as skip
                else:
                    errors += 1
            
        except Exception as e:
            print(f"Error importing lead: {e}")
            errors += 1
    
    return LeadImportResponse(
        imported=imported + updated,  # Combine for backwards compatibility
        duplicates=duplicates,
        errors=errors,
        lead_ids=lead_ids
    )


# ============== CLASSIFICATION SERVICE ==============

def get_pending_leads(limit: Optional[int] = None) -> List[dict]:
    """Get leads pending classification with retry limit. If limit is None, get ALL pending."""
    # Accept both capitalized enum values ("Pending"/"Failed") and lowercase legacy values
    query = {
        "classification_status": {"$in": [
            ClassificationStatus.PENDING.value, ClassificationStatus.FAILED.value,
            "pending", "failed",  # legacy lowercase values from old canonical ingestion
        ]},
        "classification_attempts": {"$lt": 3}  # Max 3 retries
    }
    if limit:
        return list(leads_raw_collection.find(query).limit(limit))
    return list(leads_raw_collection.find(query))


def classify_single_lead(raw_lead_id: str) -> Tuple[bool, Optional[str]]:
    """
    Classify a single lead and store results.
    Routes to the correct Gemini pipeline based on the lead's icp_segment.
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
    # linkedin_url is required by LeadRaw; use empty string as fallback for email-only leads

    def _to_str(val) -> str:
        """Safely coerce a possibly-dict field value to a plain string."""
        if val is None:
            return ""
        if isinstance(val, dict):
            # Old import format stored nested dicts; extract best text key
            for key in ("name", "value", "text", "label", "title"):
                if key in val and isinstance(val[key], str):
                    return val[key]
            return str(val)[:200]
        return str(val)

    try:
        lead = LeadRaw(
            name=_to_str(raw_lead.get("name")) or "",
            title=_to_str(raw_lead.get("title")) or "",
            linkedin_url=_to_str(raw_lead.get("linkedin_url")) or "",
            snippet=_to_str(raw_lead.get("snippet")),
            source=_to_str(raw_lead.get("source")) or "linkedin",
            first_name=_to_str(raw_lead.get("first_name")) or None,
            last_name=_to_str(raw_lead.get("last_name")) or None,
            email=_to_str(raw_lead.get("email")) or None,
            email_status=_to_str(raw_lead.get("email_status")) or None,
            location=_to_str(raw_lead.get("location")) or None,
            company_name=_to_str(raw_lead.get("company_name") or raw_lead.get("company")) or None,
            company_domain=_to_str(raw_lead.get("company_domain")) or None,
            company_website=_to_str(raw_lead.get("company_website")) or None,
            company_industry=_to_str(raw_lead.get("company_industry")) or None,
        )
    except Exception as build_exc:
        leads_raw_collection.update_one(
            {"_id": ObjectId(raw_lead_id)},
            {"$set": {
                "classification_status": ClassificationStatus.FAILED.value,
                "last_error": f"LeadRaw build error: {build_exc}"[:300],
            }}
        )
        return False, f"LeadRaw build error: {build_exc}"
    
    # Classify — route to the correct Gemini pipeline
    pipeline = SEGMENT_PIPELINE_MAP.get(
        (raw_lead.get("icp_segment") or "").lower(), "sfw_bim"
    )
    result, log = classify_lead(lead, pipeline=pipeline)
    
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
        
        # Upsert enriched lead — prefer email as dedup key; fall back to linkedin_url
        _dedup_key = {"linkedin_url": lead.linkedin_url} if lead.linkedin_url else {"email": final_email}
        enriched_dict = enriched.model_dump()

        # Merge ICP basket classification (rule-based, must be in every enriched doc)
        try:
            from .canonical_ingestion import compute_icp_basket
            basket_input = {
                "title": lead.title,
                "department": result.department.value if result.department else "",
                "seniority_level": result.seniority_level.value if result.seniority_level else "",
                "buying_role": result.buying_role.value if result.buying_role else "",
                "persona": result.persona.value if result.persona else "",
                "company_industry": result.company_industry or raw_lead.get("company_industry", ""),
                "company_revenue_range": result.company_revenue_range or raw_lead.get("company_revenue_range", ""),
                "company": result.company_name or raw_lead.get("company_name", ""),
                "icp_segment": raw_lead.get("icp_segment"),
            }
            enriched_dict.update(compute_icp_basket(basket_input))
        except Exception as _basket_err:
            logger.warning(f"compute_icp_basket failed for lead {raw_lead_id}: {_basket_err}")

        leads_enriched_collection.update_one(
            _dedup_key,
            {"$set": enriched_dict},
            upsert=True
        )

        # Get enriched lead ID
        enriched_doc = leads_enriched_collection.find_one(_dedup_key)
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

    # Qualified-only mode: show only Gmail contacts and outreach-replied leads
    QUALIFIED_SOURCES = GMAIL_SOURCES + ["outreach_reply"]
    if filters.qualified_only:
        query["source"] = {"$in": QUALIFIED_SOURCES}

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
    else:
        # Default: exclude 'already_contacted' (gmail/Leads-tab leads) from main AI Database view
        query["stage"] = {"$ne": "already_contacted"}
    
    if filters.seniority_level:
        query["seniority_level"] = filters.seniority_level.value
    
    if filters.lead_bracket:
        if filters.lead_bracket in ('lead', 'contact', 'account'):
            query["lead_bracket"] = filters.lead_bracket
    
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

    if filters.fit_tier:
        query["fit_tier"] = filters.fit_tier

    if getattr(filters, 'bounce_recovery_status', None):
        query["bounce_recovery_status"] = filters.bounce_recovery_status

    if filters.basket:
        query["classification_basket"] = filters.basket

    if filters.source:
        # Support comma-separated sources for multi-source filtering
        sources = [s.strip() for s in filters.source.split(",")]
        
        # Expand known source groups (defined later in file, but available at runtime)
        expanded_sources = []
        for s in sources:
            if s.lower() == 'gmail':
                expanded_sources.extend(GMAIL_SOURCES)
            elif s.lower() == 'csv':
                expanded_sources.extend(CSV_SOURCES)
            elif s.lower() in ('websearch', 'web_search'):
                expanded_sources.extend(WEBSEARCH_SOURCES)
            else:
                expanded_sources.append(s)
        
        query["source"] = {"$in": expanded_sources}
    
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
WEBSEARCH_SOURCES = ["web_search", "websearch", "google_search", "linkedin"]
GMAIL_SOURCES = ["gmail", "gmail_workspace", "email_sync", "email_import", "email_classification", "gmail_api", "gmail_archive", "classified_gmail"]

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

def get_emails_for_lead(email_address: str, limit: int = 50) -> List[dict]:
    """
    Fetch emails from email_metadata collection for a specific lead email address.
    Returns emails where the lead's email appears in from_email or to_emails.
    """
    if not email_address:
        return []
    
    try:
        # Find emails where this email is sender or recipient
        emails = list(email_metadata_collection.find({
            "$or": [
                {"from_email": {"$regex": email_address, "$options": "i"}},
                {"to_emails": {"$regex": email_address, "$options": "i"}}
            ]
        }).sort("timestamp", -1).limit(limit))
        
        formatted_emails = []
        for e in emails:
            # Determine direction relative to lead
            from_email = e.get("from_email", "")
            to_emails = e.get("to_emails", [])
            
            # Check if lead sent the email
            is_from_lead = email_address.lower() in from_email.lower()
            direction = "outbox" if is_from_lead else "inbox"
            
            timestamp = e.get("timestamp")
            
            formatted_emails.append({
                "id": str(e["_id"]),
                "subject": e.get("subject", "(no subject)"),
                "from": from_email,
                "from_name": e.get("from_name", ""),
                "to": to_emails if isinstance(to_emails, list) else [to_emails] if to_emails else [],
                "recipients": ", ".join(to_emails) if isinstance(to_emails, list) else to_emails,
                "snippet": e.get("snippet", ""),
                "body_plain": e.get("body_plain", ""),
                "body_html": e.get("body_html", ""),
                "date": timestamp.isoformat() if timestamp else "",
                "timestamp": timestamp,
                "direction": direction,
                "status": "Received" if direction == "inbox" else "Sent",
                "source": "IMAP",
                "sent_by": from_email,
                "has_reply": "RE:" in str(e.get("subject", "")).upper() or "FWD:" in str(e.get("subject", "")).upper(),
                "has_attachment": e.get("has_attachments", False),
                "ai_category": e.get("ai_category"),
                "ai_summary": e.get("ai_summary"),
                "thread_id": e.get("gmail_thread_id"),
                "message_id": e.get("gmail_message_id"),
            })
        
        return formatted_emails
    except Exception as e:
        print(f"Error fetching emails for lead {email_address}: {e}")
        return []


def generate_conversation_summary(emails: List[dict]) -> str:
    """
    Generate a summary of the email conversation for the lead.
    This provides a high-level overview of the communication history.
    """
    if not emails:
        return ""
    
    # Group by thread
    threads = {}
    for email in emails:
        thread_id = email.get("thread_id") or email.get("id")
        if thread_id not in threads:
            threads[thread_id] = []
        threads[thread_id].append(email)
    
    # Build summary
    sent_count = sum(1 for e in emails if e.get("direction") == "outbox")
    received_count = sum(1 for e in emails if e.get("direction") == "inbox")
    
    # Get date range
    dates = [e.get("timestamp") for e in emails if e.get("timestamp")]
    if dates:
        dates.sort()
        first_date = dates[0].strftime("%b %d, %Y") if hasattr(dates[0], 'strftime') else str(dates[0])[:10]
        last_date = dates[-1].strftime("%b %d, %Y") if hasattr(dates[-1], 'strftime') else str(dates[-1])[:10]
        date_range = f" from {first_date} to {last_date}" if first_date != last_date else f" on {first_date}"
    else:
        date_range = ""
    
    # Get unique subjects
    subjects = list(set(e.get("subject", "") for e in emails if e.get("subject")))
    subject_summary = subjects[0] if len(subjects) == 1 else f"{len(subjects)} different conversations"
    
    summary = f"Total {len(emails)} emails ({received_count} received, {sent_count} sent){date_range}. "
    summary += f"Topics: {subject_summary}. "
    
    # Check for RFQ-related emails
    rfq_emails = [e for e in emails if "RFQ" in str(e.get("subject", "")).upper() or "QUOTE" in str(e.get("subject", "")).upper()]
    if rfq_emails:
        summary += f"Contains {len(rfq_emails)} RFQ/quote related emails. "
    
    return summary.strip()


def build_timeline(lead: dict, emails: List[dict]) -> List[dict]:
    """
    Build a timeline of all activities for the lead.
    Includes: email dates, creation date, updates, etc.
    """
    timeline = []
    
    # Add lead creation event
    if lead.get("created_at"):
        created_at = lead["created_at"]
        timeline.append({
            "type": "lead_created",
            "icon": "🎯",
            "title": "Lead Created",
            "description": f"Lead was added to the system from {lead.get('source', 'unknown source')}",
            "date": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
            "timestamp": created_at
        })
    
    # Add classification event
    if lead.get("classified_at"):
        classified_at = lead["classified_at"]
        timeline.append({
            "type": "ai_classified",
            "icon": "🤖",
            "title": "AI Classification",
            "description": f"Classified as {lead.get('persona', 'Unknown')} with {int((lead.get('confidence_score', 0) or 0) * 100)}% confidence",
            "date": classified_at.isoformat() if hasattr(classified_at, 'isoformat') else str(classified_at),
            "timestamp": classified_at
        })
    
    # Add email events
    for email in emails:
        timestamp = email.get("timestamp")
        direction = email.get("direction", "inbox")
        
        if direction == "inbox":
            icon = "📩"
            title = "Email Received"
            desc = f"From: {email.get('from', 'Unknown')}"
        else:
            icon = "📤"
            title = "Email Sent"
            desc = f"To: {email.get('recipients', 'Unknown')}"
        
        timeline.append({
            "type": "email",
            "icon": icon,
            "title": title,
            "description": f"{desc}\nSubject: {email.get('subject', 'No subject')}",
            "subject": email.get("subject"),
            "date": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
            "timestamp": timestamp,
            "email_id": email.get("id"),
            "direction": direction
        })
    
    # Add lead stage change if exists
    if lead.get("lead_stage") and lead.get("updated_at") != lead.get("created_at"):
        updated_at = lead.get("updated_at")
        if updated_at:
            timeline.append({
                "type": "stage_change",
                "icon": "📊",
                "title": "Stage Updated",
                "description": f"Lead moved to {lead.get('lead_stage', 'unknown')} stage",
                "date": updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at),
                "timestamp": updated_at
            })
    
    # Sort timeline by date (most recent first)
    timeline.sort(key=lambda x: x.get("timestamp") or datetime.min, reverse=True)
    
    return timeline


def get_enriched_lead_by_id(lead_id: str, include_emails: bool = True) -> Optional[dict]:
    """
    Get a single lead by ID with emails, timeline, and conversation summary.
    Searches in multiple collections with fallback:
    1. leads_enriched (primary for AI-classified leads)
    2. leads (legacy collection from main.py)
    3. leads_raw (raw imported leads)
    
    Args:
        lead_id: The lead's ObjectId as string
        include_emails: Whether to fetch emails and build timeline (default True)
    """
    try:
        # Validate ObjectId format first
        try:
            obj_id = ObjectId(lead_id)
        except Exception as e:
            print(f"Invalid ObjectId format '{lead_id}': {e}")
            return None
        
        lead = None
        source_collection = None

        # Build queries: try ObjectId first, then string _id as fallback
        # (some leads imported via CSV/Gmail may have string _id)
        id_queries = [{"_id": obj_id}, {"_id": lead_id}]

        # 1. Try leads_enriched first (primary collection for AI Database)
        for q in id_queries:
            lead = leads_enriched_collection.find_one(q)
            if lead:
                source_collection = "leads_enriched"
                break
        
        # 2. Fallback to legacy leads collection (used by main.py)
        if not lead:
            for q in id_queries:
                lead = leads_collection.find_one(q)
                if lead:
                    source_collection = "leads"
                    break
        
        # 3. Fallback to leads_raw collection
        if not lead:
            for q in id_queries:
                lead = leads_raw_collection.find_one(q)
                if lead:
                    source_collection = "leads_raw"
                    break
        
        if not lead:
            print(f"Lead not found in any collection: {lead_id}")
            return None
        
        # Convert ObjectId to string
        lead["_id"] = str(lead["_id"])
        if "raw_lead_id" in lead:
            lead["raw_lead_id"] = str(lead["raw_lead_id"])
        lead["_source_collection"] = source_collection
        
        # Fetch emails from email_metadata if lead has an email address
        if include_emails and lead.get("email"):
            emails = get_emails_for_lead(lead["email"])
            lead["emails"] = emails
            lead["email_count"] = len(emails)
            
            # Generate conversation summary if not already present or if we have new emails
            if emails and not lead.get("conversation_summary"):
                lead["conversation_summary"] = generate_conversation_summary(emails)
                lead["summary_updated_at"] = datetime.utcnow().isoformat()
            
            # Build timeline
            lead["timeline"] = build_timeline(lead, emails)
        else:
            if "emails" not in lead:
                lead["emails"] = []
            if "timeline" not in lead:
                lead["timeline"] = []
        
        return lead
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
