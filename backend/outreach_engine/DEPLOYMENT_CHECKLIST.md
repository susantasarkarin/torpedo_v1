# Enterprise Outbound Engine - Deployment Checklist

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    ENTERPRISE OUTBOUND ENGINE                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   Campaign   │───▶│   Workflow   │───▶│   Template   │              │
│  │   Config     │    │   Engine     │    │   Renderer   │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                             │                    │                      │
│                             ▼                    ▼                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   Mailbox    │◀──▶│   Sending    │◀───│     AI       │              │
│  │   Manager    │    │   Engine     │    │   Context    │              │
│  │  (STICKY)    │    │  (THREADS)   │    │   Generator  │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         │                    │                                          │
│         ▼                    ▼                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │    Rate      │───▶│  Scheduler   │───▶│   Logging    │              │
│  │   Limiter    │    │  (Queue)     │    │   Service    │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| **WorkflowEngine** | `workflow_engine.py` | State machine for email sequence progression |
| **MailboxManager** | `mailbox_manager.py` | Sticky mailbox assignment, health monitoring |
| **AIContextGenerator** | `ai_context_generator.py` | 150-token AI context blocks (once per lead) |
| **TemplateRenderer** | `template_renderer.py` | Token replacement, dynamic signatures |
| **SendingEngine** | `sending_engine.py` | Email sending with thread continuity |
| **RateLimiter** | `rate_limiter.py` | Enterprise rate limiting (300-400/day) |
| **SendScheduler** | `scheduler.py` | Job queue based scheduling |
| **OutreachLogger** | `logging_service.py` | Comprehensive logging and analytics |

---

## Database Schema Changes

### New Collections

```javascript
// outreach_leads_v2
{
  lead_id: String (unique),
  email: String (unique),
  first_name: String,
  last_name: String,
  company: String,
  industry: String,
  title: String,
  
  // Workflow State
  workflow_id: String,
  campaign_id: String,
  current_step: Number (0-indexed),
  workflow_status: Enum ["not_started", "in_progress", "completed", "stopped", "replied", "bounced", "unsubscribed"],
  
  // STICKY Mailbox Assignment
  assigned_mailbox_id: String (NEVER changes once assigned),
  
  // Thread Continuity
  thread_id: String (Gmail),
  message_id_last_sent: String,
  in_reply_to: String,
  references: [String],
  
  // AI Context (generated ONCE, reused)
  ai_context_block: String,
  ai_context_generated_at: DateTime,
  ai_tokens_used: Number,
  
  // Engagement
  personalization_level: Enum ["light", "medium", "heavy"],
  last_sent_at: DateTime,
  next_send_at: DateTime,
  reply_status: String,
  bounce_status: Enum ["soft", "hard"],
  
  // Timestamps
  created_at: DateTime,
  updated_at: DateTime,
  workflow_started_at: DateTime,
  workflow_completed_at: DateTime
}

// outreach_mailboxes
{
  mailbox_id: String (unique),
  email_address: String (unique),
  display_name: String,
  provider: Enum ["gmail", "smtp"],
  signature_html: String,
  
  // Rate Tracking
  daily_send_count: Number,
  hourly_send_count: Number,
  daily_send_limit: Number (default 400),
  hourly_send_limit: Number (default 60),
  
  // Health
  health_status: Enum ["healthy", "warming", "paused", "suspended"],
  bounce_rate_24h: Number,
  paused_until: DateTime,
  
  is_active: Boolean
}

// outreach_templates_v2
{
  template_id: String (unique),
  company_brand: String,
  step_type: Enum ["initial", "follow_up_1", "follow_up_2", "final"],
  
  subject: String,
  body_html: String,
  
  supported_tokens: [String],
  is_active: Boolean
}

// outreach_sends_v2
{
  send_id: String (unique),
  campaign_id: String,
  lead_id: String,
  mailbox_id: String,
  
  // Thread Headers
  message_id: String (unique),
  in_reply_to: String,
  references: [String],
  thread_id: String,
  
  subject: String,
  body_html: String,
  
  status: Enum ["pending", "sent", "failed", "bounced"],
  sent_at: DateTime,
  
  personalization_level: String,
  ai_tokens_used: Number
}
```

### Required Indexes

```javascript
// Run in MongoDB shell
db.outreach_leads_v2.createIndex({lead_id: 1}, {unique: true})
db.outreach_leads_v2.createIndex({email: 1}, {unique: true})
db.outreach_leads_v2.createIndex({campaign_id: 1, workflow_status: 1})
db.outreach_leads_v2.createIndex({next_send_at: 1, workflow_status: 1})

db.outreach_mailboxes.createIndex({mailbox_id: 1}, {unique: true})
db.outreach_mailboxes.createIndex({email_address: 1}, {unique: true})

db.outreach_sends_v2.createIndex({message_id: 1}, {unique: true})
db.outreach_sends_v2.createIndex({campaign_id: 1, lead_id: 1})
db.outreach_sends_v2.createIndex({mailbox_id: 1, sent_at: -1})
```

---

## Send-Bulk Logic (Updated)

```python
async def send_bulk_campaign(campaign_id: str, lead_ids: List[str], dry_run: bool = False):
    """
    Enterprise-grade bulk sending with all controls.
    
    Flow:
    1. Load campaign config and templates
    2. For each lead:
       a. Assign mailbox (STICKY - first time only)
       b. Check mailbox rate limits
       c. Generate/retrieve AI context (ONCE per lead)
       d. Render template with tokens
       e. Send with thread continuity
       f. Log send with all metadata
    """
    
    from outreach_engine import (
        WorkflowEngine, MailboxManager, AIContextGenerator,
        TemplateRenderer, SendingEngine, RateLimiter, OutreachLogger
    )
    
    # Initialize components
    workflow = WorkflowEngine(db)
    mailbox_mgr = MailboxManager(db)
    ai_gen = AIContextGenerator(db)
    renderer = TemplateRenderer(db)
    sender = SendingEngine(db)
    rate_limiter = RateLimiter(db)
    logger = OutreachLogger(db)
    
    campaign = db.outreach_campaigns_v2.find_one({"campaign_id": campaign_id})
    
    results = {"sent": 0, "skipped": 0, "errors": []}
    
    for lead_id in lead_ids:
        lead = db.outreach_leads_v2.find_one({"lead_id": lead_id})
        
        # 1. STICKY Mailbox Assignment
        if not lead.get("assigned_mailbox_id"):
            mailbox = await mailbox_mgr.assign_mailbox_to_lead(
                lead_id, 
                campaign["mailbox_ids"]
            )
        else:
            # Use SAME mailbox (sticky)
            mailbox = db.outreach_mailboxes.find_one({
                "mailbox_id": lead["assigned_mailbox_id"]
            })
        
        # 2. Check Rate Limits
        can_send, reason = await rate_limiter.can_send(mailbox["mailbox_id"])
        if not can_send:
            results["skipped"] += 1
            continue
        
        # 3. AI Context (generate ONCE, reuse for follow-ups)
        if lead.get("personalization_level") in ["medium", "heavy"]:
            ai_context = await ai_gen.get_or_generate_context_block(lead_id)
        else:
            ai_context = ""
        
        # 4. Get Template
        current_step = lead.get("current_step", 0)
        step_type = campaign["workflow_steps"][current_step]["step_type"]
        template = db.outreach_templates_v2.find_one({
            "company_brand": campaign["brand"],
            "step_type": step_type
        })
        
        # 5. Render Email
        rendered = await renderer.render_email(
            template_id=template["template_id"],
            lead=lead,
            mailbox=mailbox
        )
        
        # 6. Send with Thread Continuity
        if not dry_run:
            send_result = await sender.send_email(
                lead=lead,
                mailbox=mailbox,
                subject=rendered["subject"],
                body_html=rendered["body_html"],
                previous_message_id=lead.get("message_id_last_sent"),
                thread_id=lead.get("thread_id")
            )
            
            # 7. Update Lead State
            await workflow.advance_workflow(lead_id)
            
            # 8. Log Send
            await logger.log_send(
                campaign_id=campaign_id,
                lead_id=lead_id,
                mailbox_used=mailbox["email_address"],
                workflow_step=current_step,
                personalization_level=lead.get("personalization_level"),
                ai_tokens_used=lead.get("ai_tokens_used", 0),
                message_id=send_result["message_id"],
                thread_id=send_result.get("thread_id")
            )
            
            results["sent"] += 1
        
        # 9. Random Delay (60-180 seconds)
        await asyncio.sleep(random.uniform(60, 180))
    
    return results
```

---

## Workflow State Machine

```
                    ┌───────────────┐
                    │  NOT_STARTED  │
                    └───────┬───────┘
                            │ start_workflow()
                            ▼
                    ┌───────────────┐
        ┌──────────▶│  IN_PROGRESS  │◀────────────┐
        │           └───────┬───────┘             │
        │                   │                      │
        │    ┌──────────────┼──────────────┐      │
        │    │              │              │      │
        │    ▼              ▼              ▼      │
        │ ┌─────┐      ┌─────────┐    ┌────────┐ │
        │ │REPLY│      │BOUNCED  │    │COMPLETE│ │
        │ │     │      │soft/hard│    │        │ │
        │ └─────┘      └─────────┘    └────────┘ │
        │                                         │
        │         ┌───────────────┐               │
        │         │ UNSUBSCRIBED  │               │
        │         └───────────────┘               │
        │                                         │
        │         ┌───────────────┐               │
        └─────────│    STOPPED    │───────────────┘
                  │   (manual)    │
                  └───────────────┘

Transitions:
- start_workflow()       → NOT_STARTED → IN_PROGRESS
- advance_workflow()     → Increment step, stay IN_PROGRESS
- handle_reply()         → IN_PROGRESS → REPLIED (stop sending)
- handle_bounce()        → IN_PROGRESS → BOUNCED (stop sending)
- handle_unsubscribe()   → IN_PROGRESS → UNSUBSCRIBED (stop sending)
- stop_workflow()        → Any → STOPPED (manual stop)
- complete_workflow()    → IN_PROGRESS → COMPLETED (all steps done)
```

---

## Migration Steps

### Pre-Migration (30 minutes)

```bash
# 1. Create backup of current database
mongodump --db email_automation --out ./backup_$(date +%Y%m%d)

# 2. Verify backup
mongorestore --db email_automation_verify --dir ./backup_$(date +%Y%m%d)/email_automation --dryRun
```

### Run Migration (15 minutes)

```bash
cd backend

# 3. Run migration script
python -m outreach_engine.migrate_to_v2

# Expected output:
# [1/6] Backing up existing data...
# [2/6] Creating new collections and indexes...
# [3/6] Migrating leads...
# [4/6] Setting up mailboxes...
# [5/6] Creating default templates...
# [6/6] Validating migration...
# MIGRATION COMPLETE
```

### Post-Migration Configuration (1 hour)

```bash
# 4. Configure mailboxes with real credentials
mongosh

use email_automation
db.outreach_mailboxes.updateOne(
  {email_address: "outreach1@surveyfieldwork.com"},
  {$set: {
    credentials_id: "<gmail_creds_id>",
    signature_html: "<your signature>",
    is_active: true
  }}
)

# 5. Add remaining mailboxes (need 4 for 8000 emails/campaign)
db.outreach_mailboxes.insertMany([
  {mailbox_id: "mb_2", email_address: "outreach2@surveyfieldwork.com", ...},
  {mailbox_id: "mb_3", email_address: "outreach3@surveyfieldwork.com", ...},
  {mailbox_id: "mb_4", email_address: "outreach4@surveyfieldwork.com", ...}
])
```

### Test Migration (30 minutes)

```bash
# 6. Test with dry run
python -c "
from outreach_engine import SendingEngine
sender = SendingEngine(db)
result = sender.send_batch(campaign_id='test', lead_ids=['lead1'], dry_run=True)
print(result)
"

# 7. Test single send
python -c "
from outreach_engine import SendingEngine, OutreachLogger
sender = SendingEngine(db)
logger = OutreachLogger(db)

# Get one lead
lead = db.outreach_leads_v2.find_one({'workflow_status': 'not_started'})

# Send test email
result = sender.send_email(lead, mailbox, 'Test Subject', '<p>Test body</p>')
print(f'Sent: {result}')

# Check logs
log = logger.get_campaign_stats('test_campaign')
print(f'Stats: {log}')
"
```

---

## Components to Remove

After confirming the new system works:

### Delete These Files

```bash
# Agents (full AI generation)
rm backend/agents/outreach_composer_agent.py
rm backend/agents/reengagement_agent.py

# Old campaign modules
rm backend/campaigns/automation.py
rm backend/campaigns/executor.py
rm backend/campaigns/personalization_engine.py

# Old outreach modules
rm backend/outreach/templates.py

# Old routers
rm backend/routers/email_campaigns.py

# Gmail automation (old composer)
rm backend/gmail_automation/email_composer.py
```

### Update Imports

```python
# In main.py - REMOVE
from agents.outreach_composer_agent import OutreachComposerAgent
from campaigns.automation import CampaignAutomation
from campaigns.executor import CampaignExecutor

# In main.py - ADD
from outreach_engine import (
    WorkflowEngine, MailboxManager, AIContextGenerator,
    TemplateRenderer, SendingEngine, RateLimiter, SendScheduler, OutreachLogger
)
```

### Archive Old Collections

```javascript
// After 30 days of successful operation
db.leads_enriched.rename("archive_leads_enriched")
db.outreach_leads.rename("archive_outreach_leads")
db.campaign_sends.rename("archive_campaign_sends")
db.campaigns.rename("archive_campaigns")
```

---

## Risk Analysis

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Data loss during migration** | HIGH | Full backup before migration, validation after |
| **Thread continuity broken** | HIGH | New engine stores message_id, in_reply_to, references |
| **Mailbox assignment changes** | MEDIUM | STICKY assignment - never changes per lead |
| **AI over-generation** | MEDIUM | 150 token cap, generate ONCE per lead only |
| **Rate limits exceeded** | MEDIUM | Built-in rate limiter with 400/day, 60/hour caps |
| **Bounce rate spike** | MEDIUM | Auto-pause at 5% bounce rate |
| **Template rendering errors** | LOW | Validation on render, fallback values |
| **Gmail API failures** | LOW | Retry logic, SMTP fallback |

### Rollback Plan

```bash
# If migration fails:

# 1. Restore from backup
mongorestore --db email_automation --dir ./backup_$(date +%Y%m%d)/email_automation

# 2. Remove new collections
mongosh
use email_automation
db.outreach_leads_v2.drop()
db.outreach_campaigns_v2.drop()
db.outreach_mailboxes.drop()
db.outreach_templates_v2.drop()
db.outreach_sends_v2.drop()

# 3. Re-enable old components
git checkout backend/agents/outreach_composer_agent.py
git checkout backend/campaigns/automation.py
```

---

## Final Deployment Checklist

### Pre-Deployment

- [ ] Database backup completed
- [ ] Migration script tested in staging
- [ ] 4 mailboxes configured with Gmail credentials
- [ ] Templates created for both brands
- [ ] Rate limits configured (400/day, 60/hour per inbox)
- [ ] OpenAI API key configured
- [ ] Celery workers configured for scheduler

### Deployment

- [ ] Run migration script
- [ ] Verify new collections created
- [ ] Verify indexes created
- [ ] Verify leads migrated correctly
- [ ] Activate mailboxes (is_active=true)

### Post-Deployment Testing

- [ ] Dry run test campaign
- [ ] Single email send test
- [ ] Verify thread continuity (In-Reply-To header)
- [ ] Verify AI context generation (150 token cap)
- [ ] Verify sticky mailbox assignment
- [ ] Verify rate limiting working
- [ ] Verify logging captures all fields

### Cleanup (After 7 Days)

- [ ] Remove old agent files
- [ ] Remove old campaign files
- [ ] Update main.py imports
- [ ] Archive old collections
- [ ] Remove unused environment variables

---

## API Reference

```python
# Initialize engines
from outreach_engine import (
    WorkflowEngine, MailboxManager, AIContextGenerator,
    TemplateRenderer, SendingEngine, RateLimiter, 
    SendScheduler, OutreachLogger
)

# Start a workflow
workflow = WorkflowEngine(db)
await workflow.start_workflow(lead_id, campaign_id)

# Assign mailbox (sticky)
mailbox_mgr = MailboxManager(db)
mailbox = await mailbox_mgr.assign_mailbox_to_lead(lead_id, mailbox_ids)

# Generate AI context (once per lead)
ai_gen = AIContextGenerator(db)
context = await ai_gen.get_or_generate_context_block(lead_id)

# Render template
renderer = TemplateRenderer(db)
email = await renderer.render_email(template_id, lead, mailbox)

# Send email
sender = SendingEngine(db)
result = await sender.send_email(lead, mailbox, subject, body)

# Log send
logger = OutreachLogger(db)
await logger.log_send(campaign_id, lead_id, mailbox_used, ...)

# Get stats
stats = await logger.get_campaign_stats(campaign_id)
```

---

## Configuration Reference

```python
# outreach_engine/config.py (create if needed)

OUTREACH_CONFIG = {
    # Rate Limits
    "daily_send_limit": 400,         # Per mailbox
    "hourly_send_limit": 60,         # Per mailbox
    "send_interval_min": 60,         # Seconds between sends
    "send_interval_max": 180,        # Seconds between sends
    
    # AI Configuration
    "ai_model": "gpt-4o-mini",
    "ai_max_tokens": 150,
    "ai_temperature": 0.7,
    
    # Health Thresholds
    "bounce_rate_threshold": 0.05,   # 5% = pause mailbox
    "complaint_rate_threshold": 0.001,
    
    # Sending Window
    "send_hours_start": 9,           # 9 AM
    "send_hours_end": 17,            # 5 PM
    "send_days": [0, 1, 2, 3, 4],    # Mon-Fri
    
    # Thread Continuity
    "domain": "surveyfieldwork.com",
    
    # Collections
    "leads_collection": "outreach_leads_v2",
    "campaigns_collection": "outreach_campaigns_v2",
    "templates_collection": "outreach_templates_v2",
    "mailboxes_collection": "outreach_mailboxes",
    "sends_collection": "outreach_sends_v2",
    "logs_collection": "outreach_send_logs",
}
```

---

*Document generated by Enterprise Outbound Engine Migration Tool*
*Last updated: {datetime.now()}*
