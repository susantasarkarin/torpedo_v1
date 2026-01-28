# AI Cold Outreach & Re-Engagement Module

## Overview

A **scalable, AI-driven cold outreach module** for B2B lead engagement that:
- Sends personalized cold emails
- Executes intelligent follow-ups based on behavior
- Tracks email engagement (bounce, open, click, reply)
- Automatically moves unresponsive leads into drip & re-engagement campaigns
- Adapts messaging based on lead attributes and engagement signals

The system maximizes replies while protecting deliverability.

---

## Architecture

### Core Components

```
backend/outreach/
├── models.py              # Data models for leads, sequences, emails, events
├── personalization.py     # 3-level personalization engine
├── sequence_engine.py     # Cold outreach sequence management
├── tracking.py            # Email event tracking service
├── automation_rules.py    # Deterministic automation rules engine
├── reengagement.py        # Drip & re-engagement campaigns
├── templates.py           # Default email templates
└── router.py              # FastAPI API endpoints
```

### Database Collections

- **outreach_leads**: Lead intelligence with engagement tracking
- **outreach_sequences**: Email sequence definitions
- **outreach_emails**: Individual email sends with tracking
- **outreach_events**: Email behavior events (opens, clicks, etc.)
- **outreach_templates**: Email templates with personalization
- **reengagement_pool**: Leads for drip campaigns
- **automation_rules**: Deterministic automation rules

---

## Features

### 1. Personalization Engine

Three levels of personalization:

**Level 1 (Light)**: Name, company, industry
```python
{{first_name}}, {{company}}, {{industry}}
```

**Level 2 (Role-Based - Default)**: + Title, seniority, department, pain points
```python
{{title}}, {{seniority}}, {{department}}, {{pain_point}}
```

**Level 3 (Deep)**: + Company-specific context, triggers, insights
```python
{{use_case}}, {{value_proposition}}, custom_fields
```

### 2. Cold Outreach Sequence Engine

Default 4-step sequence (14-18 days):

1. **Email 1 - Introduction (Day 1)**
   - Soft introduction
   - One clear pain point
   - Low-friction CTA

2. **Email 2 - Value Follow-Up (Day 4)**
   - Different angle
   - Use case + social proof
   - Behavior-based subject variants

3. **Email 3 - Direct / Break-Up (Day 7)**
   - Very concise
   - Simple yes/no CTA

4. **Email 4 - Final Touch (Day 12)**
   - Polite close-the-loop

### 3. Behavior-Based Follow-Up Logic

Adapts based on engagement:

| Behavior | Action |
|----------|--------|
| Opened but No Reply | Change CTA, shorten copy, ask simpler question |
| Not Opened | New subject line, different value angle |
| Clicked but No Reply | Reference interaction, offer walkthrough/demo |

### 4. Email Tracking & Status Management

**Email-Level Events**:
- Sent, Delivered, Bounced
- Opened, Clicked
- Replied, Unsubscribed

**Lead-Level Statuses**:
- Never Opened
- Opened – No Reply
- Engaged, Warm Lead
- Replied – Positive/Neutral/Negative
- Bounced, Unsubscribed

### 5. Automation Rules Engine

Pre-built rules:

```python
IF email_bounced = true
→ mark email invalid
→ stop all sequences

IF reply_received = true
→ stop sequence
→ mark lead as engaged

IF opened >= 2 times AND no reply
→ flag as warm lead

IF no opens after 3 emails
→ downgrade sending cadence
```

### 6. Drip & Re-Engagement Strategy

**Week 3-4 (Soft Drip)**:
- Educational content
- Industry insights
- No/soft CTA

**Month 2 (Trigger-Based)**:
- Job change
- Company growth
- Industry events
- Product updates

**Month 3-4 (Reset Outreach)**:
- New angle
- Fresh copy
- Optional sender rotation

---

## API Reference

### Lead Management

#### Enroll Leads
```http
POST /api/outreach/leads/enroll
Content-Type: application/json

{
  "leads": [
    {
      "first_name": "John",
      "last_name": "Doe",
      "email": "john@example.com",
      "company": "Acme Corp",
      "title": "VP of Engineering",
      "seniority": "VP",
      "department": "Engineering",
      "industry": "Technology",
      "pain_point": "Scaling infrastructure challenges"
    }
  ],
  "sequence_id": "sequence_id_here",
  "start_immediately": true
}
```

#### Get Lead Details
```http
GET /api/outreach/leads/{lead_id}
```

#### Update Lead Status
```http
PATCH /api/outreach/leads/{lead_id}/status
Content-Type: application/json

{
  "engagement_status": "Warm Lead",
  "tags": ["high_priority", "enterprise"]
}
```

#### List Leads
```http
GET /api/outreach/leads?sequence_id={id}&engagement_status=Engaged&skip=0&limit=50
```

### Sequence Management

#### Create Default Sequence
```http
POST /api/outreach/sequences/default
```

Creates the standard 4-step cold outreach sequence with templates.

#### Get Sequence Analytics
```http
GET /api/outreach/sequences/{sequence_id}/analytics
```

Returns:
```json
{
  "total_leads": 150,
  "emails_sent": 450,
  "emails_opened": 180,
  "emails_clicked": 45,
  "emails_replied": 22,
  "open_rate": 40.0,
  "reply_rate": 4.89,
  "positive_reply_rate": 2.93,
  "reengagement_eligible": 85,
  "reengagement_converted": 12
}
```

### Email Tracking

#### Track Email Events
```http
POST /api/outreach/tracking/sent/{email_id}
POST /api/outreach/tracking/opened/{email_id}?ip_address=1.2.3.4
POST /api/outreach/tracking/clicked/{email_id}?clicked_url=https://...
POST /api/outreach/tracking/replied/{email_id}
POST /api/outreach/tracking/bounced/{email_id}?bounce_reason=Invalid
```

#### Get Email Activity
```http
GET /api/outreach/tracking/email/{email_id}/activity
```

### Re-engagement

#### Enroll Eligible Leads
```http
POST /api/outreach/reengagement/enroll
```

Automatically enrolls leads with completed sequences.

#### Get Re-engagement Stats
```http
GET /api/outreach/reengagement/stats
```

#### Process Due Actions
```http
POST /api/outreach/reengagement/process?limit=50
```

### Automation Rules

#### List Rules
```http
GET /api/outreach/automation/rules
```

#### Get Rule Stats
```http
GET /api/outreach/automation/stats
```

#### Evaluate Lead Against Rules
```http
POST /api/outreach/automation/evaluate/{lead_id}
```

### Templates

#### Seed Default Templates
```http
POST /api/outreach/templates/seed
```

#### List Templates
```http
GET /api/outreach/templates?category=cold_outreach
```

---

## Usage Examples

### Example 1: Enroll Leads in Cold Outreach

```python
import requests

# 1. Create default sequence with templates
response = requests.post("http://localhost:8000/api/outreach/sequences/default")
sequence_id = response.json()["sequence_id"]

# 2. Enroll leads
leads = [
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
        "value_proposition": "streamlined remote collaboration tools"
    }
]

response = requests.post(
    "http://localhost:8000/api/outreach/leads/enroll",
    json={
        "leads": leads,
        "sequence_id": sequence_id,
        "start_immediately": True
    }
)

print(f"Enrolled: {response.json()['enrolled']} leads")
```

### Example 2: Track Email Events

```python
# When email is sent (from your email provider webhook)
email_id = "email_id_from_database"

requests.post(f"http://localhost:8000/api/outreach/tracking/sent/{email_id}")

# When email is opened (from tracking pixel)
requests.post(
    f"http://localhost:8000/api/outreach/tracking/opened/{email_id}",
    params={"ip_address": "203.0.113.1"}
)

# When link is clicked
requests.post(
    f"http://localhost:8000/api/outreach/tracking/clicked/{email_id}",
    params={"clicked_url": "https://yoursite.com/demo"}
)

# When lead replies
requests.post(f"http://localhost:8000/api/outreach/tracking/replied/{email_id}")
```

### Example 3: Get Sequence Performance

```python
response = requests.get(f"http://localhost:8000/api/outreach/sequences/{sequence_id}/analytics")
analytics = response.json()

print(f"Open Rate: {analytics['open_rate']}%")
print(f"Reply Rate: {analytics['reply_rate']}%")
print(f"Leads in Re-engagement: {analytics['reengagement_eligible']}")
```

### Example 4: Process Scheduled & Re-engagement

```python
# Run this periodically (e.g., every 5 minutes via cron or APScheduler)

# Process scheduled emails
response = requests.post("http://localhost:8000/api/outreach/process/scheduled-emails")
print(f"Processed {response.json()['processed']} scheduled emails")

# Enroll eligible leads in re-engagement
response = requests.post("http://localhost:8000/api/outreach/reengagement/enroll")
print(f"Enrolled {response.json()['enrolled']} leads in re-engagement")

# Process re-engagement actions
response = requests.post("http://localhost:8000/api/outreach/reengagement/process")
print(f"Processed {response.json()['processed']} re-engagement actions")
```

---

## Integration Guide

### 1. Add to FastAPI Application

```python
# In backend/main.py
from outreach.router import router as outreach_router

app = FastAPI()
app.include_router(outreach_router)
```

### 2. Connect Email Provider

Integrate with your email sending service (SendGrid, Mailgun, AWS SES, etc.):

```python
# In your email sender service
from outreach.tracking import EmailTrackingService

def send_email(email_doc):
    # Send via your provider
    response = email_provider.send(...)
    
    # Track as sent
    service = EmailTrackingService(db)
    service.track_sent(
        email_id=email_doc["_id"],
        provider_message_id=response.message_id
    )
```

### 3. Setup Webhooks

Configure webhooks from your email provider to track events:

```python
# Webhook handler
@app.post("/webhooks/email-events")
async def handle_email_events(event: dict, db=Depends(get_database)):
    service = EmailTrackingService(db)
    
    if event["type"] == "open":
        service.track_opened(event["email_id"])
    elif event["type"] == "click":
        service.track_clicked(event["email_id"], event["url"])
    elif event["type"] == "bounce":
        service.track_bounced(event["email_id"], event["reason"])
    elif event["type"] == "reply":
        service.track_replied(event["email_id"])
```

### 4. Schedule Background Jobs

```python
# Using APScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from outreach.sequence_engine import SequenceEngine
from outreach.reengagement import ReengagementEngine

scheduler = BackgroundScheduler()

# Process scheduled emails every 5 minutes
scheduler.add_job(
    lambda: SequenceEngine(db).process_scheduled_emails(),
    'interval',
    minutes=5
)

# Process re-engagement daily
scheduler.add_job(
    lambda: ReengagementEngine(db).process_due_actions(),
    'cron',
    hour=9
)

scheduler.start()
```

---

## Success Metrics

Track these KPIs in your dashboard:

- **Open Rate**: % of delivered emails opened
- **Reply Rate**: % of delivered emails replied to
- **Positive Reply Rate**: % of replies that are positive
- **Bounce Rate**: % of emails that bounced
- **Re-engagement Conversion Rate**: % of re-engaged leads that convert
- **Warm Lead Flagging**: Leads with 2+ opens

---

## Best Practices

### 1. Deliverability
- Start with small daily volumes (50-100/day)
- Warm up new domains gradually
- Monitor bounce rates (keep < 2%)
- Use valid SPF, DKIM, DMARC records

### 2. Personalization
- Always use at least Level 2 (Role-Based)
- Validate data quality before enrollment
- Use Deep personalization for high-value leads

### 3. Sequence Timing
- Respect business hours (9 AM - 5 PM local time)
- Avoid weekends for B2B
- Space follow-ups appropriately (4-7 days)

### 4. Content
- Keep emails concise (< 150 words)
- One clear CTA per email
- Test subject lines (A/B variants)
- Focus on value, not features

### 5. Compliance
- Include unsubscribe links
- Honor opt-outs immediately
- Respect CAN-SPAM and GDPR
- Stop sequences on negative replies

---

## Troubleshooting

### Low Open Rates
- Check subject lines (test variants)
- Verify sender reputation
- Ensure proper email authentication
- Review sending volume/timing

### High Bounce Rates
- Validate emails before enrollment
- Remove catch-all and risky emails
- Update email verification status

### No Replies
- Review personalization quality
- Test different value propositions
- Shorten email copy
- Improve CTAs

---

## Future Enhancements

Planned features:
- [ ] AI-powered reply sentiment analysis
- [ ] Automatic A/B testing engine
- [ ] Integration with enrichment APIs (Clearbit, Apollo)
- [ ] Advanced trigger detection (funding, hiring, etc.)
- [ ] Multi-channel sequences (email + LinkedIn)
- [ ] Real-time sender rotation
- [ ] Deliverability monitoring dashboard

---

## Support

For issues, questions, or feature requests, please refer to the main project documentation or contact the development team.
