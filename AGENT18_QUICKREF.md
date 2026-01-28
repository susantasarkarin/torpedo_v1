# AGENT 18 - QUICK REFERENCE
## Phase 3: High-Volume Infrastructure & Team Collaboration

---

## 🚀 SEND QUEUE

### Basic Usage
```python
from campaigns.send_queue import SendQueueManager

queue = SendQueueManager(redis_url="redis://localhost:6379/0")

# Enqueue email
send_id = queue.enqueue_send({
    "to": "prospect@example.com",
    "subject": "Follow up",
    "body_html": "<p>Hello</p>",
    "from_email": "sales@company.com",
    "campaign_id": "camp_123",
    "recipient_id": "recip_456"
}, priority="normal")  # critical | high | normal | low

# Dequeue for processing
sends = queue.dequeue_sends(batch_size=100)

# Mark complete or retry
queue.mark_complete(send_id)
queue.retry_failed(send_item, error_msg, max_retries=3)

# Monitor
stats = queue.get_queue_stats()
# {"critical": 5, "high": 120, "normal": 450, ...}
```

### Priority Levels
- **critical**: Transactional, time-sensitive
- **high**: Follow-ups, hot leads
- **normal**: Standard campaigns
- **low**: Re-engagement, nurture

### Retry Strategy
- **1st retry**: 5 minutes
- **2nd retry**: 15 minutes
- **3rd retry**: 45 minutes
- **Failed**: Move to dead letter queue

---

## 🛡️ THROTTLE MANAGER

### Basic Usage
```python
from campaigns.throttle_manager import ThrottleManager

throttle = ThrottleManager(
    redis_url="redis://localhost:6379/0",
    global_hourly_limit=5000,
    global_daily_limit=50000
)

# Check before sending
if not throttle.check_global_rate_limit():
    wait_time = throttle.get_wait_time()
    print(f"Wait {wait_time} seconds")
    return

if not throttle.check_campaign_rate_limit(campaign_id):
    print("Campaign throttled")
    return

if not throttle.check_mailbox_rate_limit(mailbox_id):
    print("Mailbox throttled")
    return

# Record send
throttle.record_send(campaign_id=campaign_id, mailbox_id=mailbox_id)

# Update delivery health
health = throttle.update_delivery_health(
    mailbox_id=mailbox_id,
    bounced=False,
    delivered=True
)
# Auto-throttles if bounce_rate > 5% or spam_rate > 0.1%
```

### Manual Throttling
```python
# Apply throttle
throttle.apply_throttle(
    campaign_id="camp_123",
    reason="high_bounce_rate",
    duration_hours=4,
    notes="Paused due to 8% bounce rate"
)

# Check status
status = throttle.get_throttle_status("campaign", "camp_123")
if status.is_throttled:
    print(f"Throttled until {status.throttled_until}")

# Clear throttle
throttle.clear_throttle("campaign", "camp_123")
```

### Rate Limits (Defaults)
- **Global**: 5,000/hour, 50,000/day
- **Campaign**: 500/hour
- **Mailbox**: 100/hour, 500/day

### Auto-Throttle Triggers
- Bounce rate > 5%
- Spam rate > 0.1%
- 4-hour automatic pause

---

## 📊 ACTIVITY FEED

### Basic Usage
```python
from activity.feed import ActivityFeed

feed = ActivityFeed()

# Log action
feed.log_action(
    user_id="user_123",
    action="lead_assigned",
    resource="lead",
    resource_id="lead_456",
    team_id="team_abc",
    details={
        "assigned_to": "user_789",
        "assignee_name": "John Smith"
    }
)

# Get user activity
activities = feed.get_user_activity("user_123", limit=50)

# Get team activity
team_activities = feed.get_team_activity("team_abc", limit=100)

# Get resource activity
lead_activities = feed.get_resource_activity("lead", "lead_456")

# Recent activity (last 24 hours)
recent = feed.get_recent_activity(hours=24, team_id="team_abc")

# Activity stats
stats = feed.get_activity_stats(
    team_id="team_abc",
    start_date=datetime.now() - timedelta(days=7)
)
# Returns: total, by_action, by_resource, by_user
```

### Action Types
**Leads**: `lead_created`, `lead_updated`, `lead_assigned`, `lead_enriched`, `lead_contacted`, `lead_replied`, `lead_converted`, `lead_archived`

**Campaigns**: `campaign_created`, `campaign_started`, `campaign_paused`, `campaign_resumed`, `campaign_completed`, `campaign_archived`

**Emails**: `email_sent`, `email_opened`, `email_clicked`, `email_replied`, `email_bounced`

**RFQs**: `rfq_created`, `rfq_quoted`, `rfq_won`, `rfq_lost`

**Team**: `team_member_added`, `team_member_removed`, `team_settings_updated`

**Other**: `note_added`, `file_uploaded`, `task_created`, `task_completed`

### Resource Types
`lead`, `campaign`, `email`, `rfq`, `team`, `user`, `note`, `file`, `task`

---

## 👥 TEAM API

### Lead Management
```bash
# Get team leads
GET /team/leads?team_id=team_abc&assigned_to=user_123&limit=50

# Assign lead
POST /team/leads/lead_456/assign
{
  "assign_to": "user_789",
  "notes": "High priority prospect"
}

# Unassign lead
POST /team/leads/lead_456/unassign
```

### Activity Feed
```bash
# Team activity
GET /team/activity?team_id=team_abc&hours=24&limit=100

# User activity
GET /team/activity/user/user_123?limit=50

# Filtered activity
GET /team/activity?action_filter=lead_assigned,lead_contacted&resource_filter=lead
```

### Dashboard
```bash
# Team performance
GET /team/dashboard?team_id=team_abc&days=7

# Returns:
{
  "leads": {
    "total": 1250,
    "assigned": 980,
    "unassigned": 270,
    "status_breakdown": {...}
  },
  "campaigns": {
    "total": 15,
    "active": 8
  },
  "activity": {...},
  "members": [...]
}
```

### Team Members
```bash
# List members
GET /team/members?team_id=team_abc

# Add member
POST /team/members?team_id=team_abc
{
  "user_id": "user_999",
  "email": "john@company.com",
  "name": "John Smith",
  "role": "member"
}

# Remove member
DELETE /team/members/user_999?team_id=team_abc
```

---

## 🔧 MODEL ENHANCEMENTS

### Lead Model (leads_enriched)
```python
class LeadEnriched(BaseModel):
    # ... existing fields ...
    
    # Team collaboration (Agent 18)
    assigned_to: Optional[str] = None      # User ID
    last_touched_by: Optional[str] = None  # User ID
    team_id: Optional[str] = None          # Team ID
```

### Campaign Model
```python
class Campaign(BaseModel):
    # ... existing fields ...
    
    # Ownership & visibility (Agent 18)
    created_by: str                        # Required
    team_id: Optional[str] = None
    visibility: str = "personal"           # personal | team | org
```

---

## 📈 MONITORING

### Queue Health
```python
stats = queue.get_queue_stats()

# Alert on dead letter queue
if stats['dead_letter'] > 100:
    alert("High failure rate in send queue")
```

### Rate Limit Health
```python
rate_stats = throttle.get_rate_stats()

# Alert on approaching limits
if rate_stats['global']['last_hour'] > 4500:  # 90% of 5000
    alert("Approaching global rate limit")
```

### Activity Health
```python
recent = feed.get_recent_activity(hours=1)

# Alert on no activity
if len(recent) == 0:
    alert("No activity in the last hour")
```

---

## 🎯 COMMON PATTERNS

### High-Volume Campaign
```python
# 1. Enqueue all sends with priority
for recipient in campaign.recipients:
    queue.enqueue_send({
        "to": recipient.email,
        "subject": template.render_subject(recipient),
        "body_html": template.render_body(recipient),
        "campaign_id": campaign.id,
        "recipient_id": recipient.id
    }, priority="normal")

# 2. Worker processes in batches
while True:
    sends = queue.dequeue_sends(batch_size=100)
    
    for send_item in sends:
        # Check throttle
        if not throttle.check_mailbox_rate_limit(send_item.from_email):
            queue.retry_failed(send_item, "Rate limited", max_retries=5)
            continue
        
        # Send
        try:
            result = email_provider.send(send_item)
            throttle.record_send(
                campaign_id=send_item.campaign_id,
                mailbox_id=send_item.from_email
            )
            queue.mark_complete(send_item.send_id)
            
            # Update health
            throttle.update_delivery_health(
                mailbox_id=send_item.from_email,
                delivered=True
            )
        except Exception as e:
            queue.retry_failed(send_item, str(e))
```

### Team Lead Assignment
```python
# 1. Assign lead
response = requests.post(
    f"/team/leads/{lead_id}/assign",
    json={"assign_to": user_id}
)

# 2. Activity automatically logged
activities = feed.get_resource_activity("lead", lead_id)
# Shows: lead_assigned action with details

# 3. Dashboard reflects changes
dashboard = requests.get(f"/team/dashboard?team_id={team_id}")
# member_stats shows updated assigned_leads count
```

---

## 🚀 DEPLOYMENT CHECKLIST

- [ ] Redis installed and running
- [ ] MongoDB installed and running
- [ ] Environment variables set (MONGO_URI, REDIS_URL)
- [ ] Redis memory configured (maxmemory, maxmemory-policy)
- [ ] Celery workers configured (optional)
- [ ] Monitoring alerts configured
- [ ] Activity feed cleanup scheduled (90 days)
- [ ] Send queue dead letter review process

---

## 📦 FILES

### Core Modules
- `backend/campaigns/send_queue.py` (614 lines)
- `backend/campaigns/throttle_manager.py` (598 lines)
- `backend/activity/feed.py` (548 lines)
- `backend/activity/__init__.py` (14 lines)
- `backend/routers/team.py` (623 lines)

### Enhanced Models
- `backend/leads/models.py` (team collaboration fields)
- `backend/campaigns/models.py` (ownership/visibility fields)

### Documentation
- `AGENT18_COMPLETION_REPORT.md`
- `AGENT18_DELIVERABLES.md`
- `AGENT18_QUICKREF.md` (this file)

---

**Total Code**: 2,397 lines  
**Status**: ✅ COMPLETE  
**Agent**: Agent 18  
**Date**: January 28, 2026
