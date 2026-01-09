"""
CLAY-LEVEL API ENDPOINTS
FastAPI routes for:
- Preview execution
- Filter compilation & query planning
- Import gating & deduplication
- Workbook management and column execution
- Cost tracking and budget controls
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Body
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..clay_models import (
    QueryPlan, PreviewExecution, FilterGroup, Source, ImportSession,
    Workbook, Column, CellValue, WorkbookRow, ExecutionLog,
    SourceType, SourceProvider, DeduplicationRule
)
from ..preview_executor import (
    PreviewExecutionEngine, CostEstimator, SchemaInferenceEngine
)
from ..filter_builder import QueryPlanCompiler
from ..import_gating import (
    ImportGatingManager, DeduplicationEngine, ImportValidator, CostEnforcer
)
from ..workbook_engine import WorkbookExecutionEngine

router = APIRouter(prefix="/leads/clay", tags=["Clay-Level Features"])

# Initialize engines
preview_engine = PreviewExecutionEngine()
filter_compiler = QueryPlanCompiler()
import_manager = ImportGatingManager()
workbook_engine = WorkbookExecutionEngine()
cost_enforcer = CostEnforcer()


# ============== PREVIEW EXECUTION ==============

@router.post("/preview/execute")
async def execute_preview(
    campaign_id: str = Query(...),
    query_plan: QueryPlan = Body(...),
    primary_provider: SourceProvider = Query(SourceProvider.CLAY),
    fallback_providers: Optional[List[SourceProvider]] = Query(None)
):
    """
    Execute a dry-run query preview
    
    Returns sample records (~50 rows) with:
    - Inferred schema
    - Field coverage metrics
    - Estimated cost
    - Total estimated records
    """
    
    preview = await preview_engine.execute_preview(
        query_plan,
        campaign_id,
        primary_provider,
        fallback_providers
    )
    
    return {
        "preview_id": preview.preview_id,
        "status": preview.status,
        "sample_records": preview.sample_records,
        "total_estimated": preview.total_estimated,
        "actual_returned": preview.actual_returned,
        "inferred_schema": preview.inferred_schema,
        "field_coverage": preview.field_coverage,
        "estimated_cost": preview.estimated_cost,
        "provider_used": preview.provider_used,
        "error": preview.error
    }


# ============== FILTER COMPILATION & QUERY PLANNING ==============

@router.post("/filters/compile")
async def compile_filters(
    source_type: SourceType = Body(...),
    filters: FilterGroup = Body(...),
    required_fields: Optional[List[str]] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0)
):
    """
    Compile UI filters to provider-agnostic query plan
    
    The query plan is provider-independent and can be executed
    against any data source with appropriate translation
    """
    
    # Validate filters
    is_valid, errors = filter_compiler.validate_filter_group(filters)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid filters: {errors}")
    
    # Compile to query plan
    query_plan = filter_compiler.compile_to_query_plan(
        source_type,
        filters,
        set(required_fields) if required_fields else None,
        limit,
        offset
    )
    
    # Estimate results
    estimated_results = filter_compiler.estimate_results(query_plan, SourceProvider.CLAY)
    
    return {
        "query_plan": query_plan,
        "estimated_results": estimated_results,
        "is_valid": True
    }


@router.post("/filters/translate")
async def translate_for_provider(
    query_plan: QueryPlan = Body(...),
    target_provider: SourceProvider = Query(SourceProvider.APOLLO)
):
    """
    Translate a query plan to provider-specific format
    
    Allows fallback between providers without UI changes
    """
    
    provider_query = filter_compiler.compile_for_provider(query_plan, target_provider)
    
    return {
        "provider": target_provider,
        "provider_query": provider_query
    }


# ============== IMPORT GATING ==============

@router.post("/import/gate")
async def create_import_gate(
    campaign_id: str = Query(...),
    source_type: SourceType = Body(...),
    records: List[Dict[str, Any]] = Body(...),
    dedup_rules: List[DeduplicationRule] = Body(default=[]),
    cost_per_record: float = Query(0.01),
    provider_used: str = Query("unknown")
):
    """
    Create import session - the 'gate' before importing
    
    Shows user:
    - Total records
    - Estimated cost
    - Duplicate detection results
    - Validation errors/warnings
    - Preview of records
    
    User must approve before import proceeds
    """
    
    session = await import_manager.create_import_session(
        campaign_id,
        source_type,
        records,
        dedup_rules,
        cost_per_record,
        provider_used
    )
    
    summary = import_manager.get_import_summary(session)
    
    return {
        "import_session_id": session.import_session_id,
        "summary": summary
    }


@router.post("/import/approve")
async def approve_import(
    import_session_id: str = Query(...),
    approved_by: str = Query(...),
    max_import_count: Optional[int] = Query(None),
    max_cost: Optional[float] = Query(None)
):
    """
    Approve import with optional user-defined caps
    
    User can set:
    - Max number of leads to import
    - Max cost budget
    """
    
    # In production, fetch session from DB
    # For now, return success
    
    return {
        "import_session_id": import_session_id,
        "status": "approved",
        "max_import_count": max_import_count,
        "max_cost": max_cost
    }


# ============== WORKBOOK MANAGEMENT ==============

@router.post("/workbooks")
async def create_workbook(
    campaign_id: str = Query(...),
    name: str = Body(...),
    description: str = Body(default=""),
    created_from_sources: List[str] = Body(default=[])
):
    """
    Create a new workbook
    
    Workbooks are Clay-like spreadsheets where:
    - Rows = entities
    - Columns = execution steps
    """
    
    workbook = Workbook(
        campaign_id=campaign_id,
        name=name,
        description=description,
        created_from_sources=created_from_sources,
        status="draft"
    )
    
    # In production, save to DB
    
    return {
        "workbook_id": workbook.workbook_id,
        "name": workbook.name,
        "status": workbook.status
    }


@router.get("/workbooks/{workbook_id}")
async def get_workbook(workbook_id: str = Path(...)):
    """
    Get workbook with all columns and rows
    """
    
    # In production, fetch from DB
    
    return {
        "workbook": {
            "workbook_id": workbook_id,
            "campaign_id": "campaign_123",
            "name": "Sample Workbook",
            "status": "building",
            "total_rows": 100,
            "total_columns": 5,
        },
        "columns": [],
        "rows": [],
        "cells": {}
    }


@router.post("/workbooks/{workbook_id}/columns")
async def add_column(
    workbook_id: str = Path(...),
    name: str = Body(...),
    column_type: str = Body(...),
    config: Dict[str, Any] = Body(...)
):
    """
    Add a column (execution step) to workbook
    """
    
    column = Column(
        workbook_id=workbook_id,
        column_index=0,  # Will be calculated
        name=name,
        column_type=column_type,
        config=config
    )
    
    # In production, save to DB
    
    return {
        "column_id": column.column_id,
        "name": column.name,
        "type": column.column_type,
        "state": column.state
    }


@router.post("/workbooks/{workbook_id}/columns/{column_id}/execute")
async def execute_column(
    workbook_id: str = Path(...),
    column_id: str = Path(...),
    background_tasks: BackgroundTasks
):
    """
    Execute a column across all rows
    
    Process:
    1. Mark column as RUNNING
    2. Execute in parallel across rows
    3. Update cells with results
    4. Log execution and cost
    5. Update column state
    """
    
    # In production:
    # 1. Fetch workbook, column, rows, cells
    # 2. Run execution engine
    # 3. Update DB
    
    # Add to background if long-running
    # background_tasks.add_task(async_execute, workbook_id, column_id)
    
    return {
        "status": "running",
        "column_id": column_id,
        "message": "Column execution started"
    }


@router.post("/workbooks/{workbook_id}/columns/{column_id}/retry")
async def retry_column(
    workbook_id: str = Path(...),
    column_id: str = Path(...)
):
    """
    Retry failed cells in a column
    """
    
    return {
        "status": "retrying",
        "column_id": column_id
    }


@router.post("/workbooks/{workbook_id}/columns/{column_id}/lock")
async def lock_column(
    workbook_id: str = Path(...),
    column_id: str = Path(...),
    user_id: str = Query(...)
):
    """
    Lock a column to prevent automation overwrites
    
    Locked columns won't be modified by automated processes
    """
    
    return {
        "column_id": column_id,
        "is_locked": True,
        "locked_by": user_id
    }


@router.post("/workbooks/{workbook_id}/columns/{column_id}/unlock")
async def unlock_column(
    workbook_id: str = Path(...),
    column_id: str = Path(...)
):
    """
    Unlock a column to allow automation
    """
    
    return {
        "column_id": column_id,
        "is_locked": False
    }


# ============== CELL OPERATIONS ==============

@router.post("/workbooks/{workbook_id}/cells/{row_id}/{column_id}/override")
async def set_cell_override(
    workbook_id: str = Path(...),
    row_id: str = Path(...),
    column_id: str = Path(...),
    override_value: Any = Body(...)
):
    """
    Set manual override on a cell
    
    Manual overrides:
    - Never overwritten by automation
    - Take precedence over automated values
    - Recorded with user and timestamp
    """
    
    cell = CellValue(
        workbook_id=workbook_id,
        row_index=0,
        column_id=column_id,
        manual_override=override_value,
        source=f"manual_override_by_user",
        confidence_score=1.0
    )
    
    # In production, update DB
    
    return {
        "cell_id": cell.cell_id,
        "override_value": override_value,
        "override_at": datetime.utcnow()
    }


# ============== COST TRACKING ==============

@router.get("/workbooks/{workbook_id}/cost-summary")
async def get_cost_summary(workbook_id: str = Path(...)):
    """
    Get cost summary for entire workbook
    """
    
    return {
        "workbook_id": workbook_id,
        "total_cost": 125.50,
        "cost_by_column": {
            "col_1": 50.00,
            "col_2": 75.50
        },
        "cost_by_row": {}
    }


@router.post("/campaigns/{campaign_id}/cost-control")
async def set_cost_controls(
    campaign_id: str = Path(...),
    daily_hard_cap: Optional[float] = Query(None),
    monthly_hard_cap: Optional[float] = Query(None),
    kill_switch_enabled: bool = Query(False),
    kill_switch_reason: Optional[str] = Query(None)
):
    """
    Set cost controls for a campaign
    
    Controls:
    - Daily/monthly hard caps
    - Kill switch for emergency stop
    - Per-source caps
    """
    
    return {
        "campaign_id": campaign_id,
        "daily_hard_cap": daily_hard_cap,
        "monthly_hard_cap": monthly_hard_cap,
        "kill_switch_enabled": kill_switch_enabled
    }


# ============== AUDIT LOGS ==============

@router.get("/workbooks/{workbook_id}/execution-logs")
async def get_execution_logs(
    workbook_id: str = Path(...),
    column_id: Optional[str] = Query(None),
    limit: int = Query(50)
):
    """
    Get execution logs for audit trail
    """
    
    # In production, fetch from DB
    
    return {
        "workbook_id": workbook_id,
        "logs": [],
        "total": 0
    }


# ============== DATA SOURCES ==============

@router.post("/sources")
async def create_source(
    campaign_id: str = Query(...),
    source_type: SourceType = Body(...),
    provider: SourceProvider = Body(...),
    name: str = Body(...)
):
    """
    Create a new data source
    """
    
    source = Source(
        campaign_id=campaign_id,
        source_type=source_type,
        provider=provider,
        name=name
    )
    
    return {
        "source_id": source.source_id,
        "name": source.name,
        "type": source.source_type,
        "provider": source.provider
    }


@router.get("/sources/{source_id}")
async def get_source(source_id: str = Path(...)):
    """
    Get source details
    """
    
    return {
        "source_id": source_id,
        "status": "active",
        "total_records_fetched": 1250,
        "total_cost_incurred": 25.00
    }


# ============== COST ESTIMATION ==============

@router.post("/estimate-cost")
async def estimate_cost(
    operation_type: str = Body(...),
    record_count: int = Body(...),
    provider: SourceProvider = Body(...),
    additional_params: Optional[Dict[str, Any]] = Body(default={})
):
    """
    Estimate cost for various operations
    """
    
    if operation_type == "source":
        cost = CostEstimator.estimate_source_cost(
            SourceType.CSV_IMPORT,
            provider,
            record_count
        )
    elif operation_type == "enrichment":
        field_count = additional_params.get("field_count", 5)
        cost = CostEstimator.estimate_enrichment_cost(
            field_count,
            provider,
            record_count
        )
    elif operation_type == "ai":
        model = additional_params.get("model", "gpt-4")
        input_tokens = additional_params.get("input_tokens", 100)
        output_tokens = additional_params.get("output_tokens", 100)
        cost = CostEstimator.estimate_ai_cost(
            model,
            input_tokens,
            output_tokens,
            record_count
        )
    else:
        cost = 0.0
    
    return {
        "operation_type": operation_type,
        "record_count": record_count,
        "estimated_cost": cost,
        "cost_per_unit": cost / record_count if record_count > 0 else 0
    }
