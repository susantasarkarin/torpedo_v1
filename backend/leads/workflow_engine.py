"""
WORKFLOW & DAG ENGINE
Clay-like workflow automation with dependency tracking, 
error recovery, and cost optimization

Supports:
- Multi-step workflows
- Conditional execution
- Parallel execution where possible
- Automatic retry with backoff
- Cost budgeting per workflow
- Pause/resume capability
"""

import asyncio
from typing import Dict, List, Any, Optional, Set, Callable
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque
import uuid

from .clay_models import (
    Workbook, Column, ExecutionLog, CostLedger,
    ColumnExecutionState, CostControl
)


# ============== WORKFLOW MODELS ==============

class WorkflowStatus(str, Enum):
    """Workflow execution status"""
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    """Individual task status"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # Waiting for dependency


class WorkflowTask:
    """
    A task in the workflow (typically a column execution)
    """
    
    def __init__(
        self,
        task_id: str,
        name: str,
        task_type: str,
        config: Dict[str, Any],
        dependencies: List[str] = None,
        retry_on_failure: bool = True,
        max_retries: int = 3,
        timeout_seconds: int = 300,
        continue_on_failure: bool = False,  # Don't block downstream tasks
    ):
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.config = config
        self.dependencies = set(dependencies or [])
        self.retry_on_failure = retry_on_failure
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.continue_on_failure = continue_on_failure
        
        # Execution state
        self.status = TaskStatus.PENDING
        self.retries = 0
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.output = None
    
    def is_ready(self, completed_tasks: Set[str]) -> bool:
        """Check if all dependencies are satisfied"""
        return self.dependencies.issubset(completed_tasks)
    
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_on_failure and self.retries < self.max_retries


class WorkflowDAG:
    """
    Directed Acyclic Graph representing workflow execution
    """
    
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.tasks: Dict[str, WorkflowTask] = {}
        self.completed_tasks: Set[str] = set()
        self.failed_tasks: Set[str] = set()
        self.status = WorkflowStatus.DRAFT
        self.created_at = datetime.utcnow()
        self.started_at = None
        self.completed_at = None
        self.error = None
    
    def add_task(self, task: WorkflowTask) -> None:
        """Add task to workflow"""
        if self.status not in [WorkflowStatus.DRAFT]:
            raise RuntimeError(f"Cannot add tasks to workflow in {self.status} state")
        self.tasks[task.task_id] = task
    
    def get_ready_tasks(self) -> List[WorkflowTask]:
        """Get all tasks ready to execute"""
        ready = []
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and task.is_ready(self.completed_tasks):
                ready.append(task)
        return ready
    
    def get_next_tasks(self) -> List[WorkflowTask]:
        """Get next batch of tasks to execute"""
        ready = []
        
        for task in self.tasks.values():
            # Task is ready if all dependencies are completed
            if task.status == TaskStatus.PENDING:
                if task.is_ready(self.completed_tasks):
                    ready.append(task)
        
        return ready
    
    def validate(self) -> tuple[bool, List[str]]:
        """Validate DAG for cycles and other issues"""
        
        errors = []
        
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        
        def has_cycle(task_id):
            visited.add(task_id)
            rec_stack.add(task_id)
            
            task = self.tasks[task_id]
            for dep_id in task.dependencies:
                if dep_id not in self.tasks:
                    errors.append(f"Task {task_id} depends on non-existent task {dep_id}")
                    continue
                
                if dep_id not in visited:
                    if has_cycle(dep_id):
                        return True
                elif dep_id in rec_stack:
                    errors.append(f"Cycle detected: {task_id} -> {dep_id}")
                    return True
            
            rec_stack.remove(task_id)
            return False
        
        for task_id in self.tasks:
            if task_id not in visited:
                has_cycle(task_id)
        
        return len(errors) == 0, errors
    
    def mark_completed(self, task_id: str) -> None:
        """Mark task as completed"""
        self.tasks[task_id].status = TaskStatus.COMPLETED
        self.tasks[task_id].completed_at = datetime.utcnow()
        self.completed_tasks.add(task_id)
    
    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed"""
        self.tasks[task_id].status = TaskStatus.FAILED
        self.tasks[task_id].error = error
        self.tasks[task_id].completed_at = datetime.utcnow()
        self.failed_tasks.add(task_id)
    
    def is_complete(self) -> bool:
        """Check if all tasks are complete"""
        for task in self.tasks.values():
            if task.status not in [TaskStatus.COMPLETED, TaskStatus.SKIPPED]:
                return False
        return True
    
    def can_continue(self) -> bool:
        """Check if workflow can continue (no blocking failures)"""
        for task_id in self.failed_tasks:
            task = self.tasks[task_id]
            if not task.continue_on_failure:
                # Check if any non-failed tasks depend on this
                for other_task in self.tasks.values():
                    if task_id in other_task.dependencies and other_task.status == TaskStatus.PENDING:
                        return False
        return True


# ============== WORKFLOW EXECUTOR ==============

class WorkflowExecutor:
    """
    Execute workflows with proper DAG handling, retries, and cost tracking
    """
    
    def __init__(self):
        self.workflows: Dict[str, WorkflowDAG] = {}
        self.task_executors: Dict[str, Callable] = {}
    
    async def execute_workflow(
        self,
        workflow_dag: WorkflowDAG,
        cost_control: Optional[CostControl] = None,
        max_concurrent_tasks: int = 3
    ) -> WorkflowDAG:
        """
        Execute entire workflow
        
        Process:
        1. Validate DAG
        2. Execute tasks respecting dependencies
        3. Handle retries and failures
        4. Track costs
        5. Return final DAG state
        """
        
        # Validate
        is_valid, errors = workflow_dag.validate()
        if not is_valid:
            raise ValueError(f"Invalid workflow: {errors}")
        
        workflow_dag.status = WorkflowStatus.RUNNING
        workflow_dag.started_at = datetime.utcnow()
        
        total_cost = 0.0
        
        try:
            while not workflow_dag.is_complete():
                # Check if workflow can continue
                if not workflow_dag.can_continue():
                    workflow_dag.status = WorkflowStatus.FAILED
                    workflow_dag.error = "Blocking task failed"
                    break
                
                # Get next batch of tasks
                ready_tasks = workflow_dag.get_next_tasks()
                
                if not ready_tasks:
                    break
                
                # Execute tasks with concurrency limit
                tasks_to_execute = ready_tasks[:max_concurrent_tasks]
                
                results = await asyncio.gather(
                    *[self._execute_task(task, workflow_dag, cost_control) for task in tasks_to_execute],
                    return_exceptions=True
                )
                
                # Process results
                for task, result in zip(tasks_to_execute, results):
                    if isinstance(result, Exception):
                        workflow_dag.mark_failed(task.task_id, str(result))
                    elif result.get("success"):
                        workflow_dag.mark_completed(task.task_id)
                        total_cost += result.get("cost", 0.0)
                    else:
                        workflow_dag.mark_failed(task.task_id, result.get("error"))
                
                # Check cost control
                if cost_control and cost_control.daily_hard_cap:
                    if total_cost > cost_control.daily_hard_cap:
                        workflow_dag.status = WorkflowStatus.PAUSED
                        workflow_dag.error = "Cost limit reached"
                        break
            
            if workflow_dag.is_complete():
                workflow_dag.status = WorkflowStatus.COMPLETED
            elif workflow_dag.status == WorkflowStatus.RUNNING:
                workflow_dag.status = WorkflowStatus.FAILED
        
        except Exception as e:
            workflow_dag.status = WorkflowStatus.FAILED
            workflow_dag.error = str(e)
        
        finally:
            workflow_dag.completed_at = datetime.utcnow()
        
        return workflow_dag
    
    async def _execute_task(
        self,
        task: WorkflowTask,
        workflow_dag: WorkflowDAG,
        cost_control: Optional[CostControl]
    ) -> Dict[str, Any]:
        """Execute a single task with retry logic"""
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        
        while task.retries < task.max_retries:
            try:
                # Execute task
                result = await asyncio.wait_for(
                    self._run_task(task),
                    timeout=task.timeout_seconds
                )
                
                task.output = result
                return {"success": True, "output": result, "cost": 0.0}
            
            except asyncio.TimeoutError:
                task.error = "Task timeout"
                task.retries += 1
                
                if task.can_retry():
                    await asyncio.sleep(2 ** task.retries)  # Exponential backoff
                    continue
                else:
                    return {"success": False, "error": "Timeout after retries"}
            
            except Exception as e:
                task.error = str(e)
                task.retries += 1
                
                if task.can_retry():
                    await asyncio.sleep(2 ** task.retries)
                    continue
                else:
                    return {"success": False, "error": str(e)}
        
        return {"success": False, "error": f"Failed after {task.max_retries} retries"}
    
    async def _run_task(self, task: WorkflowTask) -> Any:
        """
        Run task (hook for actual execution logic)
        
        In production, this would dispatch to appropriate executor
        based on task_type
        """
        
        # Mock execution
        await asyncio.sleep(0.1)
        return {"status": "completed", "rows_processed": 100}
    
    async def pause_workflow(self, workflow_id: str) -> None:
        """Pause a running workflow"""
        if workflow_id in self.workflows:
            workflow = self.workflows[workflow_id]
            if workflow.status == WorkflowStatus.RUNNING:
                workflow.status = WorkflowStatus.PAUSED
    
    async def resume_workflow(
        self,
        workflow_id: str,
        cost_control: Optional[CostControl] = None
    ) -> WorkflowDAG:
        """Resume a paused workflow"""
        if workflow_id not in self.workflows:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        workflow = self.workflows[workflow_id]
        if workflow.status != WorkflowStatus.PAUSED:
            raise ValueError(f"Workflow is {workflow.status}, not paused")
        
        # Resume execution
        return await self.execute_workflow(workflow, cost_control)


# ============== COST LEDGER TRACKER ==============

class CostLedgerTracker:
    """
    Track costs for all operations with budget enforcement
    """
    
    def __init__(self):
        self.ledger: List[CostLedger] = []
        self.costs_by_campaign: Dict[str, float] = defaultdict(float)
        self.costs_by_source: Dict[str, float] = defaultdict(float)
        self.costs_by_operation: Dict[str, float] = defaultdict(float)
    
    def log_cost(
        self,
        campaign_id: str,
        cost: float,
        source_id: Optional[str] = None,
        operation: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None
    ) -> CostLedger:
        """
        Log a cost event
        """
        
        from .clay_models import SourceProvider
        
        ledger_entry = CostLedger(
            campaign_id=campaign_id,
            cost=cost,
            source_id=source_id,
            provider=SourceProvider.INTERNAL_DB,  # Placeholder
            reason=operation,
            metadata=metadata or {}
        )
        
        self.ledger.append(ledger_entry)
        
        # Update totals
        self.costs_by_campaign[campaign_id] += cost
        if source_id:
            self.costs_by_source[source_id] += cost
        self.costs_by_operation[operation] += cost
        
        return ledger_entry
    
    def get_campaign_cost(self, campaign_id: str, period: str = "daily") -> float:
        """
        Get total cost for campaign in period
        """
        
        total = 0.0
        now = datetime.utcnow()
        
        if period == "daily":
            cutoff = now - timedelta(hours=24)
        elif period == "weekly":
            cutoff = now - timedelta(days=7)
        elif period == "monthly":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = datetime.min
        
        for entry in self.ledger:
            if entry.campaign_id == campaign_id and entry.created_at >= cutoff:
                total += entry.cost
        
        return total
    
    def get_remaining_budget(
        self,
        campaign_id: str,
        hard_cap: float
    ) -> float:
        """
        Get remaining budget
        """
        spent = self.get_campaign_cost(campaign_id)
        return max(0, hard_cap - spent)
    
    def check_budget(
        self,
        campaign_id: str,
        requested_cost: float,
        hard_cap: float
    ) -> tuple[bool, Optional[str]]:
        """
        Check if operation fits within budget
        """
        
        current_cost = self.get_campaign_cost(campaign_id)
        
        if current_cost + requested_cost > hard_cap:
            remaining = hard_cap - current_cost
            return False, f"Insufficient budget: ${remaining} remaining, ${requested_cost} requested"
        
        return True, None


# ============== WORKFLOW TEMPLATES ==============

class WorkflowTemplate:
    """
    Reusable workflow templates
    """
    
    # Standard enrichment workflow
    ENRICH_FROM_APOLLO = {
        "name": "Enrich with Apollo",
        "steps": [
            {
                "task_id": "step_1_apollo",
                "name": "Apollo Enrichment",
                "type": "enrichment",
                "config": {
                    "provider": "apollo",
                    "fields": ["phone", "company_website"]
                }
            }
        ]
    }
    
    # Standard dedup + enrich workflow
    DEDUP_AND_ENRICH = {
        "name": "Deduplicate and Enrich",
        "steps": [
            {
                "task_id": "step_1_dedup",
                "name": "Deduplication",
                "type": "dedup",
                "config": {
                    "fields": ["email"],
                    "action": "skip"
                }
            },
            {
                "task_id": "step_2_enrich",
                "name": "Apollo Enrichment",
                "type": "enrichment",
                "config": {
                    "provider": "apollo",
                    "fields": ["phone"]
                },
                "dependencies": ["step_1_dedup"]
            }
        ]
    }
    
    # Advanced workflow: find + enrich + score
    FIND_ENRICH_SCORE = {
        "name": "Find, Enrich, Score",
        "steps": [
            {
                "task_id": "step_1_find",
                "name": "Find Contacts",
                "type": "search",
                "config": {
                    "provider": "apollo",
                    "filters": {}
                }
            },
            {
                "task_id": "step_2_enrich",
                "name": "Enrich Contacts",
                "type": "enrichment",
                "config": {
                    "provider": "clearbit",
                    "fields": ["company_size", "funding"]
                },
                "dependencies": ["step_1_find"]
            },
            {
                "task_id": "step_3_score",
                "name": "Score Leads",
                "type": "ai_transform",
                "config": {
                    "model": "gpt-4",
                    "prompt": "Score lead fit 0-100"
                },
                "dependencies": ["step_2_enrich"]
            }
        ]
    }
