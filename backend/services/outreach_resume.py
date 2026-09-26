"""
RESTORE LEADS THAT A PAUSE PARKED
=================================

The send loop used to mark every lead it touched `workflow_status="paused"` while
the global kill switch was on (or its campaign inactive). The send query selects
only not_started / pending_scheduled / in_sequence, so a "paused" lead is never
looked at again -- and neither "resume campaign" nor `outreach_kill_switch.py
resume` moved it back. Resuming silently did nothing for exactly the leads that
had been touched, which is what happened after the 2026-08-25 pause.

The send loop no longer writes "paused" (a pause now leaves leads untouched), but
leads already parked that way exist in the wild, so resume must bring them back.

Only the exact status "paused" is touched. "paused_duplicate_brand", "suppressed",
"bounced", "skipped_*", "needs_human_intervention" and every other status are
deliberate, lead-specific outcomes and stay as they are. Restoring makes a lead
selectable again, nothing more: the per-send gate (suppression, bounce lists,
budget, config) still runs at send time, and the loop's per-cycle and daily caps
still pace it.
"""

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

PARKED_STATUS = "paused"


def restore_paused_leads(db: Any, campaign_id: Optional[str] = None) -> int:
    """
    Put leads parked as "paused" back into the send queue. With `campaign_id`
    only that campaign's leads are restored; without it, every campaign's.
    Returns how many leads were restored. Never raises: a failed restore must not
    fail the resume it belongs to (the caller still resumed sending).
    """
    flt = {"workflow_status": PARKED_STATUS}
    if campaign_id:
        flt["campaign_id"] = campaign_id
    now = datetime.utcnow()
    try:
        leads = db["outreach_leads_v2"]
        # A lead that has already been mailed continues its sequence; one that has
        # not starts it. Two updates, each an atomic bulk write.
        never_sent = leads.update_many(
            {**flt, "current_step": {"$in": [0, None]}, "last_sent_at": {"$exists": False}},
            {"$set": {"workflow_status": "not_started", "updated_at": now}})
        continuing = leads.update_many(
            flt, {"$set": {"workflow_status": "in_sequence", "updated_at": now}})
        restored = never_sent.modified_count + continuing.modified_count
        if restored:
            logger.warning("[Outreach] restored %d paused leads%s", restored,
                           f" for campaign {campaign_id}" if campaign_id else "")
        return restored
    except Exception as e:
        logger.error("[Outreach] could not restore paused leads: %s", e)
        return 0
