"""Last run / status / missed runs for every APScheduler job (CRM plan
Section 6 + 3.14 System Health): torpedo_settings.job_runs, one doc per job."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _col():
    from database import get_database
    return get_database("torpedo_settings")["job_runs"]


def record(event) -> None:
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
    now = datetime.utcnow()
    try:
        if event.code == EVENT_JOB_MISSED:
            upd = {"$set": {"last_missed_at": now, "status": "missed"}, "$inc": {"missed": 1}}
        elif event.code == EVENT_JOB_ERROR:
            upd = {"$set": {"last_run_at": now, "status": "error", "last_error": str(event.exception)[:300]},
                   "$inc": {"runs": 1, "errors": 1}}
        else:
            upd = {"$set": {"last_run_at": now, "status": "ok"}, "$inc": {"runs": 1}}
        _col().update_one({"_id": event.job_id}, upd, upsert=True)
    except Exception as e:      # bookkeeping must never break a job
        logger.debug("job_runs: %s", e)


def attach(scheduler) -> None:
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
    scheduler.add_listener(record, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
