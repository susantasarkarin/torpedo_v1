# Mail Segregation Agent - Quick Reference

## What Changed?

### Database Collections (CORRECTED)
```python
# ✅ NOW USES EXISTING COLLECTIONS

# Source emails
torpedo_gmail.email_metadata          # Emails with ai_classification_status
  ├─ lead_extracted: boolean          # ✨ NEW field to track extraction
  ├─ lead_id: string                  # ✨ NEW field to reference lead
  └─ lead_extraction_date: datetime   # ✨ NEW field to track when

# Email automation
email_automation.email_leads          # Extracted leads (quick lookup)
email_automation.classified_emails    # Classification results
email_automation.email_conversations  # Email threads
email_automation.mail_summaries       # Mail summaries

# Leads database
leads.leads                           # Primary lead documents (created here)
leads.lead_extraction_logs            # Extraction audit trail
```

## Key New Methods

### 1. Extract All Leads Batch
```python
agent = get_mail_segregation_agent()
result = await agent.extract_leads_from_emails(batch_size=50)

# Returns:
{
  "success": true,
  "total_emails": 1000,
  "extracted": 850,
  "failed": 150,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### 2. Extract Single Lead
```python
email = mail_pool_emails.find_one({"_id": email_id})
lead = await agent._extract_lead_from_email(email)
# Returns: ExtractedLead or None
```

### 3. Create/Update Lead
```python
lead = ExtractedLead(
    name="John Doe",
    email="john@example.com",
    company="Acme Corp"
)
lead_id = await agent._create_or_update_lead(lead)
# Returns: string (lead document ID)
```

### 4. Get Stats
```python
stats = agent.get_lead_extraction_stats()
# Returns: {total_emails, emails_with_leads, extraction_percentage, ...}

stats = agent.get_segregation_stats()
# Returns: {total_emails, segregated_emails, segment_breakdown, ...}
```

## Data Classes

### ExtractedLead
```python
@dataclass
class ExtractedLead:
    name: str                      # Required: "John Doe"
    email: str                     # Required: "john@example.com"
    company: str = ""              # Optional: "Acme Corp"
    title: str = ""                # Optional: "Sales Manager"
    phone: str = ""                # Optional: "+1-234-567-8900"
    linkedin: str = ""             # Optional: "https://linkedin.com/in/..."
    website: str = ""              # Optional: "https://acme.com"
    location: str = ""             # Optional: "San Francisco, CA"
    source_email_id: str = ""      # From which email
    source_email_from: str = ""    # Sender address
    source_email_subject: str = "" # Email subject
    extracted_at: str = ""         # ISO datetime
    confidence: float = 0.8        # 0.0-1.0 score
```

## Workflow Example

```python
# 1. Get agent
agent = get_mail_segregation_agent()

# 2. Extract leads from all pending emails
result = await agent.extract_leads_from_emails(batch_size=50)
# - Finds all emails with lead_extracted != True
# - Calls Gemini to extract lead data
# - Creates leads in leads.leads
# - Updates email_metadata with lead_id
# - Logs to lead_extraction_logs

# 3. Check results
print(f"Extracted {result['extracted']} leads out of {result['total_emails']}")

# 4. Get statistics
stats = agent.get_lead_extraction_stats()
print(f"Lead extraction rate: {stats['extraction_percentage']}%")
```

## Database Query Examples

### Find Emails with Extracted Leads
```python
emails_with_leads = mail_pool_emails.find({"lead_extracted": True})
```

### Find Emails Pending Lead Extraction
```python
pending = mail_pool_emails.find({"lead_extracted": {"$ne": True}})
```

### Find All Leads
```python
leads = leads_collection.find({})
```

### Find Lead by Email
```python
lead = leads_collection.find_one({"email": "john@example.com"})
```

### Get Extraction Audit Trail
```python
logs = lead_extraction_logs.find({"status": "success"})
```

### Find Emails for a Specific Lead
```python
email_leads_mapping = email_leads.find({"lead_id": lead_id})
```

## Gemini Extraction Prompt

```
Extract lead information from this email. Return JSON only.

FROM: john@acme.com (John Doe)
SUBJECT: Meeting Follow-up
BODY: [email body...]

Extract if present: name, email, company, title, phone, linkedin, website, location.
If a field is not found, omit it from JSON.

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
```

## Configuration

### Environment Variables
```bash
# MongoDB
MONGO_URI=mongodb://localhost:27017/

# Gemini API Keys (automatic rotation)
GEMINI_API_KEYS=key1,key2,key3,key4,key5,key6,key7
```

### Batch Size
```python
# Process 50 emails per batch (configurable)
await agent.extract_leads_from_emails(batch_size=50)

# Larger batch = faster but more memory
# Smaller batch = slower but less memory
```

## Performance

### API Rate Limits
- 7 Gemini API keys
- 15 requests/minute per key = 105 RPM total
- 1000 requests/day per key = 7000/day total

### Processing Time
- Per email: ~2-3 seconds (API call included)
- Per batch (50): ~100-150 seconds
- Max daily: ~140 batches = 7000 emails

## Error Handling

### What Happens on Error?
```python
# Missing email body
lead = await agent._extract_lead_from_email(email)
# Returns: None (skipped)

# Invalid Gemini response
lead = await agent._extract_lead_from_email(email)
# Returns: None (skipped, error logged)

# Duplicate email
lead = await agent._create_or_update_lead(lead_data)
# Updates existing lead, adds to source_emails list

# Database error
lead_id = await agent._create_or_update_lead(lead_data)
# Exception raised, error logged
```

## Monitoring

### Track Extraction Progress
```python
# Check pending extractions
pending = mail_pool_emails.count_documents({"lead_extracted": {"$ne": True}})
print(f"Pending: {pending} emails")

# Check success rate
stats = agent.get_lead_extraction_stats()
print(f"Success rate: {stats['extraction_percentage']}%")
```

### View Audit Trail
```python
# Recent extractions
logs = lead_extraction_logs.find().sort("extraction_date", -1).limit(10)
for log in logs:
    print(f"{log['email_id']} -> {log['lead_id']}")
```

## Troubleshooting

### No leads being extracted
1. Check if emails have `body` field
2. Verify Gemini API keys are valid
3. Check `lead_extraction_logs` for errors
4. Increase batch size to test

### Duplicate leads being created
1. This is expected if different email addresses
2. Same email address = same lead (auto-deduped)
3. Check `leads_collection.distinct("email")` for duplicates

### High failure rate
1. Check email_body field exists
2. Verify Gemini API quota not exceeded
3. Check lead_extraction_logs for specific errors
4. Test with smaller batch size

### Memory issues
1. Reduce batch size (default 50)
2. Use: `await agent.extract_leads_from_emails(batch_size=20)`

## Integration

### With Lead Enrichment
```python
from backend.leads.gemini_enrichment import enrich_lead

# After extraction, enrich the lead
lead_id = await agent._create_or_update_lead(lead_data)
await enrich_lead(lead_id)  # Add more data
```

### With CRM
```python
# Push lead to CRM after extraction
lead = leads_collection.find_one({"_id": ObjectId(lead_id)})
await push_to_crm(lead)  # Your CRM integration
```

### With Email Automation
```python
# Use email_leads mapping for automation rules
mapping = email_leads.find_one({"lead_id": lead_id})
await send_follow_up_email(mapping["email"])
```

## Files

| File | Purpose |
|------|---------|
| `backend/agents/mail_segregation_agent.py` | Main agent with lead extraction |
| `backend/agents/mail_segregation_verification.py` | Test/verify implementation |
| `LEAD_EXTRACTION_INTEGRATION.md` | Detailed documentation |
| `MAIL_SEGREGATION_IMPLEMENTATION.md` | Implementation summary |

## Testing

Run verification:
```bash
python backend/agents/mail_segregation_verification.py
```

Expected output:
```
✅ PASS: torpedo_gmail.email_metadata exists
✅ PASS: email_automation collections exist
✅ PASS: leads database exists
✅ PASS: No placeholder collections in mail_pool
✅ PASS: Agent can be instantiated
✅ PASS: All required methods exist
✅ PASS: ExtractedLead dataclass is valid
...
```

## Scheduling

### Run Every 6 Hours
```bash
0 */6 * * * cd /path/to/project && python -m backend.agents.mail_segregation_agent
```

### Run Every Hour
```bash
0 * * * * cd /path/to/project && python -m backend.agents.mail_segregation_agent
```

## Support

See [LEAD_EXTRACTION_INTEGRATION.md](LEAD_EXTRACTION_INTEGRATION.md) for complete documentation.
