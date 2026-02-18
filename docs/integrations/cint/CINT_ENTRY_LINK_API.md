# Cint Entry Link API - Complete Guide

## Overview

The Cint Entry Link API creates respondent-specific survey entry URLs. Each entry link is unique to a respondent and must be generated fresh for each survey attempt.

**⚠️ CRITICAL**: Entry links are **NOT** project-level links. They are **respondent-specific** and must be generated per user.

## API Endpoint

```
POST https://api.samplicio.us/supply/v1/entrylinks
```

## Authentication

Use your Cint API key in the Authorization header:

```http
Authorization: YOUR_CINT_API_KEY
Content-Type: application/json
Accept: application/json
```

## Request Payload

### JSON Structure

```json
{
  "survey_id": "123456",
  "supplier_code": "6777",
  "respondent_id": "USER_12345",
  "secure_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
  "return_url": "https://torpedo.cogentixresearch.com/api/cint/status"
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `survey_id` | string | ✅ Yes | The Cint survey/study ID from the opportunities webhook |
| `supplier_code` | string | ✅ Yes | Your unique Cint supplier code (default: "6777") |
| `respondent_id` | string | ✅ Yes | Your internal unique identifier for the respondent/user |
| `secure_hash` | string | ✅ Yes | HMAC-SHA256 hash for security verification (see below) |
| `return_url` | string | ✅ Yes | Callback URL for respondent outcome status updates |

## Secure Hash Generation

The `secure_hash` is an HMAC-SHA256 hash that verifies request authenticity.

### Algorithm

```
HMAC_SHA256(supplier_code + survey_id + respondent_id, encryption_key)
```

### Python Implementation

```python
import hmac
import hashlib

def generate_secure_hash(supplier_code, survey_id, respondent_id, encryption_key):
    """Generate HMAC-SHA256 secure hash for Cint entry link"""
    message = f"{supplier_code}{survey_id}{respondent_id}"
    
    hash_bytes = hmac.new(
        encryption_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return hash_bytes
```

### Example

```python
supplier_code = "6777"
survey_id = "123456"
respondent_id = "USER_12345"
encryption_key = "your_encryption_key"

# Concatenated message: "6777123456USER_12345"
message = f"{supplier_code}{survey_id}{respondent_id}"

# Generate hash
secure_hash = hmac.new(
    encryption_key.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()

# Result: "a1b2c3d4e5f6g7h8..." (64-character hex string)
```

## Response Formats

### Success Response (200 OK)

```json
{
  "live_link": "https://surveys.samplicio.us/router/default.aspx?SID=ABC123&PID=USER_12345&...",
  "survey_id": "123456",
  "respondent_id": "USER_12345"
}
```

The `live_link` is the respondent-specific URL to redirect them to the survey.

### Error Responses

| Status Code | Description | Action |
|-------------|-------------|--------|
| 404 | Survey not found or no longer active | Mark survey as inactive in your system |
| 403 | Authentication failed - invalid API key | Verify your API key is correct |
| 408 | Request timeout | Retry the request after a short delay |
| 500 | Internal server error | Retry the request or contact Cint support |

## Status Callbacks

After the respondent completes or exits the survey, Cint sends a status callback to your `return_url`.

### Callback Parameters

```json
{
  "status": "complete",
  "respondent_id": "USER_12345",
  "survey_id": "123456",
  "transaction_id": "CINT_TXN_789",
  "revenue": 1.25
}
```

### Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `complete` | Survey completed successfully | Credit the user with revenue |
| `screenout` | Respondent didn't qualify | No credit given |
| `quota_full` | Survey quota reached | No credit, block survey for other users |
| `terminate` | Survey terminated by respondent or system | No credit |
| `overquota` | Quota exceeded | Block survey for other users |
| `quality_terminate` | Terminated for quality reasons | No credit, may flag user |

## Important Notes

1. **Respondent-Specific**: Entry links are unique to each respondent. Never reuse across users.
2. **Fresh Generation**: Generate a new entry link each time a respondent starts a survey.
3. **No Caching**: Do NOT cache entry links globally. They're tied to specific respondents.
4. **Security**: The secure_hash prevents tampering and ensures request authenticity.
5. **Survey IDs**: Survey IDs come from the Cint opportunities webhook subscription.
6. **Return URL**: Must be publicly accessible for Cint to send status callbacks.

## Integration Flow

```
1. Subscribe to Cint Opportunities Webhook
   ↓
2. Receive survey opportunities (survey_id, revenue, etc.)
   ↓
3. User clicks on a survey in your platform
   ↓
4. Generate secure_hash for this user + survey
   ↓
5. Call Entry Link API with POST request
   ↓
6. Receive live_link in response
   ↓
7. Redirect user to live_link
   ↓
8. User completes/exits survey
   ↓
9. Cint sends status callback to your return_url
   ↓
10. Update user credits and survey status in your system
```

## Code Examples

### Complete Python Example

```python
import httpx
import hmac
import hashlib

async def create_cint_entry_link(survey_id: str, respondent_id: str):
    """Create a Cint entry link for a respondent"""
    
    # Configuration
    API_KEY = "your_cint_api_key"
    ENCRYPTION_KEY = "your_encryption_key"
    SUPPLIER_CODE = "6777"
    BASE_URL = "https://api.samplicio.us"
    RETURN_URL = "https://torpedo.cogentixresearch.com/api/cint/status"
    
    # Generate secure hash
    message = f"{SUPPLIER_CODE}{survey_id}{respondent_id}"
    secure_hash = hmac.new(
        ENCRYPTION_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Prepare request
    url = f"{BASE_URL}/supply/v1/entrylinks"
    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "survey_id": survey_id,
        "supplier_code": SUPPLIER_CODE,
        "respondent_id": respondent_id,
        "secure_hash": secure_hash,
        "return_url": RETURN_URL
    }
    
    # Make request
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "live_link": data["live_link"]
            }
        else:
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code
            }
```

### cURL Example

```bash
curl -X POST "https://api.samplicio.us/supply/v1/entrylinks" \
  -H "Authorization: YOUR_CINT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "survey_id": "123456",
    "supplier_code": "6777",
    "respondent_id": "USER_12345",
    "secure_hash": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
    "return_url": "https://torpedo.cogentixresearch.com/api/cint/status"
  }'
```

### JavaScript Example

```javascript
const crypto = require('crypto');
const axios = require('axios');

async function createCintEntryLink(surveyId, respondentId) {
  // Configuration
  const API_KEY = 'your_cint_api_key';
  const ENCRYPTION_KEY = 'your_encryption_key';
  const SUPPLIER_CODE = '6777';
  const BASE_URL = 'https://api.samplicio.us';
  const RETURN_URL = 'https://torpedo.cogentixresearch.com/api/cint/status';
  
  // Generate secure hash
  const message = `${SUPPLIER_CODE}${surveyId}${respondentId}`;
  const secureHash = crypto
    .createHmac('sha256', ENCRYPTION_KEY)
    .update(message)
    .digest('hex');
  
  // Make request
  try {
    const response = await axios.post(
      `${BASE_URL}/supply/v1/entrylinks`,
      {
        survey_id: surveyId,
        supplier_code: SUPPLIER_CODE,
        respondent_id: respondentId,
        secure_hash: secureHash,
        return_url: RETURN_URL
      },
      {
        headers: {
          'Authorization': API_KEY,
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      }
    );
    
    return {
      success: true,
      live_link: response.data.live_link
    };
  } catch (error) {
    return {
      success: false,
      error: error.message,
      status_code: error.response?.status
    };
  }
}
```

## Platform Implementation

In this platform, the Cint entry link functionality is implemented in:

- **Service**: `backend/app/services/cint_entrylink_service.py`
- **Router**: `backend/app/routers/cint.py`
- **Models**: `backend/app/models/cint.py`

### Get JSON Format via API

You can retrieve the complete JSON format documentation via the API:

```
GET /api/cint/entry-link-json-format
```

This returns the same structure as this document, including all field descriptions, examples, and implementation notes.

## Troubleshooting

### Common Issues

1. **403 Authentication Failed**
   - Verify your API key is correct
   - Check that the API key is active in your Cint account

2. **404 Survey Not Found**
   - Survey may have ended or reached quota
   - Verify survey_id is correct
   - Check survey status via opportunities API

3. **Invalid secure_hash**
   - Ensure encryption_key is correct
   - Verify message concatenation order: `supplier_code + survey_id + respondent_id`
   - Check for extra spaces or special characters

4. **Callback not received**
   - Ensure return_url is publicly accessible
   - Check firewall/security rules
   - Verify endpoint handles POST requests
   - Review server logs for incoming requests

## Additional Resources

- [Cint API Documentation](https://api.samplicio.us/docs)
- [Cint Developer Portal](https://developer.cint.com)
- [Platform Integration Docs](./CINT_INTEGRATION_COMPLETE.md)

## Support

For Cint API issues:
- Email: support@cint.com
- Developer Portal: https://developer.cint.com

For platform-specific issues:
- Check logs in `backend/logs/`
- Review diagnostic endpoint: `GET /api/cint/diagnostic`
- Review health endpoint: `GET /api/cint/health`
