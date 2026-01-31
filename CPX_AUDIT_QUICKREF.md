# CPX Audit Framework - Quick Reference

## API Endpoints

### Base URL
All audit endpoints: `/api/audit/`

### Main Endpoints

1. **Diagnostic Summary** (Start here!)
   ```
   GET /api/audit/diagnostic-summary?hours=24
   ```
   Returns comprehensive health check with recommended fixes.

2. **Screenout Analysis**
   ```
   GET /api/audit/screenout-analysis?lookback_hours=24
   ```
   Breakdown: IMMEDIATE_REJECT, SCREENER_FAIL, QUALITY_REJECT

3. **Current Screenout Rate**
   ```
   GET /api/audit/screenout-rate?last_n=100
   ```
   Shows if auto-pause condition is met.

4. **Time Patterns**
   ```
   GET /api/audit/time-of-day-analysis?lookback_days=7
   ```
   Detect inventory gaps by hour.

5. **Active Alerts**
   ```
   GET /api/audit/alerts?resolved=false
   ```
   Critical issues requiring attention.

6. **User Fingerprints**
   ```
   GET /api/audit/fingerprint-stats
   ```
   Track unique users and repeat attempts.

7. **Audit Logs**
   ```
   GET /api/audit/audit-logs?event_type=parameter_integrity_violation&hours=24
   ```
   Detailed event logs.

## Decision Tree

### 1. High Screenout Rate (> 80%)
→ Check `/screenout-analysis`
- **IMMEDIATE_REJECT > 50%**: Wrong geo/device/quota
  - Fix: Adjust CPX targeting settings
- **SCREENER_FAIL > 50%**: Demographics don't match
  - Fix: Improve pre-screening
- **QUALITY_REJECT > 40%**: Traffic quality issues
  - Fix: Change traffic source

### 2. User Loops
→ Check `/fingerprint-stats`
- **repeat_attempts > 10%**: Users being recycled
  - Fix: Increase cooldown or permanent blocking

### 3. Tracking Issues
→ Check `/audit-logs?event_type=parameter_integrity_violation`
- **integrity_violations > 0**: Subid mismatch
  - Fix: Review URL generation code

### 4. No Inventory
→ Check `/time-of-day-analysis`
- **Screenout spikes at certain hours**: CPX has no surveys
  - Fix: Stop sending traffic during dead hours

## Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| Screenout Rate | > 80% | Auto-pause |
| Instant Rejects | > 30% | Geo/device alert |
| Repeat Fingerprints | > 1 attempt | Block user |
| Subid Mismatch | Any | Kill switch |

## Screenout Types

| Type | Duration | Meaning |
|------|----------|---------|
| IMMEDIATE_REJECT | < 5s | Geo/device/quota mismatch |
| SCREENER_FAIL | 5-30s | Failed demographic questions |
| QUALITY_REJECT | > 30s | Detected as low quality |

## Common Issues & Fixes

### Issue: 85% Screenout Rate
```bash
# Check breakdown
curl http://localhost:8000/api/audit/screenout-analysis?lookback_hours=24

# If IMMEDIATE_REJECT is high:
# → CPX targeting doesn't match traffic
# → Review CPX dashboard settings
# → Verify traffic geo/device distribution
```

### Issue: Same Users Repeating
```bash
# Check fingerprint stats
curl http://localhost:8000/api/audit/fingerprint-stats

# Response shows repeat_attempts: 50
# → Blocking is working but traffic source is recycling
# → Contact traffic vendor
# → Implement IP-level blocking
```

### Issue: Tracking Broken
```bash
# Check for violations
curl http://localhost:8000/api/audit/audit-logs?event_type=parameter_integrity_violation

# Review code:
# backend/app/services/traffic_service.py - URL generation
# backend/routers/traffic.py - Callback handling
```

## Database Queries

### Quick Checks (MongoDB Shell)

```javascript
// Active alerts
db.cpx_audit_alerts.find({ resolved: false })

// Screenout breakdown (last 24h)
db.url_parameters.aggregate([
  { $match: { 
    createdAt: { $gte: new Date(Date.now() - 86400000) },
    status: "TERMINATED"
  }},
  { $group: { _id: "$screenout_type", count: { $sum: 1 } } }
])

// Repeat users
db.cpx_user_fingerprints.find({ attempt_count: { $gt: 1 } }).count()

// Parameter violations (last hour)
db.cpx_audit_logs.find({
  event_type: "parameter_integrity_violation",
  timestamp: { $gte: new Date(Date.now() - 3600000) }
}).count()
```

## Alert Types

| Type | Severity | Trigger |
|------|----------|---------|
| high_screenout_rate | CRITICAL | > 80% in last 100 |
| subid_mismatch | CRITICAL | Any mismatch detected |
| fingerprint_violation | HIGH | User blocked for repeat |
| instant_reject_spike | HIGH | > 30% duration < 3s |

## Integration Checklist

When adding new traffic source:

- [ ] Capture IP address for fingerprinting
- [ ] Capture Accept-Language header
- [ ] Include demographic data (age, gender, device)
- [ ] Test with 10-20 test users
- [ ] Monitor `/diagnostic-summary` for 24 hours
- [ ] Check fingerprint stats for duplicates
- [ ] Verify screenout rate < 50%

## Monitoring Schedule

### Real-time (per transaction)
- Fingerprint blocking
- Parameter integrity checks
- Duration calculation

### Every 100 transactions
- Screenout rate check
- Auto-pause evaluation

### Hourly
- Alert summary
- Time-of-day patterns

### Daily
- Full diagnostic summary
- Traffic source quality report
- Fingerprint analysis

## Testing

```bash
# Run unit tests
cd backend
python test_audit_framework.py

# Test API (requires server running)
curl http://localhost:8000/api/audit/diagnostic-summary?hours=24
```

## Emergency Actions

### Auto-Pause Triggered
1. Check `/diagnostic-summary` for root cause
2. Review recent changes to traffic sources
3. Temporarily disable problematic source
4. Monitor for 1 hour
5. Re-enable with smaller batch size

### Subid Mismatch Kill Switch
1. STOP all new traffic immediately
2. Check `/audit-logs` for violation details
3. Review URL generation in code
4. Test with single traffic record
5. Verify fix before re-enabling

### User Loop Detected
1. Review `/fingerprint-stats`
2. Export repeat fingerprints
3. Contact traffic vendor
4. Implement IP blacklist if needed
5. Increase cooldown period

## Support

For issues or questions:
1. Check this guide
2. Review `/diagnostic-summary` output
3. Check `/audit-logs` for specific errors
4. Review CPX_AUDIT_FRAMEWORK.md for details
