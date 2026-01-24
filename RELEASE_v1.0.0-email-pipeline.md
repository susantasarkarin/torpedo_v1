# Release: v1.0.0-email-pipeline

## Email Pipeline Hardening Initiative

**Release Date:** January 24, 2026  
**Tag:** `v1.0.0-email-pipeline`  
**Commit:** `15d829ed353b7d9d56007538bef145741e36d7b3`

---

## 📦 What's Included

### Phase 1: Email Deduplication & System Detection
- **Global content-based deduplication** via `dedupe_hash` (SHA256)
- **Rule-based system email detection** for bounce, OOO, auto-reply, unsubscribe
- **Zero LLM calls for system emails** (test-backed guarantee)
- **36 regression tests** in `test_phase1_email_dedup.py`

### Phase 2: Preview Resolution & Sender Metadata
- **Backend-defined preview resolution** priority: `gmail_summary → ai_summary → system_summary → snippet`
- **Sender metadata** with confidence scoring and source tracking
- **20 regression tests** in `test_phase2_preview_sender.py`

### Phase 3: UX Hardening (Frontend)
- Visual treatment for system emails (muted styling, colored badges)
- Preview rendering uses `resolved_preview` as single source of truth
- Source indicators for preview transparency

---

## 🔒 Locked Contracts

| Contract | Description |
|----------|-------------|
| `resolved_preview` | Single source of truth for frontend rendering |
| `preview_source` | Informational only, must not influence resolution logic |
| `dedupe_hash` | Enforces global idempotency across all mailboxes |
| System email bypass | Zero LLM calls for system emails (protected by tests) |

---

## 🚀 VM Deployment Steps

### Prerequisites
- SSH access to production VM
- Git configured with access to repository
- Python 3.11+ installed
- MongoDB running

### Step 1: Pull Tagged Release

```bash
# SSH into VM
ssh user@production-vm

# Navigate to project directory
cd /opt/campaign_platform

# Fetch all tags
git fetch origin --tags

# Checkout the tagged release (NEVER deploy from working branch)
git checkout tags/v1.0.0-email-pipeline

# Verify you're on the correct commit
git log -1 --oneline
# Expected: 15d829e feat(email-pipeline): Phase 1-3 email hardening initiative
```

### Step 2: Apply Database Migrations (if applicable)

```bash
# Create the new dedupe_hash unique index
mongosh torpedo_gmail --eval '
db.emails.createIndex(
  { "dedupe_hash": 1 },
  { unique: true, sparse: true, name: "unique_global_dedupe_hash" }
)
'

# Create email_type index
mongosh torpedo_gmail --eval '
db.emails.createIndex(
  { "email_type": 1 },
  { name: "idx_email_type" }
)
'

# Verify indexes
mongosh torpedo_gmail --eval 'db.emails.getIndexes()'
```

### Step 3: Install Dependencies & Restart Services

```bash
# Activate virtual environment
source .venv/bin/activate

# Install any new dependencies
pip install -r requirements.txt

# Restart backend service
sudo systemctl restart campaign-backend

# Restart frontend if needed
cd Campaign_platform
npm install
npm run build
sudo systemctl restart campaign-frontend

# Check service status
sudo systemctl status campaign-backend
sudo systemctl status campaign-frontend
```

### Step 4: Run Smoke Tests

Execute the following smoke tests to validate deployment:

```bash
# Run Python test suite
cd /opt/campaign_platform/backend
python -m pytest tests/ -v --tb=short

# Expected: 56 passed
```

---

## 🧪 Smoke Test Checklist

### 1. Deduplication Hash Enforcement
```bash
# Insert test email, verify dedupe_hash is computed
curl -X POST http://localhost:8000/api/emails/sync \
  -H "Content-Type: application/json" \
  -d '{"mailbox_id": "test", "test_mode": true}'

# Check MongoDB for dedupe_hash
mongosh torpedo_gmail --eval '
db.emails.findOne({}, {dedupe_hash: 1, _id: 0})
'
# Expected: { "dedupe_hash": "<64-char-hex>" }
```

### 2. System Emails Bypass LLM
```bash
# Check for system emails in database
mongosh torpedo_gmail --eval '
db.emails.find(
  {email_type: "system"},
  {subject: 1, system_subtype: 1, ai_llm_skipped: 1, _id: 0}
).limit(3)
'
# Expected: ai_llm_skipped: true for system emails
```

### 3. Preview Text Backend-Resolved
```bash
# Check emails have resolved_preview
mongosh torpedo_gmail --eval '
db.emails.find(
  {resolved_preview: {$exists: true, $ne: null}},
  {subject: 1, resolved_preview: 1, preview_source: 1, _id: 0}
).limit(3)
'
# Expected: preview_source is one of: gmail_summary, ai_summary, system_summary, snippet
```

### 4. No Duplicate Inserts
```bash
# Check for duplicate dedupe_hashes (should return 0)
mongosh torpedo_gmail --eval '
db.emails.aggregate([
  { $group: { _id: "$dedupe_hash", count: { $sum: 1 } } },
  { $match: { count: { $gt: 1 } } },
  { $count: "duplicates" }
])
'
# Expected: [] (empty array - no duplicates)
```

### 5. Frontend Renders Without Logic Leakage
- Open browser to `/mailpool`
- Verify system emails show with muted styling and badges
- Verify preview text matches `resolved_preview` (not re-computed client-side)
- Check browser console for no JavaScript errors

---

## 📊 Monitoring Metrics (24-72 Hour Freeze)

### Key Metrics to Monitor

| Metric | Expected Baseline | Alert Threshold |
|--------|-------------------|-----------------|
| Deduplication hit rate | 0-5% (new emails) | > 50% (indicates sync issues) |
| LLM bypass percentage | 10-30% (system emails) | < 5% (detection failing) |
| Preview mismatches | 0 | > 0 (contract violation) |
| UX regressions | 0 | Any user reports |

### Log Queries

```bash
# Check for system email detection logs
journalctl -u campaign-backend | grep "System email detected"

# Check for deduplication logs
journalctl -u campaign-backend | grep "Global duplicate detected"

# Check for any errors
journalctl -u campaign-backend --since "1 hour ago" | grep -i error
```

---

## ⚠️ Rollback Procedure

If issues are detected:

```bash
# Checkout previous release
git checkout tags/v0.x.x  # Replace with previous stable tag

# Or revert to specific commit
git checkout 01733d6  # Commit before this release

# Restart services
sudo systemctl restart campaign-backend
sudo systemctl restart campaign-frontend
```

---

## ✅ Post-Deployment Verification

After 24-72 hours with no anomalies, confirm:

- [ ] Deduplication hit rate is stable
- [ ] LLM bypass percentage matches expected system email volume
- [ ] Zero preview mismatches in logs
- [ ] No UX regression reports
- [ ] All 56 tests continue to pass

**Once verified, mark initiative as CLOSED.**

---

## 📝 Files Changed

| File | Change Type |
|------|-------------|
| `backend/email_sync/models.py` | Modified (new enums, fields) |
| `backend/email_sync/storage.py` | Modified (dedupe logic) |
| `backend/email_sync/openai_email_classifier.py` | Modified (LLM short-circuit) |
| `backend/email_sync/system_email_detector.py` | **New** (~400 lines) |
| `backend/email_sync/preview_resolver.py` | **New** (~250 lines) |
| `backend/tests/test_phase1_email_dedup.py` | **New** (36 tests) |
| `backend/tests/test_phase2_preview_sender.py` | **New** (20 tests) |
| `Campaign_platform/src/pages/MailPool.jsx` | Modified (Phase 3 UI) |
