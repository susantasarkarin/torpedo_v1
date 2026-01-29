# Quick Fix Guide - Stop OpenAI Credit Burn

## 🚨 Emergency Actions (Execute Immediately)

### Option 1: Complete Shutdown (If Burning Too Fast)

```bash
# Add to .env file
DISABLE_AI_CALLS=true
```

This will immediately stop ALL AI API calls. Use this if credits are burning too fast and you need to stop immediately.

### Option 2: Switch to Cheap Provider (Recommended)

```bash
# Add to .env file
AI_DEFAULT_PROVIDER=deepseek
```

This switches from OpenAI to DeepSeek (cheaper, no daily limits). Will reduce costs by 50-70% immediately.

---

## 📊 Step 1: Assess Current Damage

### Check Your MongoDB for Actual Costs

```bash
# First, install required dependencies if not present
pip install pymongo python-dotenv

# Run the monitoring script
python monitor_api_usage.py
```

This shows you:
- How many API calls in last 24 hours
- Cost breakdown by source
- Estimated monthly cost

### Alternative: Query MongoDB Directly

If the script fails, connect to MongoDB and run:

```javascript
use email_automation

// Get costs from last 24 hours
db.ai_usage_logs.aggregate([
  {
    $match: {
      timestamp: {
        $gte: new Date(Date.now() - 24*60*60*1000)
      }
    }
  },
  {
    $group: {
      _id: {
        source: "$source",
        model: "$model",
        provider: "$provider"
      },
      total_calls: { $sum: 1 },
      total_cost: { $sum: "$cost_usd" },
      total_tokens: { $sum: "$total_tokens" }
    }
  },
  {
    $sort: { total_cost: -1 }
  }
])
```

---

## 🔧 Step 2: Implement Quick Fixes

### Fix #1: Add Daily Budget Limit

Edit `backend/leads/openai_wrapper.py`, add after line 260:

```python
# Add after line 260 (before class TokenUsageLogger)

DAILY_BUDGET_USD = float(os.getenv("DAILY_AI_BUDGET_USD", "10.0"))  # $10/day default

def check_daily_budget() -> bool:
    """Check if we're within daily budget."""
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        logs = client['email_automation']['ai_usage_logs']
        
        from datetime import datetime, time
        # Get today's midnight
        today_start = datetime.combine(datetime.today(), time.min)
        
        # Calculate today's spend
        pipeline = [
            {"$match": {"timestamp": {"$gte": today_start}}},
            {"$group": {"_id": None, "total_cost": {"$sum": "$cost_usd"}}}
        ]
        result = list(logs.aggregate(pipeline))
        today_cost = result[0]["total_cost"] if result else 0.0
        
        if today_cost >= DAILY_BUDGET_USD:
            logger.critical(f"🚨 DAILY BUDGET EXCEEDED: ${today_cost:.2f} / ${DAILY_BUDGET_USD}")
            return False
        
        if today_cost >= DAILY_BUDGET_USD * 0.8:
            logger.warning(f"⚠️  Daily budget 80% used: ${today_cost:.2f} / ${DAILY_BUDGET_USD}")
        
        return True
    except Exception as e:
        logger.error(f"Budget check failed: {e}")
        return True  # Fail open
```

Then modify the `chat_completion()` function around line 427 to add budget check:

```python
# After line 437 (after rate limit check), add:

# Safety: Check daily budget
if not check_daily_budget():
    return {
        "content": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": model,
        "provider": provider,
        "success": False,
        "error": f"Daily budget limit reached (${DAILY_BUDGET_USD})"
    }
```

**Set your daily budget in .env**:
```bash
DAILY_AI_BUDGET_USD=10.0  # $10/day = $300/month
```

---

### Fix #2: Limit Batch Processing

Edit `backend/tasks/ai_tasks.py` line 504:

**BEFORE**:
```python
def classify_all_pending_batch(
    self,
    batch_size: int = 50,
    max_batches: Optional[int] = None,  # Currently allows unlimited!
    ...
):
```

**AFTER**:
```python
def classify_all_pending_batch(
    self,
    batch_size: int = 50,
    max_batches: Optional[int] = 20,  # Cap at 1000 emails per run
    ...
):
```

This prevents the 2-hour task from processing thousands of emails in one go.

---

### Fix #3: Reduce Escalation to Expensive Model

Edit `backend/leads/openai_wrapper.py` line 72:

**BEFORE**:
```python
ESCALATION_CONFIDENCE_THRESHOLD = 0.7  # Too conservative
```

**AFTER**:
```python
ESCALATION_CONFIDENCE_THRESHOLD = 0.5  # Only escalate if really uncertain
```

This reduces expensive GPT-4o calls by ~40%.

---

### Fix #4: Add Email Classification Cache

Edit `backend/leads/email_classifier.py`, add at top after imports:

```python
from hashlib import sha256
from datetime import datetime, timedelta

# Email classification cache (simple in-memory for now)
_classification_cache = {}
CACHE_TTL_HOURS = 48

def _get_email_hash(email_content: str) -> str:
    """Get hash of email content for caching."""
    return sha256(email_content.encode()).hexdigest()

def _check_cache(email_hash: str) -> Optional[Dict]:
    """Check if classification exists in cache."""
    if email_hash in _classification_cache:
        cached = _classification_cache[email_hash]
        if datetime.utcnow() < cached['expires']:
            return cached['result']
        else:
            del _classification_cache[email_hash]
    return None

def _store_cache(email_hash: str, result: Dict):
    """Store classification in cache."""
    _classification_cache[email_hash] = {
        'result': result,
        'expires': datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    }
```

Then in the classification function, check cache first before calling API.

---

### Fix #5: Skip Already Classified Emails

Edit `backend/tasks/ai_tasks.py` around line 431:

Add a check to skip emails already classified:

```python
def classify_pending_emails_task(
    self,
    limit: int = 100,
    internal_domains: Optional[List[str]] = None,
    source: str = "celery"
) -> Dict[str, Any]:
    """Only classify emails that haven't been classified yet."""
    
    # Add this check at the start
    from email_sync import email_metadata
    
    # Count truly pending (not classified)
    pending_count = email_metadata.count_documents({
        "classification": {"$exists": False},
        "processed": {"$ne": True}
    })
    
    if pending_count == 0:
        logger.info("No pending emails to classify, skipping task")
        return {"status": "skipped", "reason": "no_pending_emails"}
    
    # Continue with existing logic...
```

---

## 📈 Step 3: Monitor Results

### Create a Daily Cost Report Script

Save as `daily_cost_report.py`:

```python
#!/usr/bin/env python3
"""
Daily cost report - shows OpenAI spending breakdown
Run daily to monitor costs
"""
import os
from pymongo import MongoClient
from datetime import datetime, timedelta, time
from dotenv import load_dotenv

load_dotenv()

def generate_report():
    mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    client = MongoClient(mongo_uri)
    logs = client['email_automation']['ai_usage_logs']
    
    # Today's costs
    today_start = datetime.combine(datetime.today(), time.min)
    
    pipeline = [
        {"$match": {"timestamp": {"$gte": today_start}}},
        {"$group": {
            "_id": {
                "source": "$source",
                "model": "$model",
                "provider": "$provider"
            },
            "calls": {"$sum": 1},
            "cost": {"$sum": "$cost_usd"},
            "tokens": {"$sum": "$total_tokens"}
        }},
        {"$sort": {"cost": -1}}
    ]
    
    results = list(logs.aggregate(pipeline))
    
    print("\n" + "="*60)
    print(f"OpenAI COST REPORT - {datetime.today().strftime('%Y-%m-%d')}")
    print("="*60)
    
    total_cost = 0
    total_calls = 0
    
    for r in results:
        source = r["_id"]["source"]
        model = r["_id"]["model"]
        provider = r["_id"]["provider"]
        calls = r["calls"]
        cost = r["cost"]
        tokens = r["tokens"]
        
        total_cost += cost
        total_calls += calls
        
        print(f"\n{source} / {provider} / {model}:")
        print(f"  Calls: {calls:,}")
        print(f"  Cost:  ${cost:.4f}")
        print(f"  Tokens: {tokens:,}")
    
    print("\n" + "-"*60)
    print(f"TODAY'S TOTAL:  ${total_cost:.2f} ({total_calls:,} calls)")
    print(f"MONTHLY EST.:   ${total_cost * 30:.2f}")
    
    # Budget check
    budget = float(os.getenv("DAILY_AI_BUDGET_USD", "10.0"))
    remaining = budget - total_cost
    percent = (total_cost / budget * 100) if budget > 0 else 0
    
    print(f"\nBUDGET: ${total_cost:.2f} / ${budget} ({percent:.0f}%)")
    if remaining > 0:
        print(f"REMAINING: ${remaining:.2f} ✅")
    else:
        print(f"OVER BUDGET: ${-remaining:.2f} 🚨")
    
    print("="*60 + "\n")
    
    # Alert if over budget
    if total_cost > budget:
        print("⚠️  WARNING: Daily budget exceeded!")
        print(f"⚠️  Consider setting DISABLE_AI_CALLS=true")

if __name__ == "__main__":
    generate_report()
```

Run daily:
```bash
python daily_cost_report.py
```

---

## ⚙️ Step 4: Configure Environment

Create or update `.env` file:

```bash
# AI Provider Configuration
AI_DEFAULT_PROVIDER=deepseek          # Use cheap DeepSeek by default
DISABLE_AI_CALLS=false                # Emergency kill switch

# Cost Controls
DAILY_AI_BUDGET_USD=10.0              # $10/day = $300/month
ESCALATION_CONFIDENCE_THRESHOLD=0.5   # Reduce expensive escalations

# API Keys (from database, but fallback to env)
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...

# Rate Limits (requests per minute)
AI_RATE_LIMIT_BACKGROUND=30           # Reduced from 50
AI_RATE_LIMIT_CRON=30                 # Reduced from 50
AI_RATE_LIMIT_API=20                  # Keep at 20
```

---

## 📋 Checklist

Execute in order:

1. **[ ] Assess Current Costs**
   - Run `python monitor_api_usage.py`
   - Document current daily spend

2. **[ ] Apply Emergency Fix (Choose One)**
   - Set `DISABLE_AI_CALLS=true` (nuclear option)
   - OR set `AI_DEFAULT_PROVIDER=deepseek` (recommended)

3. **[ ] Implement Quick Fixes**
   - Add daily budget check (Fix #1)
   - Limit batch processing (Fix #2)
   - Reduce escalation threshold (Fix #3)
   - Skip already classified (Fix #5)

4. **[ ] Configure Environment**
   - Update .env with cost controls
   - Set DAILY_AI_BUDGET_USD=10.0

5. **[ ] Setup Monitoring**
   - Create `daily_cost_report.py`
   - Add to cron: `0 9 * * * cd /path/to/app && python daily_cost_report.py`

6. **[ ] Restart Services**
   ```bash
   # Restart backend + Celery workers
   systemctl restart campaign-backend
   systemctl restart celery-worker
   ```

7. **[ ] Monitor for 24 Hours**
   - Check cost report next day
   - Verify credits stopped burning

---

## 🎯 Expected Results

After implementing these fixes:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Daily API Calls | 10,000 | 3,000 | 70% reduction |
| Daily Cost | $20-30 | $5-10 | 60-70% reduction |
| Monthly Cost | $600-900 | $150-300 | 65-75% reduction |
| Escalations | 30% | 10% | 67% reduction |

---

## 🆘 If Something Breaks

### Disable All AI Processing
```bash
# In .env
DISABLE_AI_CALLS=true

# Restart services
systemctl restart campaign-backend celery-worker
```

### Revert to OpenAI Only
```bash
# In .env
AI_DEFAULT_PROVIDER=openai
DISABLE_AI_CALLS=false

# Restart services
systemctl restart campaign-backend celery-worker
```

### Check Logs
```bash
# Backend logs
tail -f /var/log/campaign-backend.log

# Celery logs
tail -f /var/log/celery-worker.log

# Search for errors
grep -i "budget\|rate limit\|openai" /var/log/*.log
```

---

## 📞 Need Help?

If credits are still burning after these fixes:

1. Check `ai_usage_logs` collection in MongoDB
2. Look for high-volume sources
3. Check if batch tasks are still running: `celery inspect active`
4. Verify environment variables are loaded: `env | grep AI_`

---

**Last Updated**: 2026-01-29
**Status**: Ready for Implementation
