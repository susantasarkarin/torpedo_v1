# Cint API Integration - Implementation Guide

Complete implementation of Cint Opportunities Subscription (webhook-based survey feed) and Entry Links management for the Torpedo Survey Pool platform.

## Overview

This integration enables real-time survey opportunity delivery from Cint and streamlined respondent allocation through Cint's survey network.

### Key Features

✅ **Opportunities Webhook**: Real-time survey feed via webhook (new, updated, deactivated surveys)  
✅ **Entry Links**: Create, update, retrieve supplier-specific survey entry points  
✅ **Multi-Provider Support**: Works alongside existing CPX integration  
✅ **Respondent Matching**: Intelligent matching of respondents to surveys  
✅ **Auto-Pause Logic**: Quality-based survey auto-pausing  
✅ **Metrics Tracking**: Real-time performance monitoring  
✅ **Webhook Security**: HMAC-SHA256 signature validation  

---

## Project Structure

```
backend/
├── app/
│   ├── models/
│   │   ├── cint.py                    # Cint data models (Pydantic)
│   │   └── survey_allocation.py       # Existing allocation models
│   ├── services/
│   │   ├── cint_service.py            # Cint API client & webhook handling
│   │   ├── cint_allocation_extension.py  # Allocation logic extensions
│   │   └── survey_allocation_service.py  # Existing allocation service
│   ├── routers/
│   │   ├── cint.py                    # FastAPI routes for Cint
│   │   └── survey_allocation.py       # Existing allocation routes
│   └── integrations/
│       └── cint_integration.py        # Main integration orchestrator
├── database_setup_cint.py             # MongoDB collection setup
├── main.py                            # FastAPI app entry point
└── requirements.txt
```

---

## Installation & Setup

### 1. Install Dependencies

```bash
pip install httpx pymongo pydantic fastapi
```

### 2. Configure Environment Variables

Create `.env` file in backend root:

```env
# MongoDB
MONGO_URI=mongodb://localhost:27017

# Cint API Configuration
CINT_API_KEY=your_cint_api_key_here
CINT_SUPPLIER_CODE=YOUR_SUPPLIER_CODE
CINT_ENVIRONMENT=sandbox  # or "production"
CINT_WEBHOOK_SECRET=your_webhook_secret_here

# FastAPI
API_HOST=0.0.0.0
API_PORT=8000
```

### 3. Initialize MongoDB Collections

```bash
cd backend
python database_setup_cint.py
```

This creates:
- `cint_research` database with collections:
  - `cint_surveys` (opportunity feed cache)
  - `cint_entry_links` (entry link storage)
  - `cint_settings` (integration settings)
  - `cint_metrics` (performance metrics)
  - `cint_subscriptions` (subscription configs)
  - `cint_respondent_outcomes` (session outcomes)

- Extensions to `survey_allocation` database for multi-provider support

### 4. Update FastAPI App

In `main.py`:

```python
from app.integrations.cint_integration import CintIntegration, setup_cint_with_fastapp
from app.routers import cint

# Initialize Cint integration
cint_integration = CintIntegration.load_from_env()

# Setup with FastAPI app
setup_cint_with_fastapp(app, cint_integration)

# Include Cint router
app.include_router(cint.router)
```

### 5. Start Application

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## API Endpoints

### Webhooks

#### POST `/api/cint/webhooks/opportunities`
Receives survey opportunities from Cint (called by Cint every 15 seconds)

**Payload Example:**
```json
{
  "survey_id": 123456,
  "survey_name": "Tech Industry Survey",
  "account_name": "Test Company",
  "buyer_id": 789,
  "country_language": "eng_us",
  "bid_length_of_interview": 10,
  "revenue_per_interview": {"value": 1.50, "currency_code": "USD"},
  "total_remaining": 100,
  "is_live": true,
  "message_reason": "new"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Opportunities processed",
  "count": 1
}
```

#### POST `/api/cint/webhooks/respondent-outcomes`
Receives respondent session outcomes (complete, terminate, quota_full, etc.)

### Entry Links

#### POST `/api/cint/entry-links/{survey_id}`
Create entry link for a survey

**Body:**
```json
{
  "supplier_link_type_code": "OWS",
  "tracking_type_code": "NONE",
  "default_link": "https://example.com/survey?...",
  "success_link": "https://example.com/complete?...",
  "failure_link": "https://example.com/terminate?...",
  "over_quota_link": "https://example.com/quota?..."
}
```

#### PUT `/api/cint/entry-links/{survey_id}`
Update entry link for a survey (all fields required)

#### GET `/api/cint/entry-links/{survey_id}`
Retrieve entry link for a survey

#### POST `/api/cint/build-entry-link/{survey_id}`
Build complete entry link with respondent parameters

**Query Parameters:**
- `respondent_id`: Unique respondent ID
- `country_code`: ISO country code
- `pid`: Panelist ID (optional)
- `mid`: Session/Market ID (optional)

**Response:**
```json
{
  "success": true,
  "entry_link": "https://samplicio.us/s/...?rid=xxx&cc=us&pid=yyy"
}
```

### Opportunities Management

#### GET `/api/cint/opportunities`
List active opportunities from cache

**Query Parameters:**
- `active_only`: true (default) | false
- `limit`: 1-1000 (default: 100)

#### GET `/api/cint/opportunities/{survey_id}`
Get specific opportunity details

### Subscription Management

#### POST `/api/cint/subscription/opportunities`
Create/update opportunities subscription

**Body:**
```json
{
  "callback_url": "https://your-domain.com/api/cint/webhooks/opportunities",
  "include_quotas": true,
  "payload_max_size_mb": 8,
  "payload_max_survey_count": 1000,
  "send_interval_seconds": 15,
  "opportunities_filters": [
    {
      "country_language": {"in": ["eng_us", "eng_gb"]},
      "study_type": {"eq": "adhoc"},
      "revenue_per_interview": {"gte": 1.0}
    }
  ]
}
```

#### GET `/api/cint/subscription/opportunities`
Get current subscription status

#### DELETE `/api/cint/subscription/opportunities`
Delete subscription

### Settings

#### POST `/api/cint/settings`
Update Cint integration settings

#### GET `/api/cint/settings`
Get current settings (API key redacted)

### Health

#### GET `/api/cint/health`
Health check for Cint integration

---

## Data Models

### CintOpportunity
```python
{
  "survey_id": int,
  "survey_name": str,
  "country_language": str,  # e.g., "eng_us"
  "bid_length_of_interview": int,  # minutes
  "revenue_per_interview": {"value": float, "currency_code": str},
  "conversion": float,  # 0.0-1.0
  "total_remaining": int,  # quota
  "is_live": bool,
  "message_reason": str,  # "new", "updated", "deactivated"
  # ... and more
}
```

### SupplierLink
```python
{
  "survey_id": int,
  "supplier_link_type_code": str,  # "OWS", "TS"
  "tracking_type_code": str,  # "NONE", "PIXEL", "S2S"
  "live_link": str,  # Generated by Cint
  "test_link": str,  # Generated by Cint
  "default_link": str,  # Custom redirect URLs
  "success_link": str,
  "failure_link": str,
  "over_quota_link": str,
  "quality_termination_link": str,
  "rpi": {"value": float, "currency_code": str}
}
```

---

## Core Services

### CintService
Handles API communication with Cint:

```python
service = CintService(
    api_key="your_key",
    supplier_code="your_code",
    environment="sandbox",
    cint_surveys_collection=db.cint_surveys,
    cint_entry_links_collection=db.cint_entry_links,
)

# Opportunities
result = await service.create_opportunities_subscription(config)
opportunities = await service.process_opportunity_webhook(payload)

# Entry Links
link = await service.create_entry_link(survey_id, link_config)
entry_url = service.build_entry_link(live_link, respondent_id, country_code)
```

### CintAllocationExtension
Extends survey allocation logic for Cint:

```python
extension = CintAllocationExtension(
    cint_surveys_collection=db.cint_surveys,
    cint_entry_links_collection=db.cint_entry_links,
    respondents_collection=db.respondents,
    # ... other collections
)

# Respondent matching
opportunity = await extension.match_respondent_to_cint_surveys(
    respondent, min_cpi=1.0, max_loi=30
)

# Entry link generation
entry_link = await extension.build_cint_entry_link(respondent, survey)

# Metrics
await extension.update_cint_survey_metrics(survey_id, "completed")

# Auto-pause evaluation
should_pause = await extension.evaluate_survey_for_pause(
    survey_id, 
    min_incidence_rate=10.0
)
```

---

## Workflow Examples

### 1. Set Up Opportunities Subscription

```python
from app.integrations.cint_integration import CintIntegration

integration = CintIntegration.load_from_env()

result = await integration.setup_opportunities_subscription(
    callback_url="https://your-domain.com/api/cint/webhooks/opportunities",
    countries=["eng_us", "eng_gb"],
    industries=["technology", "finance"],
    min_cpi=1.0,
    max_loi=30,
)
```

### 2. Handle Opportunity Webhook

```python
@router.post("/webhooks/opportunities")
async def handle_webhook(payload: dict, cint_service: CintService = Depends()):
    # Process opportunities
    opportunities = await cint_service.process_opportunity_webhook(payload)
    
    # Update survey cache
    for opp in opportunities:
        await allocation_ext.update_opportunity_from_webhook(opp.survey_id, opp.dict())
    
    return {"success": True, "count": len(opportunities)}
```

### 3. Allocate Respondent to Survey

```python
# Match respondent to best survey
opportunity = await allocation_ext.match_respondent_to_cint_surveys(
    respondent, min_cpi=1.0, max_loi=30
)

if opportunity:
    # Create entry link if needed
    link_result = await cint_service.get_entry_link(opportunity.survey_id)
    if not link_result.get("link"):
        await cint_service.create_entry_link(
            opportunity.survey_id,
            SupplierLinkCreate(
                supplier_link_type_code="OWS",
                tracking_type_code="NONE",
            )
        )
    
    # Build entry URL
    entry_link = cint_service.build_entry_link(
        live_link=link.live_link,
        respondent_id=respondent.rid,
        country_code=respondent.cc,
    )
    
    # Store allocation
    await allocation_ext.store_allocated_respondent(
        respondent, "cint", opportunity.survey_id,
        opportunity.survey_name, entry_link
    )
    
    return entry_link
```

### 4. Track Respondent Outcome

```python
@router.post("/webhooks/respondent-outcomes")
async def handle_outcome(payload: dict, allocation_ext: CintAllocationExtension = Depends()):
    # Parse outcome
    outcome = RespondentOutcome(**payload)
    
    # Update metrics
    if payload.get("client_status") == 11:  # Completed
        await allocation_ext.update_cint_survey_metrics(
            outcome.survey_id, "completed"
        )
    elif payload.get("client_status") in [10, 20]:  # Terminated
        await allocation_ext.update_cint_survey_metrics(
            outcome.survey_id, "terminated"
        )
    
    # Check if survey should be auto-paused
    should_pause = await allocation_ext.evaluate_survey_for_pause(
        outcome.survey_id,
        min_incidence_rate=10.0,
    )
    
    return {"success": True}
```

---

## Webhook Security

### Signature Validation

Cint sends an `X-Cint-Signature` header with HMAC-SHA256 signature:

```python
def validate_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Validate webhook signature"""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

# Usage in endpoint
@router.post("/webhooks/opportunities")
async def handle_webhook(
    request: Request,
    x_cint_signature: str = Header(...),
    cint_service: CintService = Depends(),
):
    body = await request.body()
    
    if not cint_service.validate_webhook_signature(
        body, x_cint_signature, webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Process webhook...
```

---

## Monitoring & Debugging

### Database Statistics
```python
stats = integration.get_database_stats()
# {"cint_surveys": 150, "cint_entry_links": 45, ...}
```

### Survey Statistics
```python
stats = await allocation_ext.get_cint_survey_stats(survey_id)
# {"survey_id": 123, "sent": 100, "completes": 65, "incidence_rate": 65.0, ...}
```

### Test API Connection
```python
result = await integration.test_api_connection()
# {"success": True, "data": {...}}
```

### View Logs
```bash
# Watch real-time logs
tail -f logs/app.log | grep cint

# Search for specific survey
grep "survey_id=123456" logs/app.log
```

---

## Error Handling

### Common Issues

**Problem**: 401 Unauthorized
```
Solution: Check CINT_API_KEY environment variable and API credentials
```

**Problem**: Webhook signature validation fails
```
Solution: Ensure CINT_WEBHOOK_SECRET matches value set in Cint dashboard
```

**Problem**: Entry links returning 404
```
Solution: Confirm survey has been marked live and allocation exists
```

**Problem**: Empty opportunities from webhook
```
Solution: Check opportunity subscription filters - may be too restrictive
```

---

## Testing

### Manual Testing with cURL

```bash
# Test health
curl -X GET http://localhost:8000/api/cint/health

# List opportunities
curl -X GET "http://localhost:8000/api/cint/opportunities?limit=5" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Create entry link
curl -X POST http://localhost:8000/api/cint/entry-links/123456 \
  -H "Content-Type: application/json" \
  -d '{
    "supplier_link_type_code": "OWS",
    "tracking_type_code": "NONE"
  }'

# Simulate webhook
curl -X POST http://localhost:8000/api/cint/webhooks/opportunities \
  -H "Content-Type: application/json" \
  -H "X-Cint-Signature: test_signature" \
  -d '{
    "survey_id": 123,
    "survey_name": "Test Survey",
    "country_language": "eng_us",
    "message_reason": "new"
  }'
```

---

## Next Steps

1. **Complete Endpoint Implementation**: Router endpoints currently return "Not yet implemented" - inject services via dependencies
2. **Frontend UI**: Create React components for Cint settings, opportunity listing, and monitoring
3. **APScheduler Integration**: Add periodic tasks for subscription health monitoring
4. **Error Recovery**: Implement exponential backoff for failed API calls
5. **Analytics Dashboard**: Track allocation performance across all providers

---

## References

- [Cint API Documentation](https://developer.lucidhq.com/)
- [Opportunities Subscription](https://developer.lucidhq.com/#post-create-opportunities-subscription)
- [Entry Links](https://developer.lucidhq.com/#entry-links)
- [Supply Integration Guide](https://developer.lucidhq.com/) 

---

## Support

For issues or questions:
1. Check MongoDB collections are created: `python database_setup_cint.py`
2. Verify environment variables: `echo $CINT_API_KEY`
3. Test API connection: `GET /api/cint/health`
4. Review logs: `grep -E "ERROR|WARNING" logs/app.log`
