# Torpedo Outreach System - Complete Setup Guide

## 📋 Quick Overview

Torpedo is an AI-powered cold outreach system with:

- **AI Intelligence Extraction**: Extract company insights from websites automatically
- **Lead Scoring**: intelligently score leads based on multiple factors
- **Personalized Email Generation**: Generate human-like, personalized cold emails at scale
- **Smart Follow-ups**: Automatically follow up based on engagement signals
- **Reply Classification**: AI-powered classification of incoming replies
- **Campaign Automation**: Fully automated outreach sequences with guardrails
- **Webhook Tracking**: Real-time tracking of opens, clicks, bounces, complaints
- **Self-Optimization**: Weekly AI-powered campaign optimization

---

## 🚀 Quick Start (5 minutes)

### 1. Install Dependencies

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` file in the `backend/` directory:

```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o

# Database (optional - using MongoDB by default)
MONGODB_URI=mongodb://localhost:27017/torpedo

# Celery & Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Email Provider (choose one)
# Option 1: SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# Option 2: SendGrid
SENDGRID_API_KEY=sk-your-sendgrid-key

# Option 3: Mailgun
MAILGUN_API_KEY=your-mailgun-key
MAILGUN_DOMAIN=mg.yourdomain.com

# Tracking
TRACKING_DOMAIN=track.torpedo.app

# Logging
LOG_LEVEL=INFO
```

### 3. Start Redis (for Celery)

```bash
# Option 1: Docker
docker run -d -p 6379:6379 redis:latest

# Option 2: Local Redis
redis-server
```

### 4. Run Backend Server

```bash
# In terminal 1 - Start FastAPI server
uvicorn app.main:app --reload --port 8000

# In terminal 2 - Start Celery worker
celery -A app.celery_app worker --loglevel=info

# In terminal 3 - Start Celery Beat (scheduler)
celery -A app.celery_app beat --loglevel=info
```

### 5. Test the API

```bash
# Test health
curl http://localhost:8000/api/outreach/health

# Test AI connection
curl -X POST http://localhost:8000/api/outreach/test-ai-connection

# Process a lead
curl -X POST http://localhost:8000/api/outreach/process-lead \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "TechCorp Inc",
    "contact_name": "John Smith",
    "contact_email": "john@techcorp.com",
    "contact_role": "VP of Sales",
    "website_text": "We are a fast-growing SaaS company...",
    "industry": "SaaS",
    "company_size": "50-200",
    "trigger_event": "Just raised Series B funding"
  }'
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          API Layer                              │
│              (FastAPI Routes - /api/outreach/*)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
         ┌──────▼────┐  ┌────▼──────┐  ┌──▼─────────┐
         │  Services  │  │Orchest.   │  │ Guardrails │
         ├────────────┤  ├───────────┤  ├────────────┤
         │• Lead      │  │Main Flow  │  │• Lead      │
         │  Intel     │  │Control    │  │  Score     │
         │• Email     │  │Coordinator│  │• Sender    │
         │  Gen       │  └───────────┘  │  Limits    │
         │• Reply     │                  │• Risk Mgmt │
         │  Handler   │                  └────────────┘
         └──────┬─────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
 ┌─────────┐ ┌────────┐ ┌──────────┐
 │   AI    │ │Database│ │  Email   │
 │ (OpenAI)│ │(MongoDB)│ │Providers │
 └─────────┘ └────────┘ └──────────┘
```

---

## 📚 Core Modules

### 1. Lead Intelligence Service

**Purpose**: Extract structured intelligence from company data

```python
from app.services.outreach import LeadIntelligenceService

service = LeadIntelligenceService(ai_client)
intelligence, score = await service.extract_and_score(company_data)
# Returns: LeadIntelligence + LeadScore
```

**Outputs**:
- Growth stage
- Business priorities
- Hiring signals
- Operational bottlenecks
- Revenue pressure
- Buyer persona
- Urgency score
- Personalization hooks

### 2. Email Generator Service

**Purpose**: Generate personalized cold emails and follow-ups

```python
from app.services.outreach import EmailGeneratorService

service = EmailGeneratorService(ai_client)
email, spam_result = await service.generate_and_validate(request)
# Returns: GeneratedEmail + SpamCheckResult
```

**Features**:
- Respects length limits (120-160 words)
- Spam trigger avoidance
- AI-powered personalization
- Follow-up strategies based on engagement
- Automatic regeneration if spam-flagged

### 3. Reply Handler Service

**Purpose**: Classify incoming replies and generate responses

```python
from app.services.outreach import ReplyHandlerService

service = ReplyHandlerService(ai_client)
classification = await service.classify_reply(context)
# Returns: ClassifiedReply with 10 classification types
```

**Classifications**:
- Interested
- Meeting Request
- Pricing Inquiry
- Referral
- Objection
- Not Interested
- Out of Office
- Legal Warning
- Spam Complaint Risk
- Unclear

### 4. Sender Manager Service

**Purpose**: Manage sender accounts, warmup, and allocation

```python
from app.services.outreach import SenderManagerService

manager = SenderManagerService()
manager.register_sender(sender_account)
allocation = await manager.allocate_sender(...)
# Returns: SenderAllocation
```

**Tracks**:
- Sender health scores
- Warmup stages (new → warming → warm → established)
- Daily/hourly quotas
- Bounce rates
- Complaint rates

### 5. Campaign Optimizer Service

**Purpose**: Analyze performance and generate recommendations

```python
from app.services.outreach import CampaignOptimizerService

optimizer = CampaignOptimizerService(ai_client)
report = await optimizer.generate_weekly_report(campaign_data)
# Returns: OptimizationReport
```

**Analyzes**:
- Subject line performance
- Body tone effectiveness
- Send time optimization
- Sender performance
- Industry-specific trends
- CTA effectiveness

---

## 🐍 Celery Tasks

### Email Processing Pipeline

```
├── process_email_queue
│   └── send_email_task  
│       └── (integration with SMTP/API)
│
├── process_followups
│   └── generate_followup_task
│       └── send_email_task
│
└── process_reply_task
    └── (classification + auto-response)
```

### Maintenance Tasks

```
├── Daily (midnight UTC)
│   └── reset_daily_limits
│
├── Hourly
│   └── reset_hourly_limits
│
├── Every 15 min
│   └── check_sender_health
│
└── Every 90 days
    └── cleanup_old_data
```

### Enrichment Pipeline

```
├── enrich_lead_task
│   └── generate_outreach_email_task
│       └── send_email_task
```

---

## 📡 API Endpoints

### Outreach Processing

#### `POST /api/outreach/process-lead`

Process a new lead through the full pipeline.

**Request**:
```json
{
  "company_name": "TechCorp Inc",
  "contact_name": "John Smith",
  "contact_email": "john@techcorp.com",
  "contact_role": "VP Sales",
  "website_text": "...",
  "industry": "SaaS",
  "company_size": "50-200",
  "trigger_event": "Series B funding"
}
```

**Response**:
```json
{
  "success": true,
  "email": {
    "subject": "Series B expansion - quick thought",
    "body": "Hi John...",
    "word_count": 145
  },
  "lead_score": 85,
  "priority_tier": "A",
  "spam_score": 5,
  "intelligence": {
    "growth_stage": "Scaling",
    "urgency_score": 8,
    "personalization_hooks": [...]
  }
}
```

#### `POST /api/outreach/process-reply`

Classify an incoming reply.

**Request**:
```json
{
  "from_email": "john@techcorp.com",
  "contact_name": "John Smith",
  "company_name": "TechCorp Inc",
  "subject": "Re: Series B expansion",
  "body": "This looks interesting, let's set up a call."
}
```

**Response**:
```json
{
  "success": true,
  "classification": "Meeting Request",
  "confidence": 0.95,
  "sentiment": "positive",
  "recommended_action": "Schedule meeting",
  "needs_review": false
}
```

#### `POST /api/outreach/generate-followup`

Generate a follow-up email.

**Request**:
```json
{
  "contact_email": "john@techcorp.com",
  "contact_name": "John Smith",
  "company_name": "TechCorp Inc",
  "days_since_sent": 5,
  "open_count": 2
}
```

**Response**:
```json
{
  "success": true,
  "email": {
    "subject": "One more thing about SaaS scaling",
    "body": "Hi John...",
    "strategy_used": "Add new value angle",
    "word_count": 105
  }
}
```

---

## 🔧 Configuration

### Prompts

All AI prompts are in `app/services/outreach/master_prompts.py`:

- `MASTER_SYSTEM_PROMPT` - Global rules for all AI interactions
- `LEAD_INTELLIGENCE_PROMPT` - Extract company intelligence
- `LEAD_SCORING_PROMPT` - Score leads
- `EMAIL_GENERATION_PROMPT` - Generate emails
- `FOLLOWUP_GENERATION_PROMPT` - Generate follow-ups
- `REPLY_CLASSIFIER_PROMPT` - Classify replies
- `SPAM_CHECK_PROMPT` - Check for spam triggers
- `SENDER_ALLOCATION_PROMPT` - Allocate best sender
- `WEEKLY_OPTIMIZATION_PROMPT` - Generate recommendations

### Guardrails

In `app/services/outreach/guardrails.py`:

```python
OutreachLimits(
    max_daily_emails_per_sender=50,
    max_hourly_emails_per_sender=10,
    min_lead_score=60,
    max_emails_per_lead=4,  # 1 initial + 3 follow-ups
    min_days_between_emails=3,
    max_bounce_rate=0.05,
    max_complaint_rate=0.001,
    min_sender_health=70.0
)
```

---

## 🧪 Testing

### Unit Tests

```bash
pytest tests/test_outreach/ -v
```

### Integration Tests

```bash
pytest tests/test_integration/ -v
```

### Load Testing

```bash
locust -f tests/locustfile.py
```

---

## 📊 Monitoring

### Health Checks

```bash
# Check API health
curl http://localhost:8000/api/outreach/health

# Check AI connection
curl -X POST http://localhost:8000/api/outreach/test-ai-connection

# Check Celery status
celery -A app.celery_app inspect active
```

### Logs

```bash
# API logs
tail -f logs/api.log

# Celery logs
tail -f logs/celery.log

# Application logs
tail -f logs/app.log
```

---

## 🛡️ Security & Safety

### Never Without

1. **Lead Score Check** - Always verify lead_score >= threshold
2. **Spam Check** - Always run spam validation before sending
3. **Sender Limits** - Never exceed daily/hourly quotas
4. **Bounce Rate Monitoring** - Auto-suspend sender if rate > threshold
5. **Complaint Tracking** - CRITICAL - immediately suspend on complaint
6. **Reply Risk Assessment** - Flag legal warnings and spam complaints

### Best Practices

- Rotate sender accounts regularly
- Monitor sender reputation scores
- Increase warmup time for new senders
- Implement progressive send volumes
- Track engagement metrics closely
- Maintain clean email lists
- Respect unsubscribe requests

---

## 📈 Success Metrics

Track these KPIs:

- **Delivery Rate**: % of emails successfully delivered
- **Open Rate**: % of emails opened (should aim for 25-40%)
- **Reply Rate**: % of emails receiving replies (should aim for 5-15%)
- **Meeting Rate**: % of emails converting to meetings (should aim for 1-3%)
- **Bounce Rate**: % of hard/soft bounces (should stay < 5%)
- **Complaint Rate**: % marked as spam (should stay < 0.1%)

---

## 📝 Example Workflows

### Full Lead to Meeting

```
1. POST /api/outreach/process-lead
   ↓
2. AI extracts intelligence + scores lead
   ↓
3. Generate personalized cold email
   ↓
4. Check for spam triggers
   ↓
5. Queue email for sending (Celery task)
   ↓
6. Email sent via SMTP/API
   ↓
7. Track opens/clicks via webhooks
   ↓
8. After 3 days, generate follow-up (if no reply)
   ↓
9. Send follow-up email
   ↓
10. Reply arrives → POST /api/outreach/process-reply
    ↓
11. AI classifies as "Meeting Request"
    ↓
12. Auto-generate response with meeting times
    ↓
13. Meeting scheduled!
```

---

## 🐛 Troubleshooting

### "OpenAI API key not configured"

**Fix**: Ensure `OPENAI_API_KEY` is set in `.env`

```bash
export OPENAI_API_KEY=sk-...
```

### "Redis connection refused"

**Fix**: Start Redis

```bash
docker run -d -p 6379:6379 redis:latest
```

### "Email generation failing"

**Check**:
1. API key is valid
2. Model name is correct (gpt-4o)
3. Token limits aren't exceeded
4. Check rate limits

### "Celery tasks not running"

**Check**:
```bash
celery -A app.celery_app inspect active
celery -A app.celery_app inspect registered
```

---

## 📚 Additional Resources

- [OpenAI API Documentation](https://platform.openai.com/docs)
- [Celery Documentation](https://docs.celeryproject.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [MongoDB Documentation](https://docs.mongodb.com/)

---

## 🤝 Support

For issues, check:
1. Logs in `logs/` directory
2. OpenAI API status
3. Redis/database connectivity
4. Email provider integration
5. Sender reputation

---

**Version**: 1.0.0
**Last Updated**: 2026-02-19
