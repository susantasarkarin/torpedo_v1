"""
WORKBOOK ENGINE & COLUMN EXECUTION
Clay-like spreadsheet interface with independent column execution,
caching, retries, and manual cell overrides
"""

import asyncio
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime
from enum import Enum
import uuid

from .clay_models import (
    Workbook, Column, ColumnType, ColumnExecutionState,
    WorkbookRow, CellValue, ExecutionLog, SourceProvider,
    CostLedger
)


# ============== COLUMN EXECUTION STRATEGIES ==============

class ColumnExecutionStrategy:
    """Base class for column execution strategies"""
    
    async def execute(
        self,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],  # {cell_id: cell}
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, CellValue], float]:
        """
        Execute column operation on all rows
        
        Returns:
            - Updated cells with values
            - Total cost incurred
        """
        raise NotImplementedError


class StaticFieldExecution(ColumnExecutionStrategy):
    """Execute static field column (just read from import/source)"""
    
    async def execute(
        self,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, CellValue], float]:
        
        field_name = column.config.get("field_name")
        data_source = context.get("row_data", {})  # {row_id: {fields}}
        
        cost = 0.0
        updated_cells = {}
        
        for row in rows:
            cell_id = f"{row.row_id}_{column.column_id}"
            cell = cells.get(cell_id)
            
            if not cell:
                cell = CellValue(
                    workbook_id=row.workbook_id,
                    row_index=row.row_index,
                    column_id=column.column_id
                )
            
            # Get value from source data
            row_data = data_source.get(row.row_id, {})
            extracted_value = row_data.get(field_name)
            
            cell.extracted_value = extracted_value
            cell.source = "import"
            cell.confidence_score = 1.0 if extracted_value else 0.0
            cell.execution_state = ColumnExecutionState.COMPLETED
            cell.extracted_at = datetime.utcnow()
            
            updated_cells[cell_id] = cell
        
        return updated_cells, cost


class EnrichmentExecution(ColumnExecutionStrategy):
    """Execute enrichment column (call external API)"""
    
    async def execute(
        self,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, CellValue], float]:
        
        provider = column.config.get("provider", SourceProvider.APOLLO)
        enrichment_fields = column.config.get("enrichment_fields", [])
        fallback_providers = column.config.get("fallback_providers", [])
        
        data_source = context.get("row_data", {})
        cost = 0.0
        updated_cells = {}
        
        for row in rows:
            cell_id = f"{row.row_id}_{column.column_id}"
            cell = cells.get(cell_id)
            
            if not cell:
                cell = CellValue(
                    workbook_id=row.workbook_id,
                    row_index=row.row_index,
                    column_id=column.column_id
                )
            
            # Check if cell is manually overridden - never overwrite
            if cell.manual_override is not None:
                cell.execution_state = ColumnExecutionState.COMPLETED
                updated_cells[cell_id] = cell
                continue
            
            # Get input data
            row_data = data_source.get(row.row_id, {})
            input_field = column.config.get("input_field", "email")
            input_value = row_data.get(input_field)
            
            if not input_value:
                cell.execution_state = ColumnExecutionState.COMPLETED
                cell.enriched_value = None
                updated_cells[cell_id] = cell
                continue
            
            # Mock enrichment execution
            # In production, call actual enrichment API
            enriched = await self._call_enrichment_api(
                provider, input_value, enrichment_fields, fallback_providers
            )
            
            if enriched:
                cell.enriched_value = enriched.get("data")
                cell.source = enriched.get("provider")
                cell.confidence_score = enriched.get("confidence", 0.8)
                cost += enriched.get("cost", column.cost_per_row)
            else:
                cell.error_message = "Enrichment failed"
                cell.execution_state = ColumnExecutionState.FAILED
            
            cell.execution_state = ColumnExecutionState.COMPLETED
            cell.enriched_at = datetime.utcnow()
            updated_cells[cell_id] = cell
        
        return updated_cells, cost
    
    async def _call_enrichment_api(
        self,
        provider: SourceProvider,
        input_value: str,
        fields: List[str],
        fallback_providers: List[SourceProvider]
    ) -> Optional[Dict[str, Any]]:
        """Mock enrichment API call"""
        
        # In production, call real APIs
        # Apollo: https://api.apollo.io/v1/people/search
        # Clearbit: https://person.clearbit.com/v1/combined
        # etc.
        
        # Mock response
        return {
            "provider": provider,
            "data": {
                "phone": "+1-555-1234",
                "company_size": 150,
                "revenue": "10M-50M"
            },
            "confidence": 0.9,
            "cost": 0.01
        }


class AITransformExecution(ColumnExecutionStrategy):
    """Execute AI transformation column (Claude, GPT, etc.)"""
    
    async def execute(
        self,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, CellValue], float]:
        
        model = column.config.get("model", "gpt-4")
        prompt_template = column.config.get("prompt")
        input_field = column.config.get("input_field")
        output_field = column.config.get("output_field")
        
        data_source = context.get("row_data", {})
        cost = 0.0
        updated_cells = {}
        
        for row in rows:
            cell_id = f"{row.row_id}_{column.column_id}"
            cell = cells.get(cell_id)
            
            if not cell:
                cell = CellValue(
                    workbook_id=row.workbook_id,
                    row_index=row.row_index,
                    column_id=column.column_id
                )
            
            # Skip if manually overridden
            if cell.manual_override is not None:
                cell.execution_state = ColumnExecutionState.COMPLETED
                updated_cells[cell_id] = cell
                continue
            
            # Get input
            row_data = data_source.get(row.row_id, {})
            input_value = row_data.get(input_field)
            
            if not input_value:
                cell.execution_state = ColumnExecutionState.COMPLETED
                updated_cells[cell_id] = cell
                continue
            
            # Call AI model
            ai_result = await self._call_ai_model(
                model, prompt_template, input_value
            )
            
            if ai_result:
                cell.enriched_value = ai_result.get("output")
                cell.source = model
                cell.confidence_score = ai_result.get("confidence", 0.8)
                cost += ai_result.get("cost", 0.001)
                cell.execution_state = ColumnExecutionState.COMPLETED
            else:
                cell.error_message = "AI transformation failed"
                cell.execution_state = ColumnExecutionState.FAILED
            
            cell.enriched_at = datetime.utcnow()
            updated_cells[cell_id] = cell
        
        return updated_cells, cost
    
    async def _call_ai_model(
        self,
        model: str,
        prompt_template: str,
        input_value: str
    ) -> Optional[Dict[str, Any]]:
        """Mock AI model call"""
        
        # In production, call Claude, GPT, etc.
        
        # Mock response
        return {
            "output": f"Transformed: {input_value}",
            "confidence": 0.85,
            "cost": 0.002
        }


class ComputedExecution(ColumnExecutionStrategy):
    """Execute computed/formula column"""
    
    async def execute(
        self,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        context: Dict[str, Any]
    ) -> Tuple[Dict[str, CellValue], float]:
        
        formula = column.config.get("formula")  # Python expression
        input_fields = column.config.get("input_fields", [])
        
        data_source = context.get("row_data", {})
        cost = 0.0
        updated_cells = {}
        
        for row in rows:
            cell_id = f"{row.row_id}_{column.column_id}"
            cell = cells.get(cell_id)
            
            if not cell:
                cell = CellValue(
                    workbook_id=row.workbook_id,
                    row_index=row.row_index,
                    column_id=column.column_id
                )
            
            # Skip if manually overridden
            if cell.manual_override is not None:
                cell.execution_state = ColumnExecutionState.COMPLETED
                updated_cells[cell_id] = cell
                continue
            
            # Get input values
            row_data = data_source.get(row.row_id, {})
            input_values = {f: row_data.get(f) for f in input_fields}
            
            # Execute formula
            try:
                result = eval(formula, {"__builtins__": {}}, input_values)
                cell.enriched_value = result
                cell.source = "computed"
                cell.confidence_score = 1.0
                cell.execution_state = ColumnExecutionState.COMPLETED
            except Exception as e:
                cell.error_message = str(e)
                cell.execution_state = ColumnExecutionState.FAILED
            
            cell.enriched_at = datetime.utcnow()
            updated_cells[cell_id] = cell
        
        return updated_cells, cost


# ============== WORKBOOK EXECUTION ENGINE ==============

class WorkbookExecutionEngine:
    """
    Execute columns in a workbook with proper state tracking
    
    Features:
    - Independent column execution
    - Caching and retry logic
    - Row-level and cell-level tracking
    - Audit logging
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
        self.strategies = {
            ColumnType.STATIC_FIELD: StaticFieldExecution(),
            ColumnType.ENRICHMENT: EnrichmentExecution(),
            ColumnType.AI_TRANSFORM: AITransformExecution(),
            ColumnType.COMPUTED: ComputedExecution(),
        }
    
    async def execute_column(
        self,
        workbook: Workbook,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        row_data: Dict[str, Dict[str, Any]],  # {row_id: {fields}}
        execution_log_fn=None,
        cost_ledger_fn=None
    ) -> Tuple[Dict[str, CellValue], float]:
        """
        Execute a single column across all rows
        
        Process:
        1. Check if column should run (retry_failed_only, etc.)
        2. Update column state to RUNNING
        3. Execute with appropriate strategy
        4. Handle failures (retry logic)
        5. Update cells and column state
        6. Log execution
        7. Track cost
        
        Returns: (updated_cells, total_cost)
        """
        
        context = {"row_data": row_data}
        strategy = self.strategies.get(column.column_type)
        
        if not strategy:
            raise ValueError(f"Unknown column type: {column.column_type}")
        
        # Update column state
        column.state = ColumnExecutionState.RUNNING
        
        start_time = datetime.utcnow()
        
        try:
            # Execute
            updated_cells, cost = await strategy.execute(
                column, rows, cells, context
            )
            
            # Update column state
            column.state = ColumnExecutionState.COMPLETED
            column.actual_cost_incurred += cost
            
            # Log execution
            if execution_log_fn:
                await execution_log_fn(
                    workbook.workbook_id,
                    column.column_id,
                    "executed",
                    "success",
                    cost,
                    (datetime.utcnow() - start_time).total_seconds() * 1000
                )
            
            # Track cost
            if cost_ledger_fn:
                await cost_ledger_fn(
                    workbook.campaign_id,
                    workbook.workbook_id,
                    column.column_id,
                    cost,
                    "column_execution"
                )
            
            return updated_cells, cost
        
        except Exception as e:
            column.state = ColumnExecutionState.FAILED
            
            # Log failure
            if execution_log_fn:
                await execution_log_fn(
                    workbook.workbook_id,
                    column.column_id,
                    "execution_failed",
                    "failure",
                    0,
                    (datetime.utcnow() - start_time).total_seconds() * 1000,
                    str(e)
                )
            
            raise
    
    async def retry_column(
        self,
        workbook: Workbook,
        column: Column,
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        row_data: Dict[str, Dict[str, Any]],
        retry_count: int = 0
    ) -> Tuple[Dict[str, CellValue], float]:
        """
        Retry failed cells in a column
        
        If retry_failed_only=True, only re-run failed cells
        Otherwise, re-run all cells
        """
        
        if retry_count >= column.max_retries:
            raise RuntimeError(f"Max retries ({column.max_retries}) exceeded for column {column.column_id}")
        
        # Filter rows to retry
        if column.retry_failed_only:
            # Only retry failed cells
            rows_to_retry = []
            for row in rows:
                cell_id = f"{row.row_id}_{column.column_id}"
                cell = cells.get(cell_id)
                if cell and cell.execution_state == ColumnExecutionState.FAILED:
                    rows_to_retry.append(row)
        else:
            # Retry all
            rows_to_retry = rows
        
        if not rows_to_retry:
            return cells, 0.0
        
        # Re-execute
        return await self.execute_column(
            workbook, column, rows_to_retry, cells, row_data
        )
    
    async def execute_workbook(
        self,
        workbook: Workbook,
        columns: List[Column],
        rows: List[WorkbookRow],
        cells: Dict[str, CellValue],
        row_data: Dict[str, Dict[str, Any]]
    ) -> Tuple[Dict[str, CellValue], List[ExecutionLog], float]:
        """
        Execute entire workbook (all columns)
        
        Columns execute in order, each independently
        """
        
        execution_logs = []
        total_cost = 0.0
        
        # Execute columns in sequence (could be parallelized with care)
        for column in columns:
            try:
                updated_cells, cost = await self.execute_column(
                    workbook, column, rows, cells, row_data
                )
                cells.update(updated_cells)
                total_cost += cost
            
            except Exception as e:
                print(f"Error executing column {column.column_id}: {e}")
                continue
        
        return cells, execution_logs, total_cost
    
    def lock_column(
        self,
        column: Column,
        user_id: str
    ) -> None:
        """Lock a column to prevent automation overwrites"""
        column.is_locked = True
        column.locked_by = user_id
        column.locked_at = datetime.utcnow()
    
    def unlock_column(self, column: Column) -> None:
        """Unlock a column"""
        column.is_locked = False
        column.locked_by = None
        column.locked_at = None
    
    def set_cell_override(
        self,
        cell: CellValue,
        override_value: Any,
        user_id: str
    ) -> None:
        """
        Set manual override on a cell
        
        Manual overrides are NEVER overwritten by automation
        """
        cell.manual_override = override_value
        cell.override_at = datetime.utcnow()
        cell.source = f"manual_override_by_{user_id}"
