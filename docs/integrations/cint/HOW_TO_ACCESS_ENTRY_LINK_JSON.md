# How to Access Cint Entry Link JSON Format

This guide shows you how to access the Cint Entry Link JSON format and documentation.

## Option 1: API Endpoint (Recommended)

The easiest way to get the complete JSON format is via the API endpoint:

### Request
```http
GET /api/cint/entry-link-json-format
```

### Using cURL
```bash
curl http://localhost:8000/api/cint/entry-link-json-format
```

### Using Python
```python
import requests

response = requests.get("http://localhost:8000/api/cint/entry-link-json-format")
json_format = response.json()

print(json_format)
```

### Using JavaScript/Fetch
```javascript
fetch('http://localhost:8000/api/cint/entry-link-json-format')
  .then(response => response.json())
  .then(data => console.log(data));
```

## Option 2: JSON File

View the example JSON file directly:

```
docs/integrations/cint/cint_entry_link_json_example.json
```

## Option 3: Markdown Documentation

Read the comprehensive guide:

```
docs/integrations/cint/CINT_ENTRY_LINK_API.md
```

This includes:
- Complete API documentation
- Field descriptions
- HMAC-SHA256 hash generation guide
- Code examples in Python, JavaScript, and cURL
- Status callback information
- Troubleshooting guide

## Quick Start Example

Here's a minimal example to create a Cint entry link:

```python
import hmac
import hashlib
import requests

# Configuration
API_KEY = "your_cint_api_key"
ENCRYPTION_KEY = "your_encryption_key"
SUPPLIER_CODE = "6777"

# Parameters
survey_id = "123456"
respondent_id = "USER_12345"

# Generate secure hash
message = f"{SUPPLIER_CODE}{survey_id}{respondent_id}"
secure_hash = hmac.new(
    ENCRYPTION_KEY.encode('utf-8'),
    message.encode('utf-8'),
    hashlib.sha256
).hexdigest()

# Make API request
response = requests.post(
    "https://api.samplicio.us/supply/v1/entrylinks",
    headers={
        "Authorization": API_KEY,
        "Content-Type": "application/json"
    },
    json={
        "survey_id": survey_id,
        "supplier_code": SUPPLIER_CODE,
        "respondent_id": respondent_id,
        "secure_hash": secure_hash,
        "return_url": "https://your-domain.com/api/cint/status"
    }
)

if response.status_code == 200:
    data = response.json()
    print(f"Live Link: {data['live_link']}")
else:
    print(f"Error: {response.status_code} - {response.text}")
```

## What's Included

The JSON format includes:

- ✅ **API Endpoint URL**: The Cint API endpoint
- ✅ **Authentication**: How to authenticate requests
- ✅ **Request Headers**: Required headers
- ✅ **Request Body**: Complete payload structure with examples
- ✅ **Field Descriptions**: Detailed description of each field
- ✅ **Hash Generation**: HMAC-SHA256 algorithm with examples
- ✅ **Response Formats**: Success and error responses
- ✅ **Status Callbacks**: How to handle survey completion callbacks
- ✅ **Important Notes**: Best practices and critical information
- ✅ **Code Examples**: Python, JavaScript, and cURL examples

## Support

- For API questions: Check `docs/integrations/cint/CINT_ENTRY_LINK_API.md`
- For integration help: See `docs/integrations/cint/CINT_INTEGRATION_COMPLETE.md`
- For troubleshooting: See `docs/integrations/cint/CINT_DIAGNOSTIC_GUIDE.md`
