"""
Yield management periodic tasks.

sweep_abandoned_cint_sessions closes the metrics blind spot for respondents
who click out to a Cint survey but never hit the redirect callback (closed
tab, dead survey, network drop). Those sessions previously left no trace in
cint_metrics — entrants_n is incremented only by the callback — so a survey
burning clicks without returning anyone looked identical to a survey getting
no traffic, and the conversion-based auto-deactivation never fired for it.

The sweep finds traffic records redirected to a Cint survey that are still
INCOMPLETE after ABANDON_AFTER_HOURS, counts each once as an abandoned entrant
(entrants_n + abandoned_n, releasing the pacing slot), and then re-runs the
same internal-conversion / auto-deactivation arithmetic as the live callback
in routers/traffic.py.
"""

import logging
import os
from datetime import datetime, timedelta

from celery_app import celery_app

logger = logging.getLogger(__name__)

ABANDON_AFTER_HOURS = float(os.getenv("YIELD_ABANDON_AFTER_HOURS", "4"))
SWEEP_BATCH = 5000
# Mirrors the auto-deactivation rule in routers/traffic.py: evaluate once a
# survey has >=20 tracked sessions, deactivate under 5% conversion.
MIN_SESSIONS_FOR_EVAL = 20
DEACTIVATION_CONV_THRESHOLD = 0.05


def _get_db():
    from db_pools import get_db
    return get_db


def _recompute_survey_status(metrics_col, surveys_col, sid_str: str) -> None:
    """Recompute internal conversion and auto-(de)activate — same arithmetic
    as the live redirect callback in routers/traffic.py."""
    doc = metrics_col.find_one({"survey_id": sid_str})
    if not doc:
        return
    entrants = max(doc.get("entrants_n", 0), 0)
    completes = max(doc.get("completions", 0), 0)
    current_status = doc.get("survey_status", "testing")
    if entrants < MIN_SESSIONS_FOR_EVAL:
        return

    internal_conv = (completes / entrants) if entrants else 0.0
    status_update = {
        "internal_conversion": round(internal_conv, 4),
        "functional_conversion": round(internal_conv, 4),
    }
    if internal_conv < DEACTIVATION_CONV_THRESHOLD and current_status != "inactive":
        survey_filter = {"survey_id": int(sid_str)} if sid_str.isdigit() \
            else {"survey_id": sid_str}
        survey_doc = surveys_col.find_one(survey_filter, {"conversion": 1}) or {}
        status_update.update({
            "survey_status": "inactive",
            "deactivated_at": datetime.utcnow(),
            "global_conv_at_deactivation": float(survey_doc.get("conversion") or 0),
        })
        surveys_col.update_one(survey_filter,
                               {"$set": {"is_active_in_pool": False}})
        logger.info(f"[yield-sweep] survey {sid_str} auto-deactivated "
                    f"(conv={internal_conv:.1%} over {entrants} sessions "
                    f"incl. abandonments)")
    elif internal_conv >= DEACTIVATION_CONV_THRESHOLD and current_status == "testing":
        status_update["survey_status"] = "active"
    metrics_col.update_one({"survey_id": sid_str}, {"$set": status_update})


@celery_app.task(
    name="backend.tasks.yield_tasks.sweep_abandoned_cint_sessions",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def sweep_abandoned_cint_sessions(self):
    """Count never-returned Cint redirects as abandoned entrants."""
    get_db = _get_db()
    traffic_col = get_db("traffic_flow_db")["url_parameters"]
    cint_db = get_db("cint_research")
    metrics_col = cint_db["cint_metrics"]
    surveys_col = cint_db["cint_surveys"]

    cutoff = datetime.utcnow() - timedelta(hours=ABANDON_AFTER_HOURS)
    query = {
        "currentCintSurveyId": {"$exists": True, "$ne": None},
        "cint_hashed_pid": {"$exists": True},   # actually redirected out
        "status": "INCOMPLETE",                  # callback never arrived
        "yield_abandon_swept": {"$ne": True},    # count each session once
        # updatedAt is an ISO string on the redirect path but a datetime on
        # others — match staleness for both BSON types.
        "$or": [
            {"updatedAt": {"$type": "string", "$lt": cutoff.isoformat()}},
            {"updatedAt": {"$type": "date", "$lt": cutoff}},
        ],
    }

    swept = 0
    touched_surveys = set()
    try:
        for rec in traffic_col.find(
                query, {"currentCintSurveyId": 1}).limit(SWEEP_BATCH):
            sid_str = str(rec["currentCintSurveyId"])
            claimed = traffic_col.update_one(
                {"_id": rec["_id"], "yield_abandon_swept": {"$ne": True}},
                {"$set": {"yield_abandon_swept": True,
                          "yield_abandoned_at": datetime.utcnow()}})
            if claimed.modified_count == 0:
                continue  # another worker got it
            metrics_col.update_one(
                {"survey_id": sid_str},
                {"$inc": {"entrants_n": 1, "abandoned_n": 1,
                          "current_active_entrants": -1},
                 "$set": {"last_updated": datetime.utcnow()},
                 "$setOnInsert": {"survey_id": sid_str}},
                upsert=True)
            touched_surveys.add(sid_str)
            swept += 1

        for sid_str in touched_surveys:
            try:
                _recompute_survey_status(metrics_col, surveys_col, sid_str)
            except Exception as e:
                logger.warning(f"[yield-sweep] status recompute failed for "
                               f"{sid_str}: {e}")

        logger.info(f"[yield-sweep] swept {swept} abandoned sessions across "
                    f"{len(touched_surveys)} surveys")
        return {"status": "ok", "swept": swept,
                "surveys": len(touched_surveys)}
    except Exception as e:
        logger.error(f"[yield-sweep] failed: {e}", exc_info=True)
        raise self.retry(exc=e)
