# Mail Pool Deployment Debugging Guide

## 🚨 Critical Bug Fixed

A **critical bug** was found in [gmail.py](backend/routers/gmail.py#L2254) where the `/gmail/mail-pool/emails/{id}` endpoint was returning early (`return {...}`) **before** building the thread array. This caused:
- Email threads to always return `"thread": []` 
- Only single emails shown even when conversation exists

**Fix Applied:** Changed inline `return` to `result = {...}` so thread building executes.

---

## Step 1: Verify Deployment Freshness

### 1.1 Check Frontend Version (Browser Console)

Open browser DevTools (F12) → Console. You should see:
```
[MailPool] Build: 2026.01.15.1
[MailPool] Loaded at: <timestamp>
```

If you don't see this, the old build is cached.

### 1.2 Force Cache Bypass
```bash
# Hard refresh in browser
Ctrl + Shift + R  (Windows/Linux)
Cmd + Shift + R   (Mac)

# Or clear cache completely
DevTools → Network tab → Check "Disable cache" → Refresh
```

### 1.3 Check Server Deployed Commit
```bash
# SSH to server and check current deployed commit
ssh susanta@34.41.181.74 "cd /var/www/html && git log -1 --oneline"

# Compare with local
git log -1 --oneline
```

### 1.4 Check Static Assets Hash
```bash
# List assets on server to verify new build
ssh susanta@34.41.181.74 "ls -la /var/www/html/assets/MailPool*.js && stat /var/www/html/assets/MailPool*.js"
```

---

## Step 2: Database Integrity Check

### 2.1 Run Diagnostic Script
```bash
cd backend
python scripts/debug_mailpool.py
```

This checks:
- ✅ Orphaned signatures (email_signatures vs workspace_mailboxes)
- ✅ Case sensitivity issues in email fields
- ✅ Trailing spaces in email addresses
- ✅ Thread ID coverage (legacy emails)
- ✅ Inbox count field integrity

### 2.2 Quick MongoDB Queries

**Check orphaned signatures:**
```javascript
// In mongosh
use torpedo_settings

// Get all signature emails
var sigEmails = db.email_signatures.distinct("email").map(e => e.toLowerCase())

// Get all mailbox emails  
var mbEmails = db.workspace_mailboxes.distinct("email").map(e => e.toLowerCase())

// Find orphans
sigEmails.filter(e => !mbEmails.includes(e))
```

**Check for case issues:**
```javascript
db.email_signatures.find({
  $expr: { $ne: ["$email", { $toLower: "$email" }] }
})
```

---

## Step 3: API & Payload Inspection

### 3.1 Test Thread Endpoint with cURL
```bash
# Get session ID from browser localStorage
SESSION_ID="your-session-id-here"

# Test email detail endpoint (replace EMAIL_ID with actual ObjectId)
curl -s -H "Authorization: $SESSION_ID" \
  "http://localhost:8000/gmail/mail-pool/emails/EMAIL_ID" | jq

# Expected: { success: true, email: {...}, thread: [...] }
# Bug symptom: thread: [] when it should have multiple emails
```

### 3.2 Check Thread Response Structure
The response should now contain:
```json
{
  "success": true,
  "email": {
    "id": "...",
    "thread_id": "17abc...",  // provider_thread_id
    ...
  },
  "thread": [
    { "id": "...", "email": "sender@...", "body": "First message", "date": "..." },
    { "id": "...", "email": "reply@...", "body": "Reply message", "date": "..." }
  ]
}
```

### 3.3 Check Legacy Emails Missing thread_id
```javascript
// In mongosh
use email_automation

// Count emails without thread ID
db.emails.countDocuments({
  provider_thread_id: { $exists: false }
})

// For these, backend now handles gracefully by returning single email in thread
```

---

## Step 4: Frontend State Analysis

### 4.1 Account Switching Logic

The `filterAccount` state triggers re-fetch correctly:
```javascript
// In MailPool.jsx, these effects handle account switching:
useEffect(() => {
  fetchEmails(1)
}, [filterSegment, filterSearch, filterDirection, filterAccount, filterFolder, fetchEmails])
```

### 4.2 Check for Stale Cache in React
Open React DevTools and inspect `MailPool` component state:
- `emailThread` - should update when clicking an email
- `accountInboxCounts` - should have per-account counts
- `emails` - should clear/update on account switch

### 4.3 Potential useMemo/Cache Issues
Search for memoization that might prevent updates:
```javascript
// These are fine - dependencies include filter states:
const fetchEmails = useCallback(..., [filterAccount, ...])
const fetchStats = useCallback(..., [navigate])
```

---

## Step 5: Infrastructure & Caching

### 5.1 CloudFlare Cache Rules to Check

If using CloudFlare:
1. **Page Rules** → Ensure `/api/*` has "Cache Level: Bypass"
2. **Cache-Control Headers** → API responses should have `no-cache`
3. **Purge Cache** → CloudFlare Dashboard → Caching → Purge Everything

### 5.2 Nginx/Apache Configuration

Check static file serving:
```bash
# SSH to server
ssh susanta@34.41.181.74

# Check Apache config (from apache.conf.example)
cat /etc/apache2/sites-enabled/campaign_platform.conf

# Verify /var/www/html points to latest dist
ls -la /var/www/html
ls -la /var/www/html/assets/*.js
```

Ensure API proxy is correct:
```apache
ProxyPass /api/ http://localhost:8000/
ProxyPassReverse /api/ http://localhost:8000/
```

### 5.3 Restart Services After Deployment
```bash
# Restart backend
sudo systemctl restart torpedo-backend  # or pm2 restart backend

# No need to restart Apache for static files, but if config changed:
sudo systemctl reload apache2
```

---

## Quick Verification Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Frontend version | Browser console | `[MailPool] Build: 2026.01.15.1` |
| Backend commit | `ssh ... git log -1` | Latest commit hash |
| Thread endpoint | `curl .../emails/{id}` | `thread: [...]` not empty |
| Signatures | Run debug script | No orphans/case issues |
| Cache bypass | DevTools Network | No 304 on API calls |

---

## Deploy the Fixes

```bash
# 1. Build frontend
cd Campaign_platform
npm run build

# 2. Deploy to server
scp -r dist/* susanta@34.41.181.74:/var/www/html/

# 3. Deploy backend changes
scp backend/routers/gmail.py susanta@34.41.181.74:/path/to/backend/routers/

# 4. Restart backend
ssh susanta@34.41.181.74 "sudo systemctl restart torpedo-backend"

# 5. Verify
curl -H "Authorization: ..." "https://your-domain.com/api/gmail/mail-pool/emails/SOME_ID"
```
