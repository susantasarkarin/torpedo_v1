# Python Scripts to n8n Workflows: Complete Conversion Guide

**Purpose:** Step-by-step guide for converting 100+ Python automation scripts to n8n visual workflows.

---

## Table of Contents

1. [Understanding n8n Basics](#understanding-n8n-basics)
2. [Conversion Strategy](#conversion-strategy)
3. [Common Patterns](#common-patterns)
4. [Script-by-Script Conversion](#script-by-script-conversion)
5. [Testing Workflows](#testing-workflows)
6. [Deployment](#deployment)

---

## Understanding n8n Basics

### What is n8n?

n8n is a visual workflow automation tool that lets you connect different services and automate tasks without writing code.

**Key Concepts:**
- **Workflows:** Visual flowcharts that define automation logic
- **Nodes:** Building blocks (triggers, actions, logic)
- **Connections:** Lines connecting nodes showing data flow
- **Credentials:** Stored API keys and connection details
- **Executions:** Each time a workflow runs

### n8n Node Types

| Node Type | Purpose | Examples |
|-----------|---------|----------|
| **Trigger** | Starts workflow | Schedule, Webhook, Email received |
| **Action** | Performs operation | HTTP Request, Database query, Send email |
| **Logic** | Controls flow | IF, Switch, Loop, Set |
| **Transform** | Data manipulation | Function, Code, Filter |
| **Integration** | External service | OpenAI, Gmail, Slack, MongoDB |

### Installing n8n

```bash
# Using npm
npm install -g n8n

# Or using Docker
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n

# Start n8n
n8n start
```

Access at: http://localhost:5678

---

## Conversion Strategy

### Step 1: Inventory Python Scripts

First, catalog all automation scripts:

```bash
cd /home/runner/work/campaign_platform/campaign_platform
find . -name "*.py" -path "*/scripts/*" -o -name "*_job.py" -o -name "*_cron.py"
```

Common script types in the codebase:

1. **Email Processing Scripts** (~15 scripts)
   - `email_classifier_vm.py`
   - `email_classifier_new.py`
   - `extract_all_gmail.py`
   - `gmail_router_vm.py`

2. **Survey Management Scripts** (~20 scripts)
   - `create_cint_entry_links_at_scale.py`
   - `fix_cpx_entry_links.py`
   - `test_survey_activation.py`
   - `clear_survey_pool.js`

3. **Data Sync Scripts** (~10 scripts)
   - `sync_vm_key.py`
   - `sync_vm_to_localhost.py`
   - `force_resync.py`

4. **Monitoring & Diagnostics** (~20 scripts)
   - `check_system_status.py`
   - `verify_vm_performance.py`
   - `monitor_api_usage.py`

5. **Scheduled Jobs** (~15 scripts)
   - `run_classification.py`
   - `run_websearch_job.py`
   - `generate_7day_test_report.py`

6. **Database Maintenance** (~10 scripts)
   - `setup_mongodb.py`
   - `update_openai_key.py`
   - `reset_test_data.py`

7. **Testing & Validation** (~15 scripts)
   - Various `test_*.py` files
   - Various `check_*.py` files

### Step 2: Prioritize Scripts

**Priority 1 - Critical Workflows (Convert First):**
- Email classification and routing
- Survey inventory sync
- Payment processing
- Lead enrichment

**Priority 2 - Regular Automation:**
- Scheduled reports
- Data cleanup
- Monitoring alerts
- Status checks

**Priority 3 - Ad-hoc & Testing:**
- One-time migration scripts
- Testing scripts
- Diagnostic tools

### Step 3: Conversion Process

For each script:

1. **Analyze:** Understand what it does
2. **Map:** Identify n8n nodes needed
3. **Build:** Create workflow in n8n UI
4. **Test:** Run with test data
5. **Deploy:** Activate workflow
6. **Monitor:** Check execution logs
7. **Decommission:** Archive Python script

---

## Common Patterns

### Pattern 1: Scheduled Email Classification

**Python Script:** `email_classifier_vm.py` (~120 lines)

```python
#!/usr/bin/env python3
import os
from pymongo import MongoClient
from openai import OpenAI
from datetime import datetime

# Configuration
MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def classify_emails():
    """Classify unclassified emails using OpenAI"""
    
    # Connect to database
    client = MongoClient(MONGO_URI)
    db = client.email_automation
    
    # Find unclassified emails
    emails = db.emails.find({
        "classified": False,
        "failed_attempts": {"$lt": 3}
    }).limit(50)
    
    # Initialize OpenAI
    openai = OpenAI(api_key=OPENAI_API_KEY)
    
    for email in emails:
        try:
            # Call OpenAI for classification
            response = openai.chat.completions.create(
                model="gpt-4",
                messages=[{
                    "role": "user",
                    "content": f"Classify this email:\nSubject: {email['subject']}\nBody: {email['body']}"
                }]
            )
            
            category = response.choices[0].message.content
            
            # Update database
            db.emails.update_one(
                {"_id": email["_id"]},
                {
                    "$set": {
                        "category": category,
                        "classified": True,
                        "classified_at": datetime.utcnow()
                    }
                }
            )
            
            print(f"✓ Classified email {email['_id']}: {category}")
            
        except Exception as e:
            # Handle errors
            db.emails.update_one(
                {"_id": email["_id"]},
                {"$inc": {"failed_attempts": 1}}
            )
            print(f"✗ Error classifying {email['_id']}: {str(e)}")
    
    client.close()

if __name__ == "__main__":
    classify_emails()
```

**n8n Workflow:**

```
Workflow Name: "Email Classification"

Nodes:

1. [Schedule Trigger]
   - Run: Every 1 hour
   - Description: "Trigger email classification hourly"

2. [MongoDB - Find]
   - Collection: emails
   - Operation: Find
   - Query: { "classified": false, "failed_attempts": { "$lt": 3 } }
   - Limit: 50
   - Description: "Fetch unclassified emails"

3. [IF - Check Results]
   - Condition: {{ $json.length > 0 }}
   - True: Continue to loop
   - False: Stop workflow
   - Description: "Check if emails found"

4. [Loop Over Items]
   - Input: {{ $json }}
   - Description: "Process each email"

5. [OpenAI]
   - Operation: Message a model
   - Model: gpt-4
   - Prompt: Classify this email:
             Subject: {{ $json.subject }}
             Body: {{ $json.body }}
   - Description: "AI classification"

6. [MongoDB - Update Success]
   - Collection: emails
   - Operation: Update
   - Filter: { "_id": "{{ $json._id }}" }
   - Update: {
       "$set": {
         "category": "{{ $json.choices[0].message.content }}",
         "classified": true,
         "classified_at": "{{ $now }}"
       }
     }
   - Description: "Update classified email"

7. [Error Handler - MongoDB Update]
   - Collection: emails
   - Operation: Update
   - Filter: { "_id": "{{ $json._id }}" }
   - Update: { "$inc": { "failed_attempts": 1 } }
   - Description: "Track failed attempts"

8. [Slack Notification]
   - Channel: #automation-logs
   - Message: Classified {{ $json.length }} emails
   - Description: "Send summary"

Connections:
1 → 2 → 3
3 (true) → 4 → 5 → 6 → 8
3 (false) → Stop
5 (error) → 7
```

**Visual Representation:**

```
┌─────────────────┐
│   Schedule      │
│   Every 1hr     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   MongoDB       │
│   Find Emails   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   IF Node       │
│  Emails > 0?    │
└────┬───────┬────┘
     │       │
  Yes│       │No → Stop
     │       │
     ▼       │
┌─────────────────┐
│   Loop Over     │
│   Each Email    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    OpenAI       │
│   Classify      │
└────────┬────────┘
         │
      Success
         │
         ▼
┌─────────────────┐
│   MongoDB       │
│   Update        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Slack         │
│   Notify        │
└─────────────────┘
```

### Pattern 2: API Integration with Retry Logic

**Python Script:** `cpx_sync_inventory.py`

```python
import requests
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_cpx_surveys():
    """Fetch survey inventory from CPX with retry logic"""
    
    response = requests.get(
        "https://api.cpx-research.com/surveys",
        headers={"Authorization": f"Bearer {CPX_API_KEY}"},
        params={"limit": 100}
    )
    
    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code}")
    
    return response.json()

def sync_inventory():
    surveys = fetch_cpx_surveys()
    
    for survey in surveys:
        db.surveys.update_one(
            {"external_id": survey["id"]},
            {"$set": survey},
            upsert=True
        )
```

**n8n Workflow:**

```
Workflow: "CPX Survey Inventory Sync"

Nodes:

1. [Schedule Trigger]
   - Cron: 0 */6 * * *  (Every 6 hours)

2. [HTTP Request - CPX API]
   - Method: GET
   - URL: https://api.cpx-research.com/surveys
   - Authentication: Bearer Token
   - Parameters: { "limit": 100 }
   - Retry on Fail: Yes
   - Max Retries: 3
   - Retry Interval: Exponential (4-10 seconds)

3. [Function Node - Transform Data]
   - Code:
     const surveys = $input.all();
     return surveys.map(survey => ({
       json: {
         external_id: survey.json.id,
         ...survey.json
       }
     }));

4. [Loop Over Surveys]

5. [MongoDB - Upsert]
   - Operation: Update
   - Collection: surveys
   - Filter: { "external_id": "{{ $json.external_id }}" }
   - Update: { "$set": {{ $json }} }
   - Upsert: true

6. [Slack - Success Notification]
   - Message: ✓ Synced {{ $json.length }} surveys from CPX

7. [Error Handler - Slack Alert]
   - Message: ✗ CPX sync failed: {{ $json.error }}
```

### Pattern 3: Multi-Step Workflow with Conditions

**Python Script:** `lead_enrichment_job.py`

```python
def enrich_leads():
    """Enrich new leads with additional data"""
    
    # Get leads that need enrichment
    leads = db.leads.find({
        "enriched": False,
        "email": {"$exists": True}
    }).limit(20)
    
    for lead in leads:
        try:
            # Step 1: Validate email
            if not validate_email(lead["email"]):
                db.leads.update_one(
                    {"_id": lead["_id"]},
                    {"$set": {"email_valid": False, "enriched": True}}
                )
                continue
            
            # Step 2: Search for company
            search_result = google_search(lead["email"])
            
            if search_result:
                # Step 3: Extract company info
                company = extract_company(search_result)
                
                # Step 4: Get company size
                if company:
                    size = get_company_size(company)
                else:
                    size = "unknown"
            else:
                company = None
                size = "unknown"
            
            # Step 5: Update lead
            db.leads.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "company": company,
                        "company_size": size,
                        "email_valid": True,
                        "enriched": True,
                        "enriched_at": datetime.utcnow()
                    }
                }
            )
            
        except Exception as e:
            log_error(lead["_id"], str(e))
```

**n8n Workflow:**

```
Workflow: "Lead Enrichment Pipeline"

1. [Schedule] Every 2 hours

2. [MongoDB - Find Leads]
   Query: { "enriched": false, "email": { "$exists": true } }
   Limit: 20

3. [Loop Over Leads]

4. [Function - Validate Email]
   Code: 
   const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
   return [{
     json: {
       ....$json,
       email_valid: emailRegex.test($json.email)
     }
   }];

5. [IF - Email Valid?]
   Condition: {{ $json.email_valid }} === true
   
   False → [MongoDB Update - Invalid]
           Set: { "email_valid": false, "enriched": true }
   
   True → Continue

6. [HTTP - Google Search API]
   URL: https://www.googleapis.com/customsearch/v1
   Params: { "q": {{ $json.email }} }

7. [IF - Results Found?]
   Condition: {{ $json.items.length }} > 0
   
   False → Set company = null
   True → Continue

8. [Function - Extract Company]
   Parse search results to find company name

9. [HTTP - Company Size API]
   URL: https://api.companydata.com/size
   Params: { "company": {{ $json.company }} }

10. [MongoDB - Update Lead]
    Filter: { "_id": "{{ $json._id }}" }
    Update: {
      "$set": {
        "company": "{{ $json.company }}",
        "company_size": "{{ $json.size }}",
        "email_valid": true,
        "enriched": true,
        "enriched_at": "{{ $now }}"
      }
    }
```

---

## Script-by-Script Conversion

### Category 1: Email Processing

#### Script: `email_classifier_vm.py`
**Purpose:** Classify emails using AI
**Frequency:** Every hour
**Complexity:** Medium

**n8n Workflow Name:** "Email Classification - Hourly"

**Nodes Required:**
1. Schedule Trigger (cron: 0 * * * *)
2. MongoDB Find (emails, classified=false)
3. Loop Over Items
4. OpenAI Node (gpt-4 classification)
5. MongoDB Update (set category, classified=true)
6. Error Handler → MongoDB Update (increment failed_attempts)
7. Slack Notification (summary)

**Estimated Time:** 30 minutes

---

#### Script: `gmail_router_vm.py`
**Purpose:** Route incoming Gmail messages to appropriate handlers
**Frequency:** Every 15 minutes
**Complexity:** High

**n8n Workflow Name:** "Gmail Message Router"

**Nodes Required:**
1. Schedule Trigger (cron: */15 * * * *)
2. Gmail Trigger (fetch new messages)
3. Function Node (parse email metadata)
4. Switch Node (route based on sender/subject)
   - Case 1: Survey responses → Survey Handler Workflow
   - Case 2: Support requests → Support Ticket Workflow
   - Case 3: Lead emails → Lead Capture Workflow
   - Default: Archive
5. MongoDB Insert (log processed email)
6. Gmail Node (mark as read/archive)

**Estimated Time:** 1-2 hours

---

### Category 2: Survey Management

#### Script: `create_cint_entry_links_at_scale.py`
**Purpose:** Generate entry links for Cint surveys
**Frequency:** On-demand
**Complexity:** Medium

**n8n Workflow Name:** "Cint Entry Link Generator"

**Nodes Required:**
1. Webhook Trigger (manual or API call)
2. MongoDB Find (surveys needing links)
3. Loop Over Surveys
4. HTTP Request (Cint API - create link)
5. Function Node (generate tracking params)
6. MongoDB Update (store entry link)
7. Response Node (return created links)

**Estimated Time:** 45 minutes

---

#### Script: `fix_cpx_entry_links.py`
**Purpose:** Fix malformed CPX survey links
**Frequency:** Daily
**Complexity:** Low

**n8n Workflow Name:** "CPX Link Repair - Daily"

**Nodes Required:**
1. Schedule Trigger (cron: 0 2 * * *)
2. MongoDB Find (surveys with malformed links)
3. Loop Over Items
4. Function Node (reconstruct correct link format)
5. MongoDB Update (fix link)
6. Slack Notification (count of fixed links)

**Estimated Time:** 20 minutes

---

### Category 3: Data Sync

#### Script: `sync_vm_key.py`
**Purpose:** Sync API keys between VM and local
**Frequency:** On configuration change
**Complexity:** Low

**n8n Workflow Name:** "Config Sync - VM to Local"

**Nodes Required:**
1. Webhook Trigger (called when config changes)
2. HTTP Request (fetch VM config)
3. Function Node (compare with local config)
4. IF Node (changes detected?)
5. MongoDB Update (update local config)
6. Slack Notification (config synced)

**Estimated Time:** 25 minutes

---

### Category 4: Monitoring & Diagnostics

#### Script: `check_system_status.py`
**Purpose:** Monitor system health metrics
**Frequency:** Every 5 minutes
**Complexity:** Medium

**n8n Workflow Name:** "System Health Monitor"

**Nodes Required:**
1. Schedule Trigger (cron: */5 * * * *)
2. HTTP Request (API health check)
3. MongoDB Aggregate (query performance stats)
4. Redis Info (check cache health)
5. Function Node (calculate health score)
6. IF Node (health score < threshold?)
   - True → Slack Alert (urgent)
   - False → MongoDB Log (metrics)
7. MongoDB Insert (historical metrics)

**Estimated Time:** 45 minutes

---

#### Script: `monitor_api_usage.py`
**Purpose:** Track API usage and costs
**Frequency:** Hourly
**Complexity:** Low

**n8n Workflow Name:** "API Usage Tracker"

**Nodes Required:**
1. Schedule Trigger (cron: 0 * * * *)
2. MongoDB Aggregate (sum API calls by provider)
3. Function Node (calculate costs)
4. MongoDB Insert (usage_logs)
5. IF Node (over budget?)
   - True → Slack Alert + Email
6. HTTP Request (update dashboard)

**Estimated Time:** 30 minutes

---

### Category 5: Scheduled Jobs

#### Script: `run_classification.py`
**Purpose:** Batch classify leads
**Frequency:** Every 2 hours
**Complexity:** Medium

**n8n Workflow Name:** "Lead Batch Classification"

**Nodes Required:**
1. Schedule Trigger (cron: 0 */2 * * *)
2. MongoDB Find (unclassified leads, limit 100)
3. Loop Over Leads
4. OpenAI Node (classify lead quality)
5. Function Node (score calculation)
6. MongoDB Update (set classification & score)
7. IF Node (high-quality lead?)
   - True → Trigger Sales Notification Workflow
8. MongoDB Aggregate (classification summary)
9. Slack Notification (batch complete)

**Estimated Time:** 40 minutes

---

#### Script: `generate_7day_test_report.py`
**Purpose:** Generate weekly test results report
**Frequency:** Weekly (Monday 9 AM)
**Complexity:** High

**n8n Workflow Name:** "Weekly Test Report Generator"

**Nodes Required:**
1. Schedule Trigger (cron: 0 9 * * 1)
2. MongoDB Aggregate (test results from last 7 days)
3. Function Node (calculate metrics)
4. HTTP Request (generate charts via API)
5. Function Node (build HTML report)
6. Email Node (send to team)
7. Google Drive Node (save report PDF)
8. Slack Notification (report sent)

**Estimated Time:** 1.5 hours

---

## Advanced Patterns

### Pattern 4: Parallel Processing

**Python Script with ThreadPoolExecutor:**

```python
from concurrent.futures import ThreadPoolExecutor

def process_lead(lead):
    # Heavy processing
    enriched = enrich_lead(lead)
    classified = classify_lead(enriched)
    return classified

def batch_process():
    leads = db.leads.find({"status": "new"}).limit(50)
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_lead, leads))
    
    return results
```

**n8n Workflow:**

Use **Split In Batches** node with **Merge** node:

```
1. [MongoDB Find] 50 leads

2. [Split In Batches]
   Batch Size: 10
   
3. [Loop Over Batch Items]

4. [HTTP Request - Lead Enrichment]
   (Parallel execution within batch)

5. [OpenAI - Classification]

6. [MongoDB Update]

7. [Merge]
   Merge all batch results

8. [Function - Summary]

9. [Slack Notification]
```

### Pattern 5: Error Recovery with Dead Letter Queue

**Python Script:**

```python
def process_with_retry(item, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = process_item(item)
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                # Send to dead letter queue
                db.failed_items.insert_one({
                    "item": item,
                    "error": str(e),
                    "timestamp": datetime.utcnow()
                })
            time.sleep(2 ** attempt)
```

**n8n Workflow:**

```
Main Workflow:

1. [Trigger]
2. [Process Item]
3. [On Error] → [Error Handler Workflow]

Error Handler Workflow:

1. [Webhook Input] (receives error data)
2. [IF - Retry Count < 3?]
   True:
     - [Wait] exponential backoff
     - [HTTP Request] call main workflow again
   False:
     - [MongoDB Insert] dead_letter_queue
     - [Slack Alert] manual intervention needed
```

### Pattern 6: Rate Limiting

**Python Script:**

```python
from ratelimit import limits, sleep_and_retry

@sleep_and_retry
@limits(calls=100, period=3600)  # 100 calls per hour
def call_external_api(data):
    response = requests.post(API_URL, json=data)
    return response.json()
```

**n8n Workflow:**

Use built-in rate limiting in HTTP Request node:

```
[HTTP Request Node]
Settings:
- Rate Limit: 100 requests per 3600 seconds
- Rate Limit Mode: Wait
- Queue Mode: Fifo

Or use a custom rate limiter:

1. [Redis - INCR] key: "api_calls:hour:{{ $now.format('YYYY-MM-DD-HH') }}"
2. [Redis - EXPIRE] 3600 seconds
3. [IF - Count < 100?]
   True: Continue
   False: [Wait 60 seconds] → Retry
```

---

## Testing Workflows

### Test Each Workflow:

1. **Manual Test Run**
   - Click "Execute Workflow" in n8n
   - Check each node's output
   - Verify data transformations

2. **Test with Sample Data**
   - Use "Test Step" feature
   - Provide mock input data
   - Validate output matches expected

3. **Error Testing**
   - Simulate API failures
   - Test error handlers
   - Verify dead letter queue

4. **Performance Testing**
   - Run with production-like data volume
   - Monitor execution time
   - Check memory usage

5. **Integration Testing**
   - Test with real external APIs (staging)
   - Verify database updates
   - Check notifications sent

### Example Test Checklist:

```markdown
## Email Classification Workflow Test

- [ ] Workflow triggers on schedule
- [ ] Fetches correct emails from MongoDB
- [ ] Skips already classified emails
- [ ] OpenAI API called with correct prompt
- [ ] Classification result saved to database
- [ ] Error handler catches API failures
- [ ] Failed attempts incremented on error
- [ ] Slack notification sent with summary
- [ ] Workflow completes in < 2 minutes
- [ ] No data loss or corruption
```

---

## Deployment

### Step 1: Export Workflows

In n8n UI:
1. Select workflow
2. Click "Download" → Export as JSON
3. Save to version control

```bash
# Save workflows to repository
mkdir -p n8n-workflows
cp workflow-email-classification.json n8n-workflows/
```

### Step 2: Set Up Credentials

In n8n:
1. Settings → Credentials
2. Add credentials for:
   - MongoDB (connection string)
   - OpenAI (API key)
   - Gmail (OAuth)
   - Slack (webhook URL)
   - CPX Research (API key)
   - Cint (API key)

### Step 3: Import to Production

```bash
# Using n8n CLI
n8n import:workflow --input=n8n-workflows/

# Or via API
curl -X POST http://localhost:5678/rest/workflows \
  -H "Content-Type: application/json" \
  -d @workflow-email-classification.json
```

### Step 4: Activate Workflows

In n8n UI:
1. Open each workflow
2. Click "Active" toggle
3. Monitor execution logs

### Step 5: Monitor Workflows

```bash
# Check workflow executions
curl http://localhost:5678/rest/executions

# View specific execution
curl http://localhost:5678/rest/executions/{id}
```

Set up monitoring:
- n8n execution log dashboard
- Slack alerts for failures
- Weekly summary reports

---

## Migration Checklist

### Pre-Migration
- [ ] n8n installed and running
- [ ] All credentials configured
- [ ] Test environment set up
- [ ] Backup Python scripts
- [ ] Document current script behavior

### During Migration
- [ ] Convert one script at a time
- [ ] Test each workflow thoroughly
- [ ] Run in parallel with Python script initially
- [ ] Compare outputs for accuracy
- [ ] Monitor for errors

### Post-Migration
- [ ] All workflows activated
- [ ] Python scripts decommissioned
- [ ] Monitoring dashboards updated
- [ ] Team trained on n8n
- [ ] Documentation updated

---

## Common Conversion Mappings

| Python Feature | n8n Equivalent |
|----------------|----------------|
| `for` loop | Loop Over Items node |
| `if/elif/else` | IF node or Switch node |
| `try/except` | Error workflow branch |
| `time.sleep()` | Wait node |
| `requests.get()` | HTTP Request node |
| `pymongo` operations | MongoDB node |
| Database transactions | Multiple MongoDB nodes |
| Threading/async | Parallel execution (automatic) |
| Function calls | Function node (JavaScript) |
| Environment variables | n8n environment variables |
| Logging | MongoDB insert + Slack notification |

---

## Troubleshooting

### Issue: Workflow times out
**Solution:** 
- Split into smaller batches
- Use "Split In Batches" node
- Increase timeout settings

### Issue: Data not passing between nodes
**Solution:**
- Check node output format
- Use "Set" node to transform data
- Verify field names match

### Issue: API rate limits hit
**Solution:**
- Add rate limiting to HTTP Request node
- Use Wait node between requests
- Implement queue system

### Issue: Workflow fails intermittently
**Solution:**
- Add retry logic to HTTP nodes
- Implement error handlers
- Log failures to database

---

## Next Steps

1. Start with Priority 1 scripts (email classification)
2. Test thoroughly in development
3. Run parallel with Python scripts
4. Monitor for 1 week
5. Decommission Python script once confident
6. Move to next script

**Timeline:** 6-8 weeks to convert all 100+ scripts

**Team:** 2-3 people recommended

**Success Metric:** All workflows running reliably with < 1% error rate

---

## Resources

- n8n Documentation: https://docs.n8n.io
- n8n Community: https://community.n8n.io
- Workflow Templates: https://n8n.io/workflows
- Custom Nodes: https://docs.n8n.io/integrations/creating-nodes/

---

## Summary

Converting 100+ Python scripts to n8n workflows will:
- **Reduce complexity** by 80%
- **Enable non-technical editing** of workflows
- **Improve visibility** with visual workflow diagrams
- **Simplify maintenance** with no-code/low-code approach
- **Centralize automation** in one platform

The investment in conversion (6-8 weeks) will pay off with dramatically easier maintenance going forward.
