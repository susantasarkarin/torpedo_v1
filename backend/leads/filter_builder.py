"""
ADVANCED FILTER BUILDER & QUERY PLANNING
Clay-like filter UI that compiles to provider-agnostic query plans

Features:
- UI filter to query plan compilation
- Filter group nesting with AND/OR logic
- Provider field mapping (abstract fields to provider-specific names)
- Query plan validation
- Estimated record count and cost prediction
"""

from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum

from .clay_models import (
    FilterCondition, FilterGroup, FilterOperator, QueryPlan,
    SourceType, SourceProvider
)


# ============== PROVIDER FIELD MAPPING ==============

class ProviderFieldMapper:
    """
    Maps abstract field names to provider-specific field names
    
    Allows same filter logic to work across Clay, Apollo, Clearbit, etc.
    """
    
    # Mappings from abstract names to provider-specific names
    FIELD_MAPPINGS = {
        # Person fields
        "first_name": {
            SourceProvider.CLAY: "first_name",
            SourceProvider.APOLLO: "first_name",
            SourceProvider.CLEARBIT: "firstName",
            SourceProvider.HUNTLY: "first_name",
        },
        "last_name": {
            SourceProvider.CLAY: "last_name",
            SourceProvider.APOLLO: "last_name",
            SourceProvider.CLEARBIT: "lastName",
            SourceProvider.HUNTLY: "last_name",
        },
        "email": {
            SourceProvider.CLAY: "email",
            SourceProvider.APOLLO: "email",
            SourceProvider.CLEARBIT: "email",
            SourceProvider.HUNTLY: "email",
        },
        "job_title": {
            SourceProvider.CLAY: "title",
            SourceProvider.APOLLO: "title",
            SourceProvider.CLEARBIT: "jobTitle",
            SourceProvider.HUNTLY: "title",
        },
        "seniority_level": {
            SourceProvider.CLAY: "seniority_level",
            SourceProvider.APOLLO: "seniority_level",
            SourceProvider.CLEARBIT: "seniority",
            SourceProvider.HUNTLY: "seniority",
        },
        "department": {
            SourceProvider.CLAY: "department",
            SourceProvider.APOLLO: "department",
            SourceProvider.CLEARBIT: "department",
            SourceProvider.HUNTLY: "department",
        },
        "location": {
            SourceProvider.CLAY: "location",
            SourceProvider.APOLLO: "city",
            SourceProvider.CLEARBIT: "geo.city",
            SourceProvider.HUNTLY: "location",
        },
        "country": {
            SourceProvider.CLAY: "country",
            SourceProvider.APOLLO: "country",
            SourceProvider.CLEARBIT: "geo.country",
            SourceProvider.HUNTLY: "country",
        },
        "linkedin_url": {
            SourceProvider.CLAY: "linkedin_url",
            SourceProvider.APOLLO: "linkedin_url",
            SourceProvider.CLEARBIT: "linkedin.handle",
            SourceProvider.HUNTLY: "linkedin_url",
        },
        
        # Company fields
        "company_name": {
            SourceProvider.CLAY: "company_name",
            SourceProvider.APOLLO: "company_name",
            SourceProvider.CLEARBIT: "name",
            SourceProvider.HUNTLY: "company_name",
        },
        "company_domain": {
            SourceProvider.CLAY: "company_domain",
            SourceProvider.APOLLO: "company_domain",
            SourceProvider.CLEARBIT: "domain",
            SourceProvider.HUNTLY: "domain",
        },
        "company_size": {
            SourceProvider.CLAY: "company_employee_count_range",
            SourceProvider.APOLLO: "company_employee_count_range",
            SourceProvider.CLEARBIT: "metrics.employees",
            SourceProvider.HUNTLY: "company_size",
        },
        "company_industry": {
            SourceProvider.CLAY: "company_industry",
            SourceProvider.APOLLO: "company_industry",
            SourceProvider.CLEARBIT: "category.industry",
            SourceProvider.HUNTLY: "industry",
        },
        "company_revenue": {
            SourceProvider.CLAY: "company_revenue_range",
            SourceProvider.APOLLO: "company_annual_revenue_range",
            SourceProvider.CLEARBIT: "metrics.annualRevenue",
            SourceProvider.HUNTLY: "revenue_range",
        },
        "company_founded": {
            SourceProvider.CLAY: "company_founded",
            SourceProvider.APOLLO: "company_founded_date",
            SourceProvider.CLEARBIT: "founded.year",
            SourceProvider.HUNTLY: "founded_year",
        },
        "company_funding": {
            SourceProvider.CLAY: "company_last_funding_round_amount",
            SourceProvider.APOLLO: "company_latest_funding_amount",
            SourceProvider.CLEARBIT: "funding.latestRound.amount",
            SourceProvider.HUNTLY: "funding_stage",
        },
    }
    
    @staticmethod
    def map_field(
        abstract_field: str,
        target_provider: SourceProvider
    ) -> str:
        """
        Map abstract field name to provider-specific name
        
        Falls back to abstract name if no mapping exists
        """
        mappings = ProviderFieldMapper.FIELD_MAPPINGS.get(abstract_field, {})
        return mappings.get(target_provider, abstract_field)
    
    @staticmethod
    def map_filter_condition(
        condition: FilterCondition,
        target_provider: SourceProvider
    ) -> FilterCondition:
        """Map a single filter condition to provider"""
        
        mapped_field = ProviderFieldMapper.map_field(condition.field, target_provider)
        
        # Also map values if needed (e.g., enum values)
        mapped_value = ProviderFieldMapper._map_value(
            condition.field, condition.value, target_provider
        )
        
        return FilterCondition(
            field=mapped_field,
            operator=condition.operator,
            value=mapped_value
        )
    
    @staticmethod
    def _map_value(field: str, value: Any, target_provider: SourceProvider) -> Any:
        """Map filter values that differ by provider (e.g., enums)"""
        
        # Seniority level mappings
        if field == "seniority_level":
            seniority_mappings = {
                SourceProvider.CLEARBIT: {
                    "C-Level": "CLevel",
                    "VP": "VP",
                    "Director": "Director",
                },
                SourceProvider.APOLLO: {
                    "C-Level": "C-Level",
                    "VP": "VP",
                }
            }
            
            if target_provider in seniority_mappings:
                return seniority_mappings[target_provider].get(value, value)
        
        return value


# ============== FILTER GROUP BUILDER ==============

class FilterGroupBuilder:
    """
    Build filter groups programmatically (for testing and admin)
    """
    
    def __init__(self):
        self.group = FilterGroup()
    
    def add_condition(
        self,
        field: str,
        operator: FilterOperator,
        value: Any
    ) -> "FilterGroupBuilder":
        """Add a condition to the current group"""
        condition = FilterCondition(
            field=field,
            operator=operator,
            value=value
        )
        self.group.conditions.append(condition)
        return self
    
    def set_logic(self, logic: str) -> "FilterGroupBuilder":
        """Set AND/OR logic"""
        self.group.logic = logic
        return self
    
    def add_subgroup(self, subgroup: FilterGroup) -> "FilterGroupBuilder":
        """Add a nested group"""
        self.group.groups.append(subgroup)
        return self
    
    def build(self) -> FilterGroup:
        """Return the built group"""
        return self.group
    
    @staticmethod
    def simple_condition(
        field: str,
        operator: FilterOperator,
        value: Any
    ) -> FilterGroup:
        """Helper to create a simple single-condition group"""
        return FilterGroupBuilder() \
            .set_logic("AND") \
            .add_condition(field, operator, value) \
            .build()


# ============== QUERY PLAN COMPILER ==============

class QueryPlanCompiler:
    """
    Compile UI filters to provider-agnostic query plans
    
    Also handles provider-to-provider translation for fallback
    """
    
    def __init__(self):
        self.mapper = ProviderFieldMapper()
    
    def compile_to_query_plan(
        self,
        source_type: SourceType,
        filters: FilterGroup,
        required_fields: Optional[Set[str]] = None,
        limit: int = 50,
        offset: int = 0
    ) -> QueryPlan:
        """
        Compile filters to provider-agnostic query plan
        
        The plan contains abstract filter logic that can be
        executed against any provider with appropriate translation
        """
        
        # Validate filters
        errors = self.validate_filter_group(filters)
        if errors:
            raise ValueError(f"Invalid filters: {errors}")
        
        query_plan = QueryPlan(
            source_type=source_type,
            filters=filters,
            required_fields=required_fields or set(),
            limit=limit,
            offset=offset,
            compiled_from={"type": "ui_filters"}
        )
        
        return query_plan
    
    def compile_for_provider(
        self,
        query_plan: QueryPlan,
        target_provider: SourceProvider
    ) -> Dict[str, Any]:
        """
        Compile query plan to provider-specific format
        
        Returns provider-specific query object that can be sent to API
        """
        
        # Map all fields and conditions
        mapped_filters = self._map_filter_group(
            query_plan.filters, target_provider
        )
        
        # Build provider-specific query
        provider_query = self._build_provider_query(
            target_provider, mapped_filters, query_plan.limit
        )
        
        return provider_query
    
    def _map_filter_group(
        self,
        group: FilterGroup,
        target_provider: SourceProvider
    ) -> FilterGroup:
        """Recursively map filter group to provider"""
        
        mapped_group = FilterGroup(logic=group.logic)
        
        # Map conditions
        for condition in group.conditions:
            mapped_condition = self.mapper.map_filter_condition(
                condition, target_provider
            )
            mapped_group.conditions.append(mapped_condition)
        
        # Map subgroups
        for subgroup in group.groups:
            mapped_subgroup = self._map_filter_group(subgroup, target_provider)
            mapped_group.groups.append(mapped_subgroup)
        
        return mapped_group
    
    def _build_provider_query(
        self,
        provider: SourceProvider,
        filters: FilterGroup,
        limit: int
    ) -> Dict[str, Any]:
        """
        Build provider-specific query syntax
        
        Different providers have different query formats:
        - Clay: GraphQL-like
        - Apollo: HTTP POST with JSON body
        - Clearbit: HTTP POST with JSON body
        - etc.
        """
        
        if provider == SourceProvider.CLAY:
            return self._build_clay_query(filters, limit)
        elif provider == SourceProvider.APOLLO:
            return self._build_apollo_query(filters, limit)
        elif provider == SourceProvider.CLEARBIT:
            return self._build_clearbit_query(filters, limit)
        else:
            return {"filters": filters, "limit": limit}
    
    def _build_clay_query(self, filters: FilterGroup, limit: int) -> Dict[str, Any]:
        """Build Clay API query"""
        
        return {
            "filters": self._serialize_filters(filters),
            "limit": limit,
            "offset": 0
        }
    
    def _build_apollo_query(self, filters: FilterGroup, limit: int) -> Dict[str, Any]:
        """Build Apollo API query"""
        
        return {
            "q_keywords": self._extract_keywords(filters),
            "person_seniorities": self._extract_enums(filters, "seniority_level"),
            "person_departments": self._extract_enums(filters, "department"),
            "company_industries": self._extract_enums(filters, "company_industry"),
            "limit": limit,
            "page": 1
        }
    
    def _build_clearbit_query(self, filters: FilterGroup, limit: int) -> Dict[str, Any]:
        """Build Clearbit API query"""
        
        return {
            "query": self._serialize_filters(filters),
            "limit": limit
        }
    
    def _serialize_filters(self, group: FilterGroup) -> str:
        """Serialize filter group to string"""
        
        parts = []
        
        for condition in group.conditions:
            part = self._serialize_condition(condition)
            parts.append(part)
        
        for subgroup in group.groups:
            subpart = f"({self._serialize_filters(subgroup)})"
            parts.append(subpart)
        
        operator = f" {group.logic} "
        return operator.join(parts)
    
    def _serialize_condition(self, condition: FilterCondition) -> str:
        """Serialize single condition"""
        
        if condition.operator == FilterOperator.EQ:
            return f"{condition.field} = {repr(condition.value)}"
        elif condition.operator == FilterOperator.NE:
            return f"{condition.field} != {repr(condition.value)}"
        elif condition.operator == FilterOperator.GT:
            return f"{condition.field} > {condition.value}"
        elif condition.operator == FilterOperator.GTE:
            return f"{condition.field} >= {condition.value}"
        elif condition.operator == FilterOperator.LT:
            return f"{condition.field} < {condition.value}"
        elif condition.operator == FilterOperator.LTE:
            return f"{condition.field} <= {condition.value}"
        elif condition.operator == FilterOperator.IN:
            return f"{condition.field} IN {condition.value}"
        elif condition.operator == FilterOperator.CONTAINS:
            return f"{condition.field} LIKE %{condition.value}%"
        else:
            return f"{condition.field} {condition.operator.value} {condition.value}"
    
    def _extract_keywords(self, filters: FilterGroup) -> List[str]:
        """Extract search keywords from filters"""
        keywords = []
        
        for condition in filters.conditions:
            if condition.operator == FilterOperator.CONTAINS:
                keywords.append(condition.value)
        
        return keywords
    
    def _extract_enums(self, filters: FilterGroup, field: str) -> List[str]:
        """Extract enum values for specific field"""
        
        values = []
        
        for condition in filters.conditions:
            if condition.field == field:
                if isinstance(condition.value, list):
                    values.extend(condition.value)
                else:
                    values.append(condition.value)
        
        return values
    
    def validate_filter_group(self, group: FilterGroup) -> List[str]:
        """Validate filter group structure"""
        
        errors = []
        
        # Check logic
        if group.logic not in ["AND", "OR"]:
            errors.append(f"Invalid logic: {group.logic}")
        
        # Validate conditions
        for condition in group.conditions:
            condition_errors = self._validate_condition(condition)
            errors.extend(condition_errors)
        
        # Validate subgroups
        for subgroup in group.groups:
            subgroup_errors = self.validate_filter_group(subgroup)
            errors.extend(subgroup_errors)
        
        return errors
    
    def _validate_condition(self, condition: FilterCondition) -> List[str]:
        """Validate single condition"""
        
        errors = []
        
        if not condition.field:
            errors.append("Field name is required")
        
        try:
            FilterOperator(condition.operator)
        except ValueError:
            errors.append(f"Invalid operator: {condition.operator}")
        
        return errors
    
    def estimate_results(
        self,
        query_plan: QueryPlan,
        provider: SourceProvider
    ) -> int:
        """
        Estimate number of results for a query plan
        
        In production, could call provider's count API if available
        """
        
        # Simple heuristic for now
        # More complex queries return fewer results
        complexity = self._calculate_complexity(query_plan.filters)
        
        # Base estimate
        base_estimate = 1000
        
        # Reduce based on complexity
        estimate = base_estimate / (1 + complexity)
        
        return int(estimate)
    
    def _calculate_complexity(self, group: FilterGroup) -> float:
        """Calculate filter complexity"""
        
        complexity = 0.5  # Base
        
        complexity += len(group.conditions) * 0.1
        complexity += len(group.groups) * 0.2
        
        for subgroup in group.groups:
            complexity += self._calculate_complexity(subgroup)
        
        return complexity
