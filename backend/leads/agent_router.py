"""
Lead Generation Agents API Router
FastAPI endpoints for AI agent operations
"""

import asyncio
import io
import csv
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


# WebSocket manager (optional — graceful if not available)
try:
    from websocket_manager import connection_manager as _ws_manager
    _WS_AVAILABLE = True
except ImportError:
    _ws_manager = None
    _WS_AVAILABLE = False

try:
    from ..agents import (
        AGENT_REGISTRY,
        DAILY_LEAD_LIMIT,
        LEADS_PER_BATCH,
        LeadDeduplicator,
    )
    from ..agents.schemas import (
        AgentConfig,
        AgentJobStatus,
        AgentQuotaStatus,
        AgentStatus,
        AgentType,
        CompanyDiscoveryConfig,
        ContactFinderConfig,
        LeadEnricherConfig,
        LeadScorerConfig,
        OutreachComposerConfig,
    )
except ImportError:
    from agents import (
        AGENT_REGISTRY,
        DAILY_LEAD_LIMIT,
        LEADS_PER_BATCH,
        LeadDeduplicator,
    )
    from agents.schemas import (
        AgentConfig,
        AgentJobStatus,
        AgentQuotaStatus,
        AgentStatus,
        AgentType,
        CompanyDiscoveryConfig,
        ContactFinderConfig,
        LeadEnricherConfig,
        LeadScorerConfig,
        OutreachComposerConfig,
    )

router = APIRouter(prefix="/leads/agents", tags=["Lead Generation Agents"])

# ============== MONGODB CONNECTION ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_mongo_client = _get_pooled_client()
_db = _mongo_client['email_automation']

# Collections
agent_jobs_collection = _db['agent_jobs']
agent_configs_collection = _db['agent_configurations']
discovered_companies_collection = _db['ai_discovered_companies']
outreach_drafts_collection = _db['lead_outreach_drafts']

# Create indexes
try:
    agent_jobs_collection.create_index("job_id", unique=True)
    agent_jobs_collection.create_index("status")
    agent_jobs_collection.create_index("created_at")
    agent_configs_collection.create_index("config_id", unique=True)
    agent_configs_collection.create_index([("user_id", 1), ("name", 1)])
except Exception as e:
    print(f"Warning: Could not create agent indexes: {e}")


# ============== REQUEST/RESPONSE MODELS ==============

class RunAgentsRequest(BaseModel):
    """Request to run lead generation agents"""
    agents: List[str] = Field(
        default=["company_discovery", "contact_finder", "lead_enricher", "lead_scorer", "outreach_composer"],
        description="Agents to run"
    )
    company_ids: Optional[List[str]] = Field(
        default=None,
        description="Company IDs to process (skip discovery if provided)"
    )
    config_id: Optional[str] = Field(
        default=None,
        description="Configuration preset ID to use"
    )
    icp_criteria: Optional[Dict[str, Any]] = Field(
        default=None,
        description="ICP criteria for company discovery"
    )


class RunAgentsResponse(BaseModel):
    """Response from run agents endpoint"""
    job_id: str
    status: str
    message: str
    agents_queued: List[str]


class CompanyUploadResponse(BaseModel):
    """Response from company upload"""
    success: bool
    companies_imported: int
    duplicates_skipped: int
    company_ids: List[str]
    message: str


class ConfigCreateRequest(BaseModel):
    """Request to create agent configuration"""
    name: str
    description: str = ""
    company_discovery: Optional[Dict[str, Any]] = None
    contact_finder: Optional[Dict[str, Any]] = None
    lead_enricher: Optional[Dict[str, Any]] = None
    lead_scorer: Optional[Dict[str, Any]] = None
    outreach_composer: Optional[Dict[str, Any]] = None


class ConfigUpdateRequest(BaseModel):
    """Request to update agent configuration"""
    name: Optional[str] = None
    description: Optional[str] = None
    company_discovery: Optional[Dict[str, Any]] = None
    contact_finder: Optional[Dict[str, Any]] = None
    lead_enricher: Optional[Dict[str, Any]] = None
    lead_scorer: Optional[Dict[str, Any]] = None
    outreach_composer: Optional[Dict[str, Any]] = None


# ============== QUOTA ENDPOINTS ==============

@router.get("/quota", response_model=AgentQuotaStatus)
async def get_quota_status():
    """
    Get current daily quota status.
    Returns leads generated today, daily limit, and remaining quota.
    """
    deduplicator = LeadDeduplicator()
    status = deduplicator.get_quota_status()
    
    return AgentQuotaStatus(
        leads_today=status['leads_today'],
        limit=status['limit'],
        remaining=status['remaining'],
        reset_at=status['reset_at'],
        is_limit_reached=status['is_limit_reached']
    )


# ============== COMPANY UPLOAD ENDPOINTS ==============

@router.post("/import/companies", response_model=CompanyUploadResponse)
async def import_companies(
    file: UploadFile = File(...),
    run_contact_finder: bool = Form(default=False),
    config_id: Optional[str] = Form(default=None)
):
    """
    Upload a CSV file with companies to prospect.
    
    Expected CSV columns:
    - company_name (required)
    - domain (required)
    - industry (optional)
    - size (optional)
    - location (optional)
    
    If run_contact_finder is True, automatically starts the contact finder agent.
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    try:
        content = await file.read()
        decoded = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        
        companies_imported = 0
        duplicates_skipped = 0
        company_ids = []
        
        for row in reader:
            company_name = row.get('company_name', row.get('name', '')).strip()
            domain = row.get('domain', row.get('website', '')).strip()
            
            if not company_name and not domain:
                continue
            
            # Clean up domain
            if domain:
                domain = domain.replace('http://', '').replace('https://', '').replace('www.', '').split('/')[0]
            
            # Check for duplicate
            existing = discovered_companies_collection.find_one({"domain": domain}) if domain else None
            
            if existing:
                duplicates_skipped += 1
                company_ids.append(str(existing['_id']))
                continue
            
            # Insert company
            company_doc = {
                "name": company_name,
                "domain": domain,
                "industry": row.get('industry', ''),
                "size_estimate": row.get('size', row.get('employees', '')),
                "headquarters": row.get('location', row.get('headquarters', '')),
                "description": row.get('description', ''),
                "source": "csv_upload",
                "uploaded_at": datetime.utcnow(),
                "status": "pending"
            }
            
            result = discovered_companies_collection.insert_one(company_doc)
            company_ids.append(str(result.inserted_id))
            companies_imported += 1
        
        # Optionally trigger contact finder
        if run_contact_finder and company_ids:
            try:
                from ..tasks.lead_agent_tasks import run_lead_generation_pipeline
            except ImportError:
                from tasks.lead_agent_tasks import run_lead_generation_pipeline
            
            job_id = str(uuid.uuid4())
            
            # Create job record
            job_doc = {
                "job_id": job_id,
                "status": AgentStatus.PENDING.value,
                "agents_to_run": ["contact_finder", "lead_enricher", "lead_scorer"],
                "company_ids": company_ids,
                "config_id": config_id,
                "created_at": datetime.utcnow()
            }
            agent_jobs_collection.insert_one(job_doc)
            
            # Queue the task
            run_lead_generation_pipeline.delay(
                job_id=job_id,
                company_ids=company_ids,
                config_id=config_id,
                agents_to_run=["contact_finder", "lead_enricher", "lead_scorer"]
            )
        
        return CompanyUploadResponse(
            success=True,
            companies_imported=companies_imported,
            duplicates_skipped=duplicates_skipped,
            company_ids=company_ids,
            message=f"Imported {companies_imported} companies, skipped {duplicates_skipped} duplicates"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process CSV: {str(e)}")


@router.get("/companies")
async def list_companies(
    status: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    List uploaded/discovered companies.
    """
    query = {}
    if status:
        query["status"] = status
    if industry:
        query["industry"] = {"$regex": industry, "$options": "i"}
    
    total = discovered_companies_collection.count_documents(query)
    companies = list(discovered_companies_collection.find(query)
                     .sort("uploaded_at", -1)
                     .skip(skip)
                     .limit(limit))
    
    # Convert ObjectIds
    for c in companies:
        c['_id'] = str(c['_id'])
    
    return {
        "companies": companies,
        "total": total,
        "skip": skip,
        "limit": limit
    }


# ============== AGENT RUN ENDPOINTS ==============

@router.post("/run", response_model=RunAgentsResponse)
async def run_agents(request: RunAgentsRequest):
    """
    Start the lead generation pipeline.
    
    Agents available:
    - company_discovery: Find companies matching ICP
    - contact_finder: Find contacts at companies
    - lead_enricher: Enrich lead data
    - lead_scorer: Score and classify leads
    - outreach_composer: Generate email drafts
    """
    # Validate agents
    valid_agents = list(AGENT_REGISTRY.keys())
    for agent in request.agents:
        if agent not in valid_agents:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid agent: {agent}. Valid agents: {valid_agents}"
            )
    
    # Check quota
    deduplicator = LeadDeduplicator()
    quota = deduplicator.get_quota_status()
    if quota['is_limit_reached']:
        raise HTTPException(
            status_code=429,
            detail=f"Daily lead limit of {DAILY_LEAD_LIMIT} reached. Resets at midnight UTC."
        )
    
    # Create job
    job_id = str(uuid.uuid4())
    
    job_doc = {
        "job_id": job_id,
        "status": AgentStatus.PENDING.value,
        "agents_to_run": request.agents,
        "company_ids": request.company_ids,
        "config_id": request.config_id,
        "icp_criteria": request.icp_criteria,
        "created_at": datetime.utcnow(),
        "total_steps": len(request.agents),
        "completed_steps": 0,
        "progress_percent": 0
    }
    agent_jobs_collection.insert_one(job_doc)
    
    # Queue the pipeline task
    try:
        from ..tasks.lead_agent_tasks import run_lead_generation_pipeline
    except ImportError:
        from tasks.lead_agent_tasks import run_lead_generation_pipeline
    
    run_lead_generation_pipeline.delay(
        job_id=job_id,
        company_ids=request.company_ids,
        config_id=request.config_id,
        agents_to_run=request.agents,
        icp_criteria=request.icp_criteria
    )
    
    return RunAgentsResponse(
        job_id=job_id,
        status="queued",
        message=f"Lead generation pipeline started with {len(request.agents)} agents",
        agents_queued=request.agents
    )


@router.get("/status/{job_id}", response_model=AgentJobStatus)
async def get_job_status(job_id: str):
    """
    Get status of a running or completed agent job.
    """
    job = agent_jobs_collection.find_one({"job_id": job_id})
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    
    return AgentJobStatus(
        job_id=job['job_id'],
        status=AgentStatus(job.get('status', 'pending')),
        agents_to_run=job.get('agents_to_run', []),
        current_agent=job.get('current_agent'),
        total_steps=job.get('total_steps', 0),
        completed_steps=job.get('completed_steps', 0),
        progress_percent=job.get('progress_percent', 0),
        companies_found=job.get('companies_found', 0),
        contacts_found=job.get('contacts_found', 0),
        leads_enriched=job.get('leads_enriched', 0),
        leads_scored=job.get('leads_scored', 0),
        emails_composed=job.get('emails_composed', 0),
        duplicates_skipped=job.get('duplicates_skipped', 0),
        errors=job.get('errors', []),
        warnings=job.get('warnings', []),
        started_at=job.get('started_at'),
        completed_at=job.get('completed_at'),
        config_id=job.get('config_id'),
        created_at=job.get('created_at', datetime.utcnow()),
        updated_at=job.get('updated_at', datetime.utcnow())
    )


@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100)
):
    """
    List agent jobs with optional status filter.
    """
    query = {}
    if status:
        query["status"] = status
    
    total = agent_jobs_collection.count_documents(query)
    jobs = list(agent_jobs_collection.find(query)
                .sort("created_at", -1)
                .skip(skip)
                .limit(limit))
    
    # Convert ObjectIds and format
    formatted_jobs = []
    for job in jobs:
        formatted_jobs.append({
            "job_id": job['job_id'],
            "status": job.get('status', 'unknown'),
            "agents_to_run": job.get('agents_to_run', []),
            "current_agent": job.get('current_agent'),
            "progress_percent": job.get('progress_percent', 0),
            "companies_found": job.get('companies_found', 0),
            "contacts_found": job.get('contacts_found', 0),
            "created_at": job.get('created_at'),
            "completed_at": job.get('completed_at')
        })
    
    return {
        "jobs": formatted_jobs,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """
    Cancel a running job.
    """
    job = agent_jobs_collection.find_one({"job_id": job_id})
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    
    if job.get('status') not in ['pending', 'running']:
        raise HTTPException(status_code=400, detail="Can only cancel pending or running jobs")
    
    agent_jobs_collection.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": AgentStatus.CANCELLED.value,
                "cancelled_at": datetime.utcnow()
            }
        }
    )
    
    return {"success": True, "message": f"Job {job_id} cancelled"}


# ============== CONFIGURATION ENDPOINTS ==============

@router.get("/configs")
async def list_configs(
    user_id: Optional[str] = Query(None),
    include_defaults: bool = Query(True)
):
    """
    List saved agent configurations.
    """
    query = {}
    if user_id:
        if include_defaults:
            query = {"$or": [{"user_id": user_id}, {"is_default": True}]}
        else:
            query = {"user_id": user_id}
    elif include_defaults:
        query = {"is_default": True}
    
    configs = list(agent_configs_collection.find(query).sort("name", 1))
    
    # Format response
    formatted = []
    for config in configs:
        formatted.append({
            "config_id": config.get('config_id', str(config['_id'])),
            "name": config.get('name', 'Unnamed'),
            "description": config.get('description', ''),
            "is_default": config.get('is_default', False),
            "created_at": config.get('created_at'),
            "updated_at": config.get('updated_at')
        })
    
    return {"configs": formatted}


@router.get("/configs/{config_id}")
async def get_config(config_id: str):
    """
    Get a specific agent configuration.
    """
    config = agent_configs_collection.find_one({"config_id": config_id})
    
    if not config:
        # Try by ObjectId
        try:
            config = agent_configs_collection.find_one({"_id": ObjectId(config_id)})
        except:
            pass
    
    if not config:
        raise HTTPException(status_code=404, detail=f"Configuration not found: {config_id}")
    
    # Convert ObjectId
    config['_id'] = str(config['_id'])
    
    return config


@router.post("/configs")
async def create_config(request: ConfigCreateRequest):
    """
    Create a new agent configuration preset.
    """
    config_id = str(uuid.uuid4())
    
    config_doc = {
        "config_id": config_id,
        "name": request.name,
        "description": request.description,
        "is_default": False,
        "company_discovery": request.company_discovery or CompanyDiscoveryConfig().model_dump(),
        "contact_finder": request.contact_finder or ContactFinderConfig().model_dump(),
        "lead_enricher": request.lead_enricher or LeadEnricherConfig().model_dump(),
        "lead_scorer": request.lead_scorer or LeadScorerConfig().model_dump(),
        "outreach_composer": request.outreach_composer or OutreachComposerConfig().model_dump(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    agent_configs_collection.insert_one(config_doc)
    
    return {
        "success": True,
        "config_id": config_id,
        "message": f"Configuration '{request.name}' created"
    }


@router.put("/configs/{config_id}")
async def update_config(config_id: str, request: ConfigUpdateRequest):
    """
    Update an existing agent configuration.
    """
    config = agent_configs_collection.find_one({"config_id": config_id})
    
    if not config:
        raise HTTPException(status_code=404, detail=f"Configuration not found: {config_id}")
    
    if config.get('is_default'):
        raise HTTPException(status_code=400, detail="Cannot modify default configurations")
    
    update_data = {"updated_at": datetime.utcnow()}
    
    if request.name is not None:
        update_data["name"] = request.name
    if request.description is not None:
        update_data["description"] = request.description
    if request.company_discovery is not None:
        update_data["company_discovery"] = request.company_discovery
    if request.contact_finder is not None:
        update_data["contact_finder"] = request.contact_finder
    if request.lead_enricher is not None:
        update_data["lead_enricher"] = request.lead_enricher
    if request.lead_scorer is not None:
        update_data["lead_scorer"] = request.lead_scorer
    if request.outreach_composer is not None:
        update_data["outreach_composer"] = request.outreach_composer
    
    agent_configs_collection.update_one(
        {"config_id": config_id},
        {"$set": update_data}
    )
    
    return {"success": True, "message": f"Configuration updated"}


@router.delete("/configs/{config_id}")
async def delete_config(config_id: str):
    """
    Delete an agent configuration.
    """
    config = agent_configs_collection.find_one({"config_id": config_id})
    
    if not config:
        raise HTTPException(status_code=404, detail=f"Configuration not found: {config_id}")
    
    if config.get('is_default'):
        raise HTTPException(status_code=400, detail="Cannot delete default configurations")
    
    agent_configs_collection.delete_one({"config_id": config_id})
    
    return {"success": True, "message": "Configuration deleted"}


@router.post("/configs/seed-defaults")
async def seed_default_configs():
    """
    Seed default configuration presets.
    """
    defaults = [
        {
            "config_id": "default-saas-startups",
            "name": "SaaS Startups",
            "description": "Target early-stage SaaS companies looking for growth solutions",
            "is_default": True,
            "company_discovery": {
                "icp_description": "B2B SaaS startups in growth phase looking for sales and marketing automation",
                "industries": ["SaaS", "Software", "Technology"],
                "company_sizes": ["11-50", "51-200"],
                "locations": ["United States", "Canada", "United Kingdom"]
            },
            "contact_finder": {
                "target_titles": ["CEO", "CTO", "VP Sales", "Head of Growth", "Founder"],
                "decision_levels": ["C-Level", "VP", "Director"],
                "departments": ["Executive", "Sales", "Marketing"]
            },
            "lead_scorer": {
                "ideal_titles": ["CEO", "Founder", "VP Sales", "Head of Growth"],
                "ideal_industries": ["SaaS", "Software", "Technology"],
                "ideal_company_sizes": ["11-50", "51-200"],
                "minimum_score_threshold": 60
            },
            "outreach_composer": {
                "tone": "friendly",
                "value_proposition": "We help SaaS startups scale their outbound sales 3x faster with AI-powered automation.",
                "personalization_level": "high"
            }
        },
        {
            "config_id": "default-enterprise-b2b",
            "name": "Enterprise B2B",
            "description": "Target enterprise companies with established sales teams",
            "is_default": True,
            "company_discovery": {
                "icp_description": "Enterprise B2B companies with dedicated sales and marketing teams",
                "industries": ["Enterprise Software", "Financial Services", "Healthcare"],
                "company_sizes": ["201-1000", "1000+"],
                "locations": ["United States", "United Kingdom", "Germany"]
            },
            "contact_finder": {
                "target_titles": ["VP Sales", "Director of Sales", "Head of Revenue", "CRO"],
                "decision_levels": ["VP", "Director"],
                "departments": ["Sales", "Revenue Operations"]
            },
            "lead_scorer": {
                "ideal_titles": ["VP Sales", "CRO", "Director of Sales Operations"],
                "ideal_industries": ["Enterprise Software", "Financial Services"],
                "ideal_company_sizes": ["201-1000", "1000+"],
                "minimum_score_threshold": 70
            },
            "outreach_composer": {
                "tone": "formal",
                "value_proposition": "We help enterprise sales teams reduce manual outreach by 80% while improving conversion rates.",
                "personalization_level": "medium"
            }
        },
        {
            "config_id": "default-smb-local",
            "name": "SMB Local Business",
            "description": "Target small and medium local businesses",
            "is_default": True,
            "company_discovery": {
                "icp_description": "Small and medium local businesses looking for digital solutions",
                "industries": ["Retail", "Professional Services", "Healthcare", "Real Estate"],
                "company_sizes": ["1-10", "11-50"],
                "locations": ["United States"]
            },
            "contact_finder": {
                "target_titles": ["Owner", "CEO", "President", "General Manager"],
                "decision_levels": ["C-Level", "Manager"],
                "departments": ["Executive", "Operations"]
            },
            "lead_scorer": {
                "ideal_titles": ["Owner", "CEO", "President"],
                "ideal_industries": ["Retail", "Professional Services"],
                "ideal_company_sizes": ["1-10", "11-50"],
                "minimum_score_threshold": 50
            },
            "outreach_composer": {
                "tone": "casual",
                "value_proposition": "We help small businesses save 10+ hours per week on sales outreach.",
                "personalization_level": "high"
            }
        }
    ]
    
    inserted = 0
    for default in defaults:
        existing = agent_configs_collection.find_one({"config_id": default["config_id"]})
        if not existing:
            default["created_at"] = datetime.utcnow()
            default["updated_at"] = datetime.utcnow()
            agent_configs_collection.insert_one(default)
            inserted += 1
    
    return {
        "success": True,
        "message": f"Seeded {inserted} default configurations",
        "total_defaults": len(defaults)
    }


# ============== OUTREACH DRAFTS ENDPOINTS ==============

@router.get("/drafts")
async def list_outreach_drafts(
    job_id: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    """
    List generated outreach email drafts.
    """
    query = {}
    if job_id:
        query["job_id"] = job_id
    if lead_id:
        query["lead_id"] = lead_id
    if status:
        query["status"] = status
    
    total = outreach_drafts_collection.count_documents(query)
    drafts = list(outreach_drafts_collection.find(query)
                  .sort("created_at", -1)
                  .skip(skip)
                  .limit(limit))
    
    # Convert ObjectIds
    for d in drafts:
        d['_id'] = str(d['_id'])
    
    return {
        "drafts": drafts,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: str, updates: Dict[str, Any] = Body(...)):
    """
    Update an outreach draft (e.g., edit content, mark as sent).
    """
    try:
        result = outreach_drafts_collection.update_one(
            {"_id": ObjectId(draft_id)},
            {"$set": {**updates, "updated_at": datetime.utcnow()}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Draft not found")
        
        return {"success": True, "message": "Draft updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: str):
    """
    Delete an outreach draft.
    """
    try:
        result = outreach_drafts_collection.delete_one({"_id": ObjectId(draft_id)})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Draft not found")
        
        return {"success": True, "message": "Draft deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== WEBSOCKET ENDPOINTS ==============

_AGENT_WS_CHANNEL = "lead_generation"


@router.websocket("/ws/{job_id}")
async def agent_job_websocket(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for real-time agent job progress.

    Connect for a specific job (or 'all' for all jobs) to receive:
    - agent_progress: incremental pipeline updates
    - job_completed / job_failed: terminal events
    - heartbeat: keep-alive every 30 s
    """
    if not _WS_AVAILABLE or _ws_manager is None:
        await websocket.close(code=1011, reason="WebSocket manager not available")
        return

    connected = await _ws_manager.connect(
        websocket,
        channel=_AGENT_WS_CHANNEL,
        metadata={"job_id": job_id, "connected_from": "agent_router"},
    )
    if not connected:
        return

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=35.0)
                try:
                    msg = __import__("json").loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json(
                            {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
                        )
                except Exception:
                    pass
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json(
                        {"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()}
                    )
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Agent WebSocket error: %s", exc)
    finally:
        _ws_manager.disconnect(websocket, _AGENT_WS_CHANNEL)
