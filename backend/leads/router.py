"""
AGENT 4 — BACKEND API ENGINEER
FastAPI Router for Lead Management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File, Form
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from .models import (
    LeadInput, LeadImportRequest, LeadImportResponse,
    LeadClassifyRequest, LeadClassifyResponse, LeadFilterParams,
    AttachLeadsRequest, SeniorityLevel, Department, Persona,
    CompanySize, Region, ClassificationStatus
)
from .service import (
    import_leads, classify_pending_leads, classify_single_lead,
    get_leads, get_raw_leads_with_status, attach_leads_to_campaign,
    get_lead_statistics, delete_leads_by_source, delete_all_leads
)
from .ingestion import (
    search_linkedin_leads, parse_csv_leads, import_from_google_sheet,
    import_leads_from_source
)
from .imap_leads_service import (
    import_leads_from_emails, get_email_leads, get_segment_statistics,
    get_imap_accounts, add_imap_account, remove_imap_account,
    test_imap_connection, EmailSegment
)

router = APIRouter(prefix="/leads", tags=["Leads"])


# ============== IMPORT MODELS ==============

class GoogleSearchRequest(BaseModel):
    query: str
    num_results: int = 10


class WebSearchRequest(BaseModel):
    """Enhanced web search with filters - supports multi-select"""
    designation: str = ""  # e.g., "CEO", "VP Sales" - comma separated for multiple
    countries: List[str] = []  # Multiple countries supported
    seniorities: List[str] = []  # Multiple seniority levels supported
    custom_query: str = ""  # Additional search terms
    target_count: int = 10000  # Target number of leads (now 10000)
    # Legacy single-value fields for backward compatibility
    country: str = ""
    seniority: str = ""


class GoogleSheetRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str = "Sheet1"
    range_notation: str = "A:Z"


# ============== WEB SEARCH ENDPOINT (ENHANCED) ==============

@router.post("/import/web-search")
async def import_from_web_search(
    request: WebSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/import/web-search
    Enhanced LinkedIn search with designation, country, and seniority filters.
    Supports multiple countries and seniority levels.
    Continues searching until target_count is reached (default 10000).
    Uses multiple query variations to maximize results.
    """
    try:
        # Handle both new multi-select and legacy single-select
        countries = request.countries if request.countries else ([request.country] if request.country else [])
        seniorities = request.seniorities if request.seniorities else ([request.seniority] if request.seniority else [])
        designations = [d.strip() for d in request.designation.split(",")] if request.designation else []
        
        if not designations and not countries and not seniorities and not request.custom_query:
            raise ValueError("At least one search filter (designation, country, seniority, or custom_query) is required")
        
        target_count = min(request.target_count, 10000)  # Cap at 10000
        
        # Build all query combinations for multi-select
        query_combinations = []
        
        # Generate query variations for each combination
        for designation in (designations if designations else [""]):
            for country in (countries if countries else [""]):
                for seniority in (seniorities if seniorities else [""]):
                    query_parts = []
                    
                    if designation:
                        query_parts.append(f'"{designation}"')
                    
                    if seniority:
                        # LinkedIn Seniority Levels mapping to search keywords
                        seniority_keywords = {
                            "Owner": "Owner OR Business Owner OR Proprietor",
                            "Founder": "Founder OR Co-Founder OR Cofounder",
                            "CXO": "CEO OR CTO OR CFO OR COO OR CMO OR CRO OR CIO OR CHRO OR CPO OR Chief",
                            "Partner": "Partner OR Managing Partner OR General Partner",
                            "VP": "VP OR Vice President OR SVP OR EVP OR AVP",
                            "Director": "Director OR Head of OR Group Director",
                            "Manager": "Manager OR Team Lead OR Supervisor",
                            "Senior": "Senior OR Sr. OR Lead OR Principal",
                            "Entry": "Associate OR Junior OR Entry OR Analyst",
                            "Training": "Intern OR Trainee OR Apprentice",
                            "Unpaid": "Volunteer OR Board Member"
                        }
                        if seniority in seniority_keywords:
                            query_parts.append(f"({seniority_keywords[seniority]})")
                        else:
                            query_parts.append(seniority)
                    
                    if country:
                        query_parts.append(country)
                    
                    if request.custom_query:
                        query_parts.append(request.custom_query)
                    
                    if query_parts:
                        query_combinations.append(" ".join(query_parts))
        
        # Remove duplicates
        query_combinations = list(set(query_combinations)) if query_combinations else [request.custom_query]
        
        all_leads = []
        seen_urls = set()
        batch_size = 10  # Google CSE returns max 10 per request
        
        # Loop through all query combinations
        for query in query_combinations:
            if len(all_leads) >= target_count:
                break
                
            start_index = 1
            consecutive_empty = 0
            
            # Keep searching with this query until we get no more results or hit Google CSE limit
            while len(all_leads) < target_count and consecutive_empty < 3:
                remaining = target_count - len(all_leads)
                num_to_fetch = min(batch_size, remaining)
                
                try:
                    leads = await search_linkedin_leads(
                        query=query,
                        num_results=num_to_fetch,
                        start=start_index
                    )
                    
                    if not leads:
                        consecutive_empty += 1
                        start_index += batch_size
                        continue
                    
                    consecutive_empty = 0
                    
                    # Deduplicate by linkedin_url
                    for lead in leads:
                        url = lead.get("linkedin_url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_leads.append(lead)
                    
                    start_index += len(leads)
                    
                    # Google CSE has a limit of 100 results per query
                    if start_index > 100:
                        break
                        
                except Exception as e:
                    print(f"Error searching with query '{query}': {e}")
                    break
        
        if not all_leads:
            return {"imported": 0, "message": "No LinkedIn profiles found for this query"}
        
        # Convert to LeadInput format and import
        lead_inputs = [LeadInput(**lead) for lead in all_leads]
        result = import_leads(lead_inputs)
        
        return {
            "found": len(all_leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "queries_used": len(query_combinations),
            "message": f"Found {len(all_leads)} leads across {len(query_combinations)} search(es), imported {result.imported}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== GOOGLE SEARCH ENDPOINT (LEGACY) ==============

@router.post("/import/google-search")
async def import_from_google_search(
    request: GoogleSearchRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/import/google-search
    Search LinkedIn profiles via Google Custom Search and import results.
    """
    try:
        leads = await search_linkedin_leads(
            query=request.query,
            num_results=request.num_results
        )
        
        if not leads:
            return {"imported": 0, "message": "No LinkedIn profiles found for this query"}
        
        # Convert to LeadInput format and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "found": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "message": f"Found {len(leads)} leads, imported {result.imported}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== CSV UPLOAD ENDPOINT ==============

@router.post("/import/csv")
async def import_from_csv(
    file: UploadFile = File(...),
    delimiter: str = Form(",")
):
    """
    POST /leads/import/csv
    Upload a CSV file containing leads.
    Expected columns: name, title, linkedin_url, snippet
    """
    try:
        # Read file content
        content = await file.read()
        csv_content = content.decode("utf-8")
        
        # Parse CSV
        leads = parse_csv_leads(csv_content, delimiter)
        
        if not leads:
            return {"imported": 0, "message": "No valid leads found in CSV"}
        
        # Convert to LeadInput and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "parsed": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "errors": result.errors,
            "message": f"Parsed {len(leads)} leads from CSV, imported {result.imported}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== GOOGLE SHEETS ENDPOINT ==============

@router.post("/import/google-sheets")
async def import_from_google_sheets(request: GoogleSheetRequest):
    """
    POST /leads/import/google-sheets
    Import leads from a public Google Sheet.
    Sheet must be set to "Anyone with link can view".
    """
    try:
        leads = await import_from_google_sheet(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            range_notation=request.range_notation
        )
        
        if not leads:
            return {"imported": 0, "message": "No valid leads found in sheet"}
        
        # Convert to LeadInput and import
        lead_inputs = [LeadInput(**lead) for lead in leads]
        result = import_leads(lead_inputs)
        
        return {
            "parsed": len(leads),
            "imported": result.imported,
            "duplicates": result.duplicates,
            "message": f"Imported {result.imported} leads from Google Sheet"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== JSON IMPORT ENDPOINT ==============

@router.post("/import", response_model=LeadImportResponse)
async def import_leads_endpoint(request: LeadImportRequest):
    """
    POST /leads/import
    Import LinkedIn leads with idempotent behavior.
    Duplicates are detected by linkedin_url and skipped.
    """
    try:
        result = import_leads(request.leads)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        # Classify all pending leads in background
        background_tasks.add_task(classify_pending_leads, request.batch_size)
        return LeadClassifyResponse(
            queued=request.batch_size,
            message=f"Queued up to {request.batch_size} pending leads for classification"
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
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads
    Retrieve enriched leads with filtering and pagination.
    """
    filters = LeadFilterParams(
        seniority_level=seniority_level,
        department=department,
        persona=persona,
        company_size=company_size,
        industry=industry,
        region=region,
        min_confidence=min_confidence,
        search=search,
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


@router.get("/raw")
async def get_raw_leads_endpoint():
    """
    GET /leads/raw
    Get all raw leads with their classification status.
    """
    leads = get_raw_leads_with_status()
    return {"leads": leads, "total": len(leads)}


@router.get("/statistics")
async def get_statistics_endpoint():
    """
    GET /leads/statistics
    Get lead statistics for dashboard.
    """
    return get_lead_statistics()


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


# ============== EMAIL/IMAP LEADS ENDPOINTS (Issue 7 - IMAP/SMTP) ==============

class EmailImportRequest(BaseModel):
    """Request model for email leads import via IMAP"""
    account_emails: Optional[List[str]] = None  # None = all accounts
    max_emails: int = 500
    since_days: int = 30
    segments: Optional[List[str]] = None  # Filter by segment


class IMAPAccountCreate(BaseModel):
    """Request model for adding IMAP account"""
    email: str
    password: str  # App password for Gmail
    display_name: str = ""
    imap_server: str = None  # Auto-detected from email domain
    imap_port: int = 993
    smtp_server: str = None  # Auto-detected from email domain
    smtp_port: int = 587
    use_ssl: bool = True
    is_default: bool = False


@router.get("/gmail/accounts")
async def get_email_accounts_endpoint():
    """
    GET /leads/gmail/accounts
    Get all configured IMAP email accounts.
    """
    accounts = get_imap_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@router.post("/gmail/accounts")
async def add_email_account_endpoint(request: IMAPAccountCreate):
    """
    POST /leads/gmail/accounts
    Add a new IMAP email account.
    For Gmail, use an App Password (not your regular password).
    """
    result = add_imap_account(
        email_address=request.email,
        password=request.password,
        display_name=request.display_name,
        imap_server=request.imap_server,
        imap_port=request.imap_port,
        smtp_server=request.smtp_server,
        smtp_port=request.smtp_port,
        use_ssl=request.use_ssl,
        is_default=request.is_default
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result


@router.delete("/gmail/accounts/{email}")
async def remove_email_account_endpoint(email: str):
    """
    DELETE /leads/gmail/accounts/{email}
    Remove an IMAP email account.
    """
    result = remove_imap_account(email)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/gmail/accounts/{email}/test")
async def test_email_account_endpoint(email: str):
    """
    POST /leads/gmail/accounts/{email}/test
    Test IMAP connection for an account.
    """
    result = test_imap_connection(email)
    return result


@router.post("/gmail/import")
async def import_email_leads_endpoint(
    request: EmailImportRequest,
    background_tasks: BackgroundTasks
):
    """
    POST /leads/gmail/import
    Import leads from email accounts via IMAP.
    Extracts contacts from emails and categorizes by segment.
    """
    try:
        result = import_leads_from_emails(
            account_emails=request.account_emails,
            max_emails=request.max_emails,
            since_days=request.since_days,
            segments=request.segments
        )
        
        return {
            "success": result.get("success", True),
            "emails_processed": result.get("emails_processed", 0),
            "leads_imported": result.get("leads_imported", 0),
            "duplicates": result.get("duplicates", 0),
            "errors": result.get("errors"),
            "message": result.get("message", "Import completed")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/leads")
async def get_email_leads_endpoint(
    segment: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    """
    GET /leads/gmail/leads
    Get leads extracted from emails with filtering.
    """
    skip = (page - 1) * limit
    leads = get_email_leads(
        segment=segment,
        limit=limit,
        skip=skip
    )
    
    return {
        "leads": leads,
        "total": len(leads),
        "page": page,
        "limit": limit
    }


@router.get("/gmail/segments")
async def get_email_segments_endpoint():
    """
    GET /leads/gmail/segments
    Get available segments and their lead counts.
    """
    stats = get_segment_statistics()
    segments = [
        {"id": s.value, "name": s.value.replace("_", " ").title(), "count": stats.get(s.value, 0)}
        for s in EmailSegment
    ]
    return {"segments": segments}


# ============== HEALTH CHECK ==============

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
