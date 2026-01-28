# AGENT 15 - QUICK REFERENCE GUIDE
## Phase 2 ML-Based Send Time Optimization

---

## 📦 DELIVERABLES

### 1. Send Time Optimizer
**File**: `backend/campaigns/send_time_optimizer.py` (18.3 KB)

```python
from campaigns.send_time_optimizer import SendTimeOptimizer

optimizer = SendTimeOptimizer(db, min_data_points=5, engagement_window_days=90)

# Analyze engagement by time
patterns = optimizer.analyze_engagement_by_time(lead_id)
# {"Monday": {9: 0.45, 10: 0.52, ...}, ...}

# Predict optimal send time
optimal = optimizer.predict_optimal_send_time(lead_id)
# {"day": "Tuesday", "hour": 10, "confidence": 0.87, "fallback": false}

# Batch optimize campaign
schedule = optimizer.batch_optimize_schedule(campaign_id)
# {"optimized_recipients": [...], "metrics": {...}}
```

### 2. Engagement Pattern Analyzer
**File**: `backend/analytics/engagement_patterns.py` (19.7 KB)

```python
from analytics.engagement_patterns import EngagementPatternAnalyzer

analyzer = EngagementPatternAnalyzer(db, lookback_days=90)

# Detect engagement patterns
patterns = analyzer.detect_patterns(lead_id)
# {"open_latency_hours": 2.5, "engagement_momentum": 0.8, ...}

# Suggest contact frequency
freq = analyzer.suggest_contact_frequency(industry="SaaS", seniority="VP")
# {"days_between_contacts": 4, "weekly_contacts": 2.0, ...}

# Analyze segment performance
perf = analyzer.analyze_segment_performance({"industry": "SaaS"})
# {"avg_open_rate": 0.45, "best_performing_day": "Tuesday", ...}
```

### 3. ML Lead Scorer
**File**: `backend/agents/ml_lead_scorer.py` (19.4 KB)

```python
from agents.ml_lead_scorer import MLLeadScorer

scorer = MLLeadScorer(db, lookback_days=180, min_training_samples=100)

# Score lead for reply
score = scorer.score_lead_for_reply(lead_dict)
# {"probability": 0.45, "confidence": 0.8, "factors": [...]}

# Prioritize leads
ranked = scorer.prioritize_leads(lead_ids, limit=100)
# [{"lead_id": "...", "probability": 0.65, "rank": 1}, ...]

# Train ML model (optional)
scorer.train_model()  # Returns: bool
```

---

## 🔌 API ENDPOINTS

### Send Time Optimization
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/leads/{lead_id}/optimal-send-time` | Get optimal send time for 1 lead |
| GET | `/campaigns/{campaign_id}/send-time-analysis` | Analyze entire campaign |
| POST | `/campaigns/{campaign_id}/optimize-schedule` | Optimize recipient order |

### Engagement Analysis
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/leads/{lead_id}/engagement-patterns` | Detect behavior patterns |
| GET | `/campaigns/{campaign_id}/segment-performance` | Analyze segment metrics |

### Lead Scoring
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/leads/{lead_id}/reply-score` | Get reply probability |
| POST | `/campaigns/{campaign_id}/prioritize-leads` | Rank all leads |

---

## 📊 DATA STRUCTURES

### Send Time Response
```json
{
  "day": "Tuesday",
  "hour": 10,
  "confidence": 0.87,
  "open_rate": 0.65,
  "data_points": 23,
  "fallback": false
}
```

### Engagement Pattern Response
```json
{
  "open_latency_hours": 2.5,
  "click_latency_hours": 4.2,
  "reply_latency_hours": 24.5,
  "reply_likelihood": 0.45,
  "preferred_days": ["Tuesday", "Wednesday"],
  "engagement_momentum": 0.8,
  "last_engagement": "2024-01-25T14:30:00",
  "total_sends_analyzed": 15,
  "high_value_indicator": true
}
```

### Lead Score Response
```json
{
  "probability": 0.45,
  "confidence": 0.8,
  "factors": [
    {"name": "has_replied", "impact": 0.25, "value": true},
    {"name": "open_rate", "impact": 0.15, "value": 0.6}
  ],
  "recommendation": "high_priority",
  "reasoning": "Has replied before and high open rate"
}
```

### Campaign Schedule Response
```json
{
  "optimized_recipients": [
    {
      "recipient_id": "lead_456",
      "optimal_day": "Tuesday",
      "optimal_hour": 10,
      "confidence": 0.87,
      "send_order": 1
    }
  ],
  "metrics": {
    "total_recipients": 500,
    "with_predictions": 350,
    "confidence_high": 200,
    "confidence_medium": 120,
    "confidence_low": 30,
    "fallback_defaults": 150
  }
}
```

---

## 🎯 KEY FEATURES

### Feature Extraction (ML Lead Scorer)
1. `has_opened` - Has lead ever opened email?
2. `has_replied` - Has lead ever replied?
3. `open_rate` - Historical open rate (0-1)
4. `reply_rate` - Historical reply rate (0-1)
5. `seniority_c_level` - Is C-level? (0-1)
6. `seniority_vp` - Is VP? (0-1)
7. `seniority_director` - Is Director? (0-1)
8. `company_size_enterprise` - Enterprise company? (0-1)
9. `company_size_mid_market` - Mid-market? (0-1)
10. `company_size_small` - Small company? (0-1)
11. `industry_saas` - SaaS industry? (0-1)
12. `industry_tech` - Tech industry? (0-1)
13. `recently_sent` - Days since send (decays over 30 days)
14. `engagement_momentum` - Trending up/down (0-1)

### Confidence Scoring
| Scorer | Min | Max | Factors |
|--------|-----|-----|---------|
| Send Time | 0.40 | 0.95 | Data points, completeness |
| Patterns | 0.40 | 0.95 | Segment size, data volume |
| ML Scorer | 0.30 | 1.00 | Send history, features |

### Default Values
- **Lookback Window**: 90 days (send_time, patterns), 180 days (ML)
- **Min Data Points**: 5 per hour/day (send_time)
- **Min Training Samples**: 100 (ML model)
- **Default Send Time**: Tuesday 10 AM UTC
- **Default Frequency**: 3-4 days between contacts

---

## 🗄️ MONGODB COLLECTIONS

### Used Collections
1. `campaigns` - Campaign metadata
2. `campaign_sends` - Email send/engagement history
3. `campaign_recipients` - Recipient tracking
4. `leads` - Lead attributes (industry, seniority, timezone)
5. `ab_tests` - A/B test data (if applicable)

### Required Fields
**campaign_sends:**
- `lead_id` (ObjectId)
- `sent_at` (datetime)
- `status` ("sent", "opened", "clicked", "replied")
- `opened_at` (datetime, optional)
- `clicked_at` (datetime, optional)
- `replied_at` (datetime, optional)

**leads:**
- `_id` (ObjectId)
- `email` (string)
- `industry` (string)
- `seniority_level` (string)
- `company_size` (string)
- `company_employee_count` (int)
- `timezone` (string)

---

## 📈 CONFIGURATION

### SendTimeOptimizer
```python
optimizer = SendTimeOptimizer(
    db,
    min_data_points=5,           # Min events per hour/day
    engagement_window_days=90    # Historical lookback
)
```

### EngagementPatternAnalyzer
```python
analyzer = EngagementPatternAnalyzer(
    db,
    lookback_days=90
)
```

### MLLeadScorer
```python
scorer = MLLeadScorer(
    db,
    lookback_days=180,
    min_training_samples=100
)
```

---

## 🚀 DEPLOYMENT CHECKLIST

- [ ] Install dependencies: `pip install pandas numpy scikit-learn scipy`
- [ ] Create database indexes:
  - `campaign_sends.create_index([("lead_id", 1), ("sent_at", -1)])`
  - `leads.create_index([("industry", 1), ("seniority_level", 1)])`
  - `campaign_recipients.create_index([("campaign_id", 1)])`
- [ ] Test with sample data
- [ ] Validate predictions against actual outcomes
- [ ] Monitor API response times
- [ ] Setup logging for troubleshooting
- [ ] Document custom configurations
- [ ] Train ML models on historical data

---

## ⚙️ TROUBLESHOOTING

### "No sends found for lead"
- Lead has no email history
- Check `campaign_sends` collection for lead_id
- Verify date ranges overlap with lookback_days

### "Insufficient training data"
- ML model needs 100+ samples minimum
- Check `campaign_sends` has engagement data
- May need to wait for more campaign history

### "Module not found" errors
- Install: `pip install pandas numpy scikit-learn`
- Services have fallback behavior without these

### "Connection timeout"
- Check MongoDB connection string
- Verify database has required collections
- Check network connectivity

### "ObjectId conversion error"
- Ensure lead_id/campaign_id are valid MongoDB ObjectIds or strings
- Services auto-convert valid strings

---

## 📝 USAGE PATTERNS

### Single Lead Analysis
```python
# Quick send time check
optimizer = SendTimeOptimizer(db)
best_time = optimizer.predict_optimal_send_time("lead_123")
print(f"Send to {best_time['day']} at {best_time['hour']}:00")
```

### Batch Campaign Optimization
```python
# Optimize entire campaign
schedule = optimizer.batch_optimize_schedule("campaign_456")
recipients_by_hour = {}
for r in schedule['optimized_recipients']:
    hour = r['optimal_hour']
    recipients_by_hour.setdefault(hour, []).append(r)
# Send all 10am recipients together, then 11am, etc.
```

### Lead Prioritization
```python
# Rank all leads by reply probability
scorer = MLLeadScorer(db)
ranked = scorer.prioritize_leads(all_lead_ids)
top_100 = ranked[:100]
# Focus resources on top 100 highest-probability leads
```

### Segment Analysis
```python
# Analyze a specific segment
analyzer = EngagementPatternAnalyzer(db)
freq = analyzer.suggest_contact_frequency("SaaS", "VP")
contact_interval = freq['days_between_contacts']
best_days = freq['best_days']
# Contact this segment every N days, focusing on best days
```

---

## 🎓 EXAMPLES

### Example: Send Time for Lead
```bash
curl "http://api/campaigns/leads/507f1f77bcf86cd799439011/optimal-send-time"
```

Response:
```json
{
  "success": true,
  "lead_id": "507f1f77bcf86cd799439011",
  "optimal_send_time": {
    "day": "Wednesday",
    "hour": 14,
    "confidence": 0.82,
    "open_rate": 0.58,
    "data_points": 18,
    "fallback": false
  }
}
```

### Example: Campaign Optimization
```bash
curl -X POST "http://api/campaigns/507f1f77bcf86cd799439012/optimize-schedule"
```

Response:
```json
{
  "success": true,
  "campaign_id": "507f1f77bcf86cd799439012",
  "message": "Campaign schedule optimized successfully",
  "optimization": {
    "optimized_recipients": [...],
    "metrics": {
      "total_recipients": 500,
      "with_predictions": 425,
      "confidence_high": 255,
      "fallback_defaults": 75
    }
  }
}
```

---

## 📚 INTEGRATION POINTS

### With Campaign Scheduler
```python
# During campaign scheduling
optimizer = SendTimeOptimizer(db)
schedule = optimizer.batch_optimize_schedule(campaign_id)
# Use schedule['optimized_recipients'] to order sends
```

### With Email Sender
```python
# Before sending email
optimizer = SendTimeOptimizer(db)
optimal = optimizer.predict_optimal_send_time(lead_id)
# Schedule send for optimal['day'] at optimal['hour']
```

### With Lead Scoring
```python
# During lead qualification
scorer = MLLeadScorer(db)
score = scorer.score_lead_for_reply(lead)
if score['probability'] > 0.6:
    # Prioritize for outreach
```

---

## 🔗 RELATED AGENTS

- **Agent 5**: Campaign Automation Foundation
- **Agent 8**: Multi-Channel Campaign Executor
- **Agent 10**: A/B Testing & Statistical Analysis
- **Agent 11**: Deliverability & Domain Health
- **Agent 12**: Campaign Analytics & Insights
- **Agent 14**: Performance Monitoring & Alerts

---

**Last Updated**: January 28, 2026  
**Agent**: Agent 15  
**Status**: ✅ PRODUCTION READY
