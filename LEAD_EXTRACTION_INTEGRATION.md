# Lead Extraction Integration - Mail Segregation Agent

## Overview

The Mail Segregation Agent has been updated to include **comprehensive lead extraction functionality** that automatically extracts leads from incoming emails and creates lead documents in the leads database.

## Key Features

### 1. Lead Extraction from Emails
- **Automatic Processing**: Uses Gemini AI to intelligently extract lead information from email bodies
- **Smart Detection**: Only creates leads when both name and email are found (maintains data quality)
- **Batch Processing**: Processes emails in configurable batches for efficiency
- **Confidence Scoring**: Each extracted lead includes a confidence score

### 2. Dual Storage Strategy
Extracted leads are stored in TWO locations for different purposes:

#### Location 1: `leads.leads` (Primary Leads Database)
```json
{
  "_id": ObjectId(),
  "name": "John Doe",
  "email": "john@example.com",
  "company": "Acme Corp",
  "title": "Sales Manager",
  "phone": "+1-234-567-8900",
  "linkedin": "https://linkedin.com/in/johndoe",
  "website": "https://acme.com",
  "location": "San Francisco, CA, USA",
  "source_emails": ["email_id_1", "email_id_2"],  # All emails this lead came from
  "extracted_at": "2024-01-15T10:30:00Z",
  "confidence": 0.85,
  "last_updated": "2024-01-15T10:30:00Z"
}
```

#### Location 2: `email_automation.email_leads` (Email-to-Lead Mapping)
```json
{
  "_id": ObjectId(),
  "lead_id": "65abc123...",  # Reference to leads.leads
  "email_id": "65def456...",  # Reference to email_metadata
  "name": "John Doe",
  "email": "john@example.com",
  "company": "Acme Corp",
  "title": "Sales Manager",
  "extracted_at": "2024-01-15T10:30:00Z",
  "source_email": "john@acme.com",
  "source_subject": "Meeting Follow-up"
}
```

### 3. Email Metadata Tracking
Updated email records include extraction metadata:

```json
{
  "_id": ObjectId(),
  "subject": "...",
  "from_email": "...",
  "body": "...",
  "lead_extracted": true,           // ✅ NEW - tracks extraction status
  "lead_id": "65abc123...",         // ✅ NEW - reference to created lead
  "lead_extraction_date": "2024-01-15T10:30:00Z",  // ✅ NEW - when extracted
  "ai_classification_status": "classified"         // EXISTING - classification
}
```

### 4. Extraction Logging
All lead extractions are logged for auditing:

```json
{
  "_id": ObjectId(),
  "email_id": "65def456...",
  "lead_id": "65abc123...",
  "extraction_date": "2024-01-15T10:30:00Z",
  "status": "success"
}
```

## Database Collections Used

| Collection | Database | Purpose |
|-----------|----------|---------|
| `email_metadata` | `torpedo_gmail` | Source emails with `lead_extracted` tracking |
| `email_leads` | `email_automation` | Email-to-lead mapping and quick lookups |
| `classified_emails` | `email_automation` | Classification results storage |
| `leads` | `leads` | Primary lead documents (created/updated) |
| `lead_extraction_logs` | `leads` | Extraction history and audit trail |
| `mail_summaries` | `email_automation` | Generated email segment summaries |

## API Methods

### Extract Leads Batch
```python
# Start lead extraction for all emails
result = await agent.extract_leads_from_emails(batch_size=50)
```

Returns:
```json
{
  "success": true,
  "total_emails": 1000,
  "extracted": 850,
  "failed": 150,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Extract Single Lead
```python
lead = await agent._extract_lead_from_email(email_document)
if lead:
    lead_id = await agent._create_or_update_lead(lead)
```

### Get Lead Extraction Stats
```python
stats = agent.get_lead_extraction_stats()
```

Returns:
```json
{
  "total_emails": 1000,
  "emails_with_leads": 850,
  "pending_extraction": 150,
  "extraction_percentage": 85.0,
  "total_leads_created": 650,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Mark Email as Lead Extracted
```python
success = await agent.mark_email_as_lead_extracted(email_id, lead_id)
```

## Gemini AI Integration

The lead extraction uses the **Gemini Rotator** for intelligent extraction:

```python
prompt = """
Extract lead information from this email. Return JSON only.

FROM: john@acme.com (John Doe)
SUBJECT: Meeting Follow-up
BODY: [email body...]

Extract if present: name, email, company, title, phone, linkedin, website, location.

Return JSON:
{
    "name": "Full Name",
    "email": "email@example.com",
    "company": "Company Name",
    "title": "Job Title",
    "phone": "+1-234-567-8900",
    "linkedin": "https://linkedin.com/in/profile",
    "website": "https://company.com",
    "location": "City, State, Country",
    "confidence": 0.85
}
"""
```

**Key Features:**
- 7 free-tier Gemini accounts with automatic rotation
- 15 RPM per account = 105 RPM total
- 1000 requests/day per account = 7000/day total
- Automatic fallback on quota exhaustion

## Workflow

### 1. Email Arrives
```
Gmail → webhook → email_metadata (torpedo_gmail)
  ↓
  ai_classification_status: "pending"
  lead_extracted: false
```

### 2. Mail Segregation Agent Processes
```
Mail Segregation Agent
  ↓
  1. Extract contacts from email body
  2. Use Gemini to intelligently extract lead data
  3. Create lead in leads.leads if valid
  4. Update email_leads mapping
  5. Mark email as lead_extracted = true
  6. Log to lead_extraction_logs
```

### 3. Results Stored in Multiple Collections
```
leads.leads (primary lead document)
  ↓
email_automation.email_leads (quick lookup)
  ↓
email_automation.classified_emails (if classified)
  ↓
torpedo_gmail.email_metadata (updated with lead_id)
```

## Data Quality Controls

### Validation Rules
1. **Minimum Fields**: Name AND email required (other fields optional)
2. **Confidence Threshold**: Default 0.8 confidence score
3. **Duplicate Prevention**: Checks email to avoid duplicate leads
4. **Source Tracking**: Maintains list of all emails for each lead

### Error Handling
- Invalid JSON responses: Logged and skipped
- Missing fields: Gracefully handled
- Gemini API failures: Logged with retry capability
- Database errors: Logged and counted as failed

## Configuration

### Environment Variables
```bash
# Gemini API Keys (managed by rotator)
GEMINI_API_KEYS=key1,key2,key3,key4,key5,key6,key7

# MongoDB
MONGO_URI=mongodb://localhost:27017/

# Lead Extraction
LEAD_EXTRACTION_BATCH_SIZE=50
LEAD_EXTRACTION_CONFIDENCE_THRESHOLD=0.8
```

### Batch Processing
```python
# Process 50 emails at a time
await agent.extract_leads_from_emails(batch_size=50)

# Each batch:
# - Uses Gemini rotator (automatic key rotation)
# - Updates email_metadata with lead references
# - Creates/updates leads in leads database
# - Logs all extractions for audit
```

## Performance Metrics

### Capacity
- **Gemini API**: 7000 requests/day total
- **Batch Size**: 50 emails per batch
- **Max Daily**: ~140 batches/day
- **Leads Created**: 50-100 per batch (average)

### Processing Time
- **Per Email**: ~2-3 seconds (with Gemini API call)
- **Per Batch (50)**: ~100-150 seconds
- **Parallel Batches**: 1 at a time (sequential to respect rate limits)

## Monitoring

### Key Metrics to Track
1. **Extraction Rate**: `emails_with_leads / total_emails`
2. **Lead Quality**: Number of duplicate emails → same lead
3. **API Usage**: Requests per day (tracked by rotator)
4. **Processing Time**: Time per batch

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Low extraction rate | Small email bodies | Increase confidence threshold inspection |
| Duplicate leads | No deduplication check | Query by email before creating |
| API rate limits | Too many requests | Reduce batch size or add delays |
| Missing fields | Gemini not finding | Adjust prompt or allow partial extraction |

## Integration Points

### 1. Gemini Rotator
```python
from backend.leads.gemini_rotator import get_rotator
rotator = get_rotator()  # Returns rotated API key
```

### 2. Mail Segregation Agent
```python
from backend.agents.mail_segregation_agent import get_mail_segregation_agent
agent = get_mail_segregation_agent()
await agent.extract_leads_from_emails()
```

### 3. Lead Enrichment
After extraction, leads can be enriched:
```python
from backend.leads.gemini_enrichment import enrich_lead
await enrich_lead(lead_id)  # Further enrich with Gemini
```

## Next Steps

1. **Schedule Lead Extraction**: Set up cron job to run extraction every 6 hours
2. **Monitor Metrics**: Track extraction success rate and lead quality
3. **Tune Prompts**: Adjust Gemini prompt based on extraction results
4. **Lead Enrichment**: Use extracted leads with enrichment pipeline
5. **Dashboard**: Create dashboard to visualize lead extraction metrics

## Files Modified

- `backend/agents/mail_segregation_agent.py`: Added 7 new methods for lead extraction
- Database collections: Using existing infrastructure, no new collections created

## Verification

Run the verification script to test lead extraction:
```bash
python backend/agents/mail_segregation_verification.py
```

This will verify:
- Gemini rotator integration
- Database connectivity
- Lead extraction methods
- Storage locations
- Error handling
