# AI Cold Outreach - Quick Start Guide

## Installation & Setup

### 1. Verify Module Installation

The outreach module is located at `backend/outreach/` with the following structure:

```
backend/outreach/
├── __init__.py              # Module exports
├── models.py                # Data models
├── personalization.py       # Personalization engine
├── sequence_engine.py       # Sequence management
├── tracking.py              # Email tracking
├── automation_rules.py      # Automation rules
├── reengagement.py          # Re-engagement engine
├── templates.py             # Email templates
├── router.py                # API endpoints
└── README.md                # Full documentation
```

### 2. Start the Backend Server

```bash
cd backend
uvicorn main:app --reload --port 8000
```

You should see:
```
✅ AI Cold Outreach & Re-Engagement router included
```

### 3. Initialize Default Templates and Sequence

```bash
# Initialize templates
curl -X POST http://localhost:8000/api/outreach/templates/seed

# Create default 4-step sequence
curl -X POST http://localhost:8000/api/outreach/sequences/default
```

This creates:
- 4 cold outreach email templates
- 3 re-engagement templates
- Default 14-day sequence

## Basic Usage

### Example 1: Enroll Single Lead

```python
import requests

# Get sequence ID from the default sequence creation
SEQUENCE_ID = "your_sequence_id_here"
API_BASE = "http://localhost:8000"

# Enroll a lead
response = requests.post(
    f"{API_BASE}/api/outreach/leads/enroll",
    json={
        "leads": [
            {
                "first_name": "Sarah",
                "last_name": "Johnson",
                "email": "sarah.johnson@techcorp.com",
                "company": "TechCorp",
                "title": "Director of Engineering",
                "seniority": "Director",
                "department": "Engineering",
                "industry": "Technology",
                "pain_point": "managing distributed teams",
                "use_case": "companies transitioning to remote work",
                "value_proposition": "streamlined remote collaboration"
            }
        ],
        "sequence_id": SEQUENCE_ID,
        "start_immediately": True
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

Expected output:
```json
{
  "enrolled": 1,
  "duplicates": 0,
  "errors": 0,
  "lead_ids": ["lead_id_here"]
}
```

### Example 2: Bulk Import from CSV

```python
import pandas as pd
import requests

# Load leads from CSV
df = pd.read_csv("leads.csv")

# Convert to API format
leads = []
for _, row in df.iterrows():
    leads.append({
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "company": row["company"],
        "title": row.get("title", ""),
        "seniority": row.get("seniority", "Unknown"),
        "department": row.get("department", "Other"),
        "industry": row.get("industry", ""),
        "pain_point": row.get("pain_point", ""),
    })

# Enroll in batches of 100
batch_size = 100
for i in range(0, len(leads), batch_size):
    batch = leads[i:i+batch_size]
    
    response = requests.post(
        "http://localhost:8000/api/outreach/leads/enroll",
        json={
            "leads": batch,
            "sequence_id": SEQUENCE_ID,
            "start_immediately": True
        }
    )
    
    print(f"Batch {i//batch_size + 1}: Enrolled {response.json()['enrolled']} leads")
```

### Example 3: Track Email Events (Webhook Integration)

```python
# Example webhook handler for SendGrid/Mailgun/etc.
from fastapi import APIRouter, Request
import requests

webhook_router = APIRouter()

@webhook_router.post("/webhooks/email-events")
async def handle_email_event(request: Request):
    """Handle email provider webhook events"""
    event = await request.json()
    
    # Map provider event to tracking endpoint
    event_type = event.get("event")  # "open", "click", "bounce", etc.
    email_id = event.get("email_id")  # Your internal email ID
    
    tracking_base = "http://localhost:8000/api/outreach/tracking"
    
    if event_type == "open":
        requests.post(
            f"{tracking_base}/opened/{email_id}",
            params={
                "ip_address": event.get("ip"),
                "user_agent": event.get("useragent")
            }
        )
    
    elif event_type == "click":
        requests.post(
            f"{tracking_base}/clicked/{email_id}",
            params={
                "clicked_url": event.get("url"),
                "ip_address": event.get("ip")
            }
        )
    
    elif event_type == "bounce":
        requests.post(
            f"{tracking_base}/bounced/{email_id}",
            params={"bounce_reason": event.get("reason")}
        )
    
    elif event_type == "delivered":
        requests.post(f"{tracking_base}/delivered/{email_id}")
    
    return {"status": "processed"}
```

### Example 4: Monitor Sequence Performance

```python
import requests
import pandas as pd

# Get sequence analytics
response = requests.get(
    f"http://localhost:8000/api/outreach/sequences/{SEQUENCE_ID}/analytics"
)

analytics = response.json()

# Display as DataFrame
df = pd.DataFrame([{
    "Metric": "Total Leads",
    "Value": analytics["total_leads"]
}, {
    "Metric": "Emails Sent",
    "Value": analytics["emails_sent"]
}, {
    "Metric": "Open Rate",
    "Value": f"{analytics['open_rate']}%"
}, {
    "Metric": "Reply Rate",
    "Value": f"{analytics['reply_rate']}%"
}, {
    "Metric": "Positive Reply Rate",
    "Value": f"{analytics['positive_reply_rate']}%"
}])

print(df.to_string(index=False))
```

Output:
```
                   Metric    Value
             Total Leads      150
             Emails Sent      450
               Open Rate   40.0%
              Reply Rate   4.89%
    Positive Reply Rate   2.93%
```

## Automated Processing

### Setup Background Jobs (APScheduler)

Add to `backend/main.py`:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from outreach.sequence_engine import SequenceEngine
from outreach.reengagement import ReengagementEngine

scheduler = BackgroundScheduler()

# Process scheduled emails every 5 minutes
def process_emails():
    from database import get_database
    db = get_database()
    engine = SequenceEngine(db)
    count = engine.process_scheduled_emails(limit=100)
    print(f"Processed {count} scheduled emails")

scheduler.add_job(process_emails, 'interval', minutes=5)

# Enroll eligible leads in re-engagement daily at 9 AM
def enroll_reengagement():
    from database import get_database
    db = get_database()
    engine = ReengagementEngine(db)
    count = engine.enroll_eligible_leads()
    print(f"Enrolled {count} leads in re-engagement")

scheduler.add_job(enroll_reengagement, 'cron', hour=9)

# Process re-engagement actions daily at 10 AM
def process_reengagement():
    from database import get_database
    db = get_database()
    engine = ReengagementEngine(db)
    count = engine.process_due_actions(limit=50)
    print(f"Processed {count} re-engagement actions")

scheduler.add_job(process_reengagement, 'cron', hour=10)

# Start scheduler
scheduler.start()
```

## Testing

### Run Unit Tests

```bash
cd backend
pytest tests/test_outreach_module.py -v
```

### Test API Endpoints

```bash
# Health check
curl http://localhost:8000/api/outreach/health

# List templates
curl http://localhost:8000/api/outreach/templates

# List leads
curl http://localhost:8000/api/outreach/leads

# Get re-engagement stats
curl http://localhost:8000/api/outreach/reengagement/stats
```

## Common Issues

### Issue: "Template not found"
**Solution**: Run template seeding:
```bash
curl -X POST http://localhost:8000/api/outreach/templates/seed
```

### Issue: "Sequence not found"
**Solution**: Create default sequence:
```bash
curl -X POST http://localhost:8000/api/outreach/sequences/default
```

### Issue: Emails not sending
**Solution**: Check that you've integrated with an email provider and are processing scheduled emails:
```bash
curl -X POST http://localhost:8000/api/outreach/process/scheduled-emails
```

## Next Steps

1. **Integrate Email Provider**: Connect SendGrid, Mailgun, or AWS SES
2. **Setup Webhooks**: Configure email event tracking
3. **Customize Templates**: Modify templates in `backend/outreach/templates.py`
4. **Add Custom Rules**: Create automation rules via API
5. **Build Dashboard**: Create UI for analytics and lead management

## Support

- Full documentation: `backend/outreach/README.md`
- API documentation: http://localhost:8000/docs (FastAPI auto-generated)
- Code examples: See README.md Usage Examples section
