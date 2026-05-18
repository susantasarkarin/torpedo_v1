"""
scheduler.py — Task 5: Monthly Pipeline Scheduler
=================================================

Runs the full Email CRM pipeline on the 1st of every month and maintains
a watermark so only new emails are processed.

Usage:
  python -m backend.email_crm_pipeline.scheduler --run-now
  python -m backend.email_crm_pipeline.scheduler
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_collection
from email_crm_pipeline.config import (
    DB_CRM,
    COL_PIPELINE_STATE,
    COL_PIPELINE_RUNS,
    PIPELINE_STATE_DOC_ID,
    PIPELINE_MONTHLY_DAY,
    PIPELINE_MONTHLY_HOUR_UTC,
    PIPELINE_MONTHLY_MINUTE_UTC,
)
from email_crm_pipeline.email_classifier import run_classification
from email_crm_pipeline.crm_populator import run_crm_population
from email_crm_pipeline.reactivation_identifier import run_identification
from email_crm_pipeline.email_drafter import run_drafting

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def _get_state_collections():
    state_col = get_collection(DB_CRM, COL_PIPELINE_STATE)
    runs_col = get_collection(DB_CRM, COL_PIPELINE_RUNS)
    return state_col, runs_col


def load_watermark() -> Optional[datetime]:
    state_col, _ = _get_state_collections()
    doc = state_col.find_one({"_id": PIPELINE_STATE_DOC_ID}) or {}
    value = doc.get("last_processed_date")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def save_watermark(value: datetime) -> None:
    state_col, _ = _get_state_collections()
    state_col.update_one(
        {"_id": PIPELINE_STATE_DOC_ID},
        {"$set": {"last_processed_date": value, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def record_run(run_doc: dict) -> None:
    _, runs_col = _get_state_collections()
    runs_col.insert_one(run_doc)


def run_monthly_pipeline() -> dict:
    started_at = datetime.now(timezone.utc)
    watermark = load_watermark()

    run_summary = {
        "started_at": started_at.isoformat(),
        "watermark_in": watermark.isoformat() if watermark else None,
        "steps": {},
        "status": "success",
    }

    try:
        cls = run_classification(since_date=watermark)
        run_summary["steps"]["classification"] = cls

        pop = run_crm_population(since_date=watermark)
        run_summary["steps"]["crm_population"] = pop

        react = run_identification()
        run_summary["steps"]["reactivation"] = react

        drafts = run_drafting()
        run_summary["steps"]["drafting"] = drafts

        watermark_out = datetime.now(timezone.utc)
        save_watermark(watermark_out)
        run_summary["watermark_out"] = watermark_out.isoformat()
    except Exception as exc:
        run_summary["status"] = "failed"
        run_summary["error"] = str(exc)
        log.exception("Monthly pipeline failed")

    run_summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    record_run(run_summary)
    return run_summary


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_monthly_pipeline,
        trigger=CronTrigger(
            day=PIPELINE_MONTHLY_DAY,
            hour=PIPELINE_MONTHLY_HOUR_UTC,
            minute=PIPELINE_MONTHLY_MINUTE_UTC,
        ),
        id="email_crm_monthly",
        replace_existing=True,
    )

    log.info(
        "Scheduler started. Monthly run: day=%d at %02d:%02d UTC",
        PIPELINE_MONTHLY_DAY,
        PIPELINE_MONTHLY_HOUR_UTC,
        PIPELINE_MONTHLY_MINUTE_UTC,
    )
    scheduler.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run or schedule monthly Email CRM pipeline")
    parser.add_argument("--run-now", action="store_true", help="Run pipeline immediately once")
    args = parser.parse_args()

    if args.run_now:
        summary = run_monthly_pipeline()
        print(json.dumps(summary, indent=2, default=str))
    else:
        start_scheduler()
