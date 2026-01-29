# Mail Segregation Agent - Lead Extraction Implementation

## 🎯 Executive Summary

The Mail Segregation Agent has been fully refactored to:

1. **✅ Use EXISTING storage infrastructure** (no new placeholder collections)
2. **✅ Add comprehensive lead extraction** from emails with Gemini AI
3. **✅ Create lead documents** in the leads database
4. **✅ Track extraction status** in email metadata
5. **✅ Maintain dual storage** for different use cases

## 📋 Changes Made

### 1. Database Reference Updates

**FROM (Incorrect Placeholder Collections)**
```python
mail_db = mongo_client["mail_pool"]
segregated_emails = mail_db["segregated_emails"]      # ❌ New placeholder
contact_extracted = mail_db["extracted_contacts"]     # ❌ New placeholder
mail_summaries = mail_db["summaries"]                 # ❌ New placeholder
```

**TO (Existing Infrastructure)**
```python
# Email source - existing with ai_classification_status
torpedo_gmail_db = mongo_client["torpedo_gmail"]
mail_pool_emails = torpedo_gmail_db["email_metadata"]

# Email automation - existing for classification & leads
email_automation_db = mongo_client["email_automation"]
email_leads = email_automation_db["email_leads"]           # Extract leads here
email_conversations = email_automation_db["email_conversations"]
classified_emails = email_automation_db["classified_emails"]  # Store classification

# Leads database - where actual lead documents live
leads_db = mongo_client.get_database("leads")
leads_collection = leads_db["leads"]                   # Create/update leads here
lead_extraction_logs = leads_db["lead_extraction_logs"] # Track extractions
```

### 2. New Data Classes Added

#### `ExtractedLead`
```python
@dataclass
class ExtractedLead:
    """Extracted lead from email"""
    name: str                      # Required
    email: str                     # Required
    company: str = ""              # Optional
    title: str = ""                # Optional
    phone: str = ""                # Optional
    linkedin: str = ""             # Optional
    website: str = ""              # Optional
    location: str = ""             # Optional
    source_email_id: str = ""      # Which email this came from
    source_email_from: str = ""    # Sender of source email
    source_email_subject: str = "" # Subject of source email
    extracted_at: str = ""         # When extracted
    confidence: float = 0.8        # Gemini confidence score
```

### 3. New Methods Added to MailSegregationAgent

| Method | Purpose | Storage |
|--------|---------|---------|
| `extract_leads_from_emails(batch_size=50)` | Batch extract all emails | Uses `email_automation.email_leads` |
| `_extract_lead_from_email(email)` | Use Gemini to extract lead | Calls Gemini API |
| `_create_or_update_lead(lead_data)` | Create/update in leads DB | Writes to `leads.leads` |
| `mark_email_as_lead_extracted(email_id, lead_id)` | Track extraction status | Updates `email_metadata.lead_extracted` |
| `get_lead_extraction_stats()` | Get extraction metrics | Reads from collections |

### 4. Email Metadata Updates

Emails now include extraction tracking:
```json
{
  "_id": ObjectId(),
  "subject": "...",
  "body": "...",
  "from_email": "...",
  
  // EXISTING - Classification
  "ai_classification_status": "classified",
  
  // ✅ NEW - Lead Extraction Tracking
  "lead_extracted": true,
  "lead_id": "65abc123...",
  "lead_extraction_date": "2024-01-15T10:30:00Z"
}
```

### 5. Lead Storage Locations

#### Location 1: `leads.leads` (Primary)
Used by lead enrichment, CRM integration, analytics
```json
{
  "_id": ObjectId("65abc123..."),
  "name": "John Doe",
  "email": "john@example.com",
  "company": "Acme Corp",
  "title": "Sales Manager",
  "source_emails": ["email_id_1", "email_id_2"],
  "extracted_at": "2024-01-15T10:30:00Z",
  "confidence": 0.85,
  "last_updated": "2024-01-15T10:30:00Z"
}
```

#### Location 2: `email_automation.email_leads` (Quick Lookup)
Used for email-to-lead mapping, automation rules
```json
{
  "_id": ObjectId("65def456..."),
  "lead_id": "65abc123...",
  "email_id": "65xyz789...",
  "name": "John Doe",
  "email": "john@example.com",
  "extracted_at": "2024-01-15T10:30:00Z",
  "source_email": "john@acme.com",
  "source_subject": "Meeting Follow-up"
}
```

#### Location 3: `leads.lead_extraction_logs` (Audit Trail)
Used for monitoring, debugging, analytics
```json
{
  "_id": ObjectId(),
  "email_id": "65xyz789...",
  "lead_id": "65abc123...",
  "extraction_date": "2024-01-15T10:30:00Z",
  "status": "success"
}
```

## 🔄 Workflow

### Email Processing Pipeline
```
Gmail Email Arrives
    ↓
torpedo_gmail.email_metadata
    ├─ ai_classification_status: "pending"
    └─ lead_extracted: false
    ↓
Mail Segregation Agent.extract_leads_from_emails()
    ├─ Call Gemini to extract lead data
    ├─ Create lead in leads.leads (if valid)
    ├─ Store mapping in email_automation.email_leads
    ├─ Log extraction to lead_extraction_logs
    └─ Update email_metadata with lead_id
    ↓
Email Now Has:
    ├─ lead_extracted: true
    ├─ lead_id: "65abc123..."
    └─ lead_extraction_date: "2024-01-15T10:30:00Z"
    ↓
Lead Now In leads.leads:
    ├─ name, email, company, title, etc.
    ├─ source_emails: [email_id_1, email_id_2, ...]
    └─ confidence: 0.85
```

## 📊 Data Quality Features

### Validation Rules
1. **Minimum Fields**: Both name AND email required
2. **Deduplication**: Checks if lead email already exists
3. **Source Tracking**: Maintains all emails that created a lead
4. **Confidence Scoring**: Each lead has 0.0-1.0 confidence score

### Example: Duplicate Lead Handling
```python
# First email from john@example.com
lead_id = await agent._create_or_update_lead(ExtractedLead(
    name="John Doe",
    email="john@example.com",
    company="Acme"
))
# Result: New lead created with source_emails: ["email_1"]

# Second email from john@example.com (same person)
lead_id = await agent._create_or_update_lead(ExtractedLead(
    name="John Doe",
    email="john@example.com",
    company="Acme Corp"  # Updated info
))
# Result: Same lead updated with source_emails: ["email_1", "email_2"]
#         company field updated to "Acme Corp"
```

## 🚀 Key Features

### 1. Intelligent Extraction with Gemini
```python
# Uses Gemini to parse email body and extract structured lead data
prompt = """
Extract lead information from email body.
Return JSON with: name, email, company, title, phone, linkedin, website, location

Only include fields that are clearly present in the email.
Include a confidence score (0.0-1.0).
"""
```

### 2. Batch Processing
```python
# Process emails in configurable batches
result = await agent.extract_leads_from_emails(batch_size=50)
# Returns: {success, total_emails, extracted, failed, timestamp}
```

### 3. Rate-Limited API Calls
Uses Gemini Rotator:
- 7 free-tier accounts
- 15 RPM per account = 105 RPM total
- 1000 requests/day per account = 7000/day total
- Automatic key rotation

### 4. Comprehensive Logging
```python
lead_extraction_logs.insert_one({
    "email_id": str(email["_id"]),
    "lead_id": lead_id,
    "extraction_date": datetime.utcnow(),
    "status": "success"
})
```

## 📈 Statistics & Monitoring

Get extraction statistics:
```python
stats = agent.get_lead_extraction_stats()
# Returns:
# {
#   "total_emails": 1000,
#   "emails_with_leads": 850,
#   "pending_extraction": 150,
#   "extraction_percentage": 85.0,
#   "total_leads_created": 650,
#   "timestamp": "2024-01-15T10:30:00Z"
# }
```

## 🔧 Configuration

### Environment Variables
```bash
# MongoDB
MONGO_URI=mongodb://localhost:27017/

# Gemini API Keys (managed by rotator)
GEMINI_API_KEYS=key1,key2,key3,key4,key5,key6,key7

# Extraction Settings
LEAD_EXTRACTION_BATCH_SIZE=50
LEAD_EXTRACTION_CONFIDENCE_THRESHOLD=0.8
```

## ✅ Verification

Run verification script to test all functionality:

```bash
python backend/agents/mail_segregation_verification.py
```

Tests performed:
- ✅ Database structure (correct collections)
- ✅ No placeholder collections
- ✅ Agent methods exist
- ✅ DataClasses are valid
- ✅ Gemini integration
- ✅ Lead creation logic

## 📝 Files Modified

| File | Changes |
|------|---------|
| `backend/agents/mail_segregation_agent.py` | Updated 5 database refs, added ExtractedLead class, added 5 new methods (250+ lines) |
| `backend/agents/mail_segregation_verification.py` | Created - verification script with 12 tests |
| `LEAD_EXTRACTION_INTEGRATION.md` | Created - comprehensive documentation |

## 🎯 Implementation Summary

### ✅ What Was Done
1. **Removed placeholder collections** - No new collections created
2. **Updated database references** - Using existing infrastructure
3. **Added lead extraction** - 5 new methods with Gemini integration
4. **Implemented storage strategy** - Dual location (leads.leads + email_automation.email_leads)
5. **Added tracking** - Updated email_metadata with lead_extracted flag
6. **Created logging** - lead_extraction_logs for audit trail
7. **Added statistics** - get_lead_extraction_stats() method
8. **Maintained quality** - Validation, deduplication, confidence scoring

### ✅ Integration Points
- **Gemini Rotator**: Automatic key rotation, rate limiting, quota management
- **Email Metadata**: Lead extraction status tracking
- **Lead Database**: Primary lead documents with source tracking
- **Email Automation**: Quick lookup and email-to-lead mapping

### ✅ Data Flow
```
Gmail → email_metadata → extract_leads_from_emails() → leads.leads
                             ↓
                      email_automation.email_leads
                             ↓
                      lead_extraction_logs (audit)
```

## 🚦 Next Steps

1. **Deploy**: Push changes to production
2. **Schedule**: Set up cron job: `*/6 * * * * python -m backend.agents.mail_segregation_agent`
3. **Monitor**: Track extraction metrics and lead quality
4. **Tune**: Adjust Gemini prompt based on results
5. **Enrich**: Use extracted leads with enrichment pipeline

## 📞 Support

For issues or questions:
1. Check [LEAD_EXTRACTION_INTEGRATION.md](LEAD_EXTRACTION_INTEGRATION.md) for detailed docs
2. Run verification script to test functionality
3. Check lead_extraction_logs for detailed audit trail
4. Monitor Gemini API quota usage with rotator
