"""
PREVIEW EXECUTOR SERVICE
Dry-run query execution with schema inference and cost estimation

Never persists data - only provides preview of what would be imported.
Key features:
- Query plan compilation from UI filters
- Provider-agnostic execution with fallback
- Schema inference from returned data
- Field coverage calculation
- Cost estimation
"""

import asyncio
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime
from collections import defaultdict
import json
from pydantic import BaseModel

from .clay_models import (
    QueryPlan, PreviewExecution, FilterGroup, FilterCondition,
    FilterOperator, SourceType, SourceProvider, SourceConfig,
    CostLedger
)


# ============== SCHEMA INFERENCE ==============

class SchemaInferenceEngine:
    """Infer schema (field types) from sample records"""
    
    @staticmethod
    def infer_type(value: Any) -> str:
        """Infer type of a single value"""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            # Try to infer more specific types
            if value.startswith("http"):
                return "url"
            if "@" in value:
                return "email"
            if value.startswith("+") or value.replace("-", "").replace("(", "").replace(")", "").replace(" ", "").isdigit():
                return "phone"
            return "string"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        return "unknown"
    
    @staticmethod
    def infer_schema(records: List[Dict[str, Any]]) -> Dict[str, str]:
        """
        Infer schema from multiple records
        Returns: {field: type}
        """
        schema = {}
        
        for record in records:
            for field, value in record.items():
                inferred_type = SchemaInferenceEngine.infer_type(value)
                
                if field not in schema:
                    schema[field] = inferred_type
                else:
                    # Upgrade to more general type if there's conflict
                    current = schema[field]
                    if current != inferred_type and inferred_type != "null":
                        # Promotion rules
                        if (current == "integer" and inferred_type == "number"):
                            schema[field] = "number"
                        elif (current == "number" and inferred_type == "integer"):
                            pass  # Keep number
                        elif inferred_type == "string" and current != "string":
                            schema[field] = "string"  # String is most general
        
        return schema
    
    @staticmethod
    def calculate_coverage(records: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Calculate field coverage: percentage of rows with non-null value
        Returns: {field: coverage_percentage}
        """
        if not records:
            return {}
        
        coverage = {}
        total_records = len(records)
        field_counts = defaultdict(int)
        
        # Collect all fields and count non-null
        all_fields = set()
        for record in records:
            all_fields.update(record.keys())
            for field, value in record.items():
                if value is not None and value != "":
                    field_counts[field] += 1
        
        # Calculate percentages
        for field in all_fields:
            coverage[field] = (field_counts[field] / total_records) * 100.0
        
        return coverage


# ============== QUERY EXECUTION ==============

class QueryExecutor:
    """
    Execute query plans against different providers
    Mock implementation for development - replace with real provider APIs
    """
    
    @staticmethod
    async def execute_query_plan(
        query_plan: QueryPlan,
        provider: SourceProvider,
        api_key: Optional[str] = None,
        timeout: int = 30
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """
        Execute a query plan against a provider
        
        Returns:
            - records: List of records returned (max ~50 for preview)
            - estimated_total: Estimated total records if no limit
            - cost: Cost of this execution
        """
        
        # In production, this would call real APIs (Apollo, Clearbit, Clay, etc.)
        # For now, mock implementation
        
        if provider == SourceProvider.CLAY:
            return await QueryExecutor._execute_clay(query_plan, api_key, timeout)
        elif provider == SourceProvider.APOLLO:
            return await QueryExecutor._execute_apollo(query_plan, api_key, timeout)
        elif provider == SourceProvider.CLEARBIT:
            return await QueryExecutor._execute_clearbit(query_plan, api_key, timeout)
        elif provider == SourceProvider.OPENAI:
            return await QueryExecutor._execute_openai(query_plan, api_key, timeout)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    @staticmethod
    async def _execute_clay(
        query_plan: QueryPlan,
        api_key: Optional[str],
        timeout: int
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """Mock Clay API execution"""
        # In production: call Clay's API with the compiled query
        # Clay endpoint: https://api.clay.com/v1/search
        
        mock_records = [
            {
                "id": f"record_{i}",
                "first_name": f"John_{i}",
                "last_name": "Doe",
                "email": f"john{i}@example.com",
                "company_name": f"Company {i}",
                "job_title": "Manager",
                "linkedin_url": f"https://linkedin.com/in/john{i}",
                "seniority_level": "Manager",
                "company_employee_count": 100 + (i * 50)
            }
            for i in range(25)
        ]
        
        estimated_total = 1250  # Mock estimate
        cost = 0.02 * len(mock_records)  # $0.02 per record
        
        return mock_records, estimated_total, cost
    
    @staticmethod
    async def _execute_apollo(
        query_plan: QueryPlan,
        api_key: Optional[str],
        timeout: int
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """Mock Apollo API execution"""
        mock_records = [
            {
                "id": f"apollo_{i}",
                "name": f"Jane Smith {i}",
                "email": f"jane{i}@company.com",
                "phone_number": f"+1-555-{1000+i:04d}",
                "company": f"TechCorp {i}",
                "title": "Director",
                "linkedin_url": f"https://linkedin.com/in/jane{i}"
            }
            for i in range(30)
        ]
        
        estimated_total = 850
        cost = 0.01 * len(mock_records)  # $0.01 per record
        
        return mock_records, estimated_total, cost
    
    @staticmethod
    async def _execute_clearbit(
        query_plan: QueryPlan,
        api_key: Optional[str],
        timeout: int
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """Mock Clearbit API execution"""
        mock_records = [
            {
                "name": f"Bob Johnson {i}",
                "domain": f"company{i}.com",
                "founded_date": "2015-01-15",
                "employee_count": 50 + i,
                "industry": "Technology",
                "tech_stack": ["AWS", "React"]
            }
            for i in range(20)
        ]
        
        estimated_total = 500
        cost = 0.05 * len(mock_records)  # $0.05 per record
        
        return mock_records, estimated_total, cost
    
    @staticmethod
    async def _execute_openai(
        query_plan: QueryPlan,
        api_key: Optional[str],
        timeout: int
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """Mock OpenAI API execution (for enrichment/AI transforms)"""
        # This is for AI-based enrichment, not data sourcing
        return [], 0, 0.0


class PreviewExecutionEngine:
    """
    Main engine for preview execution
    
    Orchestrates query compilation, execution, schema inference, and cost estimation
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
        self.schema_engine = SchemaInferenceEngine()
        self.query_executor = QueryExecutor()
    
    async def execute_preview(
        self,
        query_plan: QueryPlan,
        campaign_id: str,
        primary_provider: SourceProvider,
        fallback_providers: Optional[List[SourceProvider]] = None,
        timeout: int = 30
    ) -> PreviewExecution:
        """
        Execute a preview query with fallback support
        
        Process:
        1. Compile query plan (already done)
        2. Execute against primary provider
        3. If failed, try fallbacks
        4. Infer schema from results
        5. Calculate field coverage
        6. Estimate cost
        7. Return preview (never persist)
        """
        
        preview = PreviewExecution(
            campaign_id=campaign_id,
            query_plan=query_plan,
            status="running",
            executed_at=datetime.utcnow()
        )
        
        providers_to_try = [primary_provider]
        if fallback_providers:
            providers_to_try.extend(fallback_providers)
        
        last_error = None
        
        for provider in providers_to_try:
            try:
                records, estimated_total, cost = await self.query_executor.execute_query_plan(
                    query_plan, provider, timeout=timeout
                )
                
                # Success - process results
                preview.sample_records = records
                preview.total_estimated = estimated_total
                preview.actual_returned = len(records)
                preview.provider_used = provider
                
                # Schema inference
                if records:
                    preview.inferred_schema = self.schema_engine.infer_schema(records)
                    preview.field_coverage = self.schema_engine.calculate_coverage(records)
                
                # Cost estimation
                preview.estimated_cost = cost
                
                preview.status = "completed"
                return preview
            
            except Exception as e:
                last_error = str(e)
                continue  # Try next provider
        
        # All providers failed
        preview.status = "failed"
        preview.error = last_error or "All providers failed"
        return preview
    
    async def estimate_import_cost(
        self,
        query_plan: QueryPlan,
        estimated_total_records: int,
        provider: SourceProvider,
        cost_per_record: float
    ) -> float:
        """
        Estimate cost of importing all records (not just preview)
        """
        # For preview, we got cost_per_record from provider
        # Extrapolate to total
        return estimated_total_records * cost_per_record
    
    def compile_query_plan_from_filters(
        self,
        source_type: SourceType,
        filter_group: FilterGroup,
        required_fields: Optional[Set[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> QueryPlan:
        """
        Compile UI filters into provider-agnostic query plan
        
        This plan can be executed against any source and is provider-independent,
        allowing fallback between providers without UI changes.
        """
        
        query_plan = QueryPlan(
            source_type=source_type,
            filters=filter_group,
            required_fields=required_fields or set(),
            limit=limit,
            offset=offset
        )
        
        return query_plan
    
    def validate_query_plan(self, query_plan: QueryPlan) -> Tuple[bool, List[str]]:
        """
        Validate a query plan for correctness
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []
        
        # Check that required fields are known
        # This would validate against provider schema
        
        # Check filter conditions
        if not self._validate_filter_group(query_plan.filters):
            errors.append("Invalid filter conditions")
        
        return len(errors) == 0, errors
    
    def _validate_filter_group(self, group: FilterGroup) -> bool:
        """Recursively validate filter group"""
        for condition in group.conditions:
            # Validate field name
            if not condition.field:
                return False
            # Validate operator
            try:
                FilterOperator(condition.operator)
            except ValueError:
                return False
        
        for subgroup in group.groups:
            if not self._validate_filter_group(subgroup):
                return False
        
        return True


# ============== COST ESTIMATION ==============

class CostEstimator:
    """Cost estimation for various operations"""
    
    # Standard costs by provider (in USD)
    PROVIDER_COSTS = {
        SourceProvider.CLAY: 0.02,          # $0.02 per record
        SourceProvider.APOLLO: 0.01,        # $0.01 per record
        SourceProvider.CLEARBIT: 0.05,      # $0.05 per domain
        SourceProvider.HUNTLY: 0.015,       # $0.015 per record
        SourceProvider.OPENAI: 0.002,       # Variable based on tokens
        SourceProvider.GOOGLE_SEARCH: 0.005, # $0.005 per search (free tier: 100/day)
        SourceProvider.INTERNAL_DB: 0.0,    # Free
        SourceProvider.USER_IMPORT: 0.0,    # Free
        SourceProvider.LINKEDIN: 0.0,       # API access varies
        SourceProvider.CRUNCHBASE: 0.03,    # $0.03 per record
    }
    
    @staticmethod
    def estimate_source_cost(
        source_type: SourceType,
        provider: SourceProvider,
        record_count: int,
        sample_cost: Optional[float] = None
    ) -> float:
        """
        Estimate cost of sourcing N records
        
        If sample_cost provided (from preview), use that basis.
        Otherwise, use standard provider rates.
        """
        if sample_cost is not None:
            # Extrapolate from preview
            return sample_cost * record_count
        
        # Use provider standard rate
        cost_per_record = CostEstimator.PROVIDER_COSTS.get(provider, 0.0)
        return record_count * cost_per_record
    
    @staticmethod
    def estimate_enrichment_cost(
        field_count: int,
        provider: SourceProvider,
        record_count: int
    ) -> float:
        """
        Estimate cost of enriching with N fields across N records
        
        Enrichment is often per-record rather than per-field
        """
        if provider in [SourceProvider.APOLLO, SourceProvider.CLEARBIT]:
            # Most enrichment APIs charge per record enriched
            return record_count * CostEstimator.PROVIDER_COSTS.get(provider, 0.01)
        
        return 0.0
    
    @staticmethod
    def estimate_ai_cost(
        model: str,
        input_tokens: int,
        output_tokens: int,
        record_count: int
    ) -> float:
        """
        Estimate cost of AI transforms (Claude, GPT, etc.)
        """
        # Token pricing (adjust based on actual models)
        token_costs = {
            "gpt-4": {"input": 0.00003, "output": 0.00006},
            "gpt-4-turbo": {"input": 0.00001, "output": 0.00003},
            "gpt-3.5": {"input": 0.0000005, "output": 0.0000015},
            "claude-3-opus": {"input": 0.000015, "output": 0.000075},
            "claude-3-sonnet": {"input": 0.000003, "output": 0.000015},
            "claude-3-haiku": {"input": 0.00000025, "output": 0.00000125},
        }
        
        cost_per_record = token_costs.get(model, {}).get("input", 0.0) * input_tokens
        cost_per_record += token_costs.get(model, {}).get("output", 0.0) * output_tokens
        
        return cost_per_record * record_count
