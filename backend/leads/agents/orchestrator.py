"""
Orchestrator Agent: Coordinate and Validate All Phases
=======================================================

This agent handles:
1. Coordinating execution of Phase 3-6 agents
2. Validating results across all phases
3. Combining outputs into unified reports
4. Managing dependencies between phases
5. Error recovery and retry logic

The Orchestrator ensures:
- Phases run in correct order (or parallel when possible)
- Results are validated before proceeding
- Failed phases can be retried
- Complete pipeline reports are generated
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field

from .base_agent import BaseAgent, AgentResult, AgentStatus, AgentRegistry
from .phase3_agent import Phase3Agent
from .phase4_agent import Phase4Agent
from .phase5_agent import Phase5Agent
from .phase6_agent import Phase6Agent

logger = logging.getLogger(__name__)


class PipelineMode(Enum):
    """Pipeline execution modes"""
    SEQUENTIAL = "sequential"  # Run phases one after another
    PARALLEL = "parallel"      # Run independent phases in parallel
    SELECTIVE = "selective"    # Run only specified phases


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution"""
    mode: PipelineMode = PipelineMode.SEQUENTIAL
    phases_to_run: List[int] = field(default_factory=lambda: [3, 4, 5, 6])
    stop_on_failure: bool = True
    retry_failed: bool = True
    max_retries: int = 2
    validation_required: bool = True
    parallel_phases: List[List[int]] = field(default_factory=lambda: [[3], [4], [5], [6]])


@AgentRegistry.register
class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent: Coordinates all phase agents
    
    Responsibilities:
    - Execute phases in correct order
    - Validate results between phases
    - Handle failures and retries
    - Generate combined reports
    - Manage dependencies
    """
    
    def __init__(self):
        super().__init__(name="Orchestrator", phase=0)
        
        # Initialize phase agents
        self.agents: Dict[int, BaseAgent] = {
            3: Phase3Agent(),
            4: Phase4Agent(),
            5: Phase5Agent(),
            6: Phase6Agent()
        }
        
        # Default configuration
        self.config = {
            "mode": "sequential",
            "phases_to_run": [3, 4, 5, 6],
            "stop_on_failure": True,
            "retry_failed": True,
            "max_retries": 2,
            "validation_required": True,
            "min_success_rate": 0.7,  # 70% success required to proceed
            "timeout_per_phase": 300,  # 5 minutes per phase
            "enable_notifications": True
        }
        
        # Pipeline state
        self._pipeline_id: Optional[str] = None
        self._phase_results: Dict[int, AgentResult] = {}
        self._validation_results: Dict[int, Dict] = {}
    
    def get_description(self) -> str:
        return """Orchestrator Agent: Pipeline Coordinator
        
        - Coordinates execution of all phase agents (3-6)
        - Validates results between phases
        - Handles failures and automatic retries
        - Generates combined pipeline reports
        - Manages phase dependencies"""
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the full pipeline or selected phases.
        """
        import uuid
        
        self._pipeline_id = str(uuid.uuid4())[:8]
        self._phase_results = {}
        self._validation_results = {}
        
        self.log_info(f"Starting pipeline execution [{self._pipeline_id}]")
        
        # Get configuration
        mode = input_data.get("mode", self.config["mode"])
        phases = input_data.get("phases", self.config["phases_to_run"])
        
        results = {
            "pipeline_id": self._pipeline_id,
            "mode": mode,
            "phases_requested": phases,
            "phase_results": {},
            "validation": {},
            "combined_report": {},
            "status": "pending"
        }
        
        try:
            if mode == "sequential":
                phase_results = await self._run_sequential(phases, input_data)
            elif mode == "parallel":
                phase_results = await self._run_parallel(phases, input_data)
            elif mode == "selective":
                phase_results = await self._run_selective(phases, input_data)
            else:
                phase_results = await self._run_sequential(phases, input_data)
            
            results["phase_results"] = phase_results
            
            # Validate all results
            if self.config["validation_required"]:
                validation = await self._validate_all_phases()
                results["validation"] = validation
            
            # Generate combined report
            combined_report = await self._generate_combined_report()
            results["combined_report"] = combined_report
            
            # Determine overall status
            failed_phases = [p for p, r in self._phase_results.items() 
                          if r.status in [AgentStatus.FAILED, AgentStatus.CANCELLED]]
            
            if not failed_phases:
                results["status"] = "success"
            elif len(failed_phases) < len(phases):
                results["status"] = "partial"
            else:
                results["status"] = "failed"
            
            # Store pipeline run
            await self._store_pipeline_run(results)
            
        except Exception as e:
            self.log_error(f"Pipeline execution failed: {e}")
            results["status"] = "failed"
            results["error"] = str(e)
        
        self.log_info(f"Pipeline [{self._pipeline_id}] completed: {results['status']}")
        
        return results
    
    async def _run_sequential(self, phases: List[int], input_data: Dict[str, Any]) -> Dict[int, Dict]:
        """
        Run phases sequentially, passing output to next phase.
        """
        self.log_info(f"Running phases sequentially: {phases}")
        
        results = {}
        current_input = input_data.copy()
        
        for phase_num in sorted(phases):
            if phase_num not in self.agents:
                self.log_warning(f"Phase {phase_num} agent not found, skipping")
                continue
            
            agent = self.agents[phase_num]
            
            self.log_info(f"Executing Phase {phase_num}: {agent.name}")
            
            try:
                # Configure agent
                if input_data.get(f"phase{phase_num}_config"):
                    agent.configure(input_data[f"phase{phase_num}_config"])
                
                # Run with timeout
                result = await asyncio.wait_for(
                    agent.run(current_input),
                    timeout=self.config["timeout_per_phase"]
                )
                
                self._phase_results[phase_num] = result
                results[phase_num] = result.to_dict()
                
                # Check if we should continue
                if result.status == AgentStatus.FAILED:
                    if self.config["stop_on_failure"]:
                        self.log_error(f"Phase {phase_num} failed, stopping pipeline")
                        break
                    elif self.config["retry_failed"]:
                        # Retry
                        retry_result = await self._retry_phase(phase_num, current_input)
                        if retry_result:
                            self._phase_results[phase_num] = retry_result
                            results[phase_num] = retry_result.to_dict()
                
                # Pass output to next phase
                if result.output_data:
                    current_input.update(result.output_data)
                    current_input["previous_phase"] = phase_num
                    current_input["previous_result"] = result.to_dict()
                
            except asyncio.TimeoutError:
                self.log_error(f"Phase {phase_num} timed out")
                results[phase_num] = {"status": "timeout", "error": "Phase execution timed out"}
                if self.config["stop_on_failure"]:
                    break
                    
            except Exception as e:
                self.log_error(f"Phase {phase_num} error: {e}")
                results[phase_num] = {"status": "error", "error": str(e)}
                if self.config["stop_on_failure"]:
                    break
        
        return results
    
    async def _run_parallel(self, phases: List[int], input_data: Dict[str, Any]) -> Dict[int, Dict]:
        """
        Run independent phases in parallel.
        Phase 3 and 4 can run in parallel, then 5, then 6.
        """
        self.log_info(f"Running phases in parallel mode: {phases}")
        
        results = {}
        
        # Define parallel groups (phases that can run together)
        # Phase 3 (patterns) and Phase 4 (testing) are independent
        # Phase 5 (enrichment) needs Phase 3 results
        # Phase 6 (CRM) needs Phase 5 results
        
        parallel_groups = [
            [3, 4],  # Can run together
            [5],      # Needs patterns from 3
            [6]       # Needs enrichment from 5
        ]
        
        current_input = input_data.copy()
        
        for group in parallel_groups:
            # Filter to only requested phases
            group_phases = [p for p in group if p in phases]
            
            if not group_phases:
                continue
            
            self.log_info(f"Running parallel group: {group_phases}")
            
            # Create tasks for parallel execution
            tasks = []
            for phase_num in group_phases:
                if phase_num in self.agents:
                    agent = self.agents[phase_num]
                    task = asyncio.create_task(
                        self._run_phase_with_timeout(agent, phase_num, current_input)
                    )
                    tasks.append((phase_num, task))
            
            # Wait for all tasks in group
            for phase_num, task in tasks:
                try:
                    result = await task
                    self._phase_results[phase_num] = result
                    results[phase_num] = result.to_dict()
                    
                    # Update input for next group
                    if result.output_data:
                        current_input.update(result.output_data)
                        
                except Exception as e:
                    self.log_error(f"Phase {phase_num} failed in parallel: {e}")
                    results[phase_num] = {"status": "error", "error": str(e)}
        
        return results
    
    async def _run_selective(self, phases: List[int], input_data: Dict[str, Any]) -> Dict[int, Dict]:
        """
        Run only specified phases independently.
        """
        self.log_info(f"Running selective phases: {phases}")
        
        results = {}
        
        tasks = []
        for phase_num in phases:
            if phase_num in self.agents:
                agent = self.agents[phase_num]
                task = asyncio.create_task(
                    self._run_phase_with_timeout(agent, phase_num, input_data)
                )
                tasks.append((phase_num, task))
        
        for phase_num, task in tasks:
            try:
                result = await task
                self._phase_results[phase_num] = result
                results[phase_num] = result.to_dict()
            except Exception as e:
                self.log_error(f"Phase {phase_num} failed: {e}")
                results[phase_num] = {"status": "error", "error": str(e)}
        
        return results
    
    async def _run_phase_with_timeout(self, agent: BaseAgent, phase_num: int, input_data: Dict[str, Any]) -> AgentResult:
        """
        Run a phase agent with timeout.
        """
        try:
            result = await asyncio.wait_for(
                agent.run(input_data),
                timeout=self.config["timeout_per_phase"]
            )
            return result
        except asyncio.TimeoutError:
            self.log_error(f"Phase {phase_num} timed out")
            return AgentResult(
                agent_name=agent.name,
                phase=phase_num,
                status=AgentStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                errors=["Phase execution timed out"]
            )
    
    async def _retry_phase(self, phase_num: int, input_data: Dict[str, Any]) -> Optional[AgentResult]:
        """
        Retry a failed phase.
        """
        max_retries = self.config["max_retries"]
        
        for attempt in range(max_retries):
            self.log_info(f"Retrying Phase {phase_num} (attempt {attempt + 1}/{max_retries})")
            
            try:
                agent = self.agents[phase_num]
                result = await asyncio.wait_for(
                    agent.run(input_data),
                    timeout=self.config["timeout_per_phase"]
                )
                
                if result.status != AgentStatus.FAILED:
                    self.log_info(f"Phase {phase_num} retry successful")
                    return result
                    
            except Exception as e:
                self.log_warning(f"Retry attempt {attempt + 1} failed: {e}")
            
            # Wait before next retry
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        self.log_error(f"Phase {phase_num} failed after {max_retries} retries")
        return None
    
    async def _validate_all_phases(self) -> Dict[str, Any]:
        """
        Validate results from all phases.
        """
        self.log_info("Validating all phase results...")
        
        validation = {
            "phases_validated": 0,
            "phases_passed": 0,
            "phases_failed": 0,
            "issues": [],
            "phase_details": {}
        }
        
        for phase_num, result in self._phase_results.items():
            phase_validation = self._validate_phase_result(phase_num, result)
            validation["phase_details"][phase_num] = phase_validation
            validation["phases_validated"] += 1
            
            if phase_validation["passed"]:
                validation["phases_passed"] += 1
            else:
                validation["phases_failed"] += 1
                validation["issues"].extend(phase_validation.get("issues", []))
        
        validation["success_rate"] = (
            validation["phases_passed"] / max(validation["phases_validated"], 1)
        )
        validation["overall_passed"] = (
            validation["success_rate"] >= self.config["min_success_rate"]
        )
        
        self._validation_results = validation
        
        return validation
    
    def _validate_phase_result(self, phase_num: int, result: AgentResult) -> Dict[str, Any]:
        """
        Validate a single phase result.
        """
        issues = []
        passed = True
        
        # Check status
        if result.status in [AgentStatus.FAILED, AgentStatus.CANCELLED]:
            passed = False
            issues.append(f"Phase {phase_num} status: {result.status.value}")
        
        # Check for errors
        if result.errors:
            passed = False
            issues.extend([f"Phase {phase_num}: {e}" for e in result.errors[:3]])
        
        # Check success rate
        if result.records_processed > 0:
            success_rate = result.records_success / result.records_processed
            if success_rate < self.config["min_success_rate"]:
                passed = False
                issues.append(f"Phase {phase_num} success rate {success_rate:.1%} below threshold")
        
        # Phase-specific validations
        if phase_num == 3:
            # Pattern discovery should find some patterns
            patterns = result.metrics.get("patterns_discovered", 0)
            if patterns == 0 and result.records_processed > 10:
                issues.append("Phase 3: No patterns discovered despite processing emails")
        
        elif phase_num == 4:
            # Testing should have high pass rate
            tests_passed = result.metrics.get("endpoints_passed", 0)
            tests_total = result.metrics.get("endpoints_tested", 1)
            if tests_passed / tests_total < 0.8:
                passed = False
                issues.append(f"Phase 4: Low test pass rate ({tests_passed}/{tests_total})")
        
        elif phase_num == 5:
            # Enrichment should enrich some leads
            enriched = result.metrics.get("records_success", 0)
            if enriched == 0 and result.records_processed > 0:
                issues.append("Phase 5: No leads enriched")
        
        elif phase_num == 6:
            # CRM sync should sync some leads
            synced = result.output_data.get("summary", {}).get("hubspot_synced", 0)
            synced += result.output_data.get("summary", {}).get("salesforce_synced", 0)
            if synced == 0 and result.records_processed > 0:
                issues.append("Phase 6: No leads synced to CRM")
        
        return {
            "phase": phase_num,
            "passed": passed and len(issues) == 0,
            "status": result.status.value,
            "duration": result.duration_seconds,
            "records_processed": result.records_processed,
            "records_success": result.records_success,
            "issues": issues
        }
    
    async def _generate_combined_report(self) -> Dict[str, Any]:
        """
        Generate combined report from all phases.
        """
        self.log_info("Generating combined report...")
        
        report = {
            "pipeline_id": self._pipeline_id,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "phases_executed": len(self._phase_results),
                "total_duration_seconds": 0,
                "total_records_processed": 0,
                "total_records_success": 0,
                "overall_success_rate": 0
            },
            "phase_summaries": {},
            "metrics": {},
            "recommendations": []
        }
        
        total_duration = 0
        total_processed = 0
        total_success = 0
        
        for phase_num, result in self._phase_results.items():
            total_duration += result.duration_seconds
            total_processed += result.records_processed
            total_success += result.records_success
            
            report["phase_summaries"][phase_num] = {
                "agent": result.agent_name,
                "status": result.status.value,
                "duration": round(result.duration_seconds, 2),
                "processed": result.records_processed,
                "success": result.records_success,
                "errors": len(result.errors),
                "warnings": len(result.warnings)
            }
            
            # Collect key metrics
            for key, value in result.metrics.items():
                report["metrics"][f"phase{phase_num}_{key}"] = value
        
        report["summary"]["total_duration_seconds"] = round(total_duration, 2)
        report["summary"]["total_records_processed"] = total_processed
        report["summary"]["total_records_success"] = total_success
        report["summary"]["overall_success_rate"] = round(
            total_success / max(total_processed, 1) * 100, 1
        )
        
        # Generate recommendations
        report["recommendations"] = self._generate_recommendations()
        
        return report
    
    def _generate_recommendations(self) -> List[str]:
        """
        Generate recommendations based on results.
        """
        recommendations = []
        
        for phase_num, result in self._phase_results.items():
            if result.status == AgentStatus.FAILED:
                recommendations.append(f"Review Phase {phase_num} logs - execution failed")
            
            if result.errors:
                recommendations.append(f"Address {len(result.errors)} errors in Phase {phase_num}")
            
            # Phase-specific recommendations
            if phase_num == 3:
                patterns = result.metrics.get("patterns_discovered", 0)
                if patterns < 10:
                    recommendations.append("Add more email samples to improve pattern discovery")
            
            elif phase_num == 4:
                if result.output_data.get("health_report", {}).get("status") == "degraded":
                    recommendations.append("Review performance issues identified in Phase 4 health check")
            
            elif phase_num == 5:
                hit_rate = result.output_data.get("company_enrichment", {}).get("hit_rate", 100)
                if hit_rate < 50:
                    recommendations.append("Populate company cache to improve enrichment hit rate")
            
            elif phase_num == 6:
                if not result.output_data.get("hubspot_sync", {}).get("synced"):
                    recommendations.append("Configure HubSpot API key to enable CRM sync")
        
        return recommendations[:5]  # Top 5 recommendations
    
    async def _store_pipeline_run(self, results: Dict[str, Any]):
        """
        Store pipeline run in database.
        """
        try:
            collection = self.db['pipeline_runs']
            collection.insert_one({
                **results,
                "stored_at": datetime.utcnow()
            })
        except Exception as e:
            self.log_warning(f"Failed to store pipeline run: {e}")
    
    async def get_pipeline_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent pipeline runs.
        """
        collection = self.db['pipeline_runs']
        
        runs = list(collection.find().sort("stored_at", -1).limit(limit))
        
        for run in runs:
            run["_id"] = str(run["_id"])
        
        return runs
    
    async def get_agent_status(self) -> Dict[str, Any]:
        """
        Get status of all agents.
        """
        status = {}
        
        for phase_num, agent in self.agents.items():
            status[phase_num] = {
                "name": agent.name,
                "phase": agent.phase,
                "description": agent.get_description().split("\n")[0],
                "status": agent.status.value,
                "last_run": agent._started_at.isoformat() if agent._started_at else None
            }
        
        return status
    
    def cleanup(self):
        """
        Cleanup all agents.
        """
        for agent in self.agents.values():
            agent.cleanup()
        super().cleanup()
