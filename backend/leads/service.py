"""
AGENT 4 — BACKEND SERVICE LAYER
Lead management service with async processing
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
    SeniorityLevel, Department, Persona, CompanySize, Region
)
from .ai_classifier import classify_lead

load_dotenv()

# ============== DATABASE CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Collections
leads_raw_collection = db['leads_raw']
leads_enriched_collection = db['leads_enriched']
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

def import_leads(leads: List[LeadInput]) -> LeadImportResponse:
    """
    Import raw leads with idempotent behavior (skip duplicates).
    """
    imported = 0
    duplicates = 0
    errors = 0
    lead_ids = []
    
    for lead_input in leads:
        try:
            lead_raw = LeadRaw(
                name=lead_input.name,
                title=lead_input.title,
                linkedin_url=lead_input.linkedin_url,
                snippet=lead_input.snippet,
                source=lead_input.source,
                created_at=datetime.utcnow(),
                classification_status=ClassificationStatus.PENDING
            )
            
            result = leads_raw_collection.insert_one(lead_raw.model_dump())
            lead_ids.append(str(result.inserted_id))
            imported += 1
            
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

def get_pending_leads(limit: int = 10) -> List[dict]:
    """Get leads pending classification with retry limit"""
    return list(leads_raw_collection.find({
        "classification_status": {"$in": [ClassificationStatus.PENDING.value, ClassificationStatus.FAILED.value]},
        "classification_attempts": {"$lt": 3}  # Max 3 retries
    }).limit(limit))


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
    
    # Create LeadRaw model
    lead = LeadRaw(
        name=raw_lead["name"],
        title=raw_lead["title"],
        linkedin_url=raw_lead["linkedin_url"],
        snippet=raw_lead["snippet"],
        source=raw_lead.get("source", "linkedin")
    )
    
    # Classify
    result, log = classify_lead(lead)
    
    # Store classification log
    log.raw_lead_id = raw_lead_id
    classification_logs_collection.insert_one(log.model_dump())
    
    if result:
        # Create enriched lead
        enriched = LeadEnriched(
            raw_lead_id=raw_lead_id,
            name=lead.name,
            title=lead.title,
            linkedin_url=lead.linkedin_url,
            snippet=lead.snippet,
            source=lead.source,
            seniority_level=result.seniority_level,
            department=result.department,
            persona=result.persona,
            company_size=result.company_size,
            industry=result.industry,
            region=result.region,
            confidence_score=result.confidence_score,
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
        
        return True, None
    else:
        # Mark as failed
        leads_raw_collection.update_one(
            {"_id": ObjectId(raw_lead_id)},
            {"$set": {"classification_status": ClassificationStatus.FAILED.value}}
        )
        return False, log.error_message


def classify_pending_leads(batch_size: int = 10) -> Tuple[int, int]:
    """
    Process pending leads in batch.
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

def get_leads(filters: LeadFilterParams) -> Tuple[List[dict], int]:
    """
    Get enriched leads with filtering and pagination.
    Returns: (leads, total_count)
    """
    query = {}
    
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


def get_raw_leads_with_status() -> List[dict]:
    """Get all raw leads with their status for UI display"""
    leads = list(leads_raw_collection.find().sort("created_at", DESCENDING))
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

def get_lead_statistics() -> dict:
    """Get overview statistics for dashboard"""
    raw_total = leads_raw_collection.count_documents({})
    pending = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.PENDING.value})
    processing = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.PROCESSING.value})
    classified = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.CLASSIFIED.value})
    failed = leads_raw_collection.count_documents({"classification_status": ClassificationStatus.FAILED.value})
    
    enriched_total = leads_enriched_collection.count_documents({})
    high_confidence = leads_enriched_collection.count_documents({"confidence_score": {"$gte": 0.8}})
    low_confidence = leads_enriched_collection.count_documents({"confidence_score": {"$lt": 0.5}})
    
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
            "failed": failed
        },
        "enriched": {
            "total": enriched_total,
            "high_confidence": high_confidence,
            "low_confidence": low_confidence
        },
        "by_department": {d["_id"]: d["count"] for d in departments},
        "by_seniority": {s["_id"]: s["count"] for s in seniorities}
    }
