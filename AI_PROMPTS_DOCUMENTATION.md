# Campaign Platform - AI Prompt Documentation
## Complete Reference for All API Prompts

Generated: January 26, 2026

---

## 📊 System Overview

### Cost Breakdown
- **Gemini (FREE)**: 7 accounts × 15 RPM = 105 RPM total, 7,000 requests/day
- **OpenAI (PAID)**: ~$90-120/month for web search only
- **Hunter.io (Optional)**: $99/month for email pattern discovery
- **Total**: $117/month ($0.0039/lead) - 93% savings from $1,650/month

---

## 🤖 API Engines

### 1. Gemini 2.0-Flash (FREE TIER)
**Provider**: Google  
**Capacity**: 7 accounts, 15 RPM per key, 1,000 requests/day per key  
**Cost**: $0/month  
**Use Case**: Email classification, lead enrichment, contact extraction

#### Available Prompts:
1. `gemini_classify_lead` - Real-time lead categorization
2. `gemini_enrich_lead` - Inferred business intelligence
3. `gemini_extract_contacts` - Contact info parsing
4. `gemini_summarize_email` - Email analysis with sentiment
5. `gemini_segment_email` - Quick email segmentation

---

### 2. OpenAI GPT-4o-mini (PAID)
**Provider**: OpenAI  
**Cost**: ~$0.00015 per input token, ~$0.0006 per output token  
**Monthly Cost**: $90-120 (primarily for web search)  
**Use Case**: Lead classification (legacy), web search queries

#### Available Prompts:
1. `lead_classification` - Original lead enrichment prompt
2. `openai_web_search` - Web search query generation (uses web_search_preview tool)

---

### 3. Perplexity (OPTIONAL)
**Provider**: Perplexity AI  
**Cost**: ~$0.005 per request ($5-15/month)  
**Use Case**: Company discovery, market research

#### Available Prompts:
1. `perplexity_company_discovery` - Target company discovery

---

## 📝 Detailed Prompt Specifications

### GEMINI PROMPTS

#### 1. gemini_classify_lead
**Purpose**: Classify leads into CLIENT, VENDOR, RECRUITER, INTERNAL, or SPAM  
**Model**: gemini-2.0-flash  
**Temperature**: 0.3 (deterministic)  
**Max Tokens**: 500  
**Cost**: FREE  

**System Prompt**:
```
You are a B2B lead classification expert. Analyze lead information and classify into appropriate categories.

Output JSON ONLY:
{
  "category": "CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM",
  "confidence": 0.0-1.0,
  "department": "Sales|Marketing|Engineering|HR|Finance|Operations|Legal|Other",
  "seniority": "C-Level|VP|Director|Manager|IC|Entry|Unknown",
  "reasoning": "brief explanation",
  "buying_intent": 0.0-1.0,
  "priority": "HIGH|MEDIUM|LOW"
}

Classification rules:
- CLIENT: Shows buying intent, product interest, or business opportunity
- VENDOR: Offering services/products, partnership proposals
- RECRUITER: Job opportunities, recruitment outreach
- INTERNAL: Company communications, team emails
- SPAM: Unsolicited marketing, low-value content

Buying Intent: 0=no interest, 1=ready to buy. Base on language urgency and specificity.
```

**User Template**:
```
Classify this lead:
Email: {email}
Name: {full_name}
Title: {title}
Company: {company}
Subject: {email_subject}
Body: {email_body}

Respond with JSON only.
```

**Used By**: `backend/leads/gemini_enrichment.py::classify_lead()`

---

#### 2. gemini_enrich_lead
**Purpose**: Infer additional business intelligence about leads  
**Model**: gemini-2.0-flash  
**Temperature**: 0.7 (more creative)  
**Max Tokens**: 700  
**Cost**: FREE  

**System Prompt**:
```
You are a B2B lead intelligence expert. Enrich leads with inferred business information.

Output JSON ONLY:
{
  "title_variations": ["alternative title 1", "alternative title 2"],
  "inferred_skills": ["skill 1", "skill 2", "skill 3"],
  "industry_vertical": "industry name",
  "company_size_estimate": "Startup|SMB|Mid-Market|Enterprise",
  "likely_pain_points": ["pain point 1", "pain point 2"],
  "engagement_angle": "how to approach this lead"
}

Be specific and actionable. Base inferences on typical patterns for this role/company type.
```

**User Template**:
```
Enrich this lead:
Title: {title}
Company: {company}
LinkedIn: {linkedin_url}
Website: {company_website}

Return JSON only.
```

**Used By**: `backend/leads/gemini_enrichment.py::enrich_lead()`

---

#### 3. gemini_extract_contacts
**Purpose**: Extract structured contact information from email bodies  
**Model**: gemini-2.0-flash  
**Temperature**: 0.5 (balanced)  
**Max Tokens**: 1000  
**Cost**: FREE  

**System Prompt**:
```
Extract all contact information from email content.

Output JSON ONLY:
{
  "contacts": [
    {
      "name": "full name",
      "title": "job title",
      "email": "email address",
      "phone": "phone number",
      "company": "company name"
    }
  ],
  "primary_contact": {...},
  "signature_extracted": true/false
}

Extract from:
- Email signature
- Body mentions
- CC/BCC references
- Contact cards

Mark primary_contact as most senior or relevant person.
Leave empty fields as null.
```

**User Template**:
```
Extract contacts from this email:

{email_body}

Return JSON only.
```

**Used By**: 
- `backend/leads/gemini_enrichment.py::extract_contact_info()`
- `backend/leads/email_processor.py::process_email()`

---

#### 4. gemini_summarize_email
**Purpose**: Intelligent email summarization with sentiment and urgency analysis  
**Model**: gemini-2.0-flash  
**Temperature**: 0.7  
**Max Tokens**: 800  
**Cost**: FREE  

**System Prompt**:
```
Analyze and summarize email content with business insights.

Output JSON ONLY:
{
  "summary": "2-3 sentence overview",
  "key_points": ["point 1", "point 2"],
  "action_items": ["action 1", "action 2"],
  "sentiment": "POSITIVE|NEUTRAL|NEGATIVE",
  "urgency": "HIGH|MEDIUM|LOW",
  "contains_offer": true/false,
  "next_steps": "recommended response"
}

Focus on business relevance and actionable insights.
```

**User Template**:
```
Summarize this email:

Subject: {subject}
Body: {body}

Return JSON only.
```

**Used By**:
- `backend/leads/gemini_enrichment.py::summarize_email()`
- `backend/leads/email_processor.py::process_email()`

---

#### 5. gemini_segment_email
**Purpose**: Quick email categorization (fastest prompt)  
**Model**: gemini-2.0-flash  
**Temperature**: 0.3 (deterministic)  
**Max Tokens**: 200  
**Cost**: FREE  
**Latency**: ~2 seconds

**System Prompt**:
```
Quickly segment email into appropriate category.

Output JSON ONLY:
{
  "segment": "CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explanation"
}

Definitions:
- CLIENT: Potential customer, inquiry, business opportunity
- VENDOR: Services/products offered, partnerships
- RECRUITER: Job opportunities, hiring outreach
- INTERNAL: Company communications, team updates
- SPAM: Unsolicited marketing, irrelevant content
```

**User Template**:
```
Segment this email:

From: {sender}
Subject: {subject}
Body (first 500 chars): {body}

Return JSON only.
```

**Used By**:
- `backend/leads/gemini_enrichment.py::segment_email()`
- `backend/leads/email_processor.py::process_email()`

---

### OPENAI PROMPTS

#### 1. openai_web_search
**Purpose**: Generate effective web search queries for lead discovery  
**Model**: gpt-4o-mini  
**Temperature**: 0.5  
**Max Tokens**: 300  
**Cost**: ~$0.001-0.003 per request  
**Tool**: Uses `web_search_preview` for real-time web results

**System Prompt**:
```
You are a B2B lead researcher. Generate effective web search queries to find target prospects.

Format JSON ONLY:
{
  "queries": ["query 1", "query 2", "query 3"],
  "intent": "lead generation|company discovery|competitor research",
  "expected_results": "what we're looking for in results"
}

Create specific, targeted queries that will yield relevant B2B leads.
```

**User Template**:
```
Generate search queries to find leads:
Industry: {industry}
Company size: {company_size}
Location: {location}
Criteria: {criteria}

Return JSON with 3 search queries.
```

**Used By**: `backend/leads/router.py::run_web_search_job()`

---

#### 2. lead_classification (Legacy)
**Purpose**: Original lead enrichment (being phased out in favor of Gemini)  
**Model**: gpt-4o-mini  
**Temperature**: 0.1  
**Max Tokens**: 300  
**Cost**: ~$0.001-0.002 per request  

**Reason for Phasing Out**: Gemini FREE provides identical functionality at $0 cost

---

### PERPLEXITY PROMPTS

#### perplexity_company_discovery
**Purpose**: Discover target companies matching specific criteria  
**Model**: sonar  
**Temperature**: 0.2  
**Max Tokens**: 2000  
**Cost**: ~$0.005 per request  

**System Prompt**:
```
You are a B2B market research expert. Your task is to discover and list companies that match specific targeting criteria.

Output Format: Return a JSON array of companies with the following structure:
[
  {
    "name": "Company Name",
    "domain": "company.com",
    "industry": "Industry/Sector",
    "size": "Startup|SMB|Mid-Market|Enterprise",
    "headquarters": "City, Country",
    "description": "Brief 1-line description"
  }
]

Rules:
- Only include real, verifiable companies
- Focus on companies likely to have the requested decision-makers
- Prioritize companies with active hiring or growth signals
- Include a mix of company sizes unless specified
- Ensure domain is accurate (verify mentally before including)
- Do NOT include companies that have shut down or been acquired
```

**User Template**:
```
Find {count} companies matching these criteria:
Industry: {industry}
Location: {location}
Additional criteria: {criteria}

Return ONLY a valid JSON array, no other text.
```

---

## 🔄 Workflow Examples

### Workflow 1: Email Processing Pipeline
```
Email from mail_pool
    ↓
[Step 1] gemini_segment_email
    Cost: $0 | Time: ~2s
    Output: segment, confidence
    ↓
[Step 2] gemini_extract_contacts
    Cost: $0 | Time: ~2s
    Output: contacts[], primary_contact
    ↓
[Step 3] gemini_summarize_email
    Cost: $0 | Time: ~2s
    Output: summary, sentiment, urgency
    ↓
[Step 4] OPTIONAL: gemini_classify_lead (if high priority)
    Cost: $0 | Time: ~2s
    Output: category, buying_intent, priority
    ↓
Store in classified_gmail collection
Total Cost: $0
Total Time: ~6-8 seconds
```

### Workflow 2: Lead Enrichment
```
Lead from CSV
    ↓
[Check Company Cache]
    Cache Hit? → Skip to Step 2
    Cache Miss? → Continue
    ↓
[Step 1] Cache lookup (90-day TTL)
    Cost: $0 | Hit Rate: 70-90%
    ↓
[Step 2] gemini_classify_lead
    Cost: $0
    Output: category, department, seniority, buying_intent
    ↓
[Step 3] gemini_enrich_lead
    Cost: $0
    Output: title_variations, skills, industry, pain_points
    ↓
[Step 4] Store company in cache (90-day TTL)
    Cost: $0
    ↓
Store lead in leads_raw collection
Total Cost: $0
```

### Workflow 3: Web Search for Leads
```
Lead generation request
    ↓
[Step 1] openai_web_search (Generate queries)
    Model: gpt-4o-mini with web_search_preview
    Cost: ~$0.001-0.003
    Uses: openai_web_search prompt
    Output: 3 tailored search queries
    ↓
[Step 2] Execute web searches
    Uses: OpenAI web_search_preview tool
    Real-time results from web
    ↓
[Step 3] Parse and normalize results
    Extract: leads, companies, contacts
    ↓
Store results in leads_raw with source="openai_search"
Total Cost: ~$0.01-0.02 per search
```

---

## 📊 API Endpoints for Prompt Management

### View All Prompts
```bash
GET /settings/ai-prompts
Authorization: {session_token}

Returns: List of all prompts with current versions
```

### Get Specific Prompt
```bash
GET /settings/ai-prompts/{prompt_key}
Authorization: {session_token}

Example: /settings/ai-prompts/gemini_classify_lead

Returns: Prompt with version history
```

### Update Prompt
```bash
PUT /settings/ai-prompts/{prompt_key}
Authorization: {session_token}

Body:
{
  "system_prompt": "New system prompt text...",
  "user_prompt_template": "New user template with {variables}...",
  "model": "gemini-2.0-flash",
  "temperature": 0.3,
  "max_output_tokens": 500,
  "is_active": true
}

Returns: Confirmation with new version number
```

### Test Prompt
```bash
POST /settings/ai-prompts/{prompt_key}/test
Authorization: {session_token}

Body:
{
  "system_prompt": "...",  // Optional - use default if not provided
  "sample_lead": {         // Optional - uses random lead from DB
    "email": "john@techcorp.com",
    "full_name": "John Smith",
    "title": "VP Sales",
    "company": "TechCorp"
  }
}

Returns: {
  "success": true,
  "sample_lead": {...},
  "formatted_user_prompt": "...",
  "ai_response": "...",
  "tokens_used": 142,
  "model": "gemini-2.0-flash"
}
```

### Rollback to Previous Version
```bash
POST /settings/ai-prompts/{prompt_key}/rollback/{version}
Authorization: {session_token}

Example: /settings/ai-prompts/gemini_classify_lead/rollback/2

Returns: Confirmation with new version number
```

### View Prompt Documentation
```bash
GET /settings/ai-prompts-documentation
Authorization: {session_token}

Returns: Comprehensive documentation of all prompts and integration points
```

### View Prompt Usage Statistics
```bash
GET /settings/ai-prompts-usage?days=7
Authorization: {session_token}

Returns: Statistics on which prompts are used most and costs
```

---

## 🎯 Integration Points

### 1. Email Processor (`backend/leads/email_processor.py`)
**Module**: EmailProcessor class

Functions using prompts:
- `process_email()` 
  - Uses: gemini_segment_email, gemini_extract_contacts, gemini_summarize_email
- `move_to_leads()`
  - Uses: gemini_classify_lead (for full classification)

---

### 2. Gemini Enrichment (`backend/leads/gemini_enrichment.py`)
**Module**: Individual functions

Functions:
- `classify_lead()`
  - Prompt: gemini_classify_lead
  - Returns: category, confidence, department, seniority, buying_intent, priority

- `enrich_lead()`
  - Prompt: gemini_enrich_lead
  - Returns: title_variations, inferred_skills, industry, pain_points

- `extract_contact_info()`
  - Prompt: gemini_extract_contacts
  - Returns: contacts[], primary_contact

- `summarize_email()`
  - Prompt: gemini_summarize_email
  - Returns: summary, key_points, sentiment, urgency, action_items

- `segment_email()`
  - Prompt: gemini_segment_email
  - Returns: segment, confidence, reasoning

- `batch_categorize()`
  - Prompt: gemini_classify_lead
  - Returns: bulk categorization results

---

### 3. OpenAI Web Search (`backend/leads/router.py`)
**Function**: `run_web_search_job()`

- Generates search queries using: openai_web_search prompt
- Executes with: web_search_preview tool
- Returns: leads extracted from web search results

---

### 4. Historical Email Classifier (`backend/email_sync/historical_classifier.py`)
**Function**: `classify_email()`

- Prompt: lead_classification
- Legacy implementation (being phased out)
- Cost: ~$0.002 per email (expensive vs Gemini FREE)

---

## 💡 Usage Recommendations

### For Email Classification
✅ **ALWAYS use**: gemini_segment_email (fastest, FREE)  
❌ **NEVER use**: lead_classification (expensive, legacy)

### For Lead Enrichment
✅ **ALWAYS use**: gemini_classify_lead + gemini_enrich_lead (FREE)  
❌ **NEVER use**: openai lead_classification (expensive)

### For Web Search
✅ **USE**: openai_web_search (necessary - Gemini can't do web search)  
⚠️ **MINIMIZE**: Only use when no cached results available

### For Company Discovery
✅ **BEST**: Company cache (90-day TTL, FREE lookups)  
⚠️ **SECOND**: Email pattern system (database → website → Hunter.io → guess)  
❌ **LAST RESORT**: Perplexity (costly at $0.005/request)

---

## 📈 Cost Optimization Tips

1. **Maximize Cache Hit Rates**
   - Company cache should achieve 70-90% hit rate after 1 week
   - Email patterns should achieve 60%+ hit rate from mail_pool analysis

2. **Batch Operations**
   - Use `batch_categorize()` for bulk email processing (more efficient)
   - Process emails in batches of 50-100

3. **Selective Enrichment**
   - Only enrich HIGH and MEDIUM priority leads
   - Skip SPAM and INTERNAL segments

4. **Use Appropriate Models**
   - Gemini for classification/enrichment (FREE)
   - OpenAI only for web search (necessary)
   - Skip Perplexity if possible

5. **Monitor Usage**
   - Check `/settings/ai-prompts-usage` endpoint daily
   - Review cost trends and optimize

---

## 🔐 Security Notes

- All API keys stored in `torpedo_settings.app_settings` database
- Prompts are versioned with rollback capability
- All prompt tests are safe (no data saved)
- Sensitive fields masked in API responses

---

**Last Updated**: January 26, 2026  
**System Status**: ✅ All prompts active and optimized for hybrid Gemini + OpenAI system
