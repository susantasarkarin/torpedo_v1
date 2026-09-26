"""
PAUSE ALREADY-ENROLLED LEADS THE AI CLASSIFIER HAS SINCE REJECTED
===================================================================

The 2026-09-26 enrollment fix (routers/cold_outreach_router.py's
_build_basket_enrollment_query) stops a FUTURE enrollment sweep from picking up
a lead whose outreach_bucket is REJECT/REVIEW. It does nothing for a lead that
was enrolled BEFORE that verdict existed and is still mid-sequence: the send
loop's own selection query (workflow_status in not_started/pending_scheduled/
in_sequence + sendable:true + next_send_at due) never looks at outreach_bucket
either, so such a lead is still fully eligible to send its next step.

Measured 2026-09-20: 148 such leads (99 REJECT + 49 REVIEW), every one already
sendable=true and already past its next_send_at -- meaning the only thing
stopping them today is the UNRELATED global config-hold (no postal address).
The moment that's fixed, the very next 60-second send cycle would mail them
unless they are paused first.

This is a plain, deliberate exclusion: once outreach_bucket is REJECT/REVIEW
it does not change (bucket_classifier only classifies unclassified leads by
default), so there is nothing to "resume" here later the way
leads/outreach_resume.py resumes a temporary pause.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

LIVE_STATUSES = ("not_started", "pending_scheduled", "in_sequence")
PAUSE_STATUS = "ai_rejected_paused"


def find_ai_rejected_enrolled(db) -> List[Dict[str, Any]]:
    """
    Read-only: every outreach_leads_v2 row still in a live workflow state whose
    underlying lead (matched by lead_id against leads_raw._id OR
    enriched_lead_id -- enrollment links either way, see the 2026-09-26 audit)
    carries outreach_bucket REJECT or REVIEW. Returns the raw rows, not just
    ids, so a caller can report on them before deciding to pause.
    """
    # `db` here is the `torpedo` database handle; leads_raw lives in a
    # different database on the same client (matches _enroll_basket_leads'
    # own get_leads_db() pattern -- see routers/cold_outreach_router.py).
    from routers.cold_outreach_router import get_leads_db
    raw = get_leads_db()["leads_raw"]

    bucket_by_id: Dict[str, str] = {}
    for d in raw.find({"outreach_bucket": {"$in": ["REJECT", "REVIEW"]}},
                      {"outreach_bucket": 1, "enriched_lead_id": 1}):
        bucket_by_id[str(d["_id"])] = d["outreach_bucket"]
        if d.get("enriched_lead_id"):
            bucket_by_id[str(d["enriched_lead_id"])] = d["outreach_bucket"]

    if not bucket_by_id:
        return []

    live = db["outreach_leads_v2"].find(
        {"workflow_status": {"$in": list(LIVE_STATUSES)}},
        {"lead_id": 1, "email": 1, "sendable": 1, "next_send_at": 1,
         "campaign_id": 1, "current_step": 1, "workflow_status": 1})

    out = []
    for row in live:
        bucket = bucket_by_id.get(str(row.get("lead_id")))
        if bucket:
            row = dict(row)
            row["_ai_bucket"] = bucket
            out.append(row)
    return out


def apply_pause(db, rows: List[Dict[str, Any]], *, dry_run: bool = True) -> Dict[str, int]:
    """Pause the given rows. dry_run=True (default) writes nothing."""
    if dry_run:
        return {"would_pause": len(rows), "applied": 0}
    now = datetime.utcnow()
    ids = [r["_id"] for r in rows]
    res = db["outreach_leads_v2"].update_many(
        {"_id": {"$in": ids}},
        {"$set": {"workflow_status": PAUSE_STATUS,
                  "last_send_error": "paused: bucket_classifier verdict is REJECT/REVIEW",
                  "updated_at": now}})
    return {"would_pause": len(rows), "applied": res.modified_count}
