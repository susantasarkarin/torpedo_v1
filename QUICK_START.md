# Campaign Automation System - Quick Start Guide

## Overview

A complete automated email campaign system has been implemented for **Survey Fieldwork** and **Cogentix Research** that provides:

1. ✅ Service identification for both companies
2. ✅ Highly personalized outreach emails with appropriate sender addresses
3. ✅ Weekly follow-up sequences (4 emails over 3 weeks)
4. ✅ Email status tracking (open, bounce, not opened, clicked)
5. ✅ Professional email signatures for each sender
6. ✅ Automatic bounce status updates

## Files Created

### Core Implementation
- `backend/campaigns/services_config.py` - Service definitions for both companies
- `backend/campaigns/email_templates.py` - Email templates with signatures
- `backend/campaigns/automation.py` - Campaign automation logic
- `backend/routers/campaign_automation.py` - REST API endpoints
- `backend/main.py` - Updated to include new router

### Documentation & Testing
- `CAMPAIGN_AUTOMATION_DOCS.md` - Comprehensive documentation
- `backend/test_campaign_automation.py` - Test suite (all tests pass ✓)
- `backend/demo_campaign_automation.py` - Demo script
- `QUICK_START.md` - This file

## Quick Test

Run the test suite to verify everything works:

```bash
cd backend
python test_campaign_automation.py
```

Expected output: 🎉 ALL TESTS PASSED!

## View Demo

See the system in action:

```bash
cd backend
python demo_campaign_automation.py
```

## Email Senders

### Survey Fieldwork
- **Email**: indira@surveyfieldwork.com
- **Name**: Indira
- **Title**: Business Development Manager
- **Services**: 6 services (Audience Sampling, Enterprise Solutions, etc.)

### Cogentix Research
- **Email**: meera@cogentixresearch.com
- **Name**: Meera
- **Title**: Senior Research Consultant
- **Services**: 6 services (Panel Management, Data Analytics, etc.)

## Email Sequence

Each campaign automatically sends 4 emails:

1. **Day 0**: Initial Outreach - Introduction to services
2. **Day 7**: Follow-up Week 1 - Key benefits and highlights
3. **Day 14**: Follow-up Week 2 - Success stories and testimonials
4. **Day 21**: Follow-up Week 3 - Final outreach with resources

**Smart Features**:
- Follow-ups only sent if no reply received
- Sequence stops on bounce or unsubscribe
- Each email includes professional signature

## Email Tracking

The system tracks:
- **OPENED** - Email opened (with count)
- **CLICKED** - Link clicked (with count)
- **BOUNCED** - Email bounced (auto-stops sequence)
- **NOT_OPENED** - Sent but not opened
- **REPLIED** - Recipient replied (auto-stops sequence)

## API Endpoints

All endpoints are available at `/api/campaigns/automation/`:

### List Services
```http
GET /api/campaigns/automation/services
```

### Create Campaign
```http
POST /api/campaigns/automation/campaigns
Content-Type: application/json

{
  "company": "surveyfieldwork",
  "campaign_name": "Q1 2024 Outreach",
  "recipients": [
    {
      "email": "contact@example.com",
      "first_name": "John",
      "company": "Acme Corp"
    }
  ],
  "start_immediately": false
}
```

### Track Email Events
```http
POST /api/campaigns/automation/tracking/events
Content-Type: application/json

{
  "events": [
    {
      "email": "contact@example.com",
      "campaign_id": "campaign_id_here",
      "event": "opened"
    }
  ]
}
```

### Mark as Bounced
```http
POST /api/campaigns/automation/tracking/bounce/{campaign_id}/{email}
```

### Get Campaign Report
```http
GET /api/campaigns/automation/campaigns/{campaign_id}/report
```

## Usage Example

### Python Example

```python
from backend.campaigns.automation import CampaignAutomation

automation = CampaignAutomation()

# Create campaign
campaign_id = automation.create_outreach_campaign(
    company="surveyfieldwork",
    campaign_name="Market Research Agencies - Q1",
    recipients=[
        {
            "email": "director@agency.com",
            "first_name": "Sarah",
            "company": "Global Research Agency",
            "custom_variables": {
                "industry": "Market Research"
            }
        }
    ],
    start_immediately=True
)

# Track bounce
automation.process_email_tracking_updates([
    {
        "email": "director@agency.com",
        "campaign_id": campaign_id,
        "event": "bounced"
    }
])
# This automatically updates recipient status to "BOUNCED"

# Get report
report = automation.get_campaign_status_report(campaign_id)
print(f"Bounce Rate: {report['rates']['bounce_rate']}%")
```

### cURL Example

```bash
# Create campaign
curl -X POST http://localhost:8000/api/campaigns/automation/campaigns \
  -H "Content-Type: application/json" \
  -d '{
    "company": "surveyfieldwork",
    "campaign_name": "Q1 Outreach",
    "recipients": [
      {
        "email": "test@example.com",
        "first_name": "John",
        "company": "Test Corp"
      }
    ]
  }'

# Mark as bounced
curl -X POST http://localhost:8000/api/campaigns/automation/tracking/bounce/CAMPAIGN_ID/test@example.com
```

## Email Templates

### Available Templates
Each company has 4 templates:
- `initial_outreach` - First contact email
- `follow_up_week1` - Week 1 follow-up
- `follow_up_week2` - Week 2 follow-up
- `follow_up_week3` - Final follow-up

### Personalization Variables
All templates support:
- `{{first_name}}` - Recipient's first name
- `{{last_name}}` - Recipient's last name
- `{{company}}` - Recipient's company
- `{{title}}` - Job title
- `{{industry}}` - Industry (custom variable)

Example:
```
Subject: {{first_name}}, Transform Your Research with Quality Data
Body: Hi {{first_name}}, ... at {{company}} ...
```

## Bounce Handling

When an email bounces:

1. **Event received** via tracking webhook or API
2. **Recipient status** automatically updated to "BOUNCED"
3. **Sequence stopped** - no more emails sent to this recipient
4. **Timestamp recorded** - bounce_at field populated
5. **Send status updated** - individual send marked as bounced

No manual intervention required!

## Testing Checklist

- [x] Services configuration loads correctly
- [x] Email templates render with variables
- [x] Signatures included in all emails
- [x] Weekly sequence has 4 steps
- [x] Bounce updates work automatically
- [x] Tracking events process correctly
- [x] Both companies (surveyfieldwork & cogentixresearch) work
- [x] API endpoints available
- [x] Demo runs successfully

## Next Steps

1. **Configure MongoDB**: Ensure MongoDB is running and accessible
2. **Start API Server**: `uvicorn backend.main:app --reload`
3. **Create First Campaign**: Use API or Python to create a campaign
4. **Monitor Tracking**: Set up webhooks for email tracking
5. **Review Reports**: Check campaign performance metrics

## Support & Documentation

- **Full Documentation**: See `CAMPAIGN_AUTOMATION_DOCS.md`
- **Test Suite**: Run `python backend/test_campaign_automation.py`
- **Demo**: Run `python backend/demo_campaign_automation.py`
- **API Docs**: Visit `http://localhost:8000/docs` when server is running

## Key Features Summary

✅ **Service Identification**: 6 services per company, fully documented  
✅ **Personalized Emails**: Custom sender per company with professional signatures  
✅ **Weekly Follow-ups**: 4-email sequence with smart conditions  
✅ **Comprehensive Tracking**: Opens, clicks, bounces, not-opened status  
✅ **Email Signatures**: HTML signatures with contact info  
✅ **Bounce Auto-Update**: Status automatically changes to "BOUNCED"  
✅ **REST API**: Complete API for integration  
✅ **Tested**: Full test suite with 100% pass rate  

---

**Implementation Complete! ✅**

All requirements from the problem statement have been successfully implemented and tested.
