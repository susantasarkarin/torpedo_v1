"""
AGENT 4 — BACKEND API ENGINEER
FastAPI Router for Lead Management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File, Form, Body
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncio
import os
from dotenv import load_dotenv

from .models import (
    LeadInput, LeadImportRequest, LeadImportResponse,
    LeadClassifyRequest, LeadClassifyResponse, LeadFilterParams,
    AttachLeadsRequest, SeniorityLevel, Department, Persona,
    CompanySize, Region, ClassificationStatus
)
from .service import (
    import_leads, classify_pending_leads, classify_single_lead,
    get_leads, get_raw_leads_with_status, attach_leads_to_campaign,
    get_lead_statistics, delete_leads_by_source, delete_all_leads,
    get_enriched_lead_by_id, find_duplicate_emails, delete_duplicate_emails,
    leads_enriched_collection
)
from .ingestion import (
    search_linkedin_leads, parse_csv_leads, import_from_google_sheet,
    import_leads_from_source
)
from .imap_leads_service import (
    import_leads_from_emails, get_email_leads, get_segment_statistics,
    get_imap_accounts, add_imap_account, remove_imap_account,
    test_imap_connection, EmailSegment, imap_accounts_collection,
    detect_aliases_from_sent, add_detected_aliases
)
from .scheduler import (
    start_scheduler, stop_scheduler, get_scheduler_status,
    get_scheduler_logs, update_scheduler_config
)
from .routers.web_search import register_web_search_routes
from .routers.import_sources import register_import_source_routes
from .routers.email_import import register_email_import_routes
from .routers.scheduler_routes import register_scheduler_routes
from .routers.discover import register_discover_routes
from .routers.ai_database import register_ai_database_routes
from .routers.icp import register_icp_routes

load_dotenv()

router = APIRouter(prefix="/leads", tags=["Leads"])

# ============== SHARED STATE (extracted to router_shared.py) ==============
from .router_shared import (
    # MongoDB collections
    web_search_jobs_collection, email_metadata_collection, ai_companies_collection,
    # Constants
    JobStatus, DAILY_LIMIT, LEADS_PER_MINUTE, DELAY_BETWEEN_BATCHES,
    # Search control
    get_global_search_control, set_global_search_control,
    increment_error_count, reset_error_count, stop_all_jobs,
    # Rate limiting
    get_rate_limit_settings,
    # Request models
    GoogleSearchRequest, WebSearchRequest, GoogleSheetRequest,
    # Job helpers
    create_job, get_job, update_job, add_job_error,
    increment_job_counters, get_incomplete_jobs, check_and_reset_daily_limit,
    # Query generation + background loop
    generate_query_combinations, run_web_search_job,
)

register_web_search_routes(router)

register_import_source_routes(router)

# ============== CLASSIFICATION ENDPOINTS ==============

@router.post("/classify", response_model=LeadClassifyResponse)
async def classify_leads_endpoint(
    request: LeadClassifyRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/classify
    Queue leads for AI classification (async).
    If lead_ids not provided, classifies all pending leads.
    If batch_size is None, classifies ALL pending leads.
    """
    if request.lead_ids:
        # Classify specific leads in background
        for lead_id in request.lead_ids:
            background_tasks.add_task(classify_single_lead, lead_id)
        return LeadClassifyResponse(
            queued=len(request.lead_ids),
            message=f"Queued {len(request.lead_ids)} leads for classification"
        )
    else:
        # Classify all pending leads in background (None means ALL)
        background_tasks.add_task(classify_pending_leads, request.batch_size)
        if request.batch_size:
            return LeadClassifyResponse(
                queued=request.batch_size,
                message=f"Queued up to {request.batch_size} pending leads for classification"
            )
        else:
            return LeadClassifyResponse(
                queued=0,  # Unknown count, will process all
                message="Queued ALL pending leads for classification"
            )


@router.post("/classify/{lead_id}")
async def classify_single_lead_endpoint(lead_id: str):
    """
    POST /leads/classify/{lead_id}
    Classify a single lead synchronously.
    """
    success, error = classify_single_lead(lead_id)
    if success:
        return {"status": "classified", "lead_id": lead_id}
    else:
        raise HTTPException(status_code=400, detail=error or "Classification failed")


# ============== GET LEADS ENDPOINT ==============

@router.get("")
async def get_leads_endpoint(
    seniority_level: Optional[SeniorityLevel] = None,
    department: Optional[Department] = None,
    persona: Optional[Persona] = None,
    company_size: Optional[CompanySize] = None,
    industry: Optional[str] = None,
    region: Optional[Region] = None,
    min_confidence: Optional[float] = None,
    lead_stage: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    fit_tier: Optional[int] = None,
    basket: Optional[str] = None,
    bounce_recovery_status: Optional[str] = None,
    qualified_only: bool = Query(False, description="If true, show only Gmail contacts + outreach-replied leads"),
    lead_status: Optional[str] = Query(None, description="Filter by lead status: Positive, Negative, Neutral"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads
    Retrieve enriched leads with filtering and pagination.
    
    Args:
        source: Filter by source (google_search, csv_import, gmail, etc.). 
                Supports comma-separated values for multiple sources.
        qualified_only: When true, restrict results to Gmail contacts and
                        outreach-replied leads (used by the Sales Leads page).
        lead_status: Filter by lead status (Positive, Negative, Neutral).
    """
    filters = LeadFilterParams(
        seniority_level=seniority_level,
        department=department,
        persona=persona,
        company_size=company_size,
        industry=industry,
        region=region,
        min_confidence=min_confidence,
        lead_stage=lead_stage,
        source=source,
        search=search,
        fit_tier=fit_tier,
        basket=basket,
        bounce_recovery_status=bounce_recovery_status,
        qualified_only=qualified_only,
        lead_status=lead_status,
        page=page,
        limit=limit
    )
    
    leads, total = get_leads(filters)
    
    return {
        "leads": leads,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }


@router.post("/bulk-classify")
async def bulk_classify_leads_endpoint(background_tasks: BackgroundTasks):
    """
    POST /leads/bulk-classify
    1. Auto-sync any leads_raw docs missing from leads_enriched.
    2. Apply rule-based ICP basket classification to ALL leads in leads_enriched.
    Runs in background so the HTTP response returns immediately.
    """
    from .canonical_ingestion import compute_icp_basket, sync_to_enriched

    GMAIL_SOURCES = [
        "gmail", "gmail_workspace", "email_sync", "email_import",
        "email_classification", "gmail_api", "gmail_archive", "classified_gmail",
    ]

    FIELDS = {
        "_id": 1, "title": 1, "department": 1, "seniority_level": 1,
        "buying_role": 1, "persona": 1, "company_industry": 1, "industry": 1,
        "icp_segment": 1, "company_employee_count_range": 1, "company_size": 1,
        "company_revenue_range": 1, "location": 1, "company_headquarters": 1,
        "email_status": 1, "confidence_score": 1, "intent_score": 1,
        "company": 1, "company_name": 1, "source": 1,
    }

    raw_col = _jobs_db["leads_raw"]
    raw_total = raw_col.count_documents({})
    enriched_total = leads_enriched_collection.count_documents({})

    def _run_classification():
        import logging
        _log = logging.getLogger("leads.bulk_classify")

        # ── Phase 0: sync leads_raw → leads_enriched for any missing docs ──
        synced = 0
        existing_emails = set()
        existing_linkedin = set()

        # Gather existing dedup keys from leads_enriched
        for doc in leads_enriched_collection.find({}, {"email": 1, "linkedin_url": 1}):
            if doc.get("email"):
                existing_emails.add(doc["email"].lower().strip())
            if doc.get("linkedin_url"):
                existing_linkedin.add(doc["linkedin_url"].strip())

        # Iterate leads_raw and sync any not already in leads_enriched
        skip_raw = 0
        batch_size = 500
        while True:
            raw_batch = list(raw_col.find({}).skip(skip_raw).limit(batch_size))
            if not raw_batch:
                break
            for raw_doc in raw_batch:
                raw_email = (raw_doc.get("email") or "").lower().strip()
                raw_linkedin = (raw_doc.get("linkedin_url") or "").strip()
                if raw_email and raw_email in existing_emails:
                    continue
                if not raw_email and raw_linkedin and raw_linkedin in existing_linkedin:
                    continue
                # Sync this lead
                result = sync_to_enriched(raw_doc, str(raw_doc["_id"]))
                if result:
                    synced += 1
                    if raw_email:
                        existing_emails.add(raw_email)
                    if raw_linkedin:
                        existing_linkedin.add(raw_linkedin)
            skip_raw += batch_size

        _log.info(f"Bulk-classify: synced {synced} new leads from leads_raw → leads_enriched")

        # ── Phase 1: classify all leads_enriched ───────────────────────────
        skip = 0
        classified = 0
        while True:
            batch = list(leads_enriched_collection.find({}, FIELDS).skip(skip).limit(batch_size))
            if not batch:
                break
            for doc in batch:
                basket_fields = compute_icp_basket(doc)
                update_data = {**basket_fields}
                if doc.get("source") in GMAIL_SOURCES:
                    update_data["stage"] = "already_contacted"
                leads_enriched_collection.update_one({"_id": doc["_id"]}, {"$set": update_data})
                classified += 1
            skip += batch_size

        # Stamp stage on gmail leads missing stage field
        leads_enriched_collection.update_many(
            {"source": {"$in": GMAIL_SOURCES}, "stage": {"$exists": False}},
            {"$set": {"stage": "already_contacted"}}
        )
        _log.info(f"Bulk-classify: classified {classified} leads, synced {synced} new from raw")

    background_tasks.add_task(_run_classification)

    return {
        "queued": raw_total + enriched_total,
        "synced_from_raw": max(0, raw_total - enriched_total),
        "message": f"ICP classification started in background — syncing {raw_total} raw + classifying all enriched leads",
    }


@router.get("/raw")
async def get_raw_leads_endpoint(
    limit: int = Query(100, ge=1, le=500, description="Max leads to return"),
    skip: int = Query(0, ge=0, description="Number of leads to skip")
):
    """
    GET /leads/raw
    Get raw leads with their classification status (paginated for performance).
    """
    leads = get_raw_leads_with_status(limit=limit, skip=skip)
    return {"leads": leads, "total": len(leads)}


@router.get("/statistics")
async def get_statistics_endpoint():
    """
    GET /leads/statistics
    Get lead statistics for dashboard.
    """
    return get_lead_statistics()


@router.get("/pipeline")
async def get_pipeline_stats():
    """
    GET /leads/pipeline
    Returns funnel counts for the 5-stage outreach pipeline:
      1. Imported        – total leads_raw
      2. Email Ready     – leads_raw with a non-empty email
      3. SFW Outreach    – unique emails sent from @surveyfieldwork.com (any status)
      4. Cogentix Reach  – unique emails sent from @cogentixresearch.com, non-bounced
      5. Replied         – outreach leads with workflow_status=replied
      6. Enriched        – replied leads promoted to the main leads CRM collection
    """
    try:
        from pymongo import MongoClient as _MC
        import os as _os
        _uri = _os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        _client = _MC(_uri, serverSelectionTimeoutMS=5000)
        _email_db = _client['email_automation']
        _torpedo_db = _client[_os.getenv('MONGO_DB_NAME', 'torpedo')]

        raw_col = _email_db['leads_raw']
        sends_col = _torpedo_db['outreach_sends_v2']
        outreach_leads_col = _torpedo_db['outreach_leads_v2']
        leads_crm_col = _torpedo_db['leads']

        # Stage 1: Imported
        imported = raw_col.count_documents({})

        # Stage 2: Email Ready (has a usable email)
        email_ready = raw_col.count_documents({
            "email": {"$exists": True, "$ne": None, "$ne": ""}
        })

        # Stage 3: SFW Outreach – unique recipient emails sent via SFW mailboxes
        sfw_emails = sends_col.distinct("email", {
            "from_email": {"$regex": r"@surveyfieldwork\.com", "$options": "i"}
        })
        sfw_sent = len(sfw_emails)

        # Stage 4: Cogentix Outreach – unique recipient emails sent via Cogentix, not bounced
        cogentix_emails = sends_col.distinct("email", {
            "from_email": {"$regex": r"@cogentixresearch\.com", "$options": "i"},
            "status": {"$ne": "bounced"}
        })
        cogentix_sent = len(cogentix_emails)

        # Stage 5: Replied
        replied = outreach_leads_col.count_documents({"workflow_status": "replied"})

        # Stage 6: Enriched (promoted to CRM leads after reply)
        enriched_replied = leads_crm_col.count_documents({"source": "outreach_reply"})

        return {
            "stages": [
                {"id": "imported",   "label": "Imported",          "count": imported,        "color": "#6366f1"},
                {"id": "email_ready","label": "Email Ready",        "count": email_ready,     "color": "#3b82f6"},
                {"id": "sfw",        "label": "SFW Outreach",       "count": sfw_sent,        "color": "#f59e0b"},
                {"id": "cogentix",   "label": "Cogentix Outreach",  "count": cogentix_sent,   "color": "#10b981"},
                {"id": "replied",    "label": "Replied",            "count": replied,         "color": "#8b5cf6"},
                {"id": "enriched",   "label": "Enriched",           "count": enriched_replied,"color": "#ec4899"},
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CAMPAIGN ATTACHMENT ENDPOINT ==============

@router.post("/campaigns/{campaign_id}/attach")
async def attach_leads_to_campaign_endpoint(
    campaign_id: str,
    request: AttachLeadsRequest
):
    """
    POST /campaigns/{campaign_id}/attach-leads
    Attach selected leads to a campaign.
    """
    count, message = attach_leads_to_campaign(campaign_id, request.lead_ids)
    return {"attached": count, "message": message}


# ============== DELETE LEADS BY SOURCE ==============

@router.delete("/by-source/{source}")
async def delete_leads_by_source_endpoint(source: str):
    """
    DELETE /leads/by-source/{source}
    Delete all leads from a specific source (e.g., 'web_search', 'csv', 'google_search').
    """
    valid_sources = ["web_search", "google_search", "csv", "csv_import", "google_sheets", "json_import", "linkedin", "email_import"]
    
    if source not in valid_sources:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid source. Valid sources are: {', '.join(valid_sources)}"
        )
    
    try:
        result = delete_leads_by_source(source)
        return {
            "success": True,
            "source": source,
            "raw_deleted": result["raw_deleted"],
            "enriched_deleted": result["enriched_deleted"],
            "total_deleted": result["total_deleted"],
            "message": f"Deleted {result['total_deleted']} leads from source '{source}'"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/all")
async def delete_all_leads_endpoint():
    """
    DELETE /leads/all
    Delete ALL leads from both raw and enriched collections.
    Use with caution!
    """
    try:
        result = delete_all_leads()
        return {
            "success": True,
            "raw_deleted": result["raw_deleted"],
            "enriched_deleted": result["enriched_deleted"],
            "total_deleted": result["total_deleted"],
            "message": f"Deleted all {result['total_deleted']} leads"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


register_email_import_routes(router)

register_scheduler_routes(router)

# ============== ENRICHED LEAD DETAIL ==============

@router.get("/{lead_id}")
async def get_lead_by_id_endpoint(lead_id: str):
    """
    GET /leads/{lead_id}
    Get a single enriched lead by ID with all details.
    """
    # Route-order safeguard: allow static /leads/icps endpoint to work
    # even if this dynamic route is matched first.
    if lead_id == "icps":
        return await list_icps(active_only=False)

    lead = get_enriched_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": lead}


@router.put("/{lead_id}")
async def update_lead_by_id_endpoint(lead_id: str, data: dict = Body(...)):
    """
    PUT /leads/{lead_id}
    Update an enriched lead by ID. Handles stage changes for pipeline management.
    When moving to contacts (discovery_call+), automatically creates a Sales Account if needed.
    """
    from bson import ObjectId
    from database import get_client
    
    # Contact stages that trigger account creation
    CONTACT_STAGES = ["discovery_call", "presentation", "rfq_pricing", "negotiation", 
                      "won", "lost", "onboarding", "project_execution", "payment", "retention"]
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists in enriched collection
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Remove _id from update data if present
    if "_id" in data:
        del data["_id"]
    
    # Add updated timestamp
    data["updated_at"] = datetime.utcnow().isoformat()
    
    # Check if we're moving to a contact stage (create account if so)
    new_stage = data.get("stage")
    old_stage = existing_lead.get("stage")
    account_created = None
    
    if new_stage and new_stage in CONTACT_STAGES and old_stage not in CONTACT_STAGES:
        # Moving from leads to contacts - create Sales Account if company doesn't have one
        company_name = existing_lead.get("company_name")
        company_domain = existing_lead.get("company_domain")
        
        if company_name or company_domain:
            mongo_client = get_client()
            accounts_collection = mongo_client["email_automation"]["sales_accounts"]
            
            # Check if account already exists for this company
            account_query = {}
            if company_domain:
                account_query = {"$or": [
                    {"website": {"$regex": company_domain, "$options": "i"}},
                    {"company_name": {"$regex": f"^{company_name}$", "$options": "i"}} if company_name else {}
                ]}
            elif company_name:
                account_query = {"company_name": {"$regex": f"^{company_name}$", "$options": "i"}}
            
            existing_account = accounts_collection.find_one(account_query) if account_query else None
            
            if not existing_account:
                # Create new Sales Account from lead's company data
                account_data = {
                    "account_name": company_name or company_domain,
                    "company_name": company_name,
                    "industry": existing_lead.get("company_industry"),
                    "website": existing_lead.get("company_website") or (f"https://{company_domain}" if company_domain else None),
                    "address": existing_lead.get("company_headquarters"),
                    "status": "prospect",
                    "employee_count": existing_lead.get("company_employee_count"),
                    "employee_count_range": existing_lead.get("company_employee_count_range"),
                    "revenue_range": existing_lead.get("company_revenue_range"),
                    "company_type": existing_lead.get("company_type"),
                    "company_linkedin_url": existing_lead.get("company_linkedin_url"),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_from_lead_id": lead_id,
                    "contact_ids": [lead_id]  # Link this contact to the account
                }
                
                result = accounts_collection.insert_one(account_data)
                account_data["_id"] = str(result.inserted_id)
                account_created = account_data
                
                # Store account_id in lead data
                data["account_id"] = str(result.inserted_id)
            else:
                # Link contact to existing account
                account_id = str(existing_account["_id"])
                data["account_id"] = account_id
                
                # Add this contact to the account's contact_ids if not already there
                if lead_id not in existing_account.get("contact_ids", []):
                    accounts_collection.update_one(
                        {"_id": existing_account["_id"]},
                        {"$addToSet": {"contact_ids": lead_id}, "$set": {"updated_at": datetime.utcnow()}}
                    )
    
    # Update the lead
    result = leads_enriched_collection.update_one(
        {"_id": obj_id},
        {"$set": data}
    )
    
    if result.modified_count > 0:
        # Fetch and return updated lead
        updated_lead = get_enriched_lead_by_id(lead_id)
        response = {"success": True, "lead": updated_lead, "message": "Lead updated successfully"}
        if account_created:
            response["account_created"] = account_created
            response["message"] = "Lead updated and Sales Account created successfully"
        return response
    else:
        return {"success": True, "lead": get_enriched_lead_by_id(lead_id), "message": "No changes made"}


@router.post("/{lead_id}/move-to-contacts")
async def move_lead_to_contacts_endpoint(lead_id: str, payload: dict = Body(None)):
    """
    POST /leads/{lead_id}/move-to-contacts
    Moves an enriched lead into the Contacts pipeline by setting its stage.
    Also creates/links a Sales Account when transitioning into contact stages.
    """
    import re
    from bson import ObjectId
    from database import get_client

    CONTACT_STAGES = ["discovery_call", "presentation", "rfq_pricing", "negotiation",
                      "won", "lost", "onboarding", "project_execution", "payment", "retention"]

    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    stage = (payload or {}).get("stage") or "discovery_call"

    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    old_stage = existing_lead.get("stage")
    account_created = None
    update_data = {
        "stage": stage,
        "updated_at": datetime.utcnow().isoformat(),
    }

    if stage in CONTACT_STAGES and old_stage not in CONTACT_STAGES:
        company_name = existing_lead.get("company_name") or existing_lead.get("companyName")
        company_domain = existing_lead.get("company_domain") or existing_lead.get("companyDomain")

        if company_name or company_domain:
            mongo_client = get_client()
            accounts_collection = mongo_client["email_automation"]["sales_accounts"]

            account_conditions = []
            if company_domain:
                account_conditions.append({"website": {"$regex": re.escape(company_domain), "$options": "i"}})
            if company_name:
                account_conditions.append({"company_name": {"$regex": f"^{re.escape(company_name)}$", "$options": "i"}})

            if len(account_conditions) == 1:
                account_query = account_conditions[0]
            elif len(account_conditions) > 1:
                account_query = {"$or": account_conditions}
            else:
                account_query = None

            existing_account = accounts_collection.find_one(account_query) if account_query else None

            if not existing_account:
                account_data = {
                    "account_name": company_name or company_domain,
                    "company_name": company_name,
                    "industry": existing_lead.get("company_industry") or existing_lead.get("companyIndustry"),
                    "website": existing_lead.get("company_website") or existing_lead.get("companyWebsite") or (f"https://{company_domain}" if company_domain else None),
                    "address": existing_lead.get("company_headquarters") or existing_lead.get("companyHeadquarters"),
                    "status": "prospect",
                    "employee_count": existing_lead.get("company_employee_count") or existing_lead.get("companyEmployeeCount"),
                    "employee_count_range": existing_lead.get("company_employee_count_range") or existing_lead.get("companyEmployeeCountRange"),
                    "revenue_range": existing_lead.get("company_revenue_range") or existing_lead.get("companyRevenueRange"),
                    "company_type": existing_lead.get("company_type") or existing_lead.get("companyType"),
                    "company_linkedin_url": existing_lead.get("company_linkedin_url") or existing_lead.get("companyLinkedinUrl"),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "created_from_lead_id": lead_id,
                    "contact_ids": [lead_id],
                }
                result = accounts_collection.insert_one(account_data)
                account_data["_id"] = str(result.inserted_id)
                account_created = account_data
                update_data["account_id"] = str(result.inserted_id)
            else:
                account_id = str(existing_account["_id"])
                update_data["account_id"] = account_id
                if lead_id not in existing_account.get("contact_ids", []):
                    accounts_collection.update_one(
                        {"_id": existing_account["_id"]},
                        {"$addToSet": {"contact_ids": lead_id}, "$set": {"updated_at": datetime.utcnow()}},
                    )

    leads_enriched_collection.update_one({"_id": obj_id}, {"$set": update_data})
    updated = get_enriched_lead_by_id(lead_id)
    response = {"success": True, "lead": updated, "message": "Lead moved to Contacts successfully"}
    if account_created:
        response["account_created"] = account_created
        response["message"] = "Lead moved to Contacts and Sales Account created successfully"
    return response


@router.delete("/{lead_id}")
async def delete_lead_by_id_endpoint(lead_id: str):
    """
    DELETE /leads/{lead_id}
    Delete an enriched lead by ID.
    """
    from bson import ObjectId
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Delete the lead
    result = leads_enriched_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count > 0:
        return {"success": True, "message": "Lead deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete lead")


@router.get("/enriched/{lead_id}")
async def get_enriched_lead_endpoint(lead_id: str):
    """
    GET /leads/enriched/{lead_id}
    Get a single enriched lead by ID with all details.
    """
    lead = get_enriched_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": lead}


@router.patch("/{lead_id}/status")
async def update_lead_status_endpoint(lead_id: str, data: dict = Body(...)):
    """
    PATCH /leads/{lead_id}/status
    Update the lead_status field (Positive / Negative / Neutral).
    Negative leads are excluded from all outreach communications.
    """
    from bson import ObjectId

    VALID_STATUSES = {"Positive", "Negative", "Neutral"}
    new_status = data.get("lead_status")
    if new_status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"lead_status must be one of: {', '.join(sorted(VALID_STATUSES))}")

    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    result = leads_enriched_collection.update_one(
        {"_id": obj_id},
        {"$set": {"lead_status": new_status, "updated_at": datetime.utcnow().isoformat()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {"success": True, "lead_id": lead_id, "lead_status": new_status}


@router.put("/enriched/{lead_id}")
async def update_enriched_lead_endpoint(lead_id: str, data: dict = Body(...)):
    """
    PUT /leads/enriched/{lead_id}
    Update an enriched lead by ID.
    """
    from bson import ObjectId
    
    # Validate lead_id
    try:
        obj_id = ObjectId(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lead ID format")
    
    # Check if lead exists
    existing_lead = leads_enriched_collection.find_one({"_id": obj_id})
    if not existing_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Remove _id from update data if present
    if "_id" in data:
        del data["_id"]
    
    # Add updated timestamp
    data["updated_at"] = datetime.utcnow().isoformat()
    
    # Update the lead
    result = leads_enriched_collection.update_one(
        {"_id": obj_id},
        {"$set": data}
    )
    
    if result.modified_count > 0:
        # Fetch and return updated lead
        updated_lead = get_enriched_lead_by_id(lead_id)
        return {"success": True, "lead": updated_lead, "message": "Lead updated successfully"}
    else:
        return {"success": True, "lead": get_enriched_lead_by_id(lead_id), "message": "No changes made"}


# ============== DUPLICATE EMAIL HANDLING ==============

@router.get("/duplicates/emails")
async def get_duplicate_emails_endpoint():
    """
    GET /leads/duplicates/emails
    Find all leads with duplicate email addresses.
    """
    return find_duplicate_emails()


@router.delete("/duplicates/emails")
async def delete_duplicate_emails_endpoint():
    """
    DELETE /leads/duplicates/emails
    Delete duplicate leads, keeping only the oldest per email.
    """
    result = delete_duplicate_emails()
    return result


# ============== HEALTH CHECK ==============

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


register_discover_routes(router)

register_ai_database_routes(router)

register_icp_routes(router)
