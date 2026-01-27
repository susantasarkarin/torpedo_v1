# Campaign Platform - Email Automation Documentation

## Overview

This documentation describes the automated email campaign system for **Survey Fieldwork** and **Cogentix Research**. The system provides highly personalized outreach emails with weekly follow-ups, email tracking, and automatic bounce handling.

## Features

### 1. Service Identification

The system identifies and manages services offered by both companies:

#### Survey Fieldwork Services
- **Audience Sampling** - Global panel access across 50+ countries
- **Enterprise Solutions** - Custom research for large organizations
- **Security Measures** - Industry-leading fraud prevention
- **Survey Programming & Hosting** - Professional survey design
- **Qualitative Fieldwork** - Focus groups and IDIs
- **Market Research & Insights** - Comprehensive analysis

#### Cogentix Research Services
- **Panel Management & Recruitment** - Custom panel development
- **Data Analytics & Visualization** - Advanced analytics
- **Research Consulting** - Strategy and methodology
- **Technology Solutions** - Custom platforms and automation
- **Compliance & Quality Assurance** - GDPR/ISO compliance
- **Specialized Research** - Industry-specific expertise

### 2. Personalized Outreach Emails

Each campaign automatically uses the correct sender based on the company:

- **Survey Fieldwork**: `indira@surveyfieldwork.com` (Indira, Business Development Manager)
- **Cogentix Research**: `meera@cogentixresearch.com` (Meera, Senior Research Consultant)

All emails include:
- Personalized subject lines with recipient's name
- Company-specific branding and messaging
- Professional email signatures with contact details
- Variable substitution for first_name, company, industry, etc.

### 3. Weekly Follow-Up Sequence

Automated 4-step email sequence:

1. **Day 0**: Initial Outreach - Introduction to services
2. **Day 7**: Follow-up Week 1 - Key highlights and benefits
3. **Day 14**: Follow-up Week 2 - Success stories and testimonials
4. **Day 21**: Follow-up Week 3 - Final outreach with resources

**Smart Conditions**:
- Follow-ups only sent if no reply received
- Sequence stops automatically on reply or bounce
- Sequence stops on unsubscribe

### 4. Email Status Tracking

Comprehensive tracking for all emails:

- **OPENED**: Email was opened by recipient
- **CLICKED**: Link in email was clicked
- **BOUNCED**: Email bounced (hard or soft)
- **NOT_OPENED**: Email sent but not opened
- **REPLIED**: Recipient replied to email
- **SENT**: Email successfully sent
- **DELIVERED**: Email delivered to inbox

### 5. Email Signatures

Each company has a professionally formatted HTML email signature:

**Survey Fieldwork Signature**:
```
Best regards,
Indira
Business Development Manager
Survey Fieldwork
A Division of Cogentix Research Pvt Ltd

📧 indira@surveyfieldwork.com
🌐 surveyfieldwork.com
📍 Kolkata, West Bengal, India
```

**Cogentix Research Signature**:
```
Best regards,
Meera
Senior Research Consultant
Cogentix Research Pvt Ltd

📧 meera@cogentixresearch.com
🌐 cogentixresearch.com
📍 Kolkata, West Bengal, India
```

### 6. Automatic Bounce Handling

When an email bounces:
1. Recipient status automatically updated to "BOUNCED"
2. Campaign sequence stopped for that recipient
3. Send status updated to "BOUNCED"
4. Bounce timestamp recorded

## API Endpoints

### List Services
```http
GET /api/campaigns/automation/services
```
Lists all services from both companies.

**Response**:
```json
{
  "success": true,
  "services": {
    "surveyfieldwork": [...],
    "cogentixresearch": [...]
  }
}
```

### Get Service Details
```http
GET /api/campaigns/automation/services/{company}/{service_id}
```
Get detailed information about a specific service.

**Parameters**:
- `company`: "surveyfieldwork" or "cogentixresearch"
- `service_id`: Service identifier (e.g., "audience_sampling")

### Create Automated Campaign
```http
POST /api/campaigns/automation/campaigns
```
Create a campaign with automatic weekly follow-ups.

**Request Body**:
```json
{
  "company": "surveyfieldwork",
  "campaign_name": "Q1 2024 Outreach",
  "recipients": [
    {
      "email": "john.doe@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "company": "Acme Corp",
      "title": "Research Director",
      "custom_variables": {
        "industry": "Technology"
      }
    }
  ],
  "start_immediately": false
}
```

**Response**:
```json
{
  "success": true,
  "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
  "campaign_name": "Q1 2024 Outreach",
  "company": "surveyfieldwork",
  "from_email": "indira@surveyfieldwork.com",
  "from_name": "Indira",
  "recipients_added": 1,
  "sequence_steps": 4,
  "status": "draft",
  "message": "Campaign created successfully with weekly follow-up sequence"
}
```

### Process Tracking Events
```http
POST /api/campaigns/automation/tracking/events
```
Process bulk email tracking events.

**Request Body**:
```json
{
  "events": [
    {
      "email": "john.doe@example.com",
      "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
      "event": "opened",
      "timestamp": "2024-01-15T10:30:00Z",
      "send_id": "60f7b3c9e4b0c8a5d8f9e1a3"
    },
    {
      "email": "jane.smith@example.com",
      "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
      "event": "bounced",
      "timestamp": "2024-01-15T10:31:00Z"
    }
  ]
}
```

### Mark as Bounced
```http
POST /api/campaigns/automation/tracking/bounce/{campaign_id}/{email}
```
Mark a specific recipient as bounced.

**Response**:
```json
{
  "success": true,
  "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
  "email": "john.doe@example.com",
  "status": "bounced",
  "message": "Recipient john.doe@example.com marked as bounced"
}
```

### Get Campaign Report
```http
GET /api/campaigns/automation/campaigns/{campaign_id}/report
```
Get comprehensive status report with tracking metrics.

**Response**:
```json
{
  "success": true,
  "report": {
    "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
    "campaign_name": "Q1 2024 Outreach",
    "status": "active",
    "from_email": "indira@surveyfieldwork.com",
    "recipient_status": {
      "total": 100,
      "pending": 20,
      "in_sequence": 50,
      "completed": 15,
      "replied": 8,
      "bounced": 5,
      "unsubscribed": 2
    },
    "send_status": {
      "total_sends": 150,
      "sent": 140,
      "opened": 80,
      "clicked": 20,
      "bounced": 5,
      "not_opened": 55
    },
    "rates": {
      "open_rate": 57.14,
      "click_rate": 14.29,
      "bounce_rate": 3.33,
      "reply_rate": 8.0
    }
  }
}
```

### Test Email Rendering
```http
POST /api/campaigns/automation/test-email-render
```
Preview email templates with sample data.

**Request Body**:
```json
{
  "company": "surveyfieldwork",
  "template_name": "initial_outreach",
  "variables": {
    "first_name": "John",
    "company": "Acme Corp"
  }
}
```

## CLI Commands

The system includes a command-line interface for testing and management:

### List All Services
```bash
python -m backend.campaigns.automation list-services
```

### Create Sample Campaign
```bash
# For Survey Fieldwork
python -m backend.campaigns.automation create-campaign --company surveyfieldwork

# For Cogentix Research
python -m backend.campaigns.automation create-campaign --company cogentixresearch
```

### View Campaign Report
```bash
python -m backend.campaigns.automation report <campaign_id>
```

## Implementation Files

### Backend Files Created

1. **`backend/campaigns/services_config.py`**
   - Defines services for both companies
   - Includes sender emails and signatures
   - Helper functions for service lookup

2. **`backend/campaigns/email_templates.py`**
   - Email templates for initial outreach and follow-ups
   - Template rendering with variable substitution
   - Signature injection

3. **`backend/campaigns/automation.py`**
   - Campaign automation logic
   - Tracking event processing
   - Bounce status updates
   - Campaign reporting

4. **`backend/routers/campaign_automation.py`**
   - REST API endpoints
   - Request/response models
   - Integration with FastAPI

### Key Models (Existing)

The system uses existing campaign models from `backend/campaigns/models.py`:

- **Campaign**: Campaign definition with sequence steps
- **CampaignRecipient**: Individual recipient tracking
- **CampaignSend**: Email send history and tracking
- **EmailTemplate**: Reusable email templates

### Enums (Existing)

- **RecipientStatus**: pending, in_sequence, replied, **bounced**, completed, etc.
- **SendStatus**: queued, sent, delivered, opened, clicked, **bounced**, failed

## Database Collections

### `campaigns`
Campaign definitions and settings.

### `campaign_recipients`
Individual recipients with status tracking.

### `campaign_sends`
Email send history with tracking data.

### `email_templates`
Reusable email templates.

## Usage Examples

### Example 1: Create Survey Fieldwork Campaign

```python
from backend.campaigns.automation import CampaignAutomation

automation = CampaignAutomation()

recipients = [
    {
        "email": "director@research-agency.com",
        "first_name": "Sarah",
        "last_name": "Johnson",
        "company": "Global Research Agency",
        "title": "Research Director",
        "custom_variables": {
            "industry": "Market Research"
        }
    }
]

campaign_id = automation.create_outreach_campaign(
    company="surveyfieldwork",
    campaign_name="Market Research Agencies - Q1 2024",
    recipients=recipients,
    start_immediately=True
)
```

### Example 2: Track Email Events

```python
tracking_events = [
    {
        "email": "director@research-agency.com",
        "campaign_id": campaign_id,
        "event": "opened",
        "timestamp": datetime.utcnow()
    }
]

automation.process_email_tracking_updates(tracking_events)
```

### Example 3: Handle Bounces

```python
bounce_events = [
    {
        "email": "invalid@example.com",
        "campaign_id": campaign_id,
        "event": "bounced",
        "timestamp": datetime.utcnow()
    }
]

automation.process_email_tracking_updates(bounce_events)
# Automatically updates recipient status to "BOUNCED"
```

### Example 4: Get Campaign Metrics

```python
report = automation.get_campaign_status_report(campaign_id)

print(f"Open Rate: {report['rates']['open_rate']}%")
print(f"Bounce Rate: {report['rates']['bounce_rate']}%")
print(f"Bounced Recipients: {report['recipient_status']['bounced']}")
```

## Email Template Variables

Each template supports these personalization variables:

- `{{first_name}}` - Recipient's first name
- `{{last_name}}` - Recipient's last name
- `{{company}}` - Recipient's company name
- `{{title}}` - Recipient's job title
- `{{industry}}` - Industry (from custom_variables)
- `{{signature}}` - Email signature (auto-injected)

## Security & Compliance

- **GDPR Compliant**: Unsubscribe links in all emails
- **Bounce Handling**: Automatic removal from sequences
- **Rate Limiting**: Configurable daily/hourly send limits
- **Tracking Privacy**: Transparent tracking pixels
- **Data Encryption**: Secure storage of recipient data

## Best Practices

1. **Always test templates** before launching campaigns
2. **Use personalization variables** for better engagement
3. **Monitor bounce rates** and update lists regularly
4. **Respect unsubscribes** immediately
5. **Track metrics** to optimize future campaigns
6. **Segment audiences** for relevant messaging

## Troubleshooting

### Campaign not sending emails
- Check campaign status is "active"
- Verify mailbox_id is valid
- Check daily/hourly send limits

### Bounces not updating
- Ensure tracking events include correct campaign_id and email
- Verify event type is exactly "bounced"
- Check MongoDB connection

### Templates not rendering
- Verify all required variables are provided
- Check template exists in database
- Test with `/test-email-render` endpoint

## Support

For issues or questions:
- Email: indira@surveyfieldwork.com (Survey Fieldwork)
- Email: meera@cogentixresearch.com (Cogentix Research)
