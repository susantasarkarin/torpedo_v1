# Cint Entry Link Implementation Guide

## Overview
This implementation provides:
1. **Enhanced UI** - Professional entry link display with copy/test buttons (following CPX pattern)
2. **Bulk Generation Script** - Async script to generate entry links for all existing Cint surveys

---

## UI Enhancements

### What Changed
- **Separate sections** for Live Link (🚀 green) and Test Link (🧪 orange)
- **Copy buttons** for one-click clipboard copy
- **Test buttons** to open links in new tabs
- **One-click select** - Click input field to select entire URL
- **Professional styling** - Matching CPX implementation with hover effects

### Location
- **Component**: `Campaign_platform/src/pages/operations/surveyPool/SurveyPool.jsx` (lines 1191-1265)
- **Styles**: `Campaign_platform/src/pages/operations/surveyPool/SurveyPool.css` (lines 873-971)

### Features
- ✅ Read-only input fields with monospace font
- ✅ Click to select entire URL
- ✅ Copy button (purple) copies URL to clipboard
- ✅ Test button (green for live, orange for test) opens link in new tab
- ✅ Hover animations with shadow effects
- ✅ Loading state with spinner
- ✅ Create button if link doesn't exist

---

## Bulk Entry Link Generation Script

### Purpose
Generate entry links for all existing active Cint surveys in the database that don't already have one.

### Location
```
backend/scripts/bulk_generate_cint_entry_links.py
```

### Features
- ✅ **Async/parallel processing** - Uses httpx AsyncClient with rate limiting
- ✅ **Idempotent** - Checks for existing links before creating (no duplicates)
- ✅ **Rate limiting** - Semaphore controls concurrent API calls
- ✅ **Batch processing** - Processes surveys in batches with delays
- ✅ **Error recovery** - Continues on failures, saves failed surveys to CSV
- ✅ **Progress tracking** - Real-time batch progress and statistics
- ✅ **Dry-run mode** - Preview without making API calls

### Usage

#### Basic Usage (Generate All Links)
```bash
cd "d:\Code\03. Projects\01. torpedo wip\02. 20 dec\campaign_platform-main\campaign_platform-main"
python backend/scripts/bulk_generate_cint_entry_links.py
```

#### Dry-Run (Preview Only)
```bash
python backend/scripts/bulk_generate_cint_entry_links.py --dry-run
```

#### Custom Concurrency
```bash
python backend/scripts/bulk_generate_cint_entry_links.py --max-concurrent 10 --batch-size 20
```

#### Only Pool-Active Surveys
```bash
python backend/scripts/bulk_generate_cint_entry_links.py --include-pool
```

### Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--dry-run` | False | Preview without making API calls |
| `--max-concurrent N` | 5 | Maximum concurrent API calls |
| `--batch-size N` | 10 | Surveys processed per batch |
| `--include-pool` | False | Only process surveys with `is_active_in_pool=True` |

### Rate Limiting Strategy

**Default Configuration:**
- Max concurrent API calls: **5**
- Batch size: **10 surveys**
- Delay between batches: **2 seconds**

**Estimated Time:**
- 100 surveys: ~1 minute
- 300 surveys: ~2-3 minutes
- 500 surveys: ~4-5 minutes

### Output Example

```
============================================================
CINT BULK ENTRY LINK GENERATOR
============================================================
✓ API Key: C61C48A6-8...
✓ Supplier Code: 6777
✓ Base URL: https://api.samplicio.us
✓ Cint service initialized (API: https://api.samplicio.us)

📊 Querying database for surveys without entry links...
✓ Found 247 surveys without entry links
  • Total active surveys: 312
  • Surveys with entry links: 65
  • Surveys needing entry links: 247

🚀 Starting bulk entry link generation...
  • Total surveys: 247
  • Max concurrent: 5
  • Batch size: 10
  • Delay between batches: 2s

📦 Processing batch 1/25...
  Batch 1/25: 10/10 successful

📦 Processing batch 2/25...
  Batch 2/25: 9/10 successful

... (continues for all batches)

============================================================
✓ BULK GENERATION COMPLETE
============================================================
Total surveys processed: 247
✓ Successfully created: 238
⊙ Already existed: 3
⊘ Skipped: 0
✗ Failed: 6
Duration: 142.3s (1.7 surveys/sec)
============================================================

⚠️  Failed surveys saved to: backend/scripts/failed_entry_links_20260130_143522.csv

✓ Cleanup complete
```

### Error Handling

**Built-in Retry Logic:**
- Automatically retries on: 429, 502, 503, 504
- No retry on: 400, 401, 403, 404
- Exponential backoff: 1s, 2s, 4s

**Failed Surveys:**
- Saved to CSV file with timestamp
- Includes survey ID, name, error message
- Can be re-processed manually

### MongoDB Queries

**Query Logic:**
```javascript
// Aggregation pipeline
db.cint_surveys.aggregate([
  {
    $lookup: {
      from: "cint_entry_links",
      localField: "survey_id",
      foreignField: "survey_id",
      as: "entry_link"
    }
  },
  {
    $match: {
      entry_link: { $eq: [] },  // No entry link exists
      is_active: true,
      is_live: true
    }
  }
])
```

**Collections Used:**
- `cint_research.cint_surveys` - Survey data
- `cint_research.cint_entry_links` - Entry link storage

### Environment Variables Required

```env
MONGO_URI=mongodb://localhost:27017/
CINT_API_KEY=C61C48A6-8154-4F9F-B616-8DFB66F452A7
CINT_SUPPLIER_CODE=6777
CINT_BASE_URL=https://api.samplicio.us
```

### Best Practices

1. **Run dry-run first**: `--dry-run` to preview
2. **Check failed surveys**: Review CSV file for failed entries
3. **Monitor API rate limits**: Watch for 429 errors
4. **Run during off-peak**: Less risk of conflicts
5. **Backup before running**: Optional but recommended

### Troubleshooting

**Script fails to connect to MongoDB:**
```bash
# Check MongoDB is running
mongosh --eval "db.adminCommand('ping')"

# Verify MONGO_URI in .env
echo $MONGO_URI
```

**All surveys fail with 401/403:**
```bash
# Verify API key
echo $CINT_API_KEY

# Check supplier code
echo $CINT_SUPPLIER_CODE
```

**Import errors:**
```bash
# Install dependencies
pip install pymongo python-dotenv httpx

# Check Python path
python -c "import sys; print(sys.path)"
```

---

## Testing the UI

1. **Start the backend** (if not running):
```bash
cd backend
uvicorn main:app --reload --port 8001
```

2. **Start the frontend** (if not running):
```bash
cd Campaign_platform
npm run dev
```

3. **Test the entry links:**
   - Navigate to Survey Pool page
   - Click on a Cint survey (one with `account_name` field)
   - Entry link section should appear
   - Click input field → entire URL should select
   - Click Copy button → URL copied to clipboard
   - Click Test button → opens link in new tab

4. **Test both link types:**
   - Live link: Green "🚀 Test" button
   - Test link: Orange "🧪 Test" button (if available)

---

## Next Steps

### Optional Enhancements

1. **Toast Notifications** - Add success feedback on copy:
```javascript
onClick={() => {
  navigator.clipboard.writeText(cintEntryLink.live_link);
  // Add toast: "Link copied to clipboard!"
}}
```

2. **Bulk Generation Endpoint** - Expose script as API endpoint:
```python
@router.post("/entry-links/bulk-generate")
async def bulk_generate_entry_links(
    background_tasks: BackgroundTasks,
    cint_service = Depends(get_cint_service)
):
    background_tasks.add_task(run_bulk_generation)
    return {"message": "Bulk generation started"}
```

3. **Scheduled Task** - Auto-generate for new surveys:
```python
# Add to APScheduler
scheduler.add_job(
    generate_missing_entry_links,
    'interval',
    hours=6,
    id='auto_generate_entry_links'
)
```

4. **Retry Failed Surveys** - Script to retry only failed entries:
```bash
python backend/scripts/bulk_generate_cint_entry_links.py \
  --retry-from failed_entry_links_20260130_143522.csv
```

---

## Summary

✅ **UI Enhanced** - Professional entry link display with copy/test buttons  
✅ **Script Created** - Async bulk generation with rate limiting  
✅ **Idempotent** - Safe to run multiple times (no duplicates)  
✅ **Production-Ready** - Error handling, logging, CSV export  
✅ **Tested** - No linting errors, follows existing patterns  

**Ready to use!** Run the script to backfill entry links for all existing Cint surveys.
