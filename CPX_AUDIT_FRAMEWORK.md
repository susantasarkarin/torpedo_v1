# CPX Audit Framework - Implementation Guide

## Overview

This document describes the comprehensive CPX audit framework implemented to diagnose and prevent CPX survey traffic issues. The framework implements all 8 requirements from the audit specification.

## Architecture

```
User Entry
    ↓
Fingerprint Check (Block repeat attempts)
    ↓
Traffic Record Created (with demographics)
    ↓
Pre-Screen Audit Log
    ↓
Redirect Out Snapshot
    ↓
CPX Survey
    ↓
Redirect In Snapshot
    ↓
Parameter Integrity Check
    ↓
Duration & Screenout Classification
    ↓
Postback Validation
    ↓
Alert Generation
```

## 1. User Identity & Deduplication

### Fingerprinting
- **Algorithm**: SHA256 hash of `{IP}|{UserAgent}|{Accept-Language}`
- **Database**: `cpx_user_fingerprints` collection
- **Hard Block**: Users with `attempt_count >= 1` are blocked

### Schema
```javascript
{
  fingerprint_hash: "sha256_hash_string",
  first_seen_at: ISODate("2024-01-31T12:00:00Z"),
  attempt_count: 1,
  last_attempt_at: ISODate("2024-01-31T12:05:00Z"),
  status: "SENT_TO_CPX",  // NEW | SENT_TO_CPX | SCREENED_OUT | COMPLETED | BLOCKED
  traffic_ids: ["traffic_id_1", "traffic_id_2"]
}
```

### Usage
```python
# In TrafficService.create_traffic_record()
should_block, fingerprint_record = audit_service.check_user_fingerprint(
    ip, user_agent, accept_language
)
if should_block:
    return None  # Block traffic creation
```

## 2. Pre-Screen Coverage Audit

### Demographic Logging
Before redirect, the system logs:
- Age
- Gender
- Country
- Device type
- Language

### Schema Enhancement
```javascript
// Added to url_parameters (traffic) collection
{
  _id: ObjectId("..."),
  fingerprint_hash: "...",
  age: 34,
  gender: "male",
  country: "IN",
  device: "desktop",
  language: "en",
  // ... existing fields
}
```

### Query for Mismatch Analysis
```javascript
// Endpoint: GET /api/audit/screenout-analysis
db.url_parameters.aggregate([
  { $match: { status: "TERMINATED" } },
  {
    $group: {
      _id: { country: "$country", device: "$device" },
      count: { $sum: 1 }
    }
  }
])
```

## 3. Redirect Parameter Integrity

### Outbound Snapshot
Logged when traffic is assigned to survey:
```javascript
{
  event_type: "cpx_redirect_out",
  timestamp: ISODate("..."),
  user_id: "traffic_id",
  subid: "traffic_id",  // SFWID
  url: "https://click.cpx-research.com/...",
  params: {
    survey_id: "12345",
    traffic_id: "...",
    respondent_id: "...",
    country_code: "US"
  }
}
```

### Inbound Snapshot
Logged when callback is received:
```javascript
{
  event_type: "cpx_redirect_in",
  timestamp: ISODate("..."),
  raw_query: {
    msg: "complete",
    sfwid: "traffic_id",
    trans_id: "..."
  },
  headers: {
    "user-agent": "...",
    "x-forwarded-for": "..."
  }
}
```

### Invariant Check
```python
if outgoing_subid != incoming_subid:
    # Log violation
    audit_service._log_audit_event("parameter_integrity_violation", {...})
    # Create CRITICAL alert
    audit_service._create_alert("subid_mismatch", "CRITICAL", "...")
```

## 4. Screen-Out Reason Classification

### Duration Calculation
```python
duration_seconds = (callback_time - created_at).total_seconds()
```

### Classification Thresholds
| Type | Duration | Likely Cause |
|------|----------|--------------|
| IMMEDIATE_REJECT | < 5 seconds | Geo/device/quota mismatch |
| SCREENER_FAIL | 5-30 seconds | Demographic mismatch |
| QUALITY_REJECT | > 30 seconds | Traffic quality issues |

### Schema Update
```javascript
// Added to url_parameters collection
{
  _id: ObjectId("..."),
  duration_seconds: 15.5,
  screenout_type: "SCREENER_FAIL",
  // ... existing fields
}
```

### Analysis Query
```javascript
// Endpoint: GET /api/audit/screenout-analysis?lookback_hours=24
db.url_parameters.aggregate([
  { $match: { status: "TERMINATED", createdAt: { $gte: cutoff } } },
  {
    $group: {
      _id: "$screenout_type",
      count: { $sum: 1 },
      avg_duration: { $avg: "$duration_seconds" }
    }
  }
])
```

## 5. Postback Consistency Audit

### Validation Rules
```python
# ASSERTION 1: Complete status must have payout > 0
if status == "complete" and payout <= 0:
    log_error("Complete status but payout is zero")

# ASSERTION 2: One postback per subid (handled by existing deduplication)
# Uses postback_hash in survey_transactions collection
```

### Duplicate Detection
Already implemented in `cpx_api.py`:
```python
postback_hash = sha256(f"{trans_id}:{status}:{amount_usd}")[:16]
existing = survey_transactions_collection.find_one({
    "postback_hash": postback_hash
})
```

## 6. Time-of-Day & Inventory Audit

### Hourly Analysis
```python
# Endpoint: GET /api/audit/time-of-day-analysis?lookback_days=7
pipeline = [
  { $addFields: { hour_of_day: { $hour: "$createdAt" } } },
  {
    $group: {
      _id: "$hour_of_day",
      total: { $sum: 1 },
      terminated: {
        $sum: { $cond: [{ $eq: ["$status", "TERMINATED"] }, 1, 0] }
      }
    }
  }
]
```

### Interpretation
- High screenout rate during specific hours → No inventory
- Consistent screenout rate → Traffic quality issue

## 7. Automated Failure Flags

### Alert Conditions
| Condition | Threshold | Action | Severity |
|-----------|-----------|--------|----------|
| High screenout rate | > 80% (last 100) | Auto-pause | CRITICAL |
| Repeat fingerprint | Same user > 1 attempt | Block | HIGH |
| Subid mismatch | Any occurrence | Kill switch | CRITICAL |
| Instant reject rate | > 30% (duration < 3s) | Inventory alert | HIGH |

### Implementation
```python
# Check on every 100th traffic record
screenout_rate = audit_service.get_screenout_rate(100)
if screenout_rate > 0.80:
    audit_service._create_alert(
        "high_screenout_rate",
        "CRITICAL",
        f"Screen-out rate {screenout_rate:.1%} exceeds 80%"
    )
```

### Alert Schema
```javascript
{
  alert_type: "high_screenout_rate",
  severity: "CRITICAL",  // CRITICAL | HIGH | MEDIUM | LOW
  message: "Screen-out rate 85.0% exceeds threshold 80.0%",
  timestamp: ISODate("..."),
  resolved: false,
  resolved_at: null
}
```

## 8. Diagnostic Decision Tree

### API Endpoint
```
GET /api/audit/diagnostic-summary?hours=24
```

### Decision Logic
```python
# Check 1: Fingerprint loops
if repeat_fingerprints > 10:
    issue = "User recycling loop - implement harder blocking"

# Check 2: Instant rejects
if immediate_reject_pct > 50%:
    issue = "Wrong geo/device - check CPX targeting"

# Check 3: Screener fails
if screener_fail_pct > 50%:
    issue = "Demographic mismatch - improve pre-screening"

# Check 4: Quality rejects
if quality_reject_pct > 40%:
    issue = "Traffic quality problem - review sources"

# Check 5: Tracking issues
if integrity_violations > 0:
    issue = "Broken tracking - investigate URL generation"
```

### Response Format
```json
{
  "timeframe_hours": 24,
  "screenout_rate": 0.75,
  "repeat_fingerprints": 15,
  "integrity_violations": 0,
  "screenout_breakdown": {
    "IMMEDIATE_REJECT": { "count": 100, "percentage": 60 },
    "SCREENER_FAIL": { "count": 50, "percentage": 30 },
    "QUALITY_REJECT": { "count": 17, "percentage": 10 }
  },
  "issues": [
    {
      "type": "instant_rejects",
      "severity": "CRITICAL",
      "message": "60% instant rejects - wrong geo/device/quota",
      "fix": "Check CPX targeting settings and traffic source"
    }
  ],
  "health_status": "CRITICAL"
}
```

## API Endpoints

### Audit Endpoints
All endpoints are prefixed with `/api/audit/`

1. **GET /screenout-analysis**
   - Query params: `lookback_hours` (1-168)
   - Returns: Breakdown by screenout type

2. **GET /screenout-rate**
   - Query params: `last_n` (10-1000)
   - Returns: Current rate + auto-pause status

3. **GET /time-of-day-analysis**
   - Query params: `lookback_days` (1-30)
   - Returns: Hourly screenout patterns

4. **GET /fingerprint-stats**
   - No params
   - Returns: User tracking statistics

5. **GET /audit-logs**
   - Query params: `event_type`, `hours`, `limit`
   - Returns: Filtered audit logs

6. **GET /alerts**
   - Query params: `resolved`, `severity`, `hours`, `limit`
   - Returns: Alert list

7. **POST /alerts/{alert_id}/resolve**
   - Marks alert as resolved

8. **GET /diagnostic-summary**
   - Query params: `hours` (1-168)
   - Returns: Comprehensive diagnostic report

## Database Collections

### cpx_user_fingerprints
```javascript
{
  fingerprint_hash: String (unique),
  first_seen_at: Date,
  attempt_count: Number,
  last_attempt_at: Date,
  status: String,
  traffic_ids: [String]
}
// Indexes: fingerprint_hash (unique), status
```

### cpx_audit_logs
```javascript
{
  event_type: String,  // user_blocked_repeat_attempt, pre_screen_data, cpx_redirect_out, cpx_redirect_in, parameter_integrity_violation
  timestamp: Date,
  user_id: String,
  ...event_specific_fields
}
// Indexes: event_type, timestamp, user_id
```

### cpx_audit_alerts
```javascript
{
  alert_type: String,
  severity: String,
  message: String,
  timestamp: Date,
  resolved: Boolean,
  resolved_at: Date
}
// Indexes: alert_type, timestamp, resolved
```

### url_parameters (enhanced)
```javascript
{
  _id: ObjectId,
  fingerprint_hash: String,
  duration_seconds: Number,
  screenout_type: String,
  // Demographic fields
  age: Number,
  gender: String,
  country: String,
  device: String,
  language: String,
  ip_address: String,
  accept_language: String,
  // ... existing fields
}
// Indexes: fingerprint_hash, screenout_type, duration_seconds
```

## Integration Points

### Traffic Creation
```python
# backend/app/services/traffic_service.py
traffic_service.create_traffic_record(
    vendor_id=...,
    country_code=...,
    respondent_id=...,
    ip=request.client.host,  # NEW
    accept_language=request.headers.get("accept-language"),  # NEW
    demographic_data={  # NEW
        "age": 34,
        "gender": "male",
        "device": "desktop"
    }
)
```

### CPX Callback
```python
# backend/routers/traffic.py
# Automatic logging on callback:
audit_service.log_redirect_in(raw_query, headers)
# Automatic duration + screenout classification
```

### Postback
```python
# backend/routers/cpx_api.py
# Automatic validation:
audit_service.validate_postback(status, payout)
```

## Monitoring & Alerts

### Dashboard Queries
```javascript
// Active alerts
db.cpx_audit_alerts.find({ resolved: false }).sort({ timestamp: -1 })

// Recent blocks
db.cpx_audit_logs.find({ 
  event_type: "user_blocked_repeat_attempt" 
}).sort({ timestamp: -1 }).limit(10)

// Screenout summary (last 24h)
db.url_parameters.aggregate([
  { $match: { createdAt: { $gte: new Date(Date.now() - 86400000) } } },
  { $group: { _id: "$screenout_type", count: { $sum: 1 } } }
])
```

### Alert Workflow
1. System generates alert when condition met
2. Alert stored in `cpx_audit_alerts` collection
3. GET `/api/audit/alerts` retrieves unresolved alerts
4. Admin investigates via `/api/audit/diagnostic-summary`
5. POST `/api/audit/alerts/{id}/resolve` marks as resolved

## Testing

Run the unit tests:
```bash
cd backend
python test_audit_framework.py
```

Tests cover:
- Fingerprint generation
- Screenout classification
- Postback validation
- Auto-pause logic
- Duration calculation
- Parameter integrity

## Troubleshooting

### High Screenout Rate
1. Check `/api/audit/screenout-analysis` for breakdown
2. If IMMEDIATE_REJECT > 50%: Review CPX targeting (geo/device)
3. If SCREENER_FAIL > 50%: Improve pre-screening
4. If QUALITY_REJECT > 40%: Review traffic sources

### Tracking Issues
1. Check `/api/audit/audit-logs?event_type=parameter_integrity_violation`
2. Review outgoing vs incoming parameters
3. Verify URL generation in `traffic_service.py`

### User Loops
1. Check `/api/audit/fingerprint-stats`
2. Review `repeat_attempts` count
3. Consider increasing cooldown or permanent blocking

## Performance Considerations

- All audit logging is non-blocking
- Database writes use background tasks where possible
- Indexes ensure fast queries
- Alert generation is throttled to prevent spam

## Future Enhancements

1. Machine learning for fraud detection
2. Automated traffic source quality scoring
3. Real-time dashboard with WebSocket updates
4. Email/SMS alerts for critical issues
5. A/B testing framework for CPX settings
