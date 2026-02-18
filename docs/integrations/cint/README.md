# Cint Integration Documentation

This folder contains comprehensive documentation for the Cint survey integration.

## 📋 Quick Links

### Entry Link API (New! ⭐)
- **[Cint Entry Link API Guide](./CINT_ENTRY_LINK_API.md)** - Complete API documentation with examples
- **[How to Access Entry Link JSON](./HOW_TO_ACCESS_ENTRY_LINK_JSON.md)** - Quick access guide
- **[JSON Example File](./cint_entry_link_json_example.json)** - Raw JSON format reference

**API Endpoint:**
```
GET /api/cint/entry-link-json-format
```

### Integration Documentation
- **[Integration Complete](./CINT_INTEGRATION_COMPLETE.md)** - Overview of completed integration
- **[Status Report](./CINT_STATUS_REPORT.md)** - Current integration status
- **[Integration Fixes](./CINT_INTEGRATION_FIXES.md)** - History of fixes and updates
- **[Diagnostic Guide](./CINT_DIAGNOSTIC_GUIDE.md)** - Troubleshooting and diagnostics

## 🎯 What You Need

### For Developers
If you need to integrate with the Cint Entry Link API:
1. Start with **[CINT_ENTRY_LINK_API.md](./CINT_ENTRY_LINK_API.md)** for complete API documentation
2. Use **[HOW_TO_ACCESS_ENTRY_LINK_JSON.md](./HOW_TO_ACCESS_ENTRY_LINK_JSON.md)** for quick access methods
3. Reference **[cint_entry_link_json_example.json](./cint_entry_link_json_example.json)** for the exact JSON structure

### For Integration Testing
If you need to test or troubleshoot the integration:
1. Check **[CINT_INTEGRATION_COMPLETE.md](./CINT_INTEGRATION_COMPLETE.md)** for system overview
2. Use **[CINT_DIAGNOSTIC_GUIDE.md](./CINT_DIAGNOSTIC_GUIDE.md)** for debugging
3. Review **[CINT_STATUS_REPORT.md](./CINT_STATUS_REPORT.md)** for current status

## 📦 What's the Cint Entry Link API?

The Cint Entry Link API creates respondent-specific survey URLs. Each link is unique to a user and must be generated fresh for each survey attempt.

### Key Features:
- ✅ Respondent-specific URLs (no sharing/reusing)
- ✅ HMAC-SHA256 security verification
- ✅ Status callbacks (complete, screenout, quota_full, etc.)
- ✅ Real-time survey opportunity updates via webhooks

### Request Structure:
```json
{
  "survey_id": "123456",
  "supplier_code": "6777",
  "respondent_id": "USER_12345",
  "secure_hash": "computed_hmac_sha256_hash",
  "return_url": "https://your-domain.com/api/cint/status"
}
```

### Response:
```json
{
  "live_link": "https://surveys.samplicio.us/router/...",
  "survey_id": "123456",
  "respondent_id": "USER_12345"
}
```

## 🚀 Quick Start

### Get JSON Format (3 ways)

**1. Via API:**
```bash
curl http://localhost:8000/api/cint/entry-link-json-format
```

**2. Via File:**
```bash
cat docs/integrations/cint/cint_entry_link_json_example.json
```

**3. Via Documentation:**
```bash
less docs/integrations/cint/CINT_ENTRY_LINK_API.md
```

### Create Entry Link (Python)

```python
import hmac
import hashlib
import requests

# Generate secure hash
message = f"{supplier_code}{survey_id}{respondent_id}"
secure_hash = hmac.new(
    encryption_key.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()

# Create entry link
response = requests.post(
    "https://api.samplicio.us/supply/v1/entrylinks",
    headers={"Authorization": api_key},
    json={
        "survey_id": survey_id,
        "supplier_code": supplier_code,
        "respondent_id": respondent_id,
        "secure_hash": secure_hash,
        "return_url": callback_url
    }
)

live_link = response.json()["live_link"]
```

## 📚 Document Index

| Document | Purpose | Audience |
|----------|---------|----------|
| [CINT_ENTRY_LINK_API.md](./CINT_ENTRY_LINK_API.md) | Complete Entry Link API guide | Developers |
| [HOW_TO_ACCESS_ENTRY_LINK_JSON.md](./HOW_TO_ACCESS_ENTRY_LINK_JSON.md) | Access guide | All users |
| [cint_entry_link_json_example.json](./cint_entry_link_json_example.json) | JSON reference | Developers |
| [CINT_INTEGRATION_COMPLETE.md](./CINT_INTEGRATION_COMPLETE.md) | Integration overview | Integration team |
| [CINT_STATUS_REPORT.md](./CINT_STATUS_REPORT.md) | Current status | All users |
| [CINT_DIAGNOSTIC_GUIDE.md](./CINT_DIAGNOSTIC_GUIDE.md) | Troubleshooting | Support team |
| [CINT_INTEGRATION_FIXES.md](./CINT_INTEGRATION_FIXES.md) | Fix history | Integration team |

## 🔗 Related Resources

### Implementation Files
- **Service**: `backend/app/services/cint_entrylink_service.py`
- **Router**: `backend/app/routers/cint.py`
- **Models**: `backend/app/models/cint.py`

### Test Scripts
- **Entry Link Tests**: `scripts/entry_links/`
- **Cint API Tests**: `scripts/cint/`
- **Integration Test**: `test_cint_api.py`

### External Resources
- [Cint API Documentation](https://api.samplicio.us/docs)
- [Cint Developer Portal](https://developer.cint.com)
- Cint Support: support@cint.com

## 🆘 Need Help?

1. **Entry Link JSON Format**: See [CINT_ENTRY_LINK_API.md](./CINT_ENTRY_LINK_API.md)
2. **Integration Issues**: See [CINT_DIAGNOSTIC_GUIDE.md](./CINT_DIAGNOSTIC_GUIDE.md)
3. **API Questions**: Check endpoint `GET /api/cint/entry-link-json-format`
4. **Cint Support**: Email support@cint.com

---

**Last Updated:** 2026-02-18
