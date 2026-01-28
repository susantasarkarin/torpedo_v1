# Testing Checklist - AI Cold Outreach System

**System**: AI-Powered Cold Outreach Platform  
**Version**: 4.0  
**Last Updated**: January 28, 2026  
**Test Environment**: Development/Staging

---

## Pre-Testing Setup

### Installation & Environment

- [ ] **Install Dependencies**
  ```bash
  # Backend
  cd backend
  pip install -r requirements.txt
  
  # Frontend
  cd frontend
  npm install
  ```
  **Expected**: No errors, all packages installed  
  **Troubleshooting**: If pip fails, try `pip install --upgrade pip` first

- [ ] **Set Environment Variables**
  ```bash
  # Copy example env file
  cp backend/.env.example backend/.env
  
  # Required variables:
  # - DATABASE_URL
  # - OPENAI_API_KEY
  # - GMAIL_CREDENTIALS_PATH
  # - LINKEDIN_SESSION_COOKIE
  # - SECRET_KEY
  ```
  **Expected**: .env file created with all required variables  
  **Troubleshooting**: Check .env.example for all required variables

- [ ] **Run Database Migrations**
  ```bash
  cd backend
  python manage.py migrate
  ```
  **Expected**: All migrations applied successfully  
  **Troubleshooting**: If fails, check DATABASE_URL and ensure PostgreSQL is running

- [ ] **Create Superuser**
  ```bash
  python manage.py createsuperuser
  ```
  **Expected**: Admin user created  
  **Test Login**: http://localhost:8000/admin

- [ ] **Start Backend Server**
  ```bash
  cd backend
  python manage.py runserver 0.0.0.0:8000
  ```
  **Expected**: Server running on http://localhost:8000  
  **Test**: Visit http://localhost:8000/api/health

- [ ] **Start Frontend Dev Server**
  ```bash
  cd frontend
  npm run dev
  ```
  **Expected**: Server running on http://localhost:3000  
  **Test**: Visit http://localhost:3000

- [ ] **Verify Database Connection**
  ```bash
  python manage.py dbshell
  \dt  # List tables
  \q   # Quit
  ```
  **Expected**: All tables listed (leads, campaigns, sequences, etc.)

---

## Phase 1: Core Foundation

### 1.1 Data Models

#### Lead Model Testing

- [ ] **Test Lead Creation with Engagement Fields**
  ```bash
  # Via Django shell
  python manage.py shell
  
  from campaigns.models import Lead
  lead = Lead.objects.create(
      email="test@example.com",
      first_name="John",
      last_name="Doe",
      company="Acme Corp",
      engagement_score=0,
      last_engaged=None
  )
  print(f"Lead created: {lead.id}")
  ```
  **Expected**: Lead created with ID, engagement_score=0  
  **Verify**: Check admin panel at /admin/campaigns/lead/

- [ ] **Test Engagement Score Calculation**
  ```python
  # In Django shell
  lead.email_opened = 5
  lead.email_clicked = 2
  lead.replied = True
  lead.save()
  lead.calculate_engagement_score()
  print(f"Engagement score: {lead.engagement_score}")
  ```
  **Expected**: engagement_score > 0 (e.g., 75-85)  
  **Formula**: (opens×2 + clicks×5 + replies×20) / max_possible × 100

- [ ] **Test Lead Status Transitions**
  ```python
  # Test all status changes
  lead.status = 'new'
  lead.mark_as_contacted()  # Should set to 'contacted'
  lead.mark_as_engaged()    # Should set to 'engaged'
  lead.mark_as_qualified()  # Should set to 'qualified'
  ```
  **Expected**: Status changes correctly, timestamps updated

#### Campaign Model Testing

- [ ] **Test Campaign Creation with Multi-Channel**
  ```bash
  # Via API
  curl -X POST http://localhost:8000/api/campaigns/ \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Q1 SaaS Outreach",
      "channels": ["email", "linkedin"],
      "status": "draft"
    }'
  ```
  **Expected**: Campaign created, returns ID and channels array  
  **Verify**: GET /api/campaigns/{id}

- [ ] **Test A/B Testing Configuration**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/ab-test/setup \
    -H "Content-Type: application/json" \
    -d '{
      "variants": [
        {"name": "Variant A", "subject": "Quick question"},
        {"name": "Variant B", "subject": "Partnership opportunity"}
      ],
      "metric": "open_rate",
      "sample_size": 200
    }'
  ```
  **Expected**: A/B test configured, variant_id assigned to each variant  
  **Troubleshooting**: Ensure campaign has sufficient leads

### 1.2 Personalization Engine

- [ ] **Test Level 1 Personalization (Basic)**
  ```bash
  curl -X POST http://localhost:8000/api/personalization/process \
    -H "Content-Type: application/json" \
    -d '{
      "template": "Hi {{first_name}}, I work with {{company}} teams...",
      "lead_id": 1,
      "level": 1
    }'
  ```
  **Expected**: Returns "Hi John, I work with Acme Corp teams..."  
  **Tokens Tested**: {{first_name}}, {{company}}

- [ ] **Test Level 2 Personalization (Role-Based)**
  ```bash
  curl -X POST http://localhost:8000/api/personalization/process \
    -H "Content-Type: application/json" \
    -d '{
      "template": "As a {{job_title}}, you probably face {{role_pain_point}}...",
      "lead_id": 1,
      "level": 2
    }'
  ```
  **Expected**: Pain points specific to job role inserted  
  **Example**: "As a VP Sales, you probably face pipeline visibility challenges..."

- [ ] **Test Level 3 Personalization (AI-Generated)**
  ```bash
  curl -X POST http://localhost:8000/api/personalization/process \
    -H "Content-Type: application/json" \
    -d '{
      "template": "{{ai_intro}}",
      "lead_id": 1,
      "level": 3,
      "context": "Recent funding round"
    }'
  ```
  **Expected**: AI-generated intro mentioning recent funding  
  **Troubleshooting**: Requires OpenAI API key in .env

- [ ] **Test All 23 Token Types**
  ```python
  # In Django shell
  from campaigns.personalization import PersonalizationEngine
  
  tokens = [
      '{{first_name}}', '{{last_name}}', '{{full_name}}',
      '{{company}}', '{{job_title}}', '{{industry}}',
      '{{city}}', '{{state}}', '{{country}}',
      '{{website}}', '{{linkedin_url}}', '{{phone}}',
      '{{company_size}}', '{{revenue}}', '{{tech_stack}}',
      '{{pain_point}}', '{{value_prop}}', '{{case_study}}',
      '{{sender_name}}', '{{sender_title}}', '{{sender_company}}',
      '{{meeting_link}}', '{{unsubscribe_link}}'
  ]
  
  engine = PersonalizationEngine()
  lead = Lead.objects.get(id=1)
  
  for token in tokens:
      result = engine.process_token(token, lead)
      print(f"{token}: {result}")
  ```
  **Expected**: All tokens replaced with actual values or defaults  
  **Verify**: No {{...}} remain in output

- [ ] **Test Fallback Defaults**
  ```python
  # Test with lead missing data
  incomplete_lead = Lead.objects.create(
      email="incomplete@example.com"
      # No name, company, etc.
  )
  
  template = "Hi {{first_name}}, I work with {{company}}..."
  result = engine.personalize(template, incomplete_lead, level=1)
  print(result)
  ```
  **Expected**: "Hi there, I work with your company..."  
  **Defaults**: first_name → "there", company → "your company"

### 1.3 Rules Engine

- [ ] **Test Bounce → Stop Sequence Rule**
  ```python
  # Simulate bounce
  from campaigns.models import EmailActivity, Lead
  from campaigns.rules import RulesEngine
  
  lead = Lead.objects.get(id=1)
  EmailActivity.objects.create(
      lead=lead,
      campaign_id=1,
      activity_type='bounced',
      bounce_type='hard'
  )
  
  engine = RulesEngine()
  engine.process_activity(lead, 'bounced')
  
  lead.refresh_from_db()
  print(f"Status: {lead.status}")
  print(f"In sequence: {lead.in_active_sequence}")
  ```
  **Expected**: status='bounced', in_active_sequence=False  
  **Verify**: No more emails queued for this lead

- [ ] **Test Reply → Engaged Rule**
  ```python
  lead = Lead.objects.get(id=2)
  EmailActivity.objects.create(
      lead=lead,
      campaign_id=1,
      activity_type='replied',
      reply_text='Yes, I'm interested'
  )
  
  engine.process_activity(lead, 'replied')
  lead.refresh_from_db()
  
  print(f"Status: {lead.status}")  # Should be 'engaged'
  print(f"Engagement score: {lead.engagement_score}")  # Should increase
  ```
  **Expected**: status='engaged', engagement_score increased by 20 points

- [ ] **Test 2+ Opens → Warm Lead Rule**
  ```python
  lead = Lead.objects.get(id=3)
  
  # Simulate 2 opens
  EmailActivity.objects.create(lead=lead, campaign_id=1, activity_type='opened')
  EmailActivity.objects.create(lead=lead, campaign_id=1, activity_type='opened')
  
  engine.evaluate_lead_temperature(lead)
  lead.refresh_from_db()
  
  print(f"Temperature: {lead.temperature}")  # Should be 'warm'
  ```
  **Expected**: temperature='warm', tag added automatically

- [ ] **Test No Opens After 3 Emails → Downgrade Rule**
  ```python
  lead = Lead.objects.get(id=4)
  
  # Simulate 3 sends, 0 opens
  for i in range(3):
      EmailActivity.objects.create(
          lead=lead,
          campaign_id=1,
          activity_type='sent',
          sequence_step=i+1
      )
  
  engine.evaluate_engagement_drop(lead)
  lead.refresh_from_db()
  
  print(f"Engagement level: {lead.engagement_level}")
  ```
  **Expected**: engagement_level downgraded, follow-up frequency reduced

- [ ] **Test Unsubscribe → Suppression Rule**
  ```python
  lead = Lead.objects.get(id=5)
  EmailActivity.objects.create(
      lead=lead,
      campaign_id=1,
      activity_type='unsubscribed'
  )
  
  engine.process_activity(lead, 'unsubscribed')
  lead.refresh_from_db()
  
  print(f"Status: {lead.status}")  # 'unsubscribed'
  print(f"In suppression list: {lead.is_suppressed}")
  
  # Try to send email - should fail
  from campaigns.email_sender import EmailSender
  sender = EmailSender()
  result = sender.can_send_to_lead(lead)
  print(f"Can send: {result}")  # Should be False
  ```
  **Expected**: is_suppressed=True, all sends blocked

### 1.4 A/B Testing

- [ ] **Create A/B Test with 2 Variants**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/ab-test/setup \
    -H "Content-Type: application/json" \
    -d '{
      "test_name": "Subject Line Test",
      "variants": [
        {
          "name": "Short & Direct",
          "subject": "Quick question",
          "body": "Template A body..."
        },
        {
          "name": "Value-Focused",
          "subject": "Increase your revenue by 30%",
          "body": "Template B body..."
        }
      ],
      "metric": "open_rate",
      "sample_size": 200,
      "confidence_level": 0.95
    }'
  ```
  **Expected**: Test created with 2 variants, IDs returned  
  **Verify**: GET /api/campaigns/1/ab-test

- [ ] **Verify Variant Assignment (50/50 Split)**
  ```python
  # In Django shell
  from campaigns.models import Campaign, Lead, ABTestVariant
  
  campaign = Campaign.objects.get(id=1)
  variants = campaign.ab_test_variants.all()
  
  # Check distribution
  for variant in variants:
      count = Lead.objects.filter(
          ab_test_variant=variant,
          campaign=campaign
      ).count()
      print(f"{variant.name}: {count} leads")
  
  # Should be approximately 50/50
  ```
  **Expected**: Each variant ~100 leads (±10%)  
  **Troubleshooting**: Re-run assignment if distribution off

- [ ] **Generate Test Data (100 Sends Each)**
  ```python
  # Simulate email sends and opens
  from campaigns.models import EmailActivity
  import random
  
  for variant in variants:
      leads = Lead.objects.filter(ab_test_variant=variant)[:100]
      
      for lead in leads:
          # Send
          EmailActivity.objects.create(
              lead=lead,
              campaign=campaign,
              activity_type='sent'
          )
          
          # Random opens (variant B performs better)
          open_rate = 0.25 if variant.name == "Short & Direct" else 0.35
          if random.random() < open_rate:
              EmailActivity.objects.create(
                  lead=lead,
                  campaign=campaign,
                  activity_type='opened'
              )
  ```
  **Expected**: 200 total sends, variant B with higher open rate

- [ ] **Check Statistical Significance Calculation**
  ```bash
  curl http://localhost:8000/api/campaigns/1/ab-test/results
  ```
  **Expected Response**:
  ```json
  {
    "test_name": "Subject Line Test",
    "variants": [
      {
        "name": "Short & Direct",
        "sends": 100,
        "opens": 25,
        "open_rate": 0.25
      },
      {
        "name": "Value-Focused",
        "sends": 100,
        "opens": 35,
        "open_rate": 0.35
      }
    ],
    "winner": "Value-Focused",
    "confidence": 0.95,
    "p_value": 0.042,
    "is_significant": true
  }
  ```
  **Verify**: p_value < 0.05, is_significant = true

- [ ] **Test Auto-Winner Selection**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/ab-test/finalize
  ```
  **Expected**: Winner variant used for remaining leads  
  **Verify**: Check campaign.winning_variant_id is set

### 1.5 Re-engagement

- [ ] **Identify Dormant Leads (21+ Days Inactive)**
  ```bash
  curl http://localhost:8000/api/leads/dormant?days=21
  ```
  **Expected**: List of leads with last_engaged > 21 days ago  
  **Verify**: Check last_engaged field for each lead

- [ ] **Create Soft-Drip Campaign**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/reengagement \
    -H "Content-Type: application/json" \
    -d '{
      "campaign_type": "soft_drip",
      "lead_ids": [1, 2, 3],
      "sequence_steps": [
        {
          "step": 1,
          "delay_days": 0,
          "subject": "Just checking in...",
          "body": "Hey {{first_name}}, wanted to follow up..."
        },
        {
          "step": 2,
          "delay_days": 7,
          "subject": "One more thing",
          "body": "Quick update that might interest you..."
        }
      ]
    }'
  ```
  **Expected**: Campaign created, leads enrolled  
  **Verify**: Check leads have campaign_id assigned

- [ ] **Create Trigger-Based Campaign**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/reengagement \
    -H "Content-Type: application/json" \
    -d '{
      "campaign_type": "trigger_based",
      "trigger": "company_news",
      "lead_segment": "dormant_high_value",
      "template": "Saw your company {{news_event}}..."
    }'
  ```
  **Expected**: Campaign created with trigger condition  
  **Verify**: Trigger fires when news event detected

- [ ] **Create Reset Outreach Campaign**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/reengagement \
    -H "Content-Type: application/json" \
    -d '{
      "campaign_type": "reset_outreach",
      "lead_ids": [4, 5, 6],
      "reset_engagement_history": true,
      "new_angle": "Different product offering"
    }'
  ```
  **Expected**: Leads reset, engagement_score=0, new sequence starts  
  **Verify**: Check lead.engagement_history is cleared

### 1.6 LinkedIn Automation

- [ ] **Start LinkedIn Session Login**
  ```bash
  curl -X POST http://localhost:8000/api/linkedin/session/login \
    -H "Content-Type: application/json" \
    -d '{
      "email": "your@email.com",
      "password": "your_password"
    }'
  ```
  **Expected**: Session cookie returned, expires in 30 days  
  **Security**: Store session_cookie securely in .env  
  **Troubleshooting**: If 2FA enabled, need manual login first

- [ ] **Send Connection Request (With Note)**
  ```bash
  curl -X POST http://localhost:8000/api/linkedin/connect \
    -H "Content-Type: application/json" \
    -d '{
      "profile_url": "https://linkedin.com/in/john-doe",
      "note": "Hi John, saw your post about AI. Would love to connect!"
    }'
  ```
  **Expected**: 
  ```json
  {
    "status": "success",
    "action_id": "abc123",
    "daily_limit_remaining": 99
  }
  ```
  **Rate Limit**: Max 100/day

- [ ] **Check Connection Status**
  ```bash
  curl http://localhost:8000/api/linkedin/connection/status?profile_url=https://linkedin.com/in/john-doe
  ```
  **Expected**: 
  ```json
  {
    "status": "pending|connected|not_connected",
    "connected_at": "2026-01-28T10:30:00Z"
  }
  ```

- [ ] **Send Message to 1st-Degree Connection**
  ```bash
  curl -X POST http://localhost:8000/api/linkedin/message \
    -H "Content-Type: application/json" \
    -d '{
      "profile_url": "https://linkedin.com/in/john-doe",
      "message": "Thanks for connecting! Quick question about..."
    }'
  ```
  **Expected**: Message sent, daily limit decremented  
  **Prerequisite**: Must be 1st-degree connection

- [ ] **Verify Daily Limit Tracking**
  ```bash
  curl http://localhost:8000/api/linkedin/stats
  ```
  **Expected**:
  ```json
  {
    "date": "2026-01-28",
    "connections_sent": 15,
    "connections_limit": 100,
    "messages_sent": 8,
    "messages_limit": 50,
    "profile_views": 42,
    "profile_views_limit": 100
  }
  ```
  **Verify**: Limits enforced, prevents over-sending

### 1.7 Deliverability

- [ ] **Check Domain Health (SPF, DKIM, DMARC)**
  ```bash
  curl http://localhost:8000/api/deliverability/domains/yourdomain.com/health
  ```
  **Expected**:
  ```json
  {
    "domain": "yourdomain.com",
    "spf": {
      "status": "pass",
      "record": "v=spf1 include:_spf.google.com ~all"
    },
    "dkim": {
      "status": "pass",
      "selector": "google"
    },
    "dmarc": {
      "status": "pass",
      "policy": "quarantine",
      "record": "v=DMARC1; p=quarantine; rua=mailto:..."
    },
    "mx_records": ["mx1.google.com", "mx2.google.com"],
    "blacklist_status": "clean"
  }
  ```
  **Troubleshooting**: If any fail, update DNS records

- [ ] **View Gmail Pool Usage**
  ```bash
  curl http://localhost:8000/api/deliverability/gmail/pool-status
  ```
  **Expected**:
  ```json
  {
    "accounts": [
      {
        "email": "sender1@yourdomain.com",
        "sent_today": 487,
        "limit": 2000,
        "health_score": 98,
        "status": "active"
      },
      {
        "email": "sender2@yourdomain.com",
        "sent_today": 1823,
        "limit": 2000,
        "health_score": 95,
        "status": "active"
      }
    ],
    "total_sent_today": 2310,
    "total_capacity": 4000
  }
  ```

- [ ] **Verify 2000/Day Limit Tracking**
  ```python
  # Test limit enforcement
  from campaigns.models import GmailAccount, EmailActivity
  
  account = GmailAccount.objects.first()
  
  # Get today's sends
  today_sends = EmailActivity.objects.filter(
      gmail_account=account,
      sent_at__date=timezone.now().date()
  ).count()
  
  print(f"Sent today: {today_sends}")
  print(f"Can send: {account.can_send_today()}")
  print(f"Remaining: {2000 - today_sends}")
  ```
  **Expected**: can_send_today() returns False if limit reached

- [ ] **Test Reputation Metrics**
  ```bash
  curl http://localhost:8000/api/deliverability/reputation/sender1@yourdomain.com
  ```
  **Expected**:
  ```json
  {
    "email": "sender1@yourdomain.com",
    "reputation_score": 94,
    "bounce_rate": 0.02,
    "spam_complaint_rate": 0.001,
    "open_rate": 0.32,
    "engagement_rate": 0.15,
    "status": "excellent"
  }
  ```
  **Thresholds**: bounce_rate < 5%, spam_rate < 0.1%

### 1.8 Multi-Channel Sequences

- [ ] **Create Email-Only Sequence**
  ```bash
  curl -X POST http://localhost:8000/api/sequences/ \
    -H "Content-Type: application/json" \
    -d '{
      "name": "SaaS Outreach V1",
      "channels": ["email"],
      "steps": [
        {
          "step": 1,
          "channel": "email",
          "delay_days": 0,
          "subject": "Quick question",
          "body": "Hi {{first_name}}..."
        },
        {
          "step": 2,
          "channel": "email",
          "delay_days": 3,
          "subject": "Following up",
          "body": "Just wanted to circle back..."
        },
        {
          "step": 3,
          "channel": "email",
          "delay_days": 7,
          "subject": "Last attempt",
          "body": "This will be my last email..."
        }
      ]
    }'
  ```
  **Expected**: Sequence created with 3 email steps

- [ ] **Create LinkedIn-Only Sequence**
  ```bash
  curl -X POST http://localhost:8000/api/sequences/ \
    -H "Content-Type: application/json" \
    -d '{
      "name": "LinkedIn Outreach",
      "channels": ["linkedin"],
      "steps": [
        {
          "step": 1,
          "channel": "linkedin",
          "action": "connect",
          "note": "Hi {{first_name}}, I work in {{industry}}...",
          "delay_days": 0
        },
        {
          "step": 2,
          "channel": "linkedin",
          "action": "message",
          "condition": "connection_accepted",
          "message": "Thanks for connecting!",
          "delay_days": 2
        }
      ]
    }'
  ```
  **Expected**: Sequence created, step 2 conditional on acceptance

- [ ] **Create Mixed Email + LinkedIn Sequence**
  ```bash
  curl -X POST http://localhost:8000/api/sequences/ \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Multi-Channel Outreach",
      "channels": ["email", "linkedin"],
      "steps": [
        {
          "step": 1,
          "channel": "email",
          "subject": "Quick intro",
          "delay_days": 0
        },
        {
          "step": 2,
          "channel": "linkedin",
          "action": "connect",
          "delay_days": 2
        },
        {
          "step": 3,
          "channel": "email",
          "subject": "Also on LinkedIn",
          "condition": "linkedin_not_accepted",
          "delay_days": 5
        },
        {
          "step": 4,
          "channel": "linkedin",
          "action": "message",
          "condition": "linkedin_accepted",
          "delay_days": 5
        }
      ]
    }'
  ```
  **Expected**: Sequence with branching logic based on LinkedIn response

- [ ] **Test Conditional Branching**
  ```python
  # Simulate lead going through sequence
  from campaigns.models import Lead, Sequence, SequenceStep
  from campaigns.sequence_engine import SequenceEngine
  
  lead = Lead.objects.get(id=1)
  sequence = Sequence.objects.get(name="Multi-Channel Outreach")
  
  engine = SequenceEngine()
  
  # Start sequence
  engine.enroll_lead(lead, sequence)
  
  # Step 1: Send email
  engine.execute_step(lead, step=1)
  
  # Step 2: LinkedIn connect
  engine.execute_step(lead, step=2)
  
  # Simulate: LinkedIn NOT accepted
  lead.linkedin_connection_status = 'pending'
  lead.save()
  
  # Step 3: Should execute (email fallback)
  next_step = engine.get_next_step(lead)
  print(f"Next step: {next_step.step} - {next_step.channel}")
  ```
  **Expected**: Step 3 (email) executes because LinkedIn not accepted

---

## Phase 2: Intelligence & Optimization

### 2.1 Send Time Optimization

- [ ] **Analyze Historical Engagement by Time**
  ```bash
  curl http://localhost:8000/api/analytics/send-time-analysis?campaign_id=1
  ```
  **Expected**:
  ```json
  {
    "analysis_period": "Last 90 days",
    "total_sends": 15000,
    "by_day_of_week": {
      "Monday": {"sends": 2500, "open_rate": 0.28},
      "Tuesday": {"sends": 2800, "open_rate": 0.32},
      "Wednesday": {"sends": 2700, "open_rate": 0.31},
      "Thursday": {"sends": 2600, "open_rate": 0.29},
      "Friday": {"sends": 2400, "open_rate": 0.25}
    },
    "by_hour": {
      "08:00": {"sends": 800, "open_rate": 0.22},
      "09:00": {"sends": 1200, "open_rate": 0.29},
      "10:00": {"sends": 1500, "open_rate": 0.33},
      "11:00": {"sends": 1400, "open_rate": 0.31}
    },
    "best_time": {
      "day": "Tuesday",
      "hour": "10:00",
      "open_rate": 0.35
    }
  }
  ```

- [ ] **Predict Optimal Send Time for Lead**
  ```bash
  curl http://localhost:8000/api/analytics/optimal-send-time?lead_id=1
  ```
  **Expected**:
  ```json
  {
    "lead_id": 1,
    "optimal_time": "2026-01-29T10:00:00Z",
    "confidence": 0.87,
    "factors": {
      "timezone": "America/New_York",
      "past_opens": "Typically opens between 9-11 AM",
      "industry_benchmark": "Tech sector: 10 AM peak",
      "job_role": "Executives: Morning preference"
    }
  }
  ```

- [ ] **Optimize Campaign Schedule**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/optimize-schedule
  ```
  **Expected**: Campaign send times adjusted per lead  
  **Verify**: Check queued_emails table for scheduled_send_at times

### 2.2 Reply Intelligence

- [ ] **Classify Reply Sentiment**
  ```bash
  curl -X POST http://localhost:8000/api/replies/classify \
    -H "Content-Type: application/json" \
    -d '{
      "reply_text": "Thanks for reaching out! I would love to learn more about your solution. Can we schedule a call next week?",
      "lead_id": 1
    }'
  ```
  **Expected**:
  ```json
  {
    "sentiment": "positive",
    "confidence": 0.94,
    "intent": "meeting_request",
    "urgency": "high",
    "action_required": true
  }
  ```

- [ ] **Detect Reply Intent**
  ```bash
  # Test different intents
  
  # Intent: Objection
  curl -X POST http://localhost:8000/api/replies/classify \
    -d '{"reply_text": "We already use a competitor. Not interested.", "lead_id": 2}'
  # Expected: intent="objection", sentiment="negative"
  
  # Intent: Out of Office
  curl -X POST http://localhost:8000/api/replies/classify \
    -d '{"reply_text": "I am out of office until Feb 5. Will respond when back.", "lead_id": 3}'
  # Expected: intent="out_of_office", action_required=false
  
  # Intent: Request More Info
  curl -X POST http://localhost:8000/api/replies/classify \
    -d '{"reply_text": "Can you send me more details about pricing?", "lead_id": 4}'
  # Expected: intent="request_info", action_required=true
  
  # Intent: Not Decision Maker
  curl -X POST http://localhost:8000/api/replies/classify \
    -d '{"reply_text": "Please contact our VP of Sales, jane@company.com", "lead_id": 5}'
  # Expected: intent="forward_to_colleague", new_contact_suggested=true
  ```

- [ ] **Handle Objection with Generated Response**
  ```bash
  curl -X POST http://localhost:8000/api/replies/handle-objection \
    -H "Content-Type: application/json" \
    -d '{
      "objection": "We already use HubSpot for this.",
      "lead_id": 2,
      "context": "Competitor mention"
    }'
  ```
  **Expected**:
  ```json
  {
    "suggested_response": "I completely understand you're using HubSpot. Many of our customers actually use us alongside HubSpot because we specialize in [unique value]. Would you be open to a 15-minute call to see if we could complement your existing setup?",
    "objection_type": "competitor",
    "recommended_action": "send_comparison_doc",
    "auto_send": false
  }
  ```

- [ ] **Draft Auto-Response**
  ```bash
  curl -X POST http://localhost:8000/api/replies/draft-response \
    -H "Content-Type: application/json" \
    -d '{
      "reply_text": "Sounds interesting. Can you send me a case study?",
      "lead_id": 6
    }'
  ```
  **Expected**:
  ```json
  {
    "draft": "Absolutely! I'll send over a case study of how we helped [similar company] achieve [result]. I've attached it to this email. Would you be available for a quick 15-minute call next week to discuss how we could achieve similar results for [lead's company]?",
    "attachments": ["case_study_company_xyz.pdf"],
    "suggested_subject": "Re: Case Study - [Similar Company] Success Story",
    "confidence": 0.89
  }
  ```
  **Manual Review**: Check draft before sending

### 2.3 Template Performance

- [ ] **Track Template Metrics**
  ```bash
  curl http://localhost:8000/api/templates/1/metrics
  ```
  **Expected**:
  ```json
  {
    "template_id": 1,
    "name": "Cold Intro V1",
    "total_sends": 1500,
    "open_rate": 0.32,
    "click_rate": 0.08,
    "reply_rate": 0.05,
    "meeting_rate": 0.02,
    "avg_time_to_reply": "2.3 days",
    "best_performing_segment": "Tech companies, 50-200 employees"
  }
  ```

- [ ] **Get Top Templates by Segment**
  ```bash
  curl http://localhost:8000/api/templates/top?segment=saas&metric=reply_rate&limit=5
  ```
  **Expected**:
  ```json
  {
    "segment": "saas",
    "metric": "reply_rate",
    "templates": [
      {
        "id": 5,
        "name": "Problem-Agitate-Solution",
        "reply_rate": 0.09,
        "sends": 800
      },
      {
        "id": 12,
        "name": "Social Proof Heavy",
        "reply_rate": 0.07,
        "sends": 1200
      }
    ]
  }
  ```

- [ ] **Get Template Recommendations**
  ```bash
  curl http://localhost:8000/api/templates/recommend?lead_id=1
  ```
  **Expected**:
  ```json
  {
    "lead_id": 1,
    "recommendations": [
      {
        "template_id": 5,
        "name": "Problem-Agitate-Solution",
        "predicted_reply_rate": 0.08,
        "reason": "High performance with similar leads (VP Sales, SaaS)"
      },
      {
        "template_id": 8,
        "name": "Case Study Intro",
        "predicted_reply_rate": 0.07,
        "reason": "Lead has high engagement score"
      }
    ]
  }
  ```

### 2.4 Sequence Intelligence

- [ ] **Select Optimal Sequence for Lead**
  ```bash
  curl http://localhost:8000/api/sequences/recommend?lead_id=1
  ```
  **Expected**:
  ```json
  {
    "lead_id": 1,
    "recommended_sequence": {
      "id": 3,
      "name": "Enterprise SaaS - Executive",
      "predicted_reply_rate": 0.12,
      "predicted_meeting_rate": 0.06,
      "reasoning": [
        "Lead is VP-level at 500+ person company",
        "Industry: SaaS (high performing segment)",
        "This sequence has 15% higher reply rate for similar leads"
      ]
    }
  }
  ```

- [ ] **Analyze Step Performance**
  ```bash
  curl http://localhost:8000/api/sequences/3/step-analysis
  ```
  **Expected**:
  ```json
  {
    "sequence_id": 3,
    "steps": [
      {
        "step": 1,
        "sends": 1000,
        "opens": 320,
        "clicks": 80,
        "replies": 50,
        "drop_off_rate": 0.68
      },
      {
        "step": 2,
        "sends": 680,
        "opens": 190,
        "clicks": 45,
        "replies": 30,
        "drop_off_rate": 0.72
      },
      {
        "step": 3,
        "sends": 490,
        "opens": 120,
        "clicks": 25,
        "replies": 20
      }
    ],
    "insights": {
      "weakest_step": 1,
      "suggestion": "Step 1 has high drop-off. Consider stronger hook or value prop."
    }
  }
  ```

- [ ] **Get Improvement Recommendations**
  ```bash
  curl http://localhost:8000/api/sequences/3/recommendations
  ```
  **Expected**:
  ```json
  {
    "sequence_id": 3,
    "current_performance": {
      "reply_rate": 0.08,
      "meeting_rate": 0.04
    },
    "recommendations": [
      {
        "type": "timing",
        "suggestion": "Increase delay between step 1 and 2 from 3 to 5 days",
        "expected_impact": "+12% reply rate",
        "confidence": 0.78
      },
      {
        "type": "content",
        "suggestion": "Add social proof in step 1 subject line",
        "expected_impact": "+8% open rate",
        "confidence": 0.82
      },
      {
        "type": "channel",
        "suggestion": "Add LinkedIn touch after step 2 for non-openers",
        "expected_impact": "+15% engagement",
        "confidence": 0.71
      }
    ]
  }
  ```

---

## Phase 3: Scale & Enterprise

### 3.1 Send Queue

- [ ] **Enqueue Emails with Different Priorities**
  ```python
  from campaigns.models import QueuedEmail, Lead, Campaign
  from django.utils import timezone
  
  campaign = Campaign.objects.get(id=1)
  
  # Priority 1: Hot leads
  hot_leads = Lead.objects.filter(temperature='hot', campaign=campaign)[:10]
  for lead in hot_leads:
      QueuedEmail.objects.create(
          lead=lead,
          campaign=campaign,
          subject="Quick follow-up",
          body="...",
          priority=1,
          scheduled_send_at=timezone.now()
      )
  
  # Priority 3: Cold leads
  cold_leads = Lead.objects.filter(temperature='cold', campaign=campaign)[:10]
  for lead in cold_leads:
      QueuedEmail.objects.create(
          lead=lead,
          campaign=campaign,
          subject="Initial outreach",
          body="...",
          priority=3,
          scheduled_send_at=timezone.now() + timezone.timedelta(hours=1)
      )
  
  print("Queued 20 emails with different priorities")
  ```
  **Expected**: High priority emails sent first

- [ ] **Dequeue Batch of Emails**
  ```bash
  curl -X POST http://localhost:8000/api/queue/process?batch_size=50
  ```
  **Expected**:
  ```json
  {
    "processed": 50,
    "successful": 48,
    "failed": 2,
    "errors": [
      {"email_id": 123, "error": "Rate limit reached"},
      {"email_id": 124, "error": "Invalid email address"}
    ]
  }
  ```

- [ ] **Test Retry Mechanism**
  ```python
  # Simulate failed send
  from campaigns.models import QueuedEmail
  
  email = QueuedEmail.objects.filter(status='failed').first()
  print(f"Retry count: {email.retry_count}")
  print(f"Max retries: {email.max_retries}")
  
  # Manually retry
  from campaigns.queue_processor import QueueProcessor
  processor = QueueProcessor()
  result = processor.retry_email(email.id)
  
  print(f"Retry result: {result}")
  ```
  **Expected**: Email retried up to 3 times, then moved to DLQ

- [ ] **Verify Dead Letter Queue**
  ```bash
  curl http://localhost:8000/api/queue/dead-letter
  ```
  **Expected**:
  ```json
  {
    "total_dlq": 5,
    "emails": [
      {
        "id": 789,
        "lead_email": "bounced@example.com",
        "failure_reason": "Hard bounce",
        "retry_count": 3,
        "added_to_dlq_at": "2026-01-28T14:30:00Z"
      }
    ]
  }
  ```
  **Action**: Review and resolve DLQ items

### 3.2 Team Features

- [ ] **Assign Lead to Team Member**
  ```bash
  curl -X POST http://localhost:8000/api/leads/1/assign \
    -H "Content-Type: application/json" \
    -d '{
      "user_id": 5,
      "reason": "Lead replied - needs sales follow-up"
    }'
  ```
  **Expected**:
  ```json
  {
    "lead_id": 1,
    "assigned_to": {
      "id": 5,
      "name": "Sarah Johnson",
      "role": "Sales Rep"
    },
    "assigned_at": "2026-01-28T15:00:00Z"
  }
  ```
  **Verify**: Lead appears in Sarah's dashboard

- [ ] **View Team Activity Feed**
  ```bash
  curl http://localhost:8000/api/team/activity?limit=20
  ```
  **Expected**:
  ```json
  {
    "activities": [
      {
        "timestamp": "2026-01-28T15:00:00Z",
        "user": "Sarah Johnson",
        "action": "lead_assigned",
        "details": "Lead #1 (John Doe) assigned"
      },
      {
        "timestamp": "2026-01-28T14:45:00Z",
        "user": "Mike Chen",
        "action": "campaign_created",
        "details": "Created campaign: Q1 Enterprise Outreach"
      },
      {
        "timestamp": "2026-01-28T14:30:00Z",
        "user": "System",
        "action": "sequence_completed",
        "details": "50 leads completed sequence: SaaS V2"
      }
    ]
  }
  ```

- [ ] **View Team Dashboard**
  ```bash
  curl http://localhost:8000/api/team/dashboard
  ```
  **Expected**:
  ```json
  {
    "team_stats": {
      "total_leads": 5000,
      "active_campaigns": 12,
      "emails_sent_today": 1243,
      "replies_today": 38,
      "meetings_booked_today": 7
    },
    "leaderboard": [
      {
        "user": "Sarah Johnson",
        "replies": 45,
        "meetings": 12,
        "reply_rate": 0.09
      },
      {
        "user": "Mike Chen",
        "replies": 38,
        "meetings": 10,
        "reply_rate": 0.08
      }
    ],
    "team_capacity": {
      "gmail_accounts": 5,
      "remaining_sends_today": 7690,
      "linkedin_actions_remaining": 425
    }
  }
  ```

### 3.3 Advanced Analytics

- [ ] **Build Custom Report**
  ```bash
  curl -X POST http://localhost:8000/api/analytics/custom-report \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Q1 Pipeline Report",
      "date_range": {
        "start": "2026-01-01",
        "end": "2026-03-31"
      },
      "metrics": [
        "total_leads",
        "total_sends",
        "open_rate",
        "reply_rate",
        "meeting_rate",
        "pipeline_value"
      ],
      "dimensions": [
        "industry",
        "company_size",
        "campaign_name"
      ],
      "filters": {
        "lead_status": ["engaged", "qualified"],
        "campaign_type": "cold_outreach"
      }
    }'
  ```
  **Expected**: Report ID returned, can be fetched later

- [ ] **Create Cohort**
  ```bash
  curl -X POST http://localhost:8000/api/analytics/cohorts \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Jan 2026 Signups",
      "criteria": {
        "created_at": {
          "start": "2026-01-01",
          "end": "2026-01-31"
        },
        "source": "cold_outreach",
        "industry": "saas"
      }
    }'
  ```
  **Expected**: Cohort created with 234 leads

- [ ] **Compare Cohorts**
  ```bash
  curl http://localhost:8000/api/analytics/cohorts/compare?cohort_ids=1,2
  ```
  **Expected**:
  ```json
  {
    "cohorts": [
      {
        "id": 1,
        "name": "Jan 2026 Signups",
        "size": 234,
        "reply_rate": 0.08,
        "meeting_rate": 0.04,
        "avg_time_to_reply": "3.2 days"
      },
      {
        "id": 2,
        "name": "Dec 2025 Signups",
        "size": 189,
        "reply_rate": 0.06,
        "meeting_rate": 0.03,
        "avg_time_to_reply": "4.1 days"
      }
    ],
    "insights": {
      "reply_rate_change": "+33%",
      "best_cohort": "Jan 2026 Signups"
    }
  }
  ```

- [ ] **Analyze Funnel**
  ```bash
  curl http://localhost:8000/api/analytics/funnel?campaign_id=1
  ```
  **Expected**:
  ```json
  {
    "campaign_id": 1,
    "funnel_stages": [
      {
        "stage": "Sent",
        "count": 1000,
        "percentage": 100,
        "drop_off": 0
      },
      {
        "stage": "Opened",
        "count": 320,
        "percentage": 32,
        "drop_off": 68
      },
      {
        "stage": "Clicked",
        "count": 85,
        "percentage": 8.5,
        "drop_off": 23.5
      },
      {
        "stage": "Replied",
        "count": 52,
        "percentage": 5.2,
        "drop_off": 3.3
      },
      {
        "stage": "Meeting Booked",
        "count": 18,
        "percentage": 1.8,
        "drop_off": 3.4
      }
    ],
    "insights": {
      "biggest_drop": "Sent → Opened (68%)",
      "suggestion": "Improve subject lines to increase open rate"
    }
  }
  ```

- [ ] **Export Report (PDF, Excel)**
  ```bash
  # Export as PDF
  curl -X POST http://localhost:8000/api/analytics/reports/1/export?format=pdf \
    -o report.pdf
  
  # Export as Excel
  curl -X POST http://localhost:8000/api/analytics/reports/1/export?format=xlsx \
    -o report.xlsx
  ```
  **Expected**: Files downloaded successfully  
  **Verify**: Open files to check formatting

---

## Phase 4: AI Autonomy

### 4.1 Campaign Autopilot

- [ ] **Auto-Optimize Campaign**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/autopilot/enable \
    -H "Content-Type: application/json" \
    -d '{
      "optimization_goals": ["maximize_reply_rate", "minimize_unsubscribes"],
      "allowed_changes": [
        "send_times",
        "subject_lines",
        "follow_up_timing",
        "segmentation"
      ],
      "confidence_threshold": 0.80
    }'
  ```
  **Expected**:
  ```json
  {
    "autopilot_enabled": true,
    "campaign_id": 1,
    "optimization_schedule": "Daily at 2 AM UTC",
    "notification_email": "team@company.com"
  }
  ```

- [ ] **Pause Underperforming Campaign**
  ```python
  # Simulate autopilot detecting poor performance
  from campaigns.autopilot import AutopilotEngine
  
  engine = AutopilotEngine()
  
  # Check campaign performance
  analysis = engine.analyze_campaign(campaign_id=1)
  print(f"Performance score: {analysis['score']}")
  print(f"Recommendation: {analysis['recommendation']}")
  
  # If score < threshold, autopilot pauses
  if analysis['score'] < 50:
      result = engine.pause_campaign(campaign_id=1, reason="Low performance")
      print(f"Campaign paused: {result}")
  ```
  **Expected**: Campaign auto-paused if reply_rate < 2% and unsubscribe_rate > 1%

- [ ] **Review Improvement Suggestions**
  ```bash
  curl http://localhost:8000/api/campaigns/1/autopilot/suggestions
  ```
  **Expected**:
  ```json
  {
    "campaign_id": 1,
    "suggestions": [
      {
        "type": "subject_line",
        "current": "Quick question",
        "suggested": "{{company}} + {{your_company}} partnership?",
        "expected_improvement": "+15% open rate",
        "confidence": 0.84,
        "status": "pending_approval"
      },
      {
        "type": "timing",
        "current": "Send at 9 AM for all leads",
        "suggested": "Personalized send times per lead timezone",
        "expected_improvement": "+8% open rate",
        "confidence": 0.91,
        "status": "auto_applied"
      },
      {
        "type": "segmentation",
        "current": "Single sequence for all",
        "suggested": "Split into 3 segments: Enterprise, Mid-Market, SMB",
        "expected_improvement": "+12% reply rate",
        "confidence": 0.78,
        "status": "pending_approval"
      }
    ]
  }
  ```

### 4.2 Predictive Models

- [ ] **Predict Reply Probability for Leads**
  ```bash
  curl http://localhost:8000/api/predictions/reply-probability?lead_ids=1,2,3,4,5
  ```
  **Expected**:
  ```json
  {
    "predictions": [
      {
        "lead_id": 1,
        "lead_name": "John Doe",
        "reply_probability": 0.78,
        "confidence": 0.89,
        "category": "high"
      },
      {
        "lead_id": 2,
        "lead_name": "Jane Smith",
        "reply_probability": 0.34,
        "confidence": 0.82,
        "category": "low"
      }
    ]
  }
  ```
  **Verify**: Probabilities between 0-1, categorized as high/medium/low

- [ ] **Predict Meeting Probability**
  ```bash
  curl http://localhost:8000/api/predictions/meeting-probability?lead_id=1
  ```
  **Expected**:
  ```json
  {
    "lead_id": 1,
    "meeting_probability": 0.42,
    "reply_probability": 0.78,
    "conversion_probability": 0.54,
    "confidence": 0.85,
    "reasoning": {
      "positive_factors": [
        "High engagement score (82)",
        "VP-level title",
        "Company is growing (recent funding)",
        "Similar leads have 50% meeting rate"
      ],
      "negative_factors": [
        "Located in competitive market",
        "Hasn't clicked any links yet"
      ]
    }
  }
  ```

- [ ] **View Prediction Factors**
  ```bash
  curl http://localhost:8000/api/predictions/factors?model=reply_probability
  ```
  **Expected**:
  ```json
  {
    "model": "reply_probability",
    "feature_importance": [
      {
        "feature": "engagement_score",
        "importance": 0.24,
        "description": "Past email engagement"
      },
      {
        "feature": "job_title_seniority",
        "importance": 0.18,
        "description": "C-level, VP more likely to reply"
      },
      {
        "feature": "company_size",
        "importance": 0.15,
        "description": "50-500 employees optimal"
      },
      {
        "feature": "industry_match",
        "importance": 0.12,
        "description": "How well industry aligns"
      },
      {
        "feature": "personalization_level",
        "importance": 0.11,
        "description": "Level 3 personalization performs best"
      }
    ]
  }
  ```

### 4.3 Thread Analysis

- [ ] **Analyze Email Thread**
  ```bash
  curl -X POST http://localhost:8000/api/threads/analyze \
    -H "Content-Type: application/json" \
    -d '{
      "thread_id": "thread_abc123",
      "emails": [
        {
          "from": "you@company.com",
          "to": "lead@example.com",
          "subject": "Quick question",
          "body": "Hi John, I saw your post about...",
          "sent_at": "2026-01-20T10:00:00Z"
        },
        {
          "from": "lead@example.com",
          "to": "you@company.com",
          "subject": "Re: Quick question",
          "body": "Thanks for reaching out. I would like to learn more. Can we schedule a call?",
          "sent_at": "2026-01-21T14:30:00Z"
        },
        {
          "from": "you@company.com",
          "to": "lead@example.com",
          "subject": "Re: Quick question",
          "body": "Absolutely! Here is my calendar link...",
          "sent_at": "2026-01-21T15:00:00Z"
        }
      ]
    }'
  ```
  **Expected**:
  ```json
  {
    "thread_id": "thread_abc123",
    "analysis": {
      "sentiment": "positive",
      "engagement_level": "high",
      "intent": "schedule_meeting",
      "urgency": "medium",
      "decision_maker": true,
      "objections": [],
      "buying_signals": [
        "Expressed interest",
        "Requested call"
      ]
    }
  }
  ```

- [ ] **Extract Action Items**
  ```bash
  curl http://localhost:8000/api/threads/thread_abc123/action-items
  ```
  **Expected**:
  ```json
  {
    "thread_id": "thread_abc123",
    "action_items": [
      {
        "action": "Schedule call with John Doe",
        "assignee": "You",
        "priority": "high",
        "due_date": "2026-01-25",
        "status": "pending"
      },
      {
        "action": "Send calendar link",
        "assignee": "You",
        "priority": "high",
        "due_date": "2026-01-22",
        "status": "completed"
      }
    ]
  }
  ```

- [ ] **View Conversation Summary**
  ```bash
  curl http://localhost:8000/api/threads/thread_abc123/summary
  ```
  **Expected**:
  ```json
  {
    "thread_id": "thread_abc123",
    "participants": [
      "you@company.com",
      "lead@example.com"
    ],
    "email_count": 3,
    "start_date": "2026-01-20",
    "last_activity": "2026-01-21",
    "summary": "Initial outreach to John Doe about AI solution. John expressed interest and requested a call. Calendar link sent. Next step: Confirm meeting time.",
    "stage": "meeting_scheduled",
    "next_steps": [
      "Follow up if no meeting confirmed by Jan 24",
      "Send agenda 1 day before meeting"
    ]
  }
  ```

---

## API Testing

### Test All Endpoints

#### Re-engagement Endpoints

- [ ] **GET /leads/dormant**
  ```bash
  curl http://localhost:8000/api/leads/dormant?days=21&limit=50
  ```
  **Expected**: 200 OK, list of dormant leads  
  **Verify**: All leads have last_engaged > 21 days ago

- [ ] **POST /campaigns/reengagement**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/reengagement \
    -d '{"campaign_type": "soft_drip", "lead_ids": [1,2,3]}'
  ```
  **Expected**: 201 Created, campaign ID returned

#### A/B Testing Endpoints

- [ ] **POST /campaigns/{id}/ab-test/setup**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/1/ab-test/setup \
    -d '{"variants": [...], "metric": "open_rate"}'
  ```
  **Expected**: 201 Created, variant IDs returned

- [ ] **GET /campaigns/{id}/ab-test/results**
  ```bash
  curl http://localhost:8000/api/campaigns/1/ab-test/results
  ```
  **Expected**: 200 OK, statistics for each variant

#### LinkedIn Endpoints

- [ ] **POST /linkedin/session/login**
  ```bash
  curl -X POST http://localhost:8000/api/linkedin/session/login \
    -d '{"email": "...", "password": "..."}'
  ```
  **Expected**: 200 OK, session cookie returned  
  **Security**: Never log credentials

- [ ] **GET /linkedin/stats**
  ```bash
  curl http://localhost:8000/api/linkedin/stats
  ```
  **Expected**: 200 OK, daily usage stats

#### Deliverability Endpoints

- [ ] **GET /deliverability/domains/{domain}/health**
  ```bash
  curl http://localhost:8000/api/deliverability/domains/yourdomain.com/health
  ```
  **Expected**: 200 OK, SPF/DKIM/DMARC status

#### Analytics Endpoints

- [ ] **GET /campaigns/{id}/analytics/timeseries**
  ```bash
  curl http://localhost:8000/api/campaigns/1/analytics/timeseries?metric=open_rate&interval=daily&days=30
  ```
  **Expected**: 200 OK, daily open rate data for 30 days

- [ ] **GET /campaigns/{id}/analytics/funnel**
  ```bash
  curl http://localhost:8000/api/campaigns/1/analytics/funnel
  ```
  **Expected**: 200 OK, funnel stages with drop-off rates

#### Error Handling

- [ ] **Test 404 - Resource Not Found**
  ```bash
  curl http://localhost:8000/api/campaigns/99999
  ```
  **Expected**: 404 Not Found, error message

- [ ] **Test 400 - Bad Request**
  ```bash
  curl -X POST http://localhost:8000/api/campaigns/ \
    -d '{"name": ""}'  # Missing required fields
  ```
  **Expected**: 400 Bad Request, validation errors

- [ ] **Test 401 - Unauthorized**
  ```bash
  curl http://localhost:8000/api/campaigns/  # No auth token
  ```
  **Expected**: 401 Unauthorized

- [ ] **Test 429 - Rate Limit**
  ```bash
  # Send 100 requests rapidly
  for i in {1..100}; do
    curl http://localhost:8000/api/campaigns/ &
  done
  wait
  ```
  **Expected**: Some requests return 429 Too Many Requests

---

## Frontend Testing

### UI Components

- [ ] **Re-engagement Campaign Builder Loads**
  1. Navigate to http://localhost:3000/campaigns/reengagement
  2. Check page loads without errors
  3. Verify form has fields: campaign_type, lead_segment, sequence_steps
  4. Test dropdown for campaign_type (soft_drip, trigger_based, reset_outreach)
  5. Submit form and verify campaign created
  
  **Expected**: UI responsive, no console errors

- [ ] **A/B Testing Interface Displays Results**
  1. Navigate to http://localhost:3000/campaigns/1/ab-test
  2. Verify variant cards display (Variant A, Variant B)
  3. Check metrics: sends, opens, clicks, open_rate
  4. Verify winner badge shown if significant
  5. Test "Declare Winner" button
  
  **Expected**: Live results, winner highlighted

- [ ] **Workflow Builder with Branching Nodes**
  1. Navigate to http://localhost:3000/sequences/builder
  2. Drag email node onto canvas
  3. Drag LinkedIn node onto canvas
  4. Connect nodes with arrows
  5. Add conditional branch (if opened → path A, else → path B)
  6. Save sequence
  
  **Expected**: Visual builder works, sequence saves correctly

- [ ] **LinkedIn Dashboard Shows Stats**
  1. Navigate to http://localhost:3000/linkedin/dashboard
  2. Verify connection stats widget (sent, accepted, pending)
  3. Check daily limit bars (100 connection limit)
  4. View recent LinkedIn activity feed
  5. Test "Send Connection" button
  
  **Expected**: Real-time stats, limits displayed

- [ ] **Deliverability Dashboard Displays Health**
  1. Navigate to http://localhost:3000/deliverability
  2. Verify domain health cards (SPF, DKIM, DMARC)
  3. Check Gmail pool usage (accounts, sends, limits)
  4. View reputation scores
  5. Test "Check Domain" button
  
  **Expected**: All health checks visible, clear status indicators

- [ ] **Predictions Dashboard Shows Probabilities**
  1. Navigate to http://localhost:3000/predictions
  2. Verify lead scoring table with reply_probability
  3. Check prediction factors tooltip
  4. Filter by high/medium/low probability
  5. Test "Prioritize High Probability Leads" action
  
  **Expected**: Predictions displayed, filtering works

### Frontend Integration

- [ ] **Create Campaign End-to-End**
  1. Click "New Campaign"
  2. Fill in name, description, channels
  3. Select leads from table
  4. Choose sequence template
  5. Set send schedule
  6. Click "Launch Campaign"
  7. Verify redirects to campaign detail page
  8. Check campaign appears in campaigns list
  
  **Expected**: Complete flow works, campaign created

- [ ] **View Real-Time Analytics**
  1. Open campaign detail page
  2. Watch analytics widgets update (use WebSocket)
  3. Verify charts: open rate over time, funnel
  4. Check real-time feed of email activities
  5. Test date range selector
  
  **Expected**: Live updates, charts interactive

---

## Integration Testing

### End-to-End Workflows

- [ ] **E2E: Create Campaign → Send Emails → Track Opens → Trigger Follow-up**
  ```python
  # Integration test script
  from campaigns.models import Campaign, Lead, Sequence
  from campaigns.email_sender import EmailSender
  from campaigns.sequence_engine import SequenceEngine
  import time
  
  # 1. Create campaign
  campaign = Campaign.objects.create(
      name="E2E Test Campaign",
      status="active"
  )
  
  # 2. Create sequence
  sequence = Sequence.objects.create(
      name="Test Sequence",
      campaign=campaign
  )
  sequence.steps.create(step=1, subject="Step 1", delay_days=0)
  sequence.steps.create(step=2, subject="Step 2", delay_days=2)
  
  # 3. Enroll lead
  lead = Lead.objects.create(
      email="test@example.com",
      first_name="Test"
  )
  engine = SequenceEngine()
  engine.enroll_lead(lead, sequence)
  
  # 4. Send first email
  sender = EmailSender()
  result = sender.send_step(lead, step=1)
  assert result['status'] == 'sent'
  
  # 5. Simulate open
  from campaigns.models import EmailActivity
  EmailActivity.objects.create(
      lead=lead,
      campaign=campaign,
      activity_type='opened'
  )
  
  # 6. Check if step 2 triggered
  time.sleep(2)  # Wait for async processing
  lead.refresh_from_db()
  assert lead.current_sequence_step == 2
  
  print("✓ E2E test passed")
  ```
  **Expected**: All steps execute successfully

- [ ] **E2E: Create A/B Test → Collect Data → Declare Winner**
  ```python
  from campaigns.models import Campaign, ABTestVariant
  from campaigns.ab_testing import ABTestEngine
  
  # 1. Setup A/B test
  campaign = Campaign.objects.get(name="E2E Test Campaign")
  engine = ABTestEngine()
  
  variants = engine.create_test(
      campaign=campaign,
      variants=[
          {"name": "A", "subject": "Test A"},
          {"name": "B", "subject": "Test B"}
      ],
      sample_size=100
  )
  
  # 2. Assign leads
  leads = Lead.objects.all()[:100]
  engine.assign_variants(leads, variants)
  
  # 3. Simulate sends and opens
  for lead in leads[:50]:
      # Variant A: 20% open rate
      if lead.ab_test_variant == variants[0]:
          if random.random() < 0.20:
              EmailActivity.objects.create(
                  lead=lead,
                  activity_type='opened'
              )
  
  for lead in leads[50:]:
      # Variant B: 30% open rate
      if lead.ab_test_variant == variants[1]:
          if random.random() < 0.30:
              EmailActivity.objects.create(
                  lead=lead,
                  activity_type='opened'
              )
  
  # 4. Calculate results
  results = engine.calculate_results(campaign)
  
  # 5. Declare winner
  winner = engine.declare_winner(campaign, confidence=0.95)
  assert winner == variants[1]  # B should win
  
  print(f"✓ Winner: {winner.name}")
  ```

- [ ] **E2E: LinkedIn Connect → Wait for Acceptance → Send Message**
  ```python
  from campaigns.linkedin import LinkedInAutomation
  import time
  
  linkedin = LinkedInAutomation()
  
  # 1. Send connection request
  result = linkedin.connect(
      profile_url="https://linkedin.com/in/test-user",
      note="Hi! I'd love to connect."
  )
  assert result['status'] == 'success'
  
  # 2. Simulate waiting (in real test, this could take days)
  # For test purposes, manually accept or mock
  linkedin.mock_accept_connection("https://linkedin.com/in/test-user")
  
  # 3. Check status
  status = linkedin.get_connection_status("https://linkedin.com/in/test-user")
  assert status == 'connected'
  
  # 4. Send message
  message_result = linkedin.send_message(
      profile_url="https://linkedin.com/in/test-user",
      message="Thanks for connecting!"
  )
  assert message_result['status'] == 'sent'
  
  print("✓ LinkedIn E2E test passed")
  ```

- [ ] **E2E: Reply Received → Classify Sentiment → Generate Response**
  ```python
  from campaigns.reply_intelligence import ReplyClassifier, ResponseGenerator
  
  # 1. Simulate reply received
  lead = Lead.objects.get(email="test@example.com")
  reply_text = "Thanks for reaching out! I'm interested. Can you send pricing?"
  
  # 2. Classify sentiment & intent
  classifier = ReplyClassifier()
  classification = classifier.classify(reply_text)
  
  assert classification['sentiment'] == 'positive'
  assert classification['intent'] == 'request_info'
  
  # 3. Generate response
  generator = ResponseGenerator()
  response = generator.generate(
      reply_text=reply_text,
      lead=lead,
      intent=classification['intent']
  )
  
  assert 'pricing' in response['draft'].lower()
  assert len(response['draft']) > 50
  
  print("✓ Reply intelligence E2E test passed")
  print(f"Generated response: {response['draft'][:100]}...")
  ```

---

## Performance Testing

### Load Tests

- [ ] **Load Test: 10,000 Leads Import**
  ```bash
  # Generate test CSV
  python scripts/generate_test_leads.py --count=10000 --output=test_leads.csv
  
  # Time import
  time curl -X POST http://localhost:8000/api/leads/import \
    -F "file=@test_leads.csv"
  ```
  **Expected**: Import completes in < 60 seconds  
  **Verify**: All 10,000 leads in database

- [ ] **Load Test: 1,000 Concurrent Email Sends**
  ```python
  import concurrent.futures
  from campaigns.email_sender import EmailSender
  from campaigns.models import Lead
  
  sender = EmailSender()
  leads = Lead.objects.all()[:1000]
  
  def send_email(lead):
      return sender.send(
          lead=lead,
          subject="Load test",
          body="This is a test"
      )
  
  # Send concurrently
  import time
  start = time.time()
  
  with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
      futures = [executor.submit(send_email, lead) for lead in leads]
      results = [f.result() for f in concurrent.futures.as_completed(futures)]
  
  elapsed = time.time() - start
  print(f"Sent 1000 emails in {elapsed:.2f} seconds")
  print(f"Rate: {1000/elapsed:.2f} emails/second")
  ```
  **Expected**: All sends complete, rate > 10 emails/sec  
  **Troubleshooting**: If slow, check database connection pooling

- [ ] **Load Test: 100 LinkedIn Actions/Hour**
  ```python
  from campaigns.linkedin import LinkedInAutomation
  import time
  
  linkedin = LinkedInAutomation()
  
  # Simulate 100 actions spread over 1 hour
  actions_per_minute = 100 / 60  # ~1.67 actions/min
  delay_between_actions = 60 / actions_per_minute  # ~36 seconds
  
  for i in range(100):
      # Mix of connections and messages
      if i % 2 == 0:
          linkedin.connect(
              profile_url=f"https://linkedin.com/in/test-{i}",
              note="Test connection"
          )
      else:
          linkedin.send_message(
              profile_url=f"https://linkedin.com/in/test-{i}",
              message="Test message"
          )
      
      print(f"Action {i+1}/100")
      time.sleep(delay_between_actions)
  
  # Verify rate limits not exceeded
  stats = linkedin.get_stats()
  assert stats['connections_sent'] <= 100
  assert stats['messages_sent'] <= 50
  ```
  **Expected**: Rate limits respected, no blocks

### Stress Tests

- [ ] **Database Query Performance**
  ```python
  from django.db import connection
  from django.test.utils import override_settings
  import time
  
  # Test slow queries
  with connection.cursor() as cursor:
      start = time.time()
      cursor.execute("""
          SELECT l.*, COUNT(ea.id) as activity_count
          FROM campaigns_lead l
          LEFT JOIN campaigns_emailactivity ea ON ea.lead_id = l.id
          WHERE l.status = 'engaged'
          GROUP BY l.id
          ORDER BY activity_count DESC
          LIMIT 1000
      """)
      results = cursor.fetchall()
      elapsed = time.time() - start
  
  print(f"Query returned {len(results)} leads in {elapsed:.3f}s")
  assert elapsed < 1.0, "Query too slow, needs optimization"
  ```
  **Expected**: Query completes in < 1 second  
  **Fix**: Add indexes if needed

- [ ] **Memory Usage During Bulk Operations**
  ```python
  import psutil
  import os
  
  process = psutil.Process(os.getpid())
  
  # Check memory before
  mem_before = process.memory_info().rss / 1024 / 1024  # MB
  
  # Bulk operation
  from campaigns.models import Lead
  leads = Lead.objects.all()[:10000]
  lead_list = list(leads)  # Load into memory
  
  # Check memory after
  mem_after = process.memory_info().rss / 1024 / 1024  # MB
  mem_increase = mem_after - mem_before
  
  print(f"Memory before: {mem_before:.2f} MB")
  print(f"Memory after: {mem_after:.2f} MB")
  print(f"Increase: {mem_increase:.2f} MB")
  
  assert mem_increase < 500, "Memory usage too high"
  ```
  **Expected**: Memory increase < 500 MB for 10K leads

---

## Security Testing

### Authentication & Authorization

- [ ] **API Authentication Works**
  ```bash
  # Without token - should fail
  curl http://localhost:8000/api/campaigns/
  # Expected: 401 Unauthorized
  
  # With token - should work
  curl http://localhost:8000/api/campaigns/ \
    -H "Authorization: Bearer YOUR_TOKEN_HERE"
  # Expected: 200 OK
  ```

- [ ] **Rate Limiting Enforced**
  ```bash
  # Send 100 requests in 1 minute
  for i in {1..100}; do
    curl http://localhost:8000/api/campaigns/
    sleep 0.5
  done
  ```
  **Expected**: Some requests throttled (429 status)  
  **Config**: Check rate limit settings

- [ ] **Suppression List Prevents Sending**
  ```python
  from campaigns.models import Lead, SuppressionList
  from campaigns.email_sender import EmailSender
  
  # Add lead to suppression list
  lead = Lead.objects.first()
  SuppressionList.objects.create(
      email=lead.email,
      reason="User requested"
  )
  
  # Try to send
  sender = EmailSender()
  result = sender.send(
      lead=lead,
      subject="Test",
      body="Should not send"
  )
  
  assert result['status'] == 'blocked'
  assert 'suppressed' in result['reason'].lower()
  ```
  **Expected**: Email blocked, logged

- [ ] **Gmail Quota Prevents Over-Sending**
  ```python
  from campaigns.models import GmailAccount, EmailActivity
  from django.utils import timezone
  
  account = GmailAccount.objects.first()
  
  # Create 2000 sends today
  today = timezone.now().date()
  EmailActivity.objects.filter(
      gmail_account=account,
      sent_at__date=today
  ).delete()
  
  for i in range(2000):
      EmailActivity.objects.create(
          gmail_account=account,
          lead_id=1,
          activity_type='sent',
          sent_at=timezone.now()
      )
  
  # Try to send one more
  from campaigns.email_sender import EmailSender
  sender = EmailSender()
  
  result = sender.can_send_from_account(account)
  assert result == False, "Should block over-quota sends"
  ```
  **Expected**: Quota enforced, 2001st email blocked

### Data Security

- [ ] **Sensitive Data Encrypted**
  ```python
  from campaigns.models import GmailAccount
  
  account = GmailAccount.objects.first()
  
  # Check password is encrypted in DB
  from django.db import connection
  with connection.cursor() as cursor:
      cursor.execute(
          "SELECT password FROM campaigns_gmailaccount WHERE id = %s",
          [account.id]
      )
      db_password = cursor.fetchone()[0]
  
  # Should be encrypted, not plain text
  assert db_password != account.get_decrypted_password()
  assert len(db_password) > 50  # Encrypted string length
  ```

- [ ] **SQL Injection Protection**
  ```python
  from campaigns.models import Lead
  
  # Try SQL injection in search
  malicious_input = "test' OR '1'='1"
  
  # Should be safely escaped
  leads = Lead.objects.filter(first_name=malicious_input)
  count = leads.count()
  
  # Should return 0 or legitimate matches, not all leads
  total_leads = Lead.objects.count()
  assert count < total_leads, "SQL injection not prevented!"
  ```

---

## Troubleshooting Guide

### Common Issues

**Issue**: Database migrations fail  
**Solution**: 
```bash
python manage.py migrate --fake-initial
python manage.py migrate
```

**Issue**: OpenAI API errors (Level 3 personalization)  
**Solution**: Check OPENAI_API_KEY in .env, verify API credits

**Issue**: LinkedIn automation not working  
**Solution**: Re-login to refresh session cookie, check 2FA status

**Issue**: Gmail sending fails  
**Solution**: Verify OAuth credentials, check Gmail API quota

**Issue**: Frontend can't connect to backend  
**Solution**: Check CORS settings, verify backend is running on correct port

**Issue**: Slow query performance  
**Solution**: 
```sql
-- Add indexes
CREATE INDEX idx_lead_status ON campaigns_lead(status);
CREATE INDEX idx_email_activity_lead ON campaigns_emailactivity(lead_id, activity_type);
CREATE INDEX idx_lead_engagement ON campaigns_lead(engagement_score, last_engaged);
```

**Issue**: Rate limiting too aggressive  
**Solution**: Adjust settings in backend/settings.py:
```python
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    }
}
```

---

## Test Data Generation

### Generate Sample Data

```python
# scripts/generate_test_data.py
from campaigns.models import Lead, Campaign
from faker import Faker
import random

fake = Faker()

# Generate 1000 test leads
for i in range(1000):
    Lead.objects.create(
        email=fake.email(),
        first_name=fake.first_name(),
        last_name=fake.last_name(),
        company=fake.company(),
        job_title=fake.job(),
        industry=random.choice(['saas', 'ecommerce', 'finance', 'healthcare']),
        company_size=random.choice(['1-10', '11-50', '51-200', '201-500', '501+']),
        engagement_score=random.randint(0, 100),
        status=random.choice(['new', 'contacted', 'engaged', 'qualified'])
    )

print("Generated 1000 test leads")
```

Run with:
```bash
python manage.py shell < scripts/generate_test_data.py
```

---

## Success Criteria

### Phase 1: Core Foundation
- [ ] All data models have proper fields and relationships
- [ ] Personalization engine replaces all 23 token types
- [ ] Rules engine automatically manages lead lifecycle
- [ ] A/B testing declares winners with statistical confidence
- [ ] Re-engagement campaigns identify and nurture dormant leads
- [ ] LinkedIn automation respects daily limits
- [ ] Deliverability monitoring shows domain health
- [ ] Multi-channel sequences execute with proper branching

### Phase 2: Intelligence & Optimization
- [ ] Send time optimization improves open rates by 10%+
- [ ] Reply intelligence classifies sentiment with 85%+ accuracy
- [ ] Template recommendations increase reply rates
- [ ] Sequence intelligence suggests data-driven improvements

### Phase 3: Scale & Enterprise
- [ ] Send queue processes 10,000+ emails/hour
- [ ] Team features enable collaboration
- [ ] Advanced analytics provide deep insights
- [ ] Reports export correctly to PDF/Excel

### Phase 4: AI Autonomy
- [ ] Campaign autopilot improves performance without manual intervention
- [ ] Predictive models achieve 80%+ accuracy
- [ ] Thread analysis extracts action items automatically

---

## Sign-Off

**Tester Name**: ___________________________  
**Date**: ___________________________  
**Environment**: ☐ Development  ☐ Staging  ☐ Production  
**Overall Status**: ☐ Pass  ☐ Pass with Issues  ☐ Fail  

**Critical Issues**:
1. _____________________________________________________
2. _____________________________________________________

**Notes**:
_____________________________________________________________
_____________________________________________________________

---

**TESTING COMPLETE** ✓
