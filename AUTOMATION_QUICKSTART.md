# Torpedo Automation - Quick Start Guide

## Overview
This guide shows you how to use the autonomous campaign automation system in practice.

## Prerequisites
- ✅ MongoDB running
- ✅ OpenAI API key configured
- ✅ Backend server running (`python -m uvicorn backend.main:app`)
- ✅ Campaign with ICP settings (see Setup Campaign section)

---

## 1. Setup: Create a Test Campaign

### 1a. VIA MongoDB Shell
```javascript
db.campaigns.insert_one({
  "_id": "automation_test_campaign",
  "name": "Q1 SaaS Enterprise Outreach",
  "from_email": "sales@yourcompany.com",
  "from_name": "Sales Team",
  "campaign_type": "cold",
  "settings": {
    // ICP Criteria - used for autonomous routing
    "ideal_seniority_levels": ["C-Level", "VP"],
    "ideal_industries": ["SaaS", "FinTech", "MarTech"],
    "ideal_company_sizes": ["Mid-Market", "Enterprise"],
    "ideal_departments": ["Sales", "RevOps", "Marketing"],
    "ideal_regions": ["US", "EU"]
  }
})
```

### 1b. VIA Python
```python
from pymongo import MongoClient

client = MongoClient()
db = client['email_automation']

db.campaigns.insert_one({
    "_id": "automation_test_campaign",
    "name": "Q1 SaaS Enterprise Outreach",
    "from_email": "sales@yourcompany.com",
    "settings": {
        "ideal_seniority_levels": ["C-Level", "VP"],
        "ideal_industries": ["SaaS", "FinTech"],
        "ideal_company_sizes": ["Mid-Market", "Enterprise"],
        "ideal_departments": ["Sales", "RevOps"]
    }
})
```

---

## 2. Auto-Route Qualified Leads

### Via cURL
```bash
curl -X POST http://localhost:8000/automation/campaigns/automation_test_campaign/auto-route
```

### Response
```json
{
  "status": "success",
  "campaign_id": "automation_test_campaign",
  "routed_count": 23,
  "skipped_count": 5,
  "decision_logs": [
    "decision_id_1",
    "decision_id_2",
    ...
  ],
  "details": [
    {
      "lead_id": "lead_123",
      "lead_name": "John Doe",
      "lead_email": "john@example.com",
      "confidence_score": 0.92,
      "action": "routed"
    },
    {
      "lead_id": "lead_456",
      "lead_name": "Jane Smith",
      "lead_email": "jane@example.com",
      "confidence_score": 0.78,
      "action": "skipped (low confidence)"
    }
  ]
}
```

### What Happened
- ✅ 23 leads matched ICP with 0.85+ confidence
- ✅ 5 leads had confidence < 0.85 (skipped)
- ✅ Each routing decision logged with confidence score & reasoning
- ✅ Leads added to campaign_recipients collection
- ✅ Decision audit trail created for compliance

---

## 3. Generate Email Variants

### Via cURL
```bash
curl -X POST "http://localhost:8000/automation/campaigns/automation_test_campaign/auto-generate-email-variants?base_template_id=YOUR_TEMPLATE_ID&auto_select=true"
```

### Response
```json
{
  "status": "success",
  "campaign_id": "automation_test_campaign",
  "variants": [
    {
      "name": "Executive Focus",
      "subject": "Strategic Partnership: Drive Revenue Growth",
      "body_html": "Hi {{first_name}},\n\nOur platform helps Fortune 500 companies...",
      "personalization_note": "Formal, authority-driven, results-oriented",
      "confidence_score": 0.94
    },
    {
      "name": "Problem Solver",
      "subject": "{{first_name}}, solving the {{industry}} challenge",
      "body_html": "Hi {{first_name}},\n\nWe've worked with teams like yours...",
      "personalization_note": "Conversational, pain-point focused",
      "confidence_score": 0.88
    },
    {
      "name": "Innovator",
      "subject": "The future of {{industry}} in 2025",
      "body_html": "Hi {{first_name}},\n\nLeading {{company_name}} teams are already...",
      "personalization_note": "Dynamic, vision-oriented, future-focused",
      "confidence_score": 0.85
    }
  ],
  "selected_variant_id": "Executive Focus",
  "decision_log_id": "decision_id_123"
}
```

### What Happened
- ✅ 3 email variants generated with completely different tones
- ✅ "Executive Focus" selected (highest confidence: 0.94)
- ✅ All variants stored for future A/B testing
- ✅ Campaign updated with selected variant
- ✅ Decision logged: "why Executive Focus was chosen"

---

## 4. Optimize Campaign Schedule

### Via cURL
```bash
curl -X POST http://localhost:8000/automation/campaigns/automation_test_campaign/auto-optimize-schedule
```

### Response
```json
{
  "status": "success",
  "campaign_id": "automation_test_campaign",
  "send_schedule": {
    "step_0": {
      "delay_days": 0,
      "send_hours": [9, 14],
      "condition": "always",
      "priority": "initial",
      "stop_on_reply": false
    },
    "step_1": {
      "delay_days": 3,
      "send_hours": [9, 14],
      "condition": "no_reply",
      "priority": "followup",
      "stop_on_reply": true
    },
    "step_2": {
      "delay_days": 7,
      "send_hours": [10, 15],
      "condition": "no_reply",
      "priority": "followup",
      "stop_on_reply": true
    },
    "step_3": {
      "delay_days": 14,
      "send_hours": [10, 15],
      "condition": "no_reply",
      "priority": "followup",
      "stop_on_reply": true
    }
  },
  "optimization_reasoning": "Hybrid approach using historical data with industry defaults as fallback",
  "confidence_score": 0.88
}
```

### What Happened
- ✅ Analyzed historical opens (if >20 samples) OR used industry defaults
- ✅ Generated 4-step sequence (initial + 3 follow-ups)
- ✅ Adjusted delays based on lead seniority (C-Level = longer delays)
- ✅ Set send windows (9am, 2pm = highest open rates)
- ✅ Schedule stored and ready for sending

---

## 5. Monitor Compliance & Decisions

### View Decision History
```bash
curl "http://localhost:8000/automation/decisions/audit-trail?campaign_id=automation_test_campaign&limit=10"
```

### Response
```json
{
  "status": "success",
  "total": 23,
  "decisions": [
    {
      "decision_id": "decision_id_1",
      "decision_type": "lead_routing",
      "action": "route_to_campaign",
      "autonomous": true,
      "lead_id": "lead_123",
      "campaign_id": "automation_test_campaign",
      "confidence_score": 0.92,
      "reasoning": {
        "rule_matched": "ICP matching",
        "matched_attributes": ["seniority_level", "industry", "company_size"],
        "threshold_used": 0.85
      },
      "input_context": {
        "lead_attributes": {
          "seniority": "C-Level",
          "industry": "SaaS",
          "company_size": "Enterprise"
        },
        "campaign_icp": {
          "seniority_levels": ["C-Level", "VP"],
          "industries": ["SaaS", "FinTech"]
        }
      },
      "logged_at": "2025-02-15T10:30:00"
    }
  ]
}
```

### View Decision Quality Metrics
```bash
curl "http://localhost:8000/automation/decisions/confidence-stats?decision_type=lead_routing&hours=24"
```

### Response
```json
{
  "status": "success",
  "stats": {
    "period_hours": 24,
    "total_decisions": 28,
    "by_type": {
      "lead_routing": {
        "count": 23,
        "avg_confidence": 0.89,
        "min_confidence": 0.81,
        "max_confidence": 0.98,
        "below_85_threshold": 5,
        "below_85_pct": 21.7
      },
      "email_generation": {
        "count": 3,
        "avg_confidence": 0.88,
        "min_confidence": 0.85,
        "max_confidence": 0.94,
        "below_85_threshold": 0,
        "below_85_pct": 0
      },
      "schedule_optimization": {
        "count": 2,
        "avg_confidence": 0.88,
        "min_confidence": 0.88,
        "max_confidence": 0.88,
        "below_85_threshold": 0,
        "below_85_pct": 0
      }
    }
  }
}
```

### What This Tells You
- ✅ Average confidence: 0.89 (very high, > 0.85 threshold)
- ⚠️ 5 leads skipped (21.7%) due to low confidence (< 0.85)
- ✅ Email variants averaging 0.88 confidence
- ✅ All scheduling decisions high confidence (0.88)

---

## 6. Check Campaign Automation Status

### Via cURL
```bash
curl http://localhost:8000/automation/campaigns/automation_test_campaign/automation-status
```

### Response
```json
{
  "campaign_id": "automation_test_campaign",
  "routing": {
    "enabled": true,
    "mode": "ICP matching (0.85+ confidence threshold)"
  },
  "email_optimization": {
    "enabled": true,
    "selected_variant": "Executive Focus",
    "variant_count": 3,
    "variant_selection_confidence": "high"
  },
  "schedule_optimization": {
    "enabled": true,
    "approach": "hybrid",
    "optimization_time": "2025-02-15T10:35:00"
  },
  "compliance_logging": {
    "enabled": true,
    "collection": "campaign_decisions",
    "audit_trail": "Full decision reasoning with confidence scores"
  }
}
```

---

## 7. Monitor Costs

### Check OpenAI Usage (Last 24 Hours)
```python
from backend.leads.openai_wrapper import get_daily_usage_report

usage = get_daily_usage_report()
print(usage)
```

### Response
```python
{
    "period_hours": 24,
    "breakdown": [
        {
            "_id": {"model": "gpt-4o-mini", "provider": "openai"},
            "total_requests": 5,
            "total_input_tokens": 1250,
            "total_output_tokens": 340,
            "total_cost": 0.45,
            "avg_latency": 1230
        }
    ]
}
```

### Budget Check
- Cost today: $0.45
- Monthly budget: $40
- Runway: 88 campaigns at this rate
- Status: ✅ Well under budget

---

## 8. Complete Workflow: Campaign to Launch

### Step 1: Create Campaign
```bash
# Via MongoDB or API
```

### Step 2: Auto-Route Leads
```bash
POST /automation/campaigns/{id}/auto-route
# Result: 23 leads routed with 0.85+ confidence
```

### Step 3: Generate Variants
```bash
POST /automation/campaigns/{id}/auto-generate-email-variants?base_template_id=...&auto_select=true
# Result: 3 variants generated, best selected
```

### Step 4: Optimize Schedule
```bash
POST /automation/campaigns/{id}/auto-optimize-schedule
# Result: 4-step sequence optimized by lead seniority
```

### Step 5: Review Compliance
```bash
GET /automation/decisions/audit-trail?campaign_id={id}
# Result: 26 decisions logged with full reasoning
```

### Step 6: Launch Campaign
```bash
# Campaign is now ready to send
# Leads are routed, email ready, schedule optimized
# Full audit trail for compliance
```

**Total time: ~1 minute** (vs 25 minutes manual)

---

## Common Tasks

### Route Additional Leads to Existing Campaign
```bash
POST /automation/campaigns/{id}/auto-route
```

### Regenerate Email Variants
```bash
POST /automation/campaigns/{id}/auto-generate-email-variants?base_template_id=NEW_TEMPLATE&auto_select=true
```

### Re-optimize Schedule (e.g., if lead profile changes)
```bash
POST /automation/campaigns/{id}/auto-optimize-schedule
```

### Export Audit Trail for Compliance
```bash
GET /automation/decisions/audit-trail?campaign_id={id}&hours=720
# 30 days of decisions
```

---

## Troubleshooting

### "Low confidence_score" (< 0.85) - Why were leads skipped?

Check decision logs:
```bash
GET /automation/decisions/audit-trail?campaign_id={id}
```

Look for skipped lead details - shows which ICP attributes didn't match.

**Solutions:**
1. Add more seniority/industry diversity to campaign ICP
2. Ensure leads are fully enriched (seniority, industry populated)
3. Lower confidence threshold (if willing to accept more risk)

### Email variants too similar

**Cause:** Lead seniority distribution is narrow (e.g., only C-Level)

**Solutions:**
1. Increase temperature in email_optimizer.py (currently 0.7 → try 0.8)
2. Ensure leads have diverse seniority levels
3. Add more personalization instructions to AI prompt

### Schedule using defaults (not historical data)

**Cause:** Need >20 historical opens/engagement to use historical approach

**Solutions:**
1. Run campaign first to gather historical data
2. Next campaign will use hybrid (historical + defaults)
3. Check historical data in outreach_send_logs collection

---

## Next Steps

1. ✅ Create test campaign with ICP
2. ✅ Call auto-route endpoint (should route 10-30 leads)
3. ✅ Generate variants and review quality
4. ✅ Monitor decision logs for compliance
5. ✅ Check costs are under $40/month
6. ✅ Deploy to production when satisfied

---

For more details, see: `AUTOMATION_IMPLEMENTATION_SUMMARY.md`
