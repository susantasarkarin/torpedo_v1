"""
The single on/off switch for mail-AI.

Every path that lets the mail-pool AI read mail and write analysis / RFQ
proposals checks this: the four Celery tasks (the choke point -- every enqueue
path ends there), both Gmail-sync hooks, POST /rfq/resync and /rfq/resync-all,
the backfill script, and the beat schedule itself. One setting, one place.

Default OFF. The 2026-09-19 pause only removed the beat entry; Gmail-sync hooks
and /rfq/resync kept enqueuing runs of the legacy prompt (which fabricates
RFQs), so a paused pipeline was still writing. Turn it on deliberately, after
the benchmark for the current pipeline has passed:

    MAIL_AI_ENABLED=true      (backend .env; restart the backend, sales worker
                               and celery beat so all three see it)
"""

import os
from typing import Any, Dict

ENV_VAR = "MAIL_AI_ENABLED"
_TRUE = ("1", "true", "yes", "on")


def mail_ai_enabled() -> bool:
    """Read live on every call, so a worker picks up a change without an import-time snapshot."""
    return os.getenv(ENV_VAR, "").strip().lower() in _TRUE


def disabled_result(what: str) -> Dict[str, Any]:
    """What a task returns when it declines to run."""
    return {"skipped": "mail_ai_disabled", "detail": f"{what} not run: {ENV_VAR} is off"}


def disabled_message() -> str:
    return f"Mail-AI is switched off ({ENV_VAR} is not true). Nothing was queued."


def beat_entries() -> Dict[str, Dict[str, Any]]:
    """Beat schedule entries for mail-AI: none unless the switch is on.

    Re-enable checklist for the sender batch (from the 2026-09-19 pause):
    confirm the current pipeline passed its benchmark, start at limit=1, and
    watch real tick outcomes before raising the limit or shortening the interval.
    """
    if not mail_ai_enabled():
        return {}
    from celery.schedules import crontab
    return {
        "mail-pool-ai-sender-batch": {
            "task": "backend.tasks.mail_pool_ai_tasks.process_mail_pool_sender_batch",
            "schedule": 1200.0,
            "kwargs": {"limit": 1},
            "options": {"queue": "ai_processing"},
        },
        "mail-pool-ai-prefilter-audit": {
            # Nightly (02:00 UTC): re-check a random sample of rule-prefiltered
            # -out emails with the cheap model; records disagreements so a
            # too-aggressive rule filter eating real client mail is caught.
            "task": "backend.tasks.mail_pool_ai_tasks.audit_prefiltered_mail",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "ai_processing"},
        },
    }
