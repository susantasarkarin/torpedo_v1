# How to Verify Gemini Performance on VM

## Quick Start

To verify that your 7 Gemini API keys are working and AI summary/classification is functioning with real data:

### Step 1: SSH into your VM

```bash
ssh your-vm-address
```

### Step 2: Navigate to the project directory

```bash
cd /path/to/campaign_platform
```

### Step 3: Run the VM verification script

```bash
python3 verify_vm_performance.py
```

## What This Script Checks

The `verify_vm_performance.py` script connects to your actual MongoDB database and verifies:

1. **Gemini API Keys** - Checks if all 7 keys are stored in `torpedo_settings.app_settings`
2. **Recent API Activity** - Shows last 20 Gemini API requests with task types and success rates
3. **Today's Quota Usage** - Shows how many of the 7,000 daily requests have been used
4. **Classified Emails** - Shows breakdown of emails classified by segment (CLIENT/VENDOR/etc.)
5. **Generated Leads** - Shows leads created with AI enrichment and buying intent scores
6. **Performance Metrics** - Shows 24-hour statistics and success rates

## Expected Output

If everything is working correctly, you should see:

```
✅ ALL CHECKS PASSED!

Your Gemini API integration is working properly:
  • 7/7 API keys configured
  • 3,245 total API requests processed
  • 1,089 emails classified
  • 234 leads generated with AI enrichment
  • 156/7000 quota used today (2.2%)
```

## Alternative: Manual Database Checks

If you prefer to check manually:

```bash
# Connect to MongoDB
mongo

# Check Gemini keys
use torpedo_settings
db.app_settings.findOne({}, {gemini_api_key_1:1, gemini_api_key_2:1, gemini_api_key_3:1, gemini_api_key_4:1, gemini_api_key_5:1, gemini_api_key_6:1, gemini_api_key_7:1})

# Check recent Gemini API activity
use email_automation
db.gemini_requests.find().sort({timestamp:-1}).limit(10)

# Check quota usage today
db.gemini_quota.find({date: "2026-01-27"})

# Check classified emails
db.classified_gmail.countDocuments({})

# Check email breakdown by segment
db.classified_gmail.aggregate([
  {$group: {_id: "$segment", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

## Through Web UI

You can also verify through the web interface:

1. Log into the web application
2. Go to **Profile > Settings**
3. Check that all 7 Gemini API keys (gemini_api_key_1 through gemini_api_key_7) have values
4. The keys should show as masked (e.g., `AIzaSyC...xyz12`)

## Troubleshooting

### "Connection refused" error
- MongoDB may not be running: `sudo systemctl status mongod`
- Start if needed: `sudo systemctl start mongod`

### "No app_settings found"
- Keys are not in the database yet
- Add them through the Settings page in the web UI

### "No API activity recorded"
- Email processor may not be running
- Check if background tasks are active: `ps aux | grep celery`
- Check logs: `tail -f backend/nohup.out`

### Zero classified emails
- Mail pool may be empty
- Check: `mongo` → `use email_automation` → `db.mail_pool.countDocuments({})`
- Email processor may need to be triggered

## Need Help?

If the verification script shows failures or unexpected results:

1. Check the actual error messages in the output
2. Review the MongoDB collections mentioned above
3. Check backend logs for errors
4. Verify the email processor service is running

---

**Note:** The code analysis documents (GEMINI_VERIFICATION_REPORT.md, GEMINI_SUMMARY.md, etc.) explain the architecture and implementation. This script verifies the actual runtime performance with your real data.
