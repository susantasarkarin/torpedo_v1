# Gemini Email Classification & Lead Extraction

## Overview

This system uses **Google Gemini 1.5 Flash** for email segregation and automatic lead extraction. It's designed to stay within the **free tier limits** by using multiple API key rotation.

## Free Tier Limits (per API key)

| Limit | Value |
|-------|-------|
| Requests Per Day (RPD) | 1,000 |
| Requests Per Minute (RPM) | 15 |
| Tokens Per Minute (TPM) | 1,000,000 |

With **10 API keys**, you can process up to **10,000 emails per day** for free.

## Features

### Email Segregation
Classifies emails into the following categories:
- **client** - Inbound emails from prospects/customers
- **vendor** - From suppliers, service providers, partners
- **internal** - Same company domain, team communications
- **promotional** - Marketing emails, newsletters
- **invoice** - Billing, payments, invoices
- **banking** - Bank communications
- **automated** - Auto-replies, notifications
- **spam** - Junk mail
- **others** - Cannot determine

### Lead Extraction
For sales-qualified emails (client category), automatically extracts:
- **Full Name**
- **First Name**
- **Last Name**
- **Email ID**
- **Website**
- **Domain**
- Job Title
- Company Name
- Phone Number
- LinkedIn URL

Extracted leads are automatically added to **Sales > Leads** section.

## Setup

### 1. Get Gemini API Keys

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Click "Get API Key" in the left sidebar
3. Create multiple API keys (recommended: 5-10 keys for production)
4. Copy each key

### 2. Configure Environment Variables

Add your API keys to `.env` file:

```bash
# Option 1: Comma-separated list
GEMINI_API_KEYS=key1,key2,key3,key4,key5

# Option 2: Numbered keys (supports up to 20)
GEMINI_API_KEY_1=AIza...
GEMINI_API_KEY_2=AIza...
GEMINI_API_KEY_3=AIza...
GEMINI_API_KEY_4=AIza...
GEMINI_API_KEY_5=AIza...

# Option 3: Single key (limited throughput)
GEMINI_API_KEY=AIza...

# Set Gemini as default provider
EMAIL_CLASSIFICATION_PROVIDER=gemini
```

### 3. Install Dependencies

```bash
cd backend
pip install google-generativeai google-genai
# or
pip install -r requirements.txt
```

### 4. Restart Backend

```bash
# Development
uvicorn main:app --reload

# Production
sudo systemctl restart backend
```

## API Endpoints

### Check Gemini Status
```http
GET /gemini/status
```
Returns API key availability and usage statistics.

### Classify Single Email
```http
POST /gemini/classify
Content-Type: application/json

{
    "email_id": "67890abcdef12345",
    "extract_leads": true
}
```

### Batch Classification (Background)
```http
POST /gemini/classify-batch
Content-Type: application/json

{
    "limit": 100,
    "internal_domains": ["yourcompany.com"],
    "extract_leads": true
}
```

### Get Classification Stats
```http
GET /gemini/stats
```

### Get Extracted Leads
```http
GET /gemini/extracted-leads?page=1&limit=50
```

### Get Gemini Configuration
```http
GET /gemini/config
```

### Get Usage Logs
```http
GET /gemini/usage-logs?page=1&limit=50
```

## How It Works

### Classification Pipeline

1. **Keyword Pre-Classification (FREE)**
   - First attempts to classify using keyword matching
   - Catches obvious categories like promotional, automated, spam
   - No API calls needed

2. **Gemini AI Classification**
   - If keyword confidence < 60%, uses Gemini 1.5 Flash
   - Determines category with confidence score
   - Identifies sales leads

3. **Lead Extraction**
   - For sales-qualified emails, extracts contact info
   - Uses signature parsing and AI extraction
   - Creates lead in database

4. **Lead Creation**
   - Automatically adds to `leads_enriched` collection
   - Appears in **Sales > Leads** UI
   - Links to source email

### Multi-Key Rotation

```
Request 1 → Key 1 ✓
Request 2 → Key 2 ✓
Request 3 → Key 3 ✓
...
Request 15 → Key 1 (if minute passed) or Key 2 ✓
```

The system:
- Tracks usage per key (RPM, RPD)
- Automatically rotates to next available key
- Marks exhausted keys and waits for reset
- Logs all usage to MongoDB

### Rate Limiting

To stay within 15 RPM per key:
- Batch processing uses 5-second delay between requests
- With 5 keys: ~60 emails/minute
- With 10 keys: ~120 emails/minute

## Database Collections

### `torpedo_gmail.gemini_usage_logs`
Tracks all Gemini API calls:
```json
{
    "key_id": "key_1",
    "model": "gemini-1.5-flash",
    "endpoint": "email_classify",
    "input_tokens": 250,
    "output_tokens": 50,
    "success": true,
    "timestamp": "2026-01-15T10:30:00Z"
}
```

### `torpedo_gmail.gemini_classification_logs`
Logs email classifications:
```json
{
    "email_id": "67890abcdef12345",
    "category": "client",
    "confidence": 0.92,
    "method": "gemini",
    "is_sales_lead": true
}
```

### `email_automation.email_extracted_leads`
Stores extracted leads:
```json
{
    "full_name": "John Smith",
    "first_name": "John",
    "last_name": "Smith",
    "email": "john@example.com",
    "website": "https://example.com",
    "domain": "example.com",
    "source": "email_extraction",
    "lead_stage": "leads"
}
```

## Cost Comparison

| Provider | Model | Cost per 1K emails |
|----------|-------|-------------------|
| Gemini | 1.5 Flash | **$0 (Free)** |
| OpenAI | GPT-4o-mini | ~$0.15 |
| OpenAI | GPT-4o | ~$5.00 |
| Anthropic | Claude 3.5 Sonnet | ~$3.00 |

## Troubleshooting

### "No Gemini API keys configured"
- Check `.env` file has `GEMINI_API_KEY` or `GEMINI_API_KEYS`
- Restart the backend after adding keys

### "All API keys exhausted"
- Add more API keys to increase throughput
- Wait for daily reset (24 hours from first use)
- Check `/gemini/status` for key availability

### "Rate limit reached"
- System automatically waits and retries
- Consider adding more API keys
- Reduce batch size for slower processing

### Lead not appearing in Sales > Leads
- Check if email was classified as "client"
- Verify lead extraction succeeded in logs
- Check for duplicate email addresses

## Monitoring

### Real-time Status
```bash
curl http://localhost:8000/gemini/status | jq
```

### Daily Usage Report
Check MongoDB:
```javascript
db.gemini_usage_logs.aggregate([
    { $match: { timestamp: { $gte: new Date(Date.now() - 86400000) } } },
    { $group: { _id: "$key_id", requests: { $sum: 1 }, tokens: { $sum: "$total_tokens" } } }
])
```

## Best Practices

1. **Use Multiple Keys**: Aim for 5-10 keys for production
2. **Monitor Usage**: Check `/gemini/status` regularly
3. **Batch Processing**: Use background batch for large volumes
4. **Keyword First**: Let keyword classification handle obvious cases
5. **Set Internal Domains**: Configure `internal_domains` to skip internal emails

## Files

- `backend/leads/gemini_wrapper.py` - Core Gemini API wrapper with key rotation
- `backend/leads/gemini_email_classifier.py` - Email classification and lead extraction
- `backend/routers/gemini_classification.py` - REST API endpoints
- `backend/leads/email_classifier.py` - Integrated tiered classification
