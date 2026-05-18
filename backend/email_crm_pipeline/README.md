# Email CRM Pipeline

Python pipeline for:
1. Email classification and extraction (Claude Batch API)
2. CRM deduplication and upsert population
3. Reactivation candidate identification
4. Reactivation draft email generation
5. Monthly scheduled execution

## Files
- `email_classifier.py`
- `crm_populator.py`
- `reactivation_identifier.py`
- `email_drafter.py`
- `scheduler.py`
- `config.py`
- `.env.example`

## Setup
1. Install dependencies:
   - `pip install -r backend/email_crm_pipeline/requirements.txt`
2. Copy env template:
   - copy `backend/email_crm_pipeline/.env.example` values into your root `.env`
3. Ensure Mongo and Claude credentials are set:
   - `MONGO_URI`
   - `ANTHROPIC_API_KEY`

## Run Manually
- Task 1: `python -m backend.email_crm_pipeline.email_classifier --limit 100`
- Task 2: `python -m backend.email_crm_pipeline.crm_populator`
- Task 3: `python -m backend.email_crm_pipeline.reactivation_identifier`
- Task 4: `python -m backend.email_crm_pipeline.email_drafter`
- Task 5 (one-off): `python -m backend.email_crm_pipeline.scheduler --run-now`

## Start Monthly Scheduler
- `python -m backend.email_crm_pipeline.scheduler`

Default monthly trigger is day 1 at 02:00 UTC. Override with env vars:
- `PIPELINE_MONTHLY_DAY`
- `PIPELINE_MONTHLY_HOUR_UTC`
- `PIPELINE_MONTHLY_MINUTE_UTC`

## Data Flow
- Reads source emails from `campaign_platform.emails` (or `MONGO_DB_NAME` if overridden)
- Stores extraction output in `email_automation.email_crm_extractions`
- Populates existing CRM collections:
  - `email_automation.contacts`
  - `email_automation.sales_accounts`
  - `email_automation.rfqs`
  - `email_automation.vendors`
- Stores finance-classified events in `email_automation.finance_email_log`
- Writes candidates to `data/reactivation_candidates.jsonl`
- Writes drafts to `data/reactivation_drafts.jsonl`
