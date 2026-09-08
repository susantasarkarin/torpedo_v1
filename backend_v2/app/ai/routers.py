"""
HTTP surface for the AI Gateway, plus (Slice 18) one cross-cutting diagnostics
endpoint. `/ai/gpu/status` and `/ai/gpu/shutdown` predate this; `/integrations/status`
is new — a single read-only view of which external boundaries are actually
configured versus credential-blocked, for every `Protocol` this codebase has built
so far. It reports presence/absence of a credential, never the credential itself,
and never claims a boundary is "connected" merely because code exists behind it —
"configured" here means "the env var this provider's `api_key()`-style guard checks
is non-empty," nothing more.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.ai.gpu_broker import GpuBroker
from app.auth.dependencies import require_permission
from app.config import get_settings
from app.db import get_database
from app.governance.approvals import STALE_REVIEW_THRESHOLD
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import AI_ADMIN, AI_READ, INTEGRATIONS_STATUS_READ
from app.scheduler.models import EVENT_STATUSES, FAILED, MAX_ATTEMPTS, PROCESSING, STUCK_PROCESSING_THRESHOLD, Event

router = APIRouter()


def get_gpu_broker() -> GpuBroker:
    return GpuBroker(get_database()["ai_gpu_leases"])


def get_events_repository_for_status() -> CanonicalRepository[Event]:
    return CanonicalRepository(get_database()["events"], Event)


def get_proposals_repository_for_status() -> CanonicalRepository[AiProposal]:
    return CanonicalRepository(get_database()["ai_proposals"], AiProposal)


@router.get("/ai/gpu/status")
async def gpu_status(identity: ResolvedIdentity = Depends(require_permission(AI_READ)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.status()


@router.post("/ai/gpu/shutdown")
async def gpu_shutdown_now(identity: ResolvedIdentity = Depends(require_permission(AI_ADMIN)), broker: GpuBroker = Depends(get_gpu_broker)) -> dict:
    return await broker.shutdown_now()


def _configured(*env_vars: str) -> str:
    return "CONFIGURED" if all((os.getenv(v) or "").strip() for v in env_vars) else "NOT_CONFIGURED"


@router.get("/integrations/status")
async def integrations_status(
    identity: ResolvedIdentity = Depends(require_permission(INTEGRATIONS_STATUS_READ)),
    broker: GpuBroker = Depends(get_gpu_broker),
    events: CanonicalRepository[Event] = Depends(get_events_repository_for_status),
    proposals: CanonicalRepository[AiProposal] = Depends(get_proposals_repository_for_status),
) -> dict:
    gpu_broker_status = await broker.status()

    scheduler_counts = {status: len(await events.find_all({"org_id": identity.org_id, "processing_status": status})) for status in sorted(EVENT_STATUSES)}
    # Phase 10 (operations/event engine) — "FAILED" alone doesn't distinguish
    # an event still being retried from one that has exhausted MAX_ATTEMPTS
    # and needs a human. Real dead-letter visibility, using the existing
    # Event.attempts field rather than a second dead-letter table — the same
    # signal app.scheduler.orchestrator.EventOrchestrator already stops
    # retrying on, made queryable here instead of only inferable from logs.
    failed_events = await events.find_all({"org_id": identity.org_id, "processing_status": FAILED})
    exhausted_count = sum(1 for e in failed_events if e.attempts >= MAX_ATTEMPTS)
    # Phase 16 (failure/recovery audit) — a PROCESSING event this old wasn't
    # claimed by this tick; it was orphaned by a crash between claim and
    # terminal write (see app.scheduler.models.STUCK_PROCESSING_THRESHOLD).
    # The orchestrator already self-heals this on the next tick — this count
    # exists so a *persistent* stuck count (one that never drops) is visible
    # as a real signal, not only inferable from logs.
    processing_events = await events.find_all({"org_id": identity.org_id, "processing_status": PROCESSING})
    stuck_count = sum(1 for e in processing_events if datetime.now(timezone.utc) - e.updated_at >= STUCK_PROCESSING_THRESHOLD)
    pending_review = len(await proposals.find_all({"org_id": identity.org_id, "reviewed_by": None}))
    # Phase 11 (human governance) — a pending review isn't itself a problem;
    # one that's been pending longer than STALE_REVIEW_THRESHOLD is real
    # staleness, using AiProposal.created_at, no new field.
    stale_review_count = len(await proposals.find_all({"org_id": identity.org_id, "reviewed_by": None, "created_at": {"$lt": datetime.now(timezone.utc) - STALE_REVIEW_THRESHOLD}}))

    return {
        "ai_gateway": "READY",  # the gateway code path itself always exists; whether a model answers depends on the GPU broker below
        "ai_shadow_mode": "ON" if get_settings().ai_shadow_mode else "OFF",  # ON = decisions recorded, execution suppressed (Allocation/Operations/Finance-match/Email-send/Outreach-send)
        "gpu_broker": "READY" if gpu_broker_status["state"] == "ready" else ("DISABLED" if not (os.getenv("GPU_BROKER_ENABLED") or "").strip() else "UNAVAILABLE"),
        "gpu_credential": _configured("RUNPOD_API_KEY"),
        "gsc": "NOT_CONFIGURED",  # no GSC credential scheme has been designed yet — see app.leadgen.gsc's module docstring
        "cint": _configured("CINT_API_KEY", "CINT_SUPPLIER_CODE"),
        "email_send_provider": _configured("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"),  # app.outreach.smtp_provider.SmtpSendProvider — real, fails loud when unconfigured
        "email_ingestion_provider": "NOT_CONFIGURED",  # app.emailai.providers.EmailIngestionProvider — no implementation exists yet, stub or real
        # Phase 14 scheduler activity, by processing_status, for this org — real
        # counts from app.scheduler.models.Event, not a separate mocked metric.
        "scheduler_events": scheduler_counts,
        # Of the FAILED count above, how many have exhausted MAX_ATTEMPTS and
        # will never be retried automatically — real dead-letter visibility.
        "scheduler_events_exhausted": exhausted_count,
        # Of the PROCESSING count above, how many are orphaned (older than
        # STUCK_PROCESSING_THRESHOLD) — self-healed on the next tick, but a
        # persistently nonzero count is a real signal something keeps crashing.
        "scheduler_events_stuck": stuck_count,
        # Phase 1 production-foundations audit: the human review queue's own
        # backlog size — a real signal for "is anyone keeping up with shadow-mode
        # review," not a fabricated dashboard number.
        "governance_pending_review": pending_review,
        # Of the pending count above, how many have been waiting longer than
        # STALE_REVIEW_THRESHOLD — real stale-approval visibility (Phase 11).
        "governance_stale_review_count": stale_review_count,
    }
