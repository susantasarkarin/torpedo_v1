# Get Last Cint Respondent Payloads

This directory contains tools to retrieve the last N respondent payloads sent to Cint.

## Files

- **`get_last_cint_payloads.py`** - Python script to query MongoDB and retrieve Cint payloads
- **`get_last_cint_payloads.js`** - JavaScript/Node.js version of the same script
- **`vm_get_cint_payloads.sh`** - Bash wrapper to connect to VM and run the script (auto-detects Python/Node.js)
- **`README_CINT_PAYLOADS.md`** - This documentation

## Quick Start

### Option 1: Run Locally (if MongoDB is accessible)

#### Python Version
```bash
# Get last 10 payloads (default)
python scripts/get_last_cint_payloads.py

# Get last 20 payloads
python scripts/get_last_cint_payloads.py --limit 20

# Save to JSON file
python scripts/get_last_cint_payloads.py --json output.json
```

#### JavaScript Version
```bash
# Get last 10 payloads (default)
node scripts/get_last_cint_payloads.js

# Get last 20 payloads
node scripts/get_last_cint_payloads.js 20
```

**Note:** Python version requires `pymongo` package. JavaScript version requires `mongodb` package.
On the VM where the backend is deployed, dependencies should already be installed.

### Option 2: Run on VM via SSH (Recommended)

The bash wrapper automatically detects whether Python or Node.js is available on the VM.

```bash
# Configure VM connection (one-time setup)
export VM_HOST="your-vm-host.com"
export VM_USER="root"  # optional, defaults to "root"
export VM_PATH="/root/campaign_platform"  # optional

# Get last 10 payloads from VM (auto-detects runtime)
./scripts/vm_get_cint_payloads.sh

# Get last 20 payloads from VM
./scripts/vm_get_cint_payloads.sh 20

# Force specific runtime
./scripts/vm_get_cint_payloads.sh 10 python  # Use Python
./scripts/vm_get_cint_payloads.sh 10 js     # Use Node.js
```

### Option 3: Direct SSH (manual)

```bash
# Using Python
ssh user@vm-host "cd /path/to/campaign_platform && python3 scripts/get_last_cint_payloads.py --limit 10"

# Using Node.js
ssh user@vm-host "cd /path/to/campaign_platform && node scripts/get_last_cint_payloads.js 10"
```

## What Data is Retrieved?

For each of the last N respondents sent to Cint, the script retrieves:

### Payload Sent to Cint API
The actual data sent to `POST https://api.samplicio.us/supply/v1/entrylinks`:
- `survey_id` - Cint survey ID
- `supplier_code` - Your Cint supplier code (default: 6777)
- `respondent_id` - Your internal respondent ID
- `secure_hash` - HMAC-SHA256 hash for verification
- `return_url` - Status callback URL

### Metadata
- `timestamp` - When the allocation occurred
- `allocation_id` - Unique allocation ID
- `vid` - Vendor ID
- `cc` - Country code
- `ip_address` - Respondent's IP
- `user_agent` - Respondent's browser
- `survey_name` - Internal survey name
- `survey_status` - Survey status (active/paused/inactive)

### Cint Survey Details (if available)
- `survey_name` - Cint survey name
- `country_language` - Target country and language
- `loi` - Length of interview (minutes)
- `cpi` - Cost per interview (USD)
- `conversion` - Conversion rate

## Sample Output

```
================================================================================
LAST 10 RESPONDENT PAYLOADS SENT TO CINT
================================================================================

[1] Timestamp: 2026-02-18 14:30:45 UTC
--------------------------------------------------------------------------------

Payload sent to Cint API:
  POST https://api.samplicio.us/supply/v1/entrylinks
    survey_id: 12345678
    supplier_code: 6777
    respondent_id: user_abc123_1708267845
    secure_hash: [HMAC-SHA256 hash - not stored]
    return_url: https://torpedo.cogentixresearch.com/api/cint/status

Metadata:
    allocation_id: 65d3f8a1b2c4e5f6a7b8c9d0
    vid: 1001
    cc: US
    ip_address: 192.168.1.100
    user_agent: Mozilla/5.0 ...
    survey_name: US Consumer Survey
    survey_status: active

Cint Survey Details:
    survey_name: Consumer Preferences Q1 2026
    country_language: en-US
    loi: 15
    cpi: 2.50
    conversion: 0.75

================================================================================

[2] Timestamp: 2026-02-18 14:28:12 UTC
...
```

## Configuration

### Environment Variables

The script uses the following environment variables:

- `MONGO_URI` - MongoDB connection string (default: `mongodb://localhost:27017/`)
- `CINT_SUPPLIER_CODE` - Your Cint supplier code (default: `6777`)
- `CINT_CALLBACK_URL` - Status callback URL (default: `https://torpedo.cogentixresearch.com/api/cint/status`)

### VM Connection (for vm_get_cint_payloads.sh)

- `VM_HOST` - VM hostname or IP (required)
- `VM_USER` - SSH user (default: `root`)
- `VM_PATH` - Path to campaign_platform directory on VM (default: `/root/campaign_platform`)

## Database Collections Used

The script queries the following MongoDB collections:

### survey_allocation database
- `allocation_log` - Tracks all respondent allocations
- `surveys` - Survey inventory with provider info
- `respondents` - Respondent details

### cint_research database
- `cint_surveys` - Cint survey opportunities cache

## Troubleshooting

### "No Cint payloads found"

This means no respondents have been allocated to Cint surveys yet. Possible reasons:
1. No Cint surveys in the active pool
2. No respondents have been allocated yet
3. Allocation logs have expired (30-day TTL)

Check survey inventory:
```bash
mongosh survey_allocation --eval "db.surveys.find({provider:'CINT'}).count()"
```

### SSH Connection Fails

1. Verify VM_HOST is correct: `echo $VM_HOST`
2. Test SSH manually: `ssh $VM_USER@$VM_HOST`
3. Ensure SSH key is configured for passwordless access
4. Check firewall/network access to VM

### MongoDB Connection Fails

1. Verify MongoDB is running on VM: `ssh $VM_USER@$VM_HOST "systemctl status mongod"`
2. Check MONGO_URI is set correctly
3. Verify MongoDB allows connections from localhost

## Advanced Usage

### Query Specific Date Range

Modify the script to filter by date:

```python
from datetime import datetime, timedelta

# Get payloads from last 24 hours
cutoff = datetime.utcnow() - timedelta(hours=24)
logs = allocation_log.find({'timestamp': {'$gte': cutoff}}).sort('timestamp', -1)
```

### Export to CSV

```python
import csv

payloads = get_last_cint_payloads(limit=100)
with open('cint_payloads.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['timestamp', 'respondent_id', 'survey_id', ...])
    writer.writeheader()
    for payload in payloads:
        # Flatten and write rows
        ...
```

### Filter by Country

```python
# Only get US respondents
logs = allocation_log.find({'cc': 'US'}).sort('timestamp', -1)
```

## Related Scripts

- `scripts/check_respondent.js` - MongoDB shell script for basic respondent checks
- `scripts/check_respondent.py` - Python script for respondent analysis
- `scripts/cint/find_cint_db.py` - Find all Cint-related collections

## Support

For issues or questions:
1. Check MongoDB connection and permissions
2. Verify Cint integration is properly configured
3. Review allocation logs: `mongosh survey_allocation`
4. Check backend logs for allocation errors

## Notes

- The `secure_hash` is computed at runtime and not stored in the database for security
- Allocation logs have a 30-day TTL (auto-deletion)
- Payloads are reconstructed from logged allocation data
- The script is read-only and does not modify any data
