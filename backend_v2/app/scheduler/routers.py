"""
app/scheduler/routers.py — the one internal endpoint that turns Phase 14's
`EventOrchestrator` into an actual, running heartbeat.

`POST /internal/scheduler/tick` is not a Torpedo user session, deliberately —
a systemd timer calling this every few minutes is not a logged-in user any
more than Cint's outcome callback is. It reuses the exact same HMAC-signature
mechanism `app.panel.callback_security` already built for that (D-08's fix):
an unset `SCHEDULER_SIGNING_SECRET` is a configuration error and refuses to
run, never a silent skip; a bad signature is `401`, never a `200` that ran
anyway.

`GET /internal/scheduler/events` is the human-facing observability endpoint —
a normal `require_permission`-gated read, for an operator to see what's
pending/failed/processed without needing shell access to the VM.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.config import get_settings
from app.db import get_database
from app.emailai.models import InboundEmail
from app.emailai.routers import get_email_ai_service
from app.finance.routers import get_ai_finance_service, get_bill_service, get_invoice_service
from app.finance.routers import get_reconciliation_service as get_finance_reconciliation_service
from app.identity.models import Account, Person
from app.identity.facets import LeadState
from app.leadgen.models import LeadEnrollment
from app.leadgen.routers import get_leadgen_ai_service, get_outreach_ai_service
from app.models.base import CanonicalRepository
from app.outreach.models import Mailbox
from app.panel.callback_security import SignatureConfigError, SignatureInvalid, verify_hmac_signature
from app.panel.routers import get_operations_ai_service, get_survey_provider
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import SCHEDULER_READ
from app.scheduler.detectors import EventDetectionService
from app.scheduler.models import Event
from app.scheduler.orchestrator import EventOrchestrator

router = APIRouter()


def get_event_detection_service() -> EventDetectionService:
    db = get_database()
    return EventDetectionService(
        events=CanonicalRepository(db["events"], Event),
        operations_ai=get_operations_ai_service(),
        invoice_service=get_invoice_service(), bill_service=get_bill_service(),
        reconciliation_service=get_finance_reconciliation_service(),
        lead_states=CanonicalRepository(db["lead_states"], LeadState),
        accounts=CanonicalRepository(db["accounts"], Account), people=CanonicalRepository(db["people"], Person),
        inbound_emails=CanonicalRepository(db["inbound_emails"], InboundEmail),
        lead_enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox),
    )


def get_event_orchestrator() -> EventOrchestrator:
    db = get_database()
    return EventOrchestrator(
        events=CanonicalRepository(db["events"], Event),
        detection=get_event_detection_service(),
        operations_ai=get_operations_ai_service(),
        finance_ai=get_ai_finance_service(),
        leadgen_ai=get_leadgen_ai_service(),
        email_ai=get_email_ai_service(),
        outreach_ai=get_outreach_ai_service(),
        survey_provider=get_survey_provider(),
    )


def get_scheduler_signing_secret() -> str | None:
    return get_settings().scheduler_signing_secret


def get_events_repository() -> CanonicalRepository[Event]:
    return CanonicalRepository(get_database()["events"], Event)


class TickRequest(BaseModel):
    org_id: str


@router.post("/internal/scheduler/tick")
async def scheduler_tick(
    request: Request, x_signature: str = Header(alias="X-Signature"),
    orchestrator: EventOrchestrator = Depends(get_event_orchestrator),
    signing_secret: str | None = Depends(get_scheduler_signing_secret),
) -> dict:
    raw_body = await request.body()
    try:
        verify_hmac_signature(payload=raw_body, secret=signing_secret, signature_hex=x_signature)
    except SignatureConfigError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    except SignatureInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid JSON body") from exc

    body = TickRequest.model_validate(payload)
    detected = await orchestrator.run_detection_cycle(org_id=body.org_id)
    processed = await orchestrator.process_pending(org_id=body.org_id)
    return {"detected": detected, "processed": processed}


@router.get("/internal/scheduler/events")
async def list_events(
    status_filter: str | None = None,
    identity: ResolvedIdentity = Depends(require_permission(SCHEDULER_READ)),
    events: CanonicalRepository[Event] = Depends(get_events_repository),
) -> list[Event]:
    query: dict = {"org_id": identity.org_id}
    if status_filter:
        query["processing_status"] = status_filter
    return await events.find_all(query)
