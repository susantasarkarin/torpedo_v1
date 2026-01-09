"""
CLAY-LEVEL DATA MODELS & ABSTRACTION
Foundation for Clay-like list building, enrichment, and workbook functionality

This module extends existing lead models with:
- Source abstraction (provider-agnostic data ingestion)
- Filter compilation and query plans
- Workbook/DAG structure (columns, cells, execution steps)
- Cost tracking and rate limiting
- Audit logging and cell-level overrides
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal, Set, Tuple
from pydantic import BaseModel, Field, validator
from enum import Enum
import uuid


# ============== SOURCE ABSTRACTION ==============

class SourceType(str, Enum):
    """Clay-like data sources for list building"""
    CSV_IMPORT = "csv_import"
    CRM_IMPORT = "crm_import"
    COMPANY_DATABASE = "company_database"  # Enrichment database (Clay's "Companies")
    PEOPLE_DATABASE = "people_database"    # Enrichment database (Clay's "People")
    JOBS_DATABASE = "jobs_database"        # Job postings (Clay's "Job Changes")
    EMAIL_FINDER = "email_finder"          # Email finding service
    COMPANY_ENRICHMENT = "company_enrichment"  # Company data enrichment
    PEOPLE_ENRICHMENT = "people_enrichment"    # Person data enrichment
    AI_ENRICHMENT = "ai_enrichment"        # Custom AI enrichment
    WEB_SEARCH = "web_search"             # Web search results
    ZAPIER = "zapier"                     # Zapier integrations
    CUSTOM_API = "custom_api"             # Custom webhook/API


class SourceProvider(str, Enum):
    """Data providers/vendors"""
    CLAY = "clay"
    APOLLO = "apollo"
    HUNTLY = "huntly"
    CLEARBIT = "clearbit"
    OPENAI = "openai"
    PERPLEXITY = "perplexity"
    GOOGLE_SEARCH = "google_search"
    LINKEDIN = "linkedin"
    CRUNCHBASE = "crunchbase"
    INTERNAL_DB = "internal_db"
    USER_IMPORT = "user_import"


class SourceConfig(BaseModel):
    """Configuration for a data source - tells system HOW to fetch data"""
    source_type: SourceType
    provider: SourceProvider
    api_key: Optional[str] = Field(None, exclude=True)  # Sensitive
    endpoint: Optional[str] = None
    rate_limit_per_minute: int = 60
    cost_per_request: float = 0.0
    timeout_seconds: int = 30
    retry_attempts: int = 3
    supports_batch: bool = True
    batch_size: int = 100
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Source(BaseModel):
    """
    Clay-like Source: represents a data source in a list build
    Collection: sources
    """
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str  # Foreign key to campaign
    source_type: SourceType
    provider: SourceProvider
    
    # Configuration
    config: SourceConfig
    
    # Status
    status: Literal["active", "paused", "completed", "failed"] = "active"
    
    # Metadata
    name: str = ""  # User-friendly name
    description: str = ""
    
    # Execution stats
    total_records_requested: int = 0
    total_records_fetched: int = 0
    total_records_imported: int = 0
    total_cost_incurred: float = 0.0
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== FILTER & QUERY PLANNING ==============

class FilterOperator(str, Enum):
    """Operators for filter conditions"""
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NIN = "nin"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"
    EXISTS = "exists"
    BETWEEN = "between"


class FilterCondition(BaseModel):
    """Single filter condition: field operator value"""
    field: str  # e.g., "company.employee_count", "person.seniority_level"
    operator: FilterOperator
    value: Any
    
    class Config:
        use_enum_values = True


class FilterGroup(BaseModel):
    """Grouped conditions with AND/OR logic"""
    logic: Literal["AND", "OR"] = "AND"
    conditions: List[FilterCondition] = []
    groups: List["FilterGroup"] = []  # Nested groups for complex queries
    
    class Config:
        use_enum_values = True


FilterGroup.model_rebuild()  # Allow self-reference


class QueryPlan(BaseModel):
    """
    Provider-agnostic query plan compiled from UI filters
    
    This plan can be executed against any source (Clay API, Apollo, etc.)
    Allows fallback between providers without recompiling UI
    """
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType
    filters: FilterGroup
    
    # Field selection (for optimization)
    required_fields: Set[str] = Field(default_factory=set)
    
    # Pagination
    limit: int = 50  # Preview limit
    offset: int = 0
    
    # Cost estimation
    estimated_cost: float = 0.0
    estimated_records: int = 0
    
    # Compilation metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    compiled_from: Optional[Dict[str, Any]] = None  # Original UI filter structure
    
    class Config:
        use_enum_values = True


# ============== PREVIEW & DRY-RUN EXECUTION ==============

class PreviewExecution(BaseModel):
    """
    Dry-run execution of a query plan with NO persistence
    
    Clay-like preview: "This query will fetch ~X records with these fields"
    """
    preview_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    query_plan: QueryPlan
    
    # Execution results
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    
    # Results (limited to ~50 rows)
    sample_records: List[Dict[str, Any]] = []
    total_estimated: int = 0  # Estimated total if executed without limit
    actual_returned: int = 0
    
    # Schema inference from results
    inferred_schema: Dict[str, Any] = {}  # {field: type, ...}
    field_coverage: Dict[str, float] = {}  # {field: % populated}
    
    # Execution details
    provider_used: Optional[SourceProvider] = None
    execution_time_ms: int = 0
    error: Optional[str] = None
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True


# ============== IMPORT GATING ==============

class DeduplicationRule(BaseModel):
    """Rules for identifying duplicates before import"""
    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # Matching strategy
    match_type: Literal["exact", "fuzzy", "email_domain", "company_name_and_domain"] = "exact"
    fields: List[str]  # Fields to match on (e.g., ["email"], ["first_name", "last_name", "company_name"])
    
    # Fuzzy matching config
    fuzzy_threshold: float = 0.85  # 0-1, similarity score
    
    # Action on match
    action: Literal["skip", "merge", "update", "flag"] = "skip"  # What to do with duplicates
    
    class Config:
        use_enum_values = True


class ImportSession(BaseModel):
    """
    Clay-like import gate: shows cost, deduplication, and validation BEFORE persistence
    
    Collection: import_sessions
    """
    import_session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    
    # Source info
    source_id: Optional[str] = None  # If from a source
    source_type: SourceType
    
    # Gating info - what user sees before clicking "Import"
    total_records_in_source: int  # Total that would be imported
    estimated_total_cost: float  # Cost of this import
    
    # Deduplication preview
    dedup_rules: List[DeduplicationRule]
    estimated_duplicates: int  # How many would be skipped
    estimated_new_leads: int  # How many actually new
    
    # User-defined caps
    max_import_count: Optional[int] = None  # User can cap how many to import
    
    # Cost cap
    max_cost: Optional[float] = None
    
    # Validation results
    validation_status: Literal["pending", "valid", "warnings", "failed"] = "pending"
    validation_errors: List[str] = []
    validation_warnings: List[str] = []
    
    # Preview of records (first N)
    preview_records: List[Dict[str, Any]] = []
    
    # Status
    status: Literal["pending", "approved", "cancelled", "importing", "completed"] = "pending"
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    
    # Execution
    imported_record_count: int = 0
    actual_cost_incurred: float = 0.0
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ============== WORKBOOK & COLUMNS (Clay-like spreadsheet) ==============

class ColumnType(str, Enum):
    """Types of columns in the workbook (Clay's execution steps)"""
    STATIC_FIELD = "static_field"      # Simple data field from import
    ENRICHMENT = "enrichment"          # Enrichment step (Apollo, Clearbit, etc.)
    AI_TRANSFORM = "ai_transform"      # LLM transformation (Claude, GPT, etc.)
    COMPUTED = "computed"              # Formula/logic
    EMAIL_FINDER = "email_finder"      # Email finding
    DEDUP_GROUP = "dedup_group"       # Deduplication grouping
    VALIDATION = "validation"          # Data validation


class ColumnExecutionState(str, Enum):
    """Execution state for a column (Clay shows this visually)"""
    NOT_RUN = "not_run"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_FAILED = "partial_failed"
    CANCELLED = "cancelled"


class Column(BaseModel):
    """
    A column in the workbook - represents an execution step
    
    Each column:
    - Can be run independently
    - Has its own cache
    - Can be retried
    - Can be locked (prevents automation overwrites)
    - Shows execution state clearly
    
    Collection: workbook_columns
    """
    column_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workbook_id: str  # Foreign key
    
    # Identity
    column_index: int  # Position in workbook (0-based)
    name: str  # Display name
    
    # Type & configuration
    column_type: ColumnType
    config: Dict[str, Any]  # Type-specific config
    
    # e.g., for ENRICHMENT:
    # {
    #   "provider": "apollo",
    #   "enrichment_fields": ["phone", "company_employees"],
    #   "fallback_providers": ["clearbit"]
    # }
    
    # e.g., for AI_TRANSFORM:
    # {
    #   "model": "gpt-4",
    #   "prompt": "Extract company size...",
    #   "input_field": "company_name",
    #   "output_field": "company_size_category"
    # }
    
    # Execution state
    state: ColumnExecutionState = ColumnExecutionState.NOT_RUN
    
    # Cost tracking
    cost_per_row: float = 0.0
    estimated_total_cost: float = 0.0
    actual_cost_incurred: float = 0.0
    
    # Caching & retry
    cacheable: bool = True
    retry_failed_only: bool = False  # Can re-run failed cells
    max_retries: int = 3
    
    # Lock to prevent automation overwrites
    is_locked: bool = False
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


class CellValue(BaseModel):
    """
    A cell in the workbook: row × column intersection
    
    Each cell records:
    - Value (the actual data)
    - Source (where it came from)
    - Confidence (how confident in the value)
    - Cost (what it cost to generate)
    - Timestamp (when it was created)
    - Manual override (human-set value never overwritten by automation)
    
    Collection: workbook_cells
    """
    cell_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workbook_id: str
    row_index: int
    column_id: str
    
    # Value storage (multi-layered)
    extracted_value: Optional[Any] = None  # Raw value from source
    enriched_value: Optional[Any] = None   # After enrichment/transformation
    manual_override: Optional[Any] = None  # User-set value (never overwritten)
    
    @property
    def final_value(self) -> Optional[Any]:
        """Returns effective value: manual override > enriched > extracted"""
        if self.manual_override is not None:
            return self.manual_override
        if self.enriched_value is not None:
            return self.enriched_value
        return self.extracted_value
    
    # Metadata about the value
    source: Optional[str] = None  # Where it came from (e.g., "apollo", "gpt-4", "user_import")
    confidence_score: float = 1.0  # 0-1
    cost: float = 0.0
    
    # Execution
    execution_state: ColumnExecutionState = ColumnExecutionState.NOT_RUN
    error_message: Optional[str] = None
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    extracted_at: Optional[datetime] = None
    enriched_at: Optional[datetime] = None
    override_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True


class WorkbookRow(BaseModel):
    """
    A row in the workbook (an entity - person, company, etc.)
    
    Collection: workbook_rows
    """
    row_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workbook_id: str
    row_index: int
    
    # Entity reference
    entity_type: Literal["person", "company", "job", "custom"] = "person"
    entity_id: Optional[str] = None  # Foreign key to actual entity
    
    # Deduplication
    dedup_group_id: Optional[str] = None  # If part of duplicate group
    
    # Status
    status: Literal["draft", "active", "archived", "error"] = "draft"
    
    # Row-level cost
    total_row_cost: float = 0.0
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Workbook(BaseModel):
    """
    Clay-like workbook: spreadsheet-style interface for list building
    
    Rows = entities
    Columns = execution steps (enrichment, AI, computed logic)
    
    Each column can be:
    - Run independently
    - Cached and retried
    - Locked to prevent overwrites
    
    Collection: workbooks
    """
    workbook_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    
    # Identity
    name: str
    description: str = ""
    
    # Structure
    total_rows: int = 0
    total_columns: int = 0
    
    # Status
    status: Literal["draft", "building", "ready", "paused", "archived"] = "draft"
    
    # Source lineage
    created_from_sources: List[str] = []  # source_ids
    
    # Preview reference
    last_preview_id: Optional[str] = None
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


# ============== AUDIT & EXECUTION LOGS ==============

class ExecutionLog(BaseModel):
    """
    Detailed log of column/cell execution for audit trail
    
    Collection: execution_logs
    """
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workbook_id: str
    column_id: Optional[str] = None
    cell_id: Optional[str] = None
    
    # What happened
    action: str  # "executed", "failed", "retried", "cached", "overridden"
    status: Literal["success", "failure", "partial"] = "success"
    
    # Details
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Cost & duration
    cost: float = 0.0
    duration_ms: int = 0
    
    # Provider info
    provider: Optional[SourceProvider] = None
    provider_response_time_ms: int = 0
    
    # User & timestamp
    executed_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


class CostLedger(BaseModel):
    """
    Cost tracking for budget control
    
    Collection: cost_ledgers
    """
    ledger_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    
    # Scope
    source_id: Optional[str] = None
    workbook_id: Optional[str] = None
    column_id: Optional[str] = None
    
    # Cost
    cost: float
    provider: SourceProvider
    
    # Cap enforcement
    hard_cap_exceeded: bool = False
    rate_limit_violated: bool = False
    kill_switch_triggered: bool = False
    
    # Details
    reason: str  # "preview_execution", "import", "enrichment", etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Timestamp
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


# ============== CONFIGURATION & CONTROLS ==============

class CostControl(BaseModel):
    """Cost and rate limit controls"""
    daily_hard_cap: Optional[float] = None  # Stop everything if exceeded
    monthly_hard_cap: Optional[float] = None
    per_source_daily_cap: Optional[float] = None
    
    # Kill switch
    kill_switch_enabled: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_triggered_at: Optional[datetime] = None
    
    # Rate limits
    global_rate_limit: int = 1000  # Requests per minute
    provider_fallback_enabled: bool = True
    
    class Config:
        use_enum_values = True


class CampaignClayConfig(BaseModel):
    """
    Clay-like configuration for a campaign
    Extends existing campaign model
    
    Collection: campaign_clay_configs
    """
    config_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    
    # Core Clay features
    enable_preview: bool = True
    enable_workbook: bool = True
    enable_cost_estimation: bool = True
    
    # Configuration
    cost_controls: CostControl = Field(default_factory=CostControl)
    dedup_rules: List[DeduplicationRule] = []
    
    # Preferences
    default_batch_size: int = 100
    default_preview_limit: int = 50
    auto_deduplicate_on_import: bool = True
    
    # Dates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True
