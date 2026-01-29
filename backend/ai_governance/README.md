# AI GOVERNANCE FRAMEWORK

## Overview

This document describes the mandatory AI workflow consolidation and governance implementation. This is a **complete refactor** of how AI providers are used in the codebase.

## Provider Boundaries (STRICT)

### ✅ Gemini - Email Intelligence ONLY
Gemini is the **single source of truth** for email-related AI operations:

| Allowed | Forbidden |
|---------|-----------|
| Email classification | Web search |
| Email summarization | External lead discovery |
| Lead extraction FROM emails | Prospect enrichment outside email |
| Thread analysis | Any non-email operations |

**Entry Point:** `backend/ai_governance/gemini_gateway.py`

### ✅ ChatGPT/OpenAI - Web Search ONLY
OpenAI/ChatGPT is restricted to external operations:

| Allowed | Forbidden |
|---------|-----------|
| Web search | Email classification |
| External lead discovery | Email summarization |
| Company enrichment (web) | Background/scheduled tasks |
| | Reprocessing existing emails |

**Entry Point:** `backend/ai_governance/openai_gateway.py`

### ❌ DeepSeek - COMPLETELY REMOVED
DeepSeek has been **completely removed** from the codebase:
- No SDKs
- No environment variables
- No fallback logic
- No conditional routing

**Any DeepSeek reference = build failure**

## Gemini Usage Constraints

### 1. Daily Request Cap: 7,000
- **Hard limit enforced in application code**
- When limit reached: calls fail closed, no retries, error logged once
- Tracked in MongoDB: `ai_governance.gemini_daily_usage`

```python
# Enforcement in governance_checks.py
GEMINI_DAILY_LIMIT = 7000

def check_gemini_daily_limit() -> bool:
    current, remaining = get_gemini_daily_usage()
    return remaining > 0
```

### 2. One Classification Per Email
- Each email can be classified **once and only once**
- Enforced via MongoDB unique constraint on `email_id`
- Reclassification is **explicitly forbidden**

```python
# Database constraint
_classification_guard_collection.create_index(
    [("email_id", 1)], 
    unique=True,
    name="unique_email_classification"
)
```

### 3. Single Execution Path
- Only `gemini_gateway.py` may invoke Gemini
- All other Gemini calls have been removed
- No worker, scheduler, or task may bypass this entry point

### 4. No Parallel AI Paths
- No concurrent Gemini calls for same email
- Locking via `acquire_classification_lock()`
- Parallel workers short-circuit safely

### 5. No Infinite Processing
- No `while(true)` for Gemini operations
- No "process until empty" loops
- All operations are:
  - Event-driven
  - Bounded (max_count enforced)
  - Deterministic

### 6. No Batch Retries
- Failed Gemini calls are logged once
- **No automatic retry**
- Any retry must be manual and explicit

## File Structure

```
backend/ai_governance/
├── __init__.py              # Public exports
├── gemini_gateway.py        # SINGLE Gemini entry point
├── openai_gateway.py        # OpenAI (web search only)
├── governance_checks.py     # Enforcement layer
├── migrations.py            # Database migrations
└── verify_governance.py     # Acceptance criteria verification
```

## Usage Examples

### Classify an Email (Gemini)
```python
from backend.ai_governance import classify_email, GeminiDailyLimitExceeded, EmailAlreadyClassified

try:
    result = classify_email(
        email_id="abc123",
        subject="Hello",
        body="Email content...",
        from_email="sender@example.com"
    )
    print(f"Category: {result.category}")
except EmailAlreadyClassified:
    print("Email already classified - cannot reclassify")
except GeminiDailyLimitExceeded:
    print("Daily limit reached - try tomorrow")
```

### Web Search (OpenAI)
```python
from backend.ai_governance import web_search

result = web_search("company information query")
for item in result["results"]:
    print(item["title"])
```

### Check Governance Status
```python
from backend.ai_governance.governance_checks import get_governance_status

status = get_governance_status()
print(f"Gemini usage: {status['gemini']['current_usage']}/{status['gemini']['daily_limit']}")
```

## API Endpoints

### Governance Status
```
GET /api/v2/ai/status
GET /api/v2/ai/gemini/usage
GET /api/v2/ai/health
```

### Gemini Operations
```
POST /api/v2/ai/gemini/classify
POST /api/v2/ai/gemini/summarize
POST /api/v2/ai/gemini/extract-leads
```

### OpenAI Operations
```
POST /api/v2/ai/openai/web-search
POST /api/v2/ai/openai/discover-leads
```

### Forbidden (Return 403/410)
```
POST /api/v2/ai/openai/classify      # 403 Forbidden
POST /api/v2/ai/openai/summarize     # 403 Forbidden
POST /api/v2/ai/deepseek/*           # 410 Gone
```

## Migration Guide

### Before (OLD - DEPRECATED)
```python
from backend.leads.openai_wrapper import chat_completion

result = chat_completion(
    messages=[{"role": "user", "content": "Classify this email..."}],
    provider="deepseek",  # ❌ REMOVED
    model="deepseek-chat" # ❌ REMOVED
)
```

### After (NEW - REQUIRED)
```python
from backend.ai_governance import classify_email

result = classify_email(
    email_id="...",
    subject="...",
    body="...",
    from_email="..."
)
```

## Database Changes

Run migrations before deploying:
```bash
python -m backend.ai_governance.migrations
```

This creates:
1. `ai_governance.gemini_daily_usage` - Daily usage tracking
2. `ai_governance.email_classification_guard` - Unique constraint on email_id
3. `ai_governance.governance_audit_log` - Audit trail
4. Removes all DeepSeek settings from `torpedo_settings.app_settings`

## Verification

Run acceptance criteria verification:
```bash
python -m backend.ai_governance.verify_governance
```

All checks must pass:
- ✓ No DeepSeek references
- ✓ Single Gemini entry point
- ✓ Gemini daily cap enforced
- ✓ One classification per email
- ✓ No Gemini in schedulers/crons
- ✓ No Gemini automatic retries
- ✓ No ChatGPT for email ops

## Acceptance Criteria

The implementation is **INVALID** if ANY are true:
- [ ] Email can be sent to Gemini more than once
- [ ] Gemini called without checking daily cap
- [ ] More than one file invokes Gemini
- [ ] Scheduler/cron triggers Gemini
- [ ] Automatic retries exist for Gemini
- [ ] ChatGPT touches email classification/summaries
- [ ] DeepSeek exists anywhere

All must be **NO** ✓
