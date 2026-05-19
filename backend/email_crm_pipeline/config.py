"""
config.py — Centralised configuration for the Email CRM Pipeline.

All constants, environment variables, and collection names live here.
Import from this module instead of reading os.getenv() directly in scripts.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Default Anthropic model requested by the master prompt.
# Environment overrides are supported for temporary experimentation.
CLASSIFIER_MODEL = os.getenv(
	"EMAIL_PIPELINE_CLASSIFIER_MODEL",
	os.getenv("CLASSIFICATION_MODEL", "claude-sonnet-4-20250514"),
)

DRAFTER_MODEL = os.getenv(
	"EMAIL_PIPELINE_DRAFTER_MODEL",
	os.getenv("DRAFTING_MODEL", "claude-sonnet-4-20250514"),
)

# Emails sent per Anthropic Batch API call (max 10,000; keep at 100 for safety)
BATCH_SIZE: int = int(os.getenv("EMAIL_PIPELINE_BATCH_SIZE", "100"))

# Retry failed batch items with individual requests
MAX_ITEM_RETRIES: int = int(os.getenv("MAX_BATCH_ITEM_RETRIES", "2"))

# How many seconds to wait between batch status polls
BATCH_POLL_INTERVAL: int = int(os.getenv("BATCH_POLL_INTERVAL_SECONDS", "60"))

# Max tokens per extraction response (JSON fits comfortably in 1024)
CLASSIFIER_MAX_TOKENS = 1024

# Max tokens per draft response (subject + 150-word body)
DRAFTER_MAX_TOKENS = 512

# ---------------------------------------------------------------------------
# MongoDB — Email Sync Source
# ---------------------------------------------------------------------------
# The email_sync module stores emails in the database named by MONGO_DB_NAME.
# Keep EMAIL_SOURCE_DB / EMAIL_SOURCE_COLLECTION for compatibility with the
# prompt and existing environment templates.
DB_EMAIL_SYNC: str = os.getenv("EMAIL_SOURCE_DB", os.getenv("MONGO_DB_NAME", "campaign_platform"))
COL_EMAILS = os.getenv("EMAIL_SOURCE_COLLECTION", "emails")
COL_MAILBOXES = os.getenv("EMAIL_SOURCE_MAILBOX_COLLECTION", "mailboxes")

# ---------------------------------------------------------------------------
# MongoDB — CRM Target (existing production collections)
# ---------------------------------------------------------------------------
DB_CRM = os.getenv("CRM_TARGET_DB", "email_automation")
COL_CONTACTS = os.getenv("CONTACTS_COLLECTION", "contacts")          # upsert key: email
COL_SALES_ACCOUNTS = os.getenv("ACCOUNTS_COLLECTION", "sales_accounts")  # upsert key: (normalized_name, country)
COL_RFQS = os.getenv("RFQS_COLLECTION", "rfqs")                  # upsert key: (account_id, subject_key, month)
COL_VENDORS = os.getenv("VENDORS_COLLECTION", "vendors")            # existing panel vendor registry (read-only here)
COL_FINANCE_LOG = os.getenv("FINANCE_LOG_COLLECTION", "finance_email_log")

# ---------------------------------------------------------------------------
# MongoDB — Pipeline-specific collections (created by this pipeline)
# ---------------------------------------------------------------------------
# Raw Claude extraction output — one doc per email
COL_EMAIL_EXTRACTIONS = "email_crm_extractions"

# Job-change history for contacts
COL_CONTACT_HISTORY = "contact_history"

# Watermark and active batch tracking
COL_PIPELINE_STATE = "pipeline_state"

# Run-level summaries (one doc per pipeline run)
COL_PIPELINE_RUNS = "pipeline_runs"

# Identified reactivation candidates (also written to JSONL)
COL_REACTIVATION = "reactivation_candidates"

# ---------------------------------------------------------------------------
# File output paths
# ---------------------------------------------------------------------------
PIPELINE_DATA_DIR = Path(os.getenv("PIPELINE_DATA_DIR", str(_PROJECT_ROOT / "data")))
EMAIL_POOL_FILE = Path(os.getenv("EMAIL_POOL_FILE", str(PIPELINE_DATA_DIR / "email_pool.jsonl")))
REACTIVATION_FILE = PIPELINE_DATA_DIR / "reactivation_candidates.jsonl"
DRAFTS_FILE = PIPELINE_DATA_DIR / "reactivation_drafts.jsonl"

# ---------------------------------------------------------------------------
# Monthly scheduler
# ---------------------------------------------------------------------------
PIPELINE_MONTHLY_DAY: int = int(os.getenv("PIPELINE_MONTHLY_DAY", "1"))
PIPELINE_MONTHLY_HOUR_UTC: int = int(os.getenv("PIPELINE_MONTHLY_HOUR_UTC", "2"))
PIPELINE_MONTHLY_MINUTE_UTC: int = int(os.getenv("PIPELINE_MONTHLY_MINUTE_UTC", "0"))

# Global state key used in pipeline_state collection
PIPELINE_STATE_DOC_ID = "email_crm_pipeline_state"

# ---------------------------------------------------------------------------
# Reactivation thresholds
# ---------------------------------------------------------------------------
DORMANT_MONTHS = 6            # contacts silent for this many months → Bucket 1
DORMANT_MIN_EXCHANGES = 2     # minimum prior emails to qualify as warm
UNANSWERED_DAYS = 30          # pitch unanswered after this many days → Bucket 2
