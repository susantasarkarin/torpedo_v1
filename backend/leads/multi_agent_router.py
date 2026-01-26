"""
Multi-Agent System API Router
==============================

FastAPI endpoints for the multi-agent lead generation system.

Endpoints:
- /agents/list - List all available agents
- /agents/run/{phase} - Run a specific phase agent
- /agents/run/pipeline - Run the full pipeline via orchestrator
- /agents/status - Get status of all agents
- /agents/history - Get pipeline execution history
- /agents/{phase}/stats - Get statistics for a phase
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

# Import agents
from .agents import (
    Phase3Agent,
    Phase4Agent,
    Phase5Agent,
    Phase6Agent,
    OrchestratorAgent,
    AgentStatus
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Multi-Agent System"])


# ============== REQUEST/RESPONSE MODELS ==============

class RunPhaseRequest(BaseModel):
    """Request to run a specific phase agent"""
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom configuration for the agent"
    )
    input_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Input data for the agent"
    )
    async_mode: bool = Field(
        default=False,
        description="Run in background (returns job ID immediately)"
    )


class RunPipelineRequest(BaseModel):
    """Request to run the full pipeline"""
    mode: str = Field(
        default="sequential",
        description="Execution mode: sequential, parallel, or selective"
    )
    phases: List[int] = Field(
        default=[3, 4, 5, 6],
        description="Phases to run (3=patterns, 4=testing, 5=enrichment, 6=CRM)"
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pipeline configuration"
    )
    input_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Input data for all phases"
    )
    async_mode: bool = Field(
        default=False,
        description="Run in background"
    )


class AgentResponse(BaseModel):
    """Response from agent execution"""
    success: bool
    agent_name: str
    phase: int
    status: str
    duration_seconds: float
    records_processed: int
    records_success: int
    errors: List[str]
    warnings: List[str]
    metrics: Dict[str, Any]
    output: Dict[str, Any]


class PipelineResponse(BaseModel):
    """Response from pipeline execution"""
    success: bool
    pipeline_id: str
    status: str
    phases_executed: int
    phase_results: Dict[str, Any]
    validation: Dict[str, Any]
    combined_report: Dict[str, Any]


class JobResponse(BaseModel):
    """Response for async job submission"""
    job_id: str
    status: str
    message: str


# ============== BACKGROUND JOB STORAGE ==============

# In-memory job storage (use Redis in production)
_active_jobs: Dict[str, Dict[str, Any]] = {}


# ============== AGENT INSTANCES ==============

def get_agent(phase: int):
    """Get agent instance by phase number"""
    agents = {
        3: Phase3Agent,
        4: Phase4Agent,
        5: Phase5Agent,
        6: Phase6Agent,
        0: OrchestratorAgent
    }
    
    agent_class = agents.get(phase)
    if not agent_class:
        raise HTTPException(status_code=404, detail=f"Phase {phase} agent not found")
    
    return agent_class()


# ============== ENDPOINTS ==============

@router.get("/list")
async def list_agents():
    """
    List all available agents with their descriptions.
    """
    agents_info = []
    
    for phase in [3, 4, 5, 6, 0]:
        try:
            agent = get_agent(phase)
            agents_info.append({
                "phase": phase,
                "name": agent.name,
                "description": agent.get_description(),
                "available": True
            })
        except Exception as e:
            agents_info.append({
                "phase": phase,
                "name": f"Phase {phase}",
                "description": "Agent not available",
                "available": False,
                "error": str(e)
            })
    
    return {
        "agents": agents_info,
        "total": len(agents_info)
    }


@router.post("/run/pipeline", response_model=PipelineResponse)
async def run_pipeline_route(
    request: RunPipelineRequest,
    background_tasks: BackgroundTasks
):
    """
    Run the full pipeline via the Orchestrator agent.
    
    Modes:
    - sequential: Run phases one after another
    - parallel: Run independent phases in parallel
    - selective: Run only specified phases independently
    """
    # This route needs to be BEFORE /run/{phase} to avoid matching "pipeline" as a phase
    orchestrator = OrchestratorAgent()
    
    # Configure orchestrator
    if request.config:
        orchestrator.configure(request.config)
    
    input_data = request.input_data or {}
    input_data["mode"] = request.mode
    input_data["phases"] = request.phases
    
    if request.async_mode:
        # Run in background
        import uuid
        job_id = str(uuid.uuid4())[:8]
        _active_jobs[job_id] = {
            "status": "running",
            "type": "pipeline",
            "phases": request.phases,
            "started_at": datetime.utcnow().isoformat()
        }
        
        async def run_async():
            try:
                result = await orchestrator.run(input_data)
                _active_jobs[job_id] = {
                    "status": result.status.value,
                    "result": result.to_dict(),
                    "completed_at": datetime.utcnow().isoformat()
                }
            except Exception as e:
                _active_jobs[job_id] = {
                    "status": "error",
                    "error": str(e),
                    "completed_at": datetime.utcnow().isoformat()
                }
        
        background_tasks.add_task(run_async)
        
        return PipelineResponse(
            success=True,
            pipeline_id=job_id,
            status="queued",
            phases_executed=0,
            phase_results={},
            validation={},
            combined_report={"message": f"Pipeline {job_id} queued for execution"}
        )
    
    # Run synchronously
    try:
        result = await orchestrator.run(input_data)
        
        return PipelineResponse(
            success=result.status in [AgentStatus.SUCCESS, AgentStatus.PARTIAL],
            pipeline_id=result.metrics.get("pipeline_id", "unknown"),
            status=result.status.value,
            phases_executed=result.metrics.get("phases_completed", 0),
            phase_results=result.output_data.get("phase_results", {}),
            validation=result.output_data.get("validation", {}),
            combined_report=result.output_data.get("combined_report", {})
        )
    
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        orchestrator.cleanup()


@router.post("/run/{phase}", response_model=AgentResponse)
async def run_phase_agent(
    phase: int,
    request: RunPhaseRequest,
    background_tasks: BackgroundTasks
):
    """
    Run a specific phase agent.
    
    Phases:
    - 3: Email Pattern Discovery + Company Cache
    - 4: Testing & Validation
    - 5: Automated Enrichment
    - 6: CRM Integration
    """
    if phase == 0:
        raise HTTPException(
            status_code=400, 
            detail="Use /agents/run/pipeline for orchestrator"
        )
    
    agent = get_agent(phase)
    
    # Configure agent
    if request.config:
        agent.configure(request.config)
    
    input_data = request.input_data or {}
    
    if request.async_mode:
        # Run in background
        import uuid
        job_id = str(uuid.uuid4())[:8]
        _active_jobs[job_id] = {
            "status": "running",
            "phase": phase,
            "started_at": datetime.utcnow().isoformat()
        }
        
        async def run_async():
            try:
                result = await agent.run(input_data)
                _active_jobs[job_id] = {
                    "status": result.status.value,
                    "result": result.to_dict(),
                    "completed_at": datetime.utcnow().isoformat()
                }
            except Exception as e:
                _active_jobs[job_id] = {
                    "status": "error",
                    "error": str(e),
                    "completed_at": datetime.utcnow().isoformat()
                }
        
        background_tasks.add_task(run_async)
        
        return AgentResponse(
            success=True,
            agent_name=agent.name,
            phase=phase,
            status="queued",
            duration_seconds=0,
            records_processed=0,
            records_success=0,
            errors=[],
            warnings=[],
            metrics={"job_id": job_id},
            output={"message": f"Job {job_id} queued for background execution"}
        )
    
    # Run synchronously
    try:
        result = await agent.run(input_data)
        
        return AgentResponse(
            success=result.status in [AgentStatus.SUCCESS, AgentStatus.PARTIAL],
            agent_name=result.agent_name,
            phase=result.phase,
            status=result.status.value,
            duration_seconds=result.duration_seconds,
            records_processed=result.records_processed,
            records_success=result.records_success,
            errors=result.errors,
            warnings=result.warnings,
            metrics=result.metrics,
            output=result.output_data
        )
    
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        agent.cleanup()


@router.get("/status")
async def get_agents_status():
    """
    Get status of all agents.
    """
    orchestrator = OrchestratorAgent()
    
    try:
        status = await orchestrator.get_agent_status()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "agents": status,
            "active_jobs": len(_active_jobs)
        }
    finally:
        orchestrator.cleanup()


@router.get("/jobs")
async def list_jobs():
    """
    List all active and recent jobs.
    """
    return {
        "jobs": _active_jobs,
        "total": len(_active_jobs)
    }


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Get status of a specific job.
    """
    job = _active_jobs.get(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return {
        "job_id": job_id,
        **job
    }


@router.get("/history")
async def get_pipeline_history(limit: int = Query(default=10, le=100)):
    """
    Get recent pipeline execution history.
    """
    orchestrator = OrchestratorAgent()
    
    try:
        history = await orchestrator.get_pipeline_history(limit=limit)
        
        return {
            "runs": history,
            "total": len(history)
        }
    finally:
        orchestrator.cleanup()


@router.get("/{phase}/stats")
async def get_phase_stats(phase: int):
    """
    Get statistics for a specific phase.
    """
    agent = get_agent(phase)
    
    try:
        if phase == 3:
            stats = await agent.get_stats()
        elif phase == 4:
            # Phase 4 doesn't have persistent stats
            stats = {"message": "Run phase 4 to generate test results"}
        elif phase == 5:
            stats = await agent.get_pipeline_stats()
        elif phase == 6:
            stats = await agent.get_sync_stats()
        else:
            stats = {"message": "Stats not available for this phase"}
        
        return {
            "phase": phase,
            "agent": agent.name,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        agent.cleanup()


@router.post("/{phase}/configure")
async def configure_agent(phase: int, config: Dict[str, Any]):
    """
    Update configuration for a phase agent.
    Configuration is applied for the next run.
    """
    agent = get_agent(phase)
    
    try:
        agent.configure(config)
        
        return {
            "phase": phase,
            "agent": agent.name,
            "config_updated": True,
            "current_config": agent.config
        }
    finally:
        agent.cleanup()


@router.post("/3/lookup-company")
async def lookup_company(domain: str):
    """
    Look up a company in the cache (Phase 3).
    """
    agent = Phase3Agent()
    
    try:
        result = await agent.lookup_company(domain)
        
        if result:
            return {
                "found": True,
                "company": result
            }
        else:
            return {
                "found": False,
                "message": f"Company {domain} not in cache"
            }
    finally:
        agent.cleanup()


@router.post("/3/predict-email")
async def predict_email(domain: str, first_name: str, last_name: str = ""):
    """
    Predict email address based on discovered patterns (Phase 3).
    """
    agent = Phase3Agent()
    
    try:
        result = await agent.predict_email(domain, first_name, last_name)
        
        if result:
            return {
                "success": True,
                **result
            }
        else:
            return {
                "success": False,
                "message": f"No pattern found for domain {domain}"
            }
    finally:
        agent.cleanup()


@router.post("/6/configure-hubspot")
async def configure_hubspot(api_key: str):
    """
    Configure HubSpot integration (Phase 6).
    """
    agent = Phase6Agent()
    
    try:
        result = await agent.configure_hubspot(api_key)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        agent.cleanup()


@router.get("/health")
async def agents_health():
    """
    Health check for the agent system.
    """
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": {}
    }
    
    for phase in [3, 4, 5, 6]:
        try:
            agent = get_agent(phase)
            health["agents"][phase] = {
                "name": agent.name,
                "available": True
            }
            agent.cleanup()
        except Exception as e:
            health["agents"][phase] = {
                "available": False,
                "error": str(e)
            }
            health["status"] = "degraded"
    
    return health
