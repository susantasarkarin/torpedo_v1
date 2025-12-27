"""
AGENT 4 — BACKEND API ENGINEER
FastAPI Router for Lead Management
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File, Form
from typing import Optional
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
    get_lead_statistics
)
from .ingestion import (
    search_linkedin_leads, parse_csv_leads, import_from_google_sheet,
    import_leads_from_source
)

router = APIRouter(prefix="/leads", tags=["Leads"])


# ============== IMPORT MODELS ==============

class GoogleSearchRequest(BaseModel):
    query: str
    num_results: int = 10


class WebSearchRequest(BaseModel):
    """Enhanced web search with filters"""
    designation: str = ""  # e.g., "CEO", "VP Sales"
    country: str = ""  # e.g., "India", "USA"
    seniority: str = ""  # e.g., "C-Level", "VP"
    custom_query: str = ""  # Additional search terms
    target_count: int = 100  # Target number of leads (up to 5000)


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
    Continues searching until target_count is reached (max 5000).
    """
    try:
        # Build search query from filters
        query_parts = []
        
        if request.designation:
            query_parts.append(f'"{request.designation}"')
        
        if request.seniority:
            seniority_keywords = {
                "C-Level": "CEO OR CTO OR CFO OR COO OR CMO OR CRO OR Chief",
                "VP": "VP OR Vice President OR SVP OR EVP",
                "Director": "Director OR Head of",
                "Manager": "Manager OR Team Lead",
                "IC": "Analyst OR Specialist OR Engineer OR Developer"
            }
            if request.seniority in seniority_keywords:
                query_parts.append(f"({seniority_keywords[request.seniority]})")
            else:
                query_parts.append(request.seniority)
        
        if request.country:
            query_parts.append(request.country)
        
        if request.custom_query:
            query_parts.append(request.custom_query)
        
        if not query_parts:
            raise ValueError("At least one search filter (designation, country, seniority, or custom_query) is required")
        
        final_query = " ".join(query_parts)
        target_count = min(request.target_count, 5000)  # Cap at 5000
        
        all_leads = []
        start_index = 1
        batch_size = 10  # Google CSE returns max 10 per request
        
        # Keep searching until we reach target or no more results
        while len(all_leads) < target_count:
            remaining = target_count - len(all_leads)
            num_to_fetch = min(batch_size, remaining)
            
            leads = await search_linkedin_leads(
                query=final_query,
                num_results=num_to_fetch,
                start=start_index
            )
            
            if not leads:
                break  # No more results
            
            all_leads.extend(leads)
            start_index += len(leads)
            
            # Safety check - Google CSE has limits
            if start_index > 100:  # Google CSE max is 100 results per query
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
            "query_used": final_query,
            "message": f"Found {len(all_leads)} leads, imported {result.imported}"
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


# ============== HEALTH CHECK ==============

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
