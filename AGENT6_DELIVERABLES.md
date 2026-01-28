# Agent 6 Deliverables - Timezone Scheduler & Domain Health Service

**Author**: Agent 6  
**Date**: January 28, 2026  
**Mission**: Create timezone detection/scheduling service and DNS-based domain health monitoring

---

## 📦 Deliverables

### 1. Timezone-Aware Send Scheduler
**File**: `backend/campaigns/send_scheduler.py` (432 lines)

**Features**:
- ✅ Timezone detection from lead location (city, state, country, coordinates)
- ✅ US state to timezone mapping (50 states)
- ✅ Major city to timezone mapping (30+ cities globally)
- ✅ Country default timezone mapping (10+ countries)
- ✅ Latitude/longitude timezone detection using timezonefinder
- ✅ Recipient local time calculation
- ✅ Send window validation (default: 9-11am, 2-4pm local time)
- ✅ Next send window calculation
- ✅ Convenience functions for direct use

**Key Classes**:
- `SendScheduler`: Main scheduler service class

**Key Methods**:
- `detect_timezone(city, state, country, latitude, longitude)` → str
- `get_recipient_local_time(recipient, reference_time)` → datetime
- `is_within_send_window(local_time, windows)` → bool
- `can_send_now(recipient, windows)` → (bool, str)
- `get_next_send_window(recipient, windows)` → datetime

**Usage Example**:
```python
from backend.campaigns import SendScheduler

scheduler = SendScheduler()

recipient = {
    'city': 'San Francisco',
    'state': 'CA',
    'country': 'US'
}

# Check if can send now
can_send, reason = scheduler.can_send_now(recipient)
print(f"Can send: {can_send}, Reason: {reason}")

# Get recipient's local time
local_time = scheduler.get_recipient_local_time(recipient)
print(f"Recipient local time: {local_time}")

# Get next send window
next_window = scheduler.get_next_send_window(recipient)
print(f"Next send window: {next_window}")
```

---

### 2. Domain Health Service
**File**: `backend/deliverability/domain_health.py` (634 lines)

**Features**:
- ✅ SPF record verification with validation
- ✅ DKIM selector validation (checks 12 common selectors)
- ✅ Auto-detection of valid DKIM selectors
- ✅ DMARC policy checking (none/quarantine/reject)
- ✅ MX record validation
- ✅ Composite health score calculation (0-100)
- ✅ Letter grade assignment (A-F)
- ✅ Automated recommendations generation
- ✅ Comprehensive error handling

**Key Classes**:
- `DomainHealthService`: Main domain health monitoring service

**Key Methods**:
- `check_spf(domain)` → Dict
- `check_dkim(domain, selector)` → Dict
- `check_dkim_auto(domain)` → Dict (checks multiple selectors)
- `check_dmarc(domain)` → Dict
- `check_mx_records(domain)` → List[str]
- `calculate_health_score(domain)` → Dict (full report with score 0-100)
- `get_recommendations(health_result)` → List[str]

**Health Score Breakdown**:
- SPF: 25 points (pass=25, fail/none=0)
- DKIM: 25 points (valid=25, none=0)
- DMARC: 25 points (reject=25, quarantine=20, none=10, missing=0)
- MX: 25 points (has records=25, none=0)

**Grading Scale**:
- A: 90-100 (Excellent)
- B: 80-89 (Good)
- C: 70-79 (Fair)
- D: 60-69 (Poor)
- F: 0-59 (Failing)

**Usage Example**:
```python
from backend.deliverability import DomainHealthService

service = DomainHealthService()

# Full health check
result = service.calculate_health_score('example.com')

print(f"Score: {result['score']}/100 (Grade: {result['grade']})")
print(f"SPF: {result['spf']['status']}")
print(f"DKIM: {len(result['dkim']['valid_selectors'])} valid selectors")
print(f"DMARC: {result['dmarc']['policy']}")
print(f"MX: {len(result['mx'])} records")

# Get recommendations
recommendations = service.get_recommendations(result)
for rec in recommendations:
    print(f"- {rec}")
```

---

## 📚 Dependencies

**New Dependencies Required**:

```bash
pip install timezonefinder
pip install pytz
pip install dnspython
```

**Dependency Details**:
- `timezonefinder` (v6.x): Timezone detection from coordinates
- `pytz` (2024.x): Timezone handling and conversion
- `dnspython` (v2.x): DNS query and record parsing

**Installation**:
```bash
cd backend
pip install timezonefinder pytz dnspython
```

---

## 🔗 Integration Points

### Campaign Executor Integration
**File**: `backend/campaigns/campaign_executor.py`

To integrate timezone-aware scheduling into the campaign executor's `_can_send()` method:

```python
from backend.campaigns import SendScheduler

class CampaignExecutor:
    def __init__(self):
        self.scheduler = SendScheduler()
    
    def _can_send(self, recipient: Dict, campaign_settings: Dict) -> Tuple[bool, str]:
        """Enhanced with timezone awareness"""
        
        # ... existing checks ...
        
        # Check timezone-aware send window
        can_send, reason = self.scheduler.can_send_now(
            recipient,
            windows=campaign_settings.get('send_windows', [(9, 11), (14, 16)])
        )
        
        if not can_send:
            return False, f"Outside send window: {reason}"
        
        return True, "Can send"
```

### Domain Health Monitoring
**Use Case**: Pre-send domain validation

```python
from backend.deliverability import DomainHealthService

def validate_sender_domain(email: str) -> Tuple[bool, str]:
    """Validate sender domain health before campaign start"""
    domain = email.split('@')[1]
    
    service = DomainHealthService()
    health = service.calculate_health_score(domain)
    
    if health['score'] < 60:
        return False, f"Domain health too low ({health['score']}/100, Grade: {health['grade']})"
    
    return True, f"Domain health acceptable ({health['score']}/100)"
```

---

## 🧪 Testing

Both modules include `__main__` blocks for standalone testing:

```bash
# Test Send Scheduler
cd backend/campaigns
python send_scheduler.py

# Test Domain Health Service
cd backend/deliverability
python domain_health.py
```

---

## 📊 Module Statistics

| Module | File | Lines | Functions | Classes |
|--------|------|-------|-----------|---------|
| Send Scheduler | send_scheduler.py | 432 | 8 | 1 |
| Domain Health | domain_health.py | 634 | 10 | 1 |
| **Total** | | **1,066** | **18** | **2** |

---

## ✅ Completion Summary

**Status**: ✅ **COMPLETE**

All requirements implemented:

1. ✅ Timezone detection service with multiple detection strategies
2. ✅ Send window validation (9-11am, 2-4pm local time)
3. ✅ Integration-ready for campaign_executor.py
4. ✅ DNS-based health checks (SPF, DKIM, DMARC, MX)
5. ✅ Composite health score (0-100) with letter grades
6. ✅ Automated recommendations generation
7. ✅ Comprehensive error handling and logging
8. ✅ Convenience functions for easy integration
9. ✅ Complete documentation and examples
10. ✅ Standalone testing capabilities

**Dependencies**: timezonefinder, pytz, dnspython

**Ready for production use**.

---

## 🚀 Next Steps

1. Install required dependencies: `pip install timezonefinder pytz dnspython`
2. Integrate `SendScheduler` into `campaign_executor.py`'s `_can_send()` method
3. Add domain health checks to campaign creation workflow
4. Consider adding database models to store domain health history
5. Set up periodic domain health monitoring (daily/weekly)

---

**End of Agent 6 Deliverables**
