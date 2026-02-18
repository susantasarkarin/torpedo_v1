# Quick Reference: Get Respondent Payloads

## New Endpoint

```
GET /api/cint/respondent-payloads?limit=10
```

## What It Returns

The entry link payloads for the last N respondents who were sent to Cint surveys, along with their outcome data.

## Quick Examples

### Get Last 10 Respondents (default)
```bash
curl http://localhost:8000/api/cint/respondent-payloads
```

### Get Last 25 Respondents
```bash
curl http://localhost:8000/api/cint/respondent-payloads?limit=25
```

### Python
```python
import requests

response = requests.get(
    "http://localhost:8000/api/cint/respondent-payloads",
    params={"limit": 10}
)

data = response.json()

for respondent in data["respondents"]:
    print(f"Respondent ID: {respondent['entry_link_payload']['respondent_id']}")
    print(f"Survey ID: {respondent['entry_link_payload']['survey_id']}")
    print(f"Status: {respondent['outcome']['final_status']}")
    print(f"Payout: ${respondent['outcome']['payout']}")
    print("---")
```

## Response Example

```json
{
  "success": true,
  "count": 10,
  "respondents": [
    {
      "entry_link_payload": {
        "survey_id": "123456",
        "supplier_code": "6777",
        "respondent_id": "USER_12345",
        "secure_hash": "[REDACTED]",
        "return_url": "https://torpedo.cogentixresearch.com/api/cint/status"
      },
      "outcome": {
        "session_id": "SESSION_ABC123",
        "final_status": "complete",
        "marketplace_status": 10,
        "client_status": 3,
        "payout": 1.25,
        "currency": "USD",
        "entry_date": "2026-02-18T10:30:00Z",
        "last_date": "2026-02-18T10:45:00Z",
        "received_at": "2026-02-18T10:46:00Z"
      },
      "api_endpoint": "POST https://api.samplicio.us/supply/v1/entrylinks"
    }
  ],
  "note": "secure_hash is redacted for security...",
  "retrieved_at": "2026-02-18T14:50:00Z"
}
```

## What Each Field Means

### Entry Link Payload
- **survey_id**: The Cint survey this respondent was sent to
- **supplier_code**: Your Cint supplier code (usually "6777")
- **respondent_id**: Your internal user/respondent ID
- **secure_hash**: HMAC-SHA256 hash (redacted for security)
- **return_url**: Where Cint sends status callbacks

### Outcome
- **session_id**: Cint's unique session identifier
- **final_status**: What happened (complete, screenout, quota_full, etc.)
- **marketplace_status**: Cint's status code
- **client_status**: Client/buyer's status code
- **payout**: Money earned (for completed surveys)
- **currency**: Usually "USD"
- **entry_date**: When they started the survey
- **last_date**: Last status update from Cint
- **received_at**: When we received the outcome

## Status Values

| Status | Meaning | Payout? |
|--------|---------|---------|
| complete | Survey completed successfully | Yes ✅ |
| screenout | Didn't qualify | No ❌ |
| quota_full | Survey full | No ❌ |
| terminate | Terminated by user/system | No ❌ |
| overquota | Quota exceeded | No ❌ |
| quality_terminate | Quality issue | No ❌ |

## Common Use Cases

1. **View recent activity**: See what surveys respondents are taking
2. **Check payouts**: Review earnings for completed surveys
3. **Debug issues**: Verify payloads were created correctly
4. **Analytics**: Analyze completion rates and patterns
5. **Audit trail**: Track respondent survey history

## Security Note

🔒 The `secure_hash` is **intentionally redacted** for security. It should never be exposed or logged publicly.

## Full Documentation

See `docs/integrations/cint/RESPONDENT_PAYLOADS_API.md` for complete details.

## Related Endpoints

- `GET /api/cint/entry-link-json-format` - Get JSON format specification
- `POST /api/cint/respondent-link` - Create new entry link
- `POST /api/cint/webhooks/respondent-outcomes` - Webhook for outcomes
