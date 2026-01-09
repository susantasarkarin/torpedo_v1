# CLAY-LEVEL IMPLEMENTATION GUIDE

## Overview

This implementation extends the existing lead generation module with **Clay-level functionality** while preserving all existing code, data models, and integrations. The system adds sophisticated list building, enrichment, and lead management capabilities.

## Architecture

### Core Components

#### 1. **Data Models** (`clay_models.py`)

Foundational Pydantic models for:

- **Source Abstraction**: `Source`, `SourceType`, `SourceProvider`, `SourceConfig`
  - Provider-agnostic data source representation
  - Supports CSV, CRM, Companies DB, People DB, Jobs DB, enrichment providers

- **Filter & Query Planning**: `FilterCondition`, `FilterGroup`, `QueryPlan`
  - UI filters compile to provider-agnostic query plans
  - Allows fallback between providers without UI changes

- **Preview & Dry-run**: `PreviewExecution`
  - Executes queries with NO persistence
  - Returns schema inference, field coverage, cost estimation

- **Import Gating**: `ImportSession`, `DeduplicationRule`
  - Shows user cost, duplicates, validation results before import
  - User-defined caps on record count and cost

- **Workbook (Clay-like Spreadsheet)**:
  - `Workbook`: Container for list building
  - `Column`: Execution step (enrichment, AI, computed, static field)
  - `CellValue`: Individual data cell with value, source, confidence, cost, timestamp
  - `WorkbookRow`: Entity (person, company, job)

- **Execution & Audit**: `ExecutionLog`, `CostLedger`
  - Complete audit trail of all operations
  - Cost tracking with hard caps and kill switches

---

#### 2. **Preview Executor** (`preview_executor.py`)

Dry-run query engine for:

- **Schema Inference** (`SchemaInferenceEngine`)
  - Analyzes sample records to infer types
  - Calculates field coverage %
  - Returns schema: `{field: type}`

- **Query Execution** (`QueryExecutor`)
  - Executes query plans against providers (Clay, Apollo, Clearbit, etc.)
  - Mock implementations for development
  - Returns: records, estimated total, cost

- **Cost Estimation** (`CostEstimator`)
  - Standard rates by provider
  - Extrapolates from preview cost
  - Supports sourcing, enrichment, AI transforms

---

#### 3. **Filter Builder** (`filter_builder.py`)

Advanced filter compilation:

- **Field Mapping** (`ProviderFieldMapper`)
  - Abstracts field names across providers
  - Example: `seniority_level` → Clay: `seniority_level`, Apollo: `seniority_level`, Clearbit: `seniority`

- **Query Planning** (`QueryPlanCompiler`)
  - Compiles UI filters to provider-agnostic query plans
  - Translates plans to provider-specific formats
  - Validates filter structures
  - Estimates result counts

- **Supported Operators**:
  - `EQ`, `NE`, `GT`, `GTE`, `LT`, `LTE`, `IN`, `NIN`
  - `CONTAINS`, `STARTS_WITH`, `ENDS_WITH`, `REGEX`, `EXISTS`, `BETWEEN`

---

#### 4. **Import Gating** (`import_gating.py`)

Pre-import validation and deduplication:

- **Deduplication** (`DeduplicationEngine`)
  - Exact matching on fields
  - Fuzzy matching with threshold
  - Composite keys (first + last + company)
  - Email domain matching
  - Database comparison to find existing duplicates

- **Validation** (`ImportValidator`)
  - Required field checking (email mandatory)
  - Email format validation
  - Warning detection

- **Import Gating** (`ImportGatingManager`)
  - Creates import session showing:
    - Total records
    - Estimated cost
    - Estimated duplicates
    - Validation results
    - Preview of first N records
  - User-defined caps on count and cost
  - Cost control enforcement

---

#### 5. **Workbook Engine** (`workbook_engine.py`)

Column execution and state management:

- **Execution Strategies**:
  - `StaticFieldExecution`: Read from import
  - `EnrichmentExecution`: Call enrichment API
  - `AITransformExecution`: Call AI model (Claude, GPT)
  - `ComputedExecution`: Execute formula/logic

- **Column Features**:
  - Independent execution (columns run separately)
  - Caching and retry logic
  - Lock mechanism (prevents automation overwrites)
  - Execution state tracking (not_run → running → completed/failed)

- **Cell Features**:
  - Multi-layered values: extracted → enriched → manual_override
  - Manual overrides NEVER overwritten by automation
  - Source tracking (where value came from)
  - Confidence scoring (0-1)
  - Cost tracking per cell
  - Full audit trail

---

#### 6. **API Routes** (`clay_routes.py`)

RESTful endpoints for:

- **Preview**: `/clay/preview/execute` - Dry-run query
- **Filters**: `/clay/filters/compile`, `/clay/filters/translate` - Query planning
- **Import**: `/clay/import/gate`, `/clay/import/approve` - Gating
- **Workbooks**: `/clay/workbooks/*` - CRUD and execution
- **Columns**: `/clay/columns/*/execute`, `/clay/columns/*/retry`, `/clay/columns/*/lock`
- **Cells**: `/clay/cells/*/override` - Manual cell overrides
- **Cost**: `/clay/cost-control`, `/clay/estimate-cost` - Budget controls
- **Audit**: `/clay/execution-logs` - Audit trails

---

## Usage Flows

### 1. **Build a List (Clay-style)**

```
User → Filter UI → Compile to Query Plan → Preview Execution
                        ↓
                  Schema Inference
                        ↓
              Cost Estimation + Field Coverage
                        ↓
                  User sees preview (50 rows)
                        ↓
                  User approves import with caps
                        ↓
              Create Workbook from Import Session
```

### 2. **Enrich a Workbook**

```
Workbook (rows + columns)
    ↓
User adds "Enrichment" column (Apollo)
    ↓
User clicks "Execute" on column
    ↓
System runs enrichment in parallel across all rows
    ↓
Updates cells with enriched values (never overwriting manual overrides)
    ↓
Tracks cost per cell/row/column
    ↓
User can lock column to prevent re-execution
```

### 3. **Manual Cell Override**

```
User clicks on cell in workbook
    ↓
System shows: extracted value, enriched value, source, confidence
    ↓
User types new value and clicks override
    ↓
Value stored as "manual_override"
    ↓
Future automations SKIP this cell (never overwrite)
    ↓
All changes logged with user + timestamp
```

### 4. **Import with Deduplication Gate**

```
User selects records to import
    ↓
System detects duplicates within batch
    ↓
System checks database for duplicates
    ↓
Shows:
  - Total: 1000 records
  - New: 850 (after dedup)
  - Duplicates: 150
  - Estimated Cost: $8.50
  - Validation: 2 errors, 15 warnings
    ↓
User optionally:
  - Set max_count: 500
  - Set max_cost: $5.00
    ↓
User clicks "Approve"
    ↓
System enforces caps during actual import
```

---

## Key Features

### ✅ **Provider-Agnostic Architecture**

- Write filters once, execute against any provider
- Fall back to alternative providers on failure
- Field mapping abstracts provider differences

### ✅ **Dry-run Preview**

- Execute queries without persistence
- Schema inference from actual data
- Field coverage metrics (% of rows with value)
- Cost estimation before any charges

### ✅ **Import Gating**

- Deduplication detection BEFORE import
- Validation with errors + warnings
- Preview of actual records
- User-defined cost/record caps
- Cost enforcement with hard caps + kill switch

### ✅ **Spreadsheet Workbook**

- Rows = entities, Columns = execution steps
- Independent column execution (parallel-safe)
- Column state tracking (not_run → running → completed/failed)
- Caching and retry logic

### ✅ **Cell-Level Granularity**

- Each cell records: value, source, confidence, cost, timestamp
- Manual overrides persist across automations
- Full audit trail
- Never-overwrite-manual-override guarantee

### ✅ **Cost Control**

- Cost tracking per operation, column, row, cell
- Daily/monthly hard caps
- Per-source caps
- Kill switch for emergencies
- Provider fallback with cost optimization

### ✅ **Determinism & Auditability**

- All operations logged
- Full lineage: where did this value come from?
- Separation of extraction vs. inference vs. generation
- Schema validation
- Confidence scoring

---

## Integration with Existing Code

### ✅ **Preserves Existing Models**

The implementation extends (not replaces) existing:
- `Lead`, `LeadRaw`, `LeadEnriched` models
- `AIClassificationLog` for AI enrichment
- Existing MongoDB collections
- All existing API endpoints

### ✅ **Extends Collections**

New collections alongside existing:
- `sources` - data sources
- `workbooks` - Clay-like spreadsheets
- `workbook_columns` - execution steps
- `workbook_rows` - entities
- `workbook_cells` - individual data cells
- `execution_logs` - audit trail
- `cost_ledgers` - cost tracking
- `import_sessions` - import gates
- `campaign_clay_configs` - Clay features per campaign

### ✅ **Backward Compatible**

- Existing endpoints unchanged
- New Clay endpoints under `/leads/clay/*` prefix
- No breaking changes to current functionality
- Gradual migration path

---

## Configuration

### Campaign-Level Settings (`CampaignClayConfig`)

```python
{
    "campaign_id": "campaign_123",
    "enable_preview": true,           # Enable dry-run previews
    "enable_workbook": true,          # Enable spreadsheet interface
    "enable_cost_estimation": true,   # Show cost estimates
    
    "cost_controls": {
        "daily_hard_cap": 100.0,      # Stop at $100/day
        "monthly_hard_cap": 2000.0,   # Stop at $2000/month
        "per_source_daily_cap": 500.0,
        "kill_switch_enabled": false,
        "global_rate_limit": 1000     # Requests/minute
    },
    
    "dedup_rules": [
        {
            "match_type": "exact",
            "fields": ["email"],
            "action": "skip"           # Skip duplicates
        }
    ],
    
    "default_batch_size": 100,
    "default_preview_limit": 50,
    "auto_deduplicate_on_import": true
}
```

---

## Implementation Checklist

### Phase 1: Foundation (Complete)
- [x] Data models (`clay_models.py`)
- [x] Preview executor (`preview_executor.py`)
- [x] Filter builder (`filter_builder.py`)
- [x] Import gating (`import_gating.py`)
- [x] Workbook engine (`workbook_engine.py`)
- [x] React components (Workbook.jsx, Workbook.css)
- [x] API routes (`clay_routes.py`)

### Phase 2: Backend Integration (Next)
- [ ] Register routes in main FastAPI app
- [ ] Add MongoDB collection indexes
- [ ] Implement actual provider API calls (Clay, Apollo, Clearbit)
- [ ] Add cost control middleware
- [ ] Implement background execution for long-running operations

### Phase 3: Frontend Integration
- [ ] Hook Workbook component into campaign sidebar
- [ ] Add filter builder UI component
- [ ] Integrate import gate modal into existing import flow
- [ ] Add cost estimation display
- [ ] Add execution state indicators

### Phase 4: Production Hardening
- [ ] Rate limiting enforcement
- [ ] Provider fallback logic
- [ ] Error recovery
- [ ] Performance optimization (batch processing, caching)
- [ ] Security: API key management, permission checks

---

## Example: Building a List

```python
# 1. Create filter
filters = FilterGroupBuilder() \
    .set_logic("AND") \
    .add_condition("seniority_level", FilterOperator.EQ, "VP") \
    .add_condition("company_industry", FilterOperator.IN, ["Technology", "Fintech"]) \
    .build()

# 2. Compile to query plan
query_plan = compiler.compile_to_query_plan(
    source_type=SourceType.PEOPLE_DATABASE,
    filters=filters,
    required_fields={"email", "seniority_level", "company_industry"}
)

# 3. Execute preview
preview = await preview_engine.execute_preview(
    query_plan,
    campaign_id="campaign_123",
    primary_provider=SourceProvider.CLAY
)

# Show user:
# - Total estimated: 1,250 VPs at tech/fintech companies
# - Field coverage: email 95%, seniority 100%
# - Estimated cost: $25.00 (1,250 × $0.02)
# - Sample: 50 rows with full details

# 4. User approves with caps
session = await import_manager.create_import_session(
    campaign_id="campaign_123",
    source_type=SourceType.PEOPLE_DATABASE,
    records=preview.sample_records,  # Plus full results when imported
    dedup_rules=[DeduplicationRule(fields=["email"], action="skip")],
    cost_per_record=0.02
)

# 5. User sees import gate
# - Total: 1,250 records
# - New: 1,100 (after dedup)
# - Duplicates: 150
# - Cost: $22.00
# - Validation: OK

# 6. User approves
session = await import_manager.approve_import(
    import_session_id=session.import_session_id,
    approved_by="user_123",
    max_import_count=500,  # Only import 500
    max_cost=10.0          # Only spend $10
)

# 7. System creates workbook
workbook = Workbook(
    campaign_id="campaign_123",
    name="VP Tech/Fintech - Jan 2026",
    created_from_sources=[source_id]
)

# 8. User adds enrichment column
column = Column(
    workbook_id=workbook.workbook_id,
    name="Apollo Enrichment",
    column_type=ColumnType.ENRICHMENT,
    config={
        "provider": SourceProvider.APOLLO,
        "enrichment_fields": ["phone", "company_website", "hiring_intent"]
    }
)

# 9. User clicks "Execute" → runs enrichment across 500 rows
# 10. System updates cells with enriched values
# 11. User can manually edit any cell → becomes "manual override"
# 12. Re-running column skips manual override cells

# Audit log shows every operation:
# - Import: 500 records imported for $10.00
# - Execute: Apollo enrichment on 500 rows, cost $5.00
# - Override: User changed cell [row 5, column "phone"]
```

---

## API Example Usage

### Preview Query

```bash
POST /leads/clay/preview/execute
{
    "campaign_id": "campaign_123",
    "query_plan": {
        "source_type": "people_database",
        "filters": {
            "logic": "AND",
            "conditions": [
                {
                    "field": "seniority_level",
                    "operator": "eq",
                    "value": "VP"
                }
            ]
        }
    },
    "primary_provider": "clay"
}

Response:
{
    "preview_id": "prev_789",
    "status": "completed",
    "sample_records": [...50 records...],
    "total_estimated": 1250,
    "actual_returned": 50,
    "inferred_schema": {
        "first_name": "string",
        "last_name": "string",
        "email": "email",
        "company_name": "string"
    },
    "field_coverage": {
        "email": 95.0,
        "first_name": 98.0,
        "company_name": 92.0
    },
    "estimated_cost": 25.00,
    "provider_used": "clay"
}
```

### Create Import Gate

```bash
POST /leads/clay/import/gate
{
    "campaign_id": "campaign_123",
    "source_type": "people_database",
    "records": [...1000 records...],
    "dedup_rules": [
        {
            "match_type": "exact",
            "fields": ["email"],
            "action": "skip"
        }
    ],
    "cost_per_record": 0.02
}

Response:
{
    "import_session_id": "sess_456",
    "summary": {
        "total_records": 1000,
        "estimated_new": 850,
        "estimated_duplicates": 150,
        "estimated_cost": 17.00,
        "validation_status": "valid",
        "preview_records": [...10 records...]
    }
}
```

### Execute Column

```bash
POST /leads/clay/workbooks/wb_123/columns/col_456/execute

Response:
{
    "status": "running",
    "column_id": "col_456",
    "message": "Column execution started"
}

# Check status periodically...
# Returns updated cells when complete
```

---

## Next Steps

1. **Register routes** in main FastAPI app
2. **Add indices** to MongoDB for performance
3. **Implement real provider APIs** (Clay, Apollo, Clearbit, etc.)
4. **Build cost middleware** for enforcing hard caps
5. **Create frontend components** for filter builder and import gate
6. **Add background job** framework for long-running operations
7. **Wire up to existing campaign flow** for seamless integration

---

## References

- **Clay.com**: Reference implementation for list building + enrichment
- **Existing CRM**: Preserve all existing functionality
- **FastAPI**: Modern Python web framework
- **MongoDB**: Document database for flexible schemas
- **Pydantic**: Data validation
- **React**: Frontend UI

