"""
Event — Phase 14's event/scheduler backbone, the "heartbeat" the completion
review explicitly named as the missing piece: `OperationsAIService.detect_triggers()`,
`InvoiceService.list_open()`, `LeadState`-needs-ICP-evaluation, and every other
real detector this codebase already built are functions nobody was calling.
This model, plus `app.scheduler.detectors`/`app.scheduler.orchestrator`, is what
calls them, on a cadence, safely.

**Not Celery, deliberately.** The VM is 2 vCPU / 3.8GB with swap already
saturated (`docs/AI_NATIVE_COMPLETION_CHECKLIST.md`'s hard-blockers table) —
a broker + separate worker process is real new infrastructure weight for a
platform this small. `EventOrchestrator` (orchestrator.py) is invoked by one
internal endpoint (`app.scheduler.routers`), triggered by a systemd timer on
this same FastAPI process — a detection+processing cycle is just another async
call, not a new service. Nothing about `EventOrchestrator`'s own code knows or
cares how it's invoked, so swapping to Celery later, if the platform outgrows
this, needs zero change to it or to the detectors.

**Idempotency is this model's whole job.** `dedupe_key` is a deterministic
string a detector computes before ever inserting an `Event` — `find_one` first,
insert only if nothing with that key exists yet. Two shapes of key are used,
deliberately:
- **One-shot conditions** (a lead never ICP-evaluated, an email never
  classified) key on the entity alone (`f"{event_type}:{entity_id}"`) — once
  the condition clears (the AI runs, or a human acts), the underlying query the
  detector runs no longer matches that entity, so it naturally stops recurring.
  A `FAILED` attempt stays retryable under the *same* key, not a fresh event.
- **Recurring conditions** (an invoice overdue today may still be overdue
  tomorrow, a survey may still be low-conversion tomorrow) key on
  `f"{event_type}:{entity_id}:{date}"` — a legitimate, still-true condition gets
  a fresh look every day, without the same day's detection run spamming a
  second `Event` for a condition already queued or already decided today.

**Single-flight processing** reuses `CanonicalRepository.update()`'s existing
optimistic-concurrency guarantee — no new locking primitive. Claiming an event
is a version-guarded `PENDING/FAILED -> PROCESSING` update; a `VersionConflict`
means another tick (or a concurrent worker, once this ever runs as more than
one process) already claimed it, so the orchestrator just moves on to the next
one instead of double-processing.
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import CanonicalDocument

PENDING = "PENDING"
PROCESSING = "PROCESSING"
PROCESSED = "PROCESSED"
FAILED = "FAILED"
EVENT_STATUSES = frozenset({PENDING, PROCESSING, PROCESSED, FAILED})

# One entry per real, detectable condition this slice actually wires up — see
# app.scheduler.detectors' module docstring for what was deliberately left out
# and why (no fabricated trigger for coverage's sake).
EVENT_TYPES = frozenset({
    "survey_operations_trigger",
    "ar_followup_due",
    "ap_followup_due",
    "reconciliation_unmatched",
    "lead_icp_evaluation_due",
    "email_classification_due",
    "outreach_followup_due",
    "lead_conversion_due",
    "email_ingestion_due",
})

# A FAILED event stays retryable up to this many attempts, then stops being
# picked up automatically — a real, recurring failure (e.g. every attempt
# raises LLMUnavailable because no GPU credential exists yet) needs a human to
# notice and unblock the credential, not an infinite silent retry loop.
MAX_ATTEMPTS = 5


class Event(CanonicalDocument):
    event_type: str
    entity_type: str
    entity_id: str
    occurred_at: datetime
    dedupe_key: str
    payload: dict = {}  # detection-time context the handler needs (e.g. trigger_type, mailbox_id)
    processing_status: str = PENDING
    attempts: int = 0
    last_error: str | None = None
    result: dict | None = None  # processing-time outcome (e.g. the Decision's own fields) — never a fabricated success value
