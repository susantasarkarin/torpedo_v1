# Issue #2: Transferred Leads Visibility - Testing Instructions

## Prerequisites
MongoDB must be accessible on the production server at 139.59.32.72.

## Deployment & Execution

### Option 1: Run on Production Server (Recommended)

1. **SSH into production server:**
   ```bash
   ssh root@139.59.32.72
   ```

2. **Navigate to application directory:**
   ```bash
   cd /root/campaign_platform
   ```

3. **Upload test script:**
   ```bash
   # From your local machine, copy the test script
   scp test_issue2_transferred_leads.py root@139.59.32.72:/root/campaign_platform/
   ```

4. **Run the test:**
   ```bash
   python3 test_issue2_transferred_leads.py
   ```

5. **View results:**
   ```bash
   cat issue2_test_results.txt
   ```

### Option 2: Run Locally with SSH Tunnel

If the MongoDB port is not exposed publicly:

1. **Create SSH tunnel:**
   ```powershell
   ssh -L 27017:localhost:27017 root@139.59.32.72
   ```

2. **In another terminal, modify the script connection string to:**
   ```python
   client = MongoClient('mongodb://localhost:27017/')
   ```

3. **Run the test locally:**
   ```powershell
   python test_issue2_transferred_leads.py
   ```

### Option 3: Manual MongoDB Queries

If you prefer to run queries manually via mongosh:

```bash
# Connect to MongoDB on production server
mongosh mongodb://localhost:27017/email_automation

# TEST 1: Count transferred leads
db.vendor_leads.countDocuments({transferred_from_ai_database: true})

# TEST 2: Check fields in transferred leads
db.vendor_leads.findOne({transferred_from_ai_database: true})

# TEST 3: Check bidirectional references
var vendorLead = db.vendor_leads.findOne({transferred_from_ai_database: true, source_lead_id: {$exists: true}})
print("Vendor Lead ID:", vendorLead._id)
print("Source Lead ID:", vendorLead.source_lead_id)

# Switch to ai_database and verify back-reference
use ai_database
db.leads_enriched.findOne({_id: ObjectId(vendorLead.source_lead_id)}, {vendor_lead_id: 1})

# TEST 5: Check sales linkage
use sales
db.leads.countDocuments({enrichment_source: "vendor_leads"})
```

## Expected Results Format

The test script will output results in this format:

```
TEST_1_QUERY_TRANSFERRED | PASS/FAIL | Count of transferred leads or error
TEST_2_FIELDS_PRESENT | PASS/FAIL | List any missing fields
TEST_3_BIDIRECTIONAL_REFS | PASS/FAIL | Confirm IDs link correctly
TEST_4_UI_VISIBILITY | NOTE_REQUIRES_MANUAL_CHECK | Manual verification needed
TEST_5_SALES_LINKAGE | PASS/FAIL | Found in sales.leads or error
```

## Troubleshooting

### MongoDB Connection Issues
- Verify MongoDB is running: `systemctl status mongod`
- Check MongoDB logs: `tail -f /var/log/mongodb/mongod.log`
- Verify port is listening: `netstat -tlnp | grep 27017`

### No Transferred Leads Found
- Check if the transfer process has been triggered
- Verify the AI classification has marked leads as "Tier 1"
- Check logs: `tail -f /root/campaign_platform/logs/transfer.log`

### Missing Fields
- May indicate incomplete data during transfer
- Check the transfer_leads() function in backend code
- Verify source data in ai_database.leads_enriched

## UI Verification (TEST 4)

To manually verify UI visibility:

1. Open browser: http://139.59.32.72:3000
2. Navigate to: **AI Database** → **Vendor List**
3. Look for leads with "Transferred from AI" badge or indicator
4. Verify the following information is displayed:
   - Lead email
   - Company name
   - Transfer timestamp
   - Source reference

## Next Steps After Testing

- If all tests PASS: Mark Issue #2 as RESOLVED
- If any test FAILS: Document the failure in the issue tracker
- If fields are missing: Update the transfer_leads() function
- If bidirectional refs fail: Fix the reference logic in transfer code
