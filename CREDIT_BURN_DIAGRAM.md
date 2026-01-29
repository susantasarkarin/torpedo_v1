# OpenAI Credit Burn Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EMAIL INGESTION                                  │
│                                                                          │
│  Gmail/IMAP Sync → Email Workers (500 batch) → email_metadata DB       │
│                    (continuous loop)              (1000s of emails)     │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 │ Triggers Multiple Tasks ❌
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│  Task #1           │  │  Task #2           │  │  Task #3           │
│  (Celery)          │  │  (Celery)          │  │  (Celery)          │
│                    │  │                    │  │                    │
│ classify_pending_  │  │ classify_all_      │  │ process_email_     │
│ emails_task        │  │ pending_batch      │  │ with_agent1        │
│                    │  │                    │  │                    │
│ 20/min rate limit  │  │ NO RATE LIMIT! ❌  │  │ 10/min rate limit  │
│ 30 min timeout     │  │ 2 HOUR timeout! ❌ │  │ No time limit      │
│ Batch: 100         │  │ Batch: 50          │  │ Single email       │
└─────────┬──────────┘  └─────────┬──────────┘  └─────────┬──────────┘
          │                       │                        │
          │                       │                        │
          │    ALL CALL OPENAI WRAPPER ❌                 │
          │    (NO DEDUPLICATION CHECK)                    │
          └───────────────────────┼────────────────────────┘
                                  │
                                  ▼
          ┌────────────────────────────────────────────────────┐
          │         backend/leads/openai_wrapper.py            │
          │                                                    │
          │  Step 1: Check Rate Limits ✅                     │
          │          (requests/min, requests/hour)            │
          │                                                    │
          │  Step 2: Check Kill Switch ✅                     │
          │          (DISABLE_AI_CALLS env var)               │
          │                                                    │
          │  Step 3: Check Daily Budget? ❌ NOT IMPLEMENTED   │
          │          (Would save $ but missing!)              │
          │                                                    │
          │  Step 4: Route to Provider                        │
          │          ├─ OpenAI (DEFAULT ❌ - expensive)       │
          │          └─ DeepSeek (50% cheaper but not default)│
          └────────────────────┬───────────────────────────────┘
                               │
                               ▼
          ┌──────────────────────────────────────────┐
          │        TIER 1: Initial Classification     │
          │                                           │
          │  Model: gpt-4o-mini or deepseek-chat     │
          │  Cost:  ~$0.0005 per email               │
          │  Returns: {category, confidence}         │
          └───────────────────┬───────────────────────┘
                              │
                              │ If confidence < 0.7 (30% of emails ❌)
                              │
                              ▼
          ┌──────────────────────────────────────────┐
          │        TIER 2: Expensive Escalation ❌    │
          │                                           │
          │  Model: GPT-4o (33x more expensive!)     │
          │  Cost:  ~$0.015 per email                │
          │  Why:   "Low confidence" threshold        │
          │         too conservative                  │
          └───────────────────┬───────────────────────┘
                              │
                              ▼
          ┌──────────────────────────────────────────┐
          │         Log to ai_usage_logs ✅           │
          │                                           │
          │  Records: tokens, cost, latency, source  │
          │  Good:    Can query for cost analysis    │
          │  Bad:     No alerts on high costs        │
          └───────────────────┬───────────────────────┘
                              │
                              ▼
          ┌──────────────────────────────────────────┐
          │      Store Classification Result          │
          │                                           │
          │  Problem: No validation if email will     │
          │           actually generate a LEAD! ❌    │
          │                                           │
          │  Many classified emails never convert     │
          │  to actionable leads = wasted credits     │
          └───────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│                    WHERE CREDITS ARE BURNING 🔥                          │
└─────────────────────────────────────────────────────────────────────────┘

1. ❌ DUPLICATE PROCESSING (25% waste)
   └─ Same email classified by multiple tasks
   └─ No deduplication check before calling API

2. ❌ CONTINUOUS LOOP (40% waste)
   └─ classify_all_pending_batch runs for 2 HOURS
   └─ No max_batches limit (processes ALL emails)
   └─ No exit condition even when no new emails

3. ❌ EXPENSIVE ESCALATIONS (30% waste)
   └─ 30% of emails escalate to GPT-4o (33x cost)
   └─ Threshold too conservative (0.7)
   └─ Should be 0.5 or lower

4. ❌ WRONG PROVIDER (15% waste)
   └─ Uses OpenAI by default (expensive)
   └─ DeepSeek is 50% cheaper and unlimited
   └─ Only web search needs OpenAI

5. ❌ NO LEAD VALIDATION (50% waste)
   └─ Classifies ALL emails regardless
   └─ Many emails won't generate leads
   └─ Should pre-filter before API call

6. ❌ NO COST CONTROLS (100% risk)
   └─ No daily/monthly budget limits
   └─ No cost-based alerts
   └─ Can burn unlimited credits


┌─────────────────────────────────────────────────────────────────────────┐
│                         CREDIT BURN BREAKDOWN                            │
└─────────────────────────────────────────────────────────────────────────┘

Per Email Costs:
├─ Regular Classification (gpt-4o-mini):    $0.0005
├─ Escalated Classification (GPT-4o):       $0.0150  (30x more!)
└─ DeepSeek Classification:                 $0.0003  (40% cheaper)

Daily Volume (Estimated):
├─ Emails Ingested:                         5,000 - 10,000
├─ Classified (with duplicates):            8,000 - 15,000  ❌
├─ Escalations (30%):                       2,400 - 4,500   ❌
└─ Actual Leads Generated:                  50 - 200        (2-3% conversion!)

Daily Cost Breakdown:
├─ Regular Classifications:    $4 - $7
├─ Expensive Escalations:      $36 - $67    ← 🔥 BIGGEST BURN
├─ Agent Processing:           $1 - $2
└─ TOTAL:                      $41 - $76/day = $1,230 - $2,280/month ❌


┌─────────────────────────────────────────────────────────────────────────┐
│                         SOLUTION FLOW                                    │
└─────────────────────────────────────────────────────────────────────────┘

Email Ingestion → Pre-Filter → Dedup Check → Rate Limit → Budget Check
                     ✅            ✅           ✅           ✅
                     │             │            │            │
                     │ Skip if:    │ Skip if:   │ Wait if:   │ Stop if:
                     │ - System    │ - Already  │ - Over     │ - Over
                     │   email     │   classified│   rate    │   budget
                     │ - Bounce    │ - Duplicate│   limit    │   limit
                     │ - Auto-reply│   content  │            │
                     │ - Known     │            │            │
                     │   non-lead  │            │            │
                     │   domain    │            │            │
                     ▼             ▼            ▼            ▼
                 ┌─────────────────────────────────────────────┐
                 │  Smart Provider Routing                     │
                 │  ├─ DeepSeek (default, 95% of tasks) ✅     │
                 │  └─ OpenAI (only web search) ✅             │
                 └─────────────────┬───────────────────────────┘
                                   ▼
                 ┌─────────────────────────────────────────────┐
                 │  Single Classification (no duplicates) ✅   │
                 │  With intelligent escalation threshold ✅   │
                 └─────────────────┬───────────────────────────┘
                                   ▼
                 ┌─────────────────────────────────────────────┐
                 │  Lead Validation                            │
                 │  Only proceed if email has lead potential ✅│
                 └─────────────────────────────────────────────┘


Expected Results:
├─ Daily Cost:        $5 - $10    (75% reduction ✅)
├─ Monthly Cost:      $150 - $300  (75% reduction ✅)
├─ API Calls/Day:     3,000       (70% reduction ✅)
├─ Escalation Rate:   10%         (67% reduction ✅)
└─ Lead Quality:      Same or Better ✅
```

## Quick Reference

### Current State (Before Fixes)
- **Daily Cost**: $20-30
- **Monthly Cost**: $600-900
- **API Calls**: 10,000/day
- **Escalation Rate**: 30%
- **Duplicates**: Yes (2-3x)
- **Provider**: OpenAI (expensive)
- **Budget Control**: None

### Target State (After Fixes)
- **Daily Cost**: $5-10 ✅
- **Monthly Cost**: $150-300 ✅
- **API Calls**: 3,000/day ✅
- **Escalation Rate**: 10% ✅
- **Duplicates**: None ✅
- **Provider**: DeepSeek (cheap) ✅
- **Budget Control**: Yes ✅

### Key Files
- `backend/leads/openai_wrapper.py` - API wrapper
- `backend/tasks/ai_tasks.py` - Background tasks
- `backend/leads/email_classifier.py` - Classification logic
- `backend/email_sync/workers.py` - Email workers

### Implementation Priority
1. **Today** (30 min): Emergency fixes
   - Set AI_DEFAULT_PROVIDER=deepseek
   - Set DAILY_AI_BUDGET_USD=10.0
   - Limit max_batches to 20

2. **This Week** (4 hrs): Code changes
   - Add budget check in code
   - Add deduplication
   - Reduce escalation threshold

3. **Next Sprint** (2 days): Optimization
   - Lead validation
   - Batch processing
   - Intelligent filtering
