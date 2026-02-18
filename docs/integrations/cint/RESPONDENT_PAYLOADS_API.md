# Get Respondent Entry Link Payloads

## Endpoint

```
GET /api/cint/respondent-payloads?limit=10
```

## Description

Retrieves the entry link payloads for the last N respondents who have been sent to Cint surveys. This endpoint reconstructs the payloads that were sent to the Cint API based on stored respondent outcome data.

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 10 | Number of recent respondents to return (min: 1, max: 100) |

## Response Format

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
        "secure_hash": "[REDACTED - Use HMAC_SHA256(supplier_code + survey_id + respondent_id, encryption_key)]",
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
  "note": "secure_hash is redacted for security. Generate using: HMAC_SHA256(supplier_code + survey_id + respondent_id, encryption_key)",
  "retrieved_at": "2026-02-18T14:50:00Z"
}
```

## Field Descriptions

### Entry Link Payload Fields

| Field | Description |
|-------|-------------|
| `survey_id` | Cint survey ID that the respondent was sent to |
| `supplier_code` | Supplier code (typically "6777") |
| `respondent_id` | Your internal respondent/user ID |
| `secure_hash` | HMAC-SHA256 hash (redacted for security) |
| `return_url` | Callback URL for status updates |

### Outcome Fields

| Field | Description |
|-------|-------------|
| `session_id` | Cint session ID for this respondent attempt |
| `final_status` | Final outcome status (complete, screenout, quota_full, etc.) |
| `marketplace_status` | Cint marketplace status code |
| `client_status` | Client/buyer status code |
| `payout` | Revenue earned (for completed surveys) |
| `currency` | Currency code (typically "USD") |
| `entry_date` | When respondent entered the survey |
| `last_date` | Last update timestamp from Cint |
| `received_at` | When the outcome was received by our system |

## Examples

### Get Last 10 Respondents

```bash
curl http://localhost:8000/api/cint/respondent-payloads?limit=10
```

### Get Last 25 Respondents

```bash
curl http://localhost:8000/api/cint/respondent-payloads?limit=25
```

### Python Example

```python
import requests

response = requests.get(
    "http://localhost:8000/api/cint/respondent-payloads",
    params={"limit": 10}
)

data = response.json()

for respondent in data["respondents"]:
    payload = respondent["entry_link_payload"]
    outcome = respondent["outcome"]
    
    print(f"Respondent: {payload['respondent_id']}")
    print(f"Survey: {payload['survey_id']}")
    print(f"Status: {outcome['final_status']}")
    print(f"Payout: ${outcome['payout']}")
    print("---")
```

### JavaScript Example

```javascript
fetch('http://localhost:8000/api/cint/respondent-payloads?limit=10')
  .then(response => response.json())
  .then(data => {
    data.respondents.forEach(respondent => {
      const payload = respondent.entry_link_payload;
      const outcome = respondent.outcome;
      
      console.log(`Respondent: ${payload.respondent_id}`);
      console.log(`Survey: ${payload.survey_id}`);
      console.log(`Status: ${outcome.final_status}`);
      console.log(`Payout: $${outcome.payout}`);
      console.log('---');
    });
  });
```

## Security Note

⚠️ **Important**: The `secure_hash` field is **redacted** in the response for security reasons. 

The secure hash is an HMAC-SHA256 hash that authenticates entry link requests to Cint. It should never be exposed publicly or logged.

To generate a secure hash for a new entry link:

```python
import hmac
import hashlib

message = f"{supplier_code}{survey_id}{respondent_id}"
secure_hash = hmac.new(
    encryption_key.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

## Use Cases

This endpoint is useful for:

1. **Debugging**: Review what payloads were sent for specific respondents
2. **Analytics**: Analyze survey completion patterns and payouts
3. **Testing**: Verify that entry links are being created correctly
4. **Audit**: Track which respondents were sent to which surveys
5. **Reporting**: Generate reports on respondent activity and earnings

## Error Responses

### 503 Service Unavailable

Database connection not available:

```json
{
  "detail": "Database not available. Cannot retrieve respondent data."
}
```

### 500 Internal Server Error

Error retrieving data:

```json
{
  "detail": "Failed to retrieve respondent payloads: [error message]"
}
```

## Notes

- Respondents are returned in reverse chronological order (most recent first)
- Only respondents with stored outcome data are included
- The endpoint reconstructs payloads from stored data, not from logs
- If no respondent data exists, an empty list is returned with `count: 0`
- The `secure_hash` is intentionally redacted for security

## Related Endpoints

- **Entry Link JSON Format**: `GET /api/cint/entry-link-json-format`
- **Create Entry Link**: `POST /api/cint/respondent-link`
- **Respondent Outcomes Webhook**: `POST /api/cint/webhooks/respondent-outcomes`
- **Status Callback**: `POST /api/cint/status`

## See Also

- [Cint Entry Link API Guide](./CINT_ENTRY_LINK_API.md)
- [How to Access Entry Link JSON](./HOW_TO_ACCESS_ENTRY_LINK_JSON.md)
