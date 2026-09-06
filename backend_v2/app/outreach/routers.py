"""
HTTP surface for outreach. Same discipline as `app.leadgen.routers`: every write
derives `org_id` from the resolved identity, permission-gated throughout.

`StubSendProvider` is a test-only double now — see `get_send_provider()`
(Slice 21, same upgrade `get_survey_provider()` got in Slice 18: a real
`SmtpSendProvider`, not a stub, is the production default, and it already
fails loud when unconfigured rather than faking success). Kept here, not
deleted, because test files still import and override it directly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db import get_database
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult, SendProvider
from app.outreach.service import MessagingFacade, OutreachError
from app.outreach.suppression import Suppression, SuppressionService
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import OUTREACH_ADMIN, OUTREACH_SEND, OUTREACH_SUPPRESS

from app.auth.dependencies import require_permission

router = APIRouter()


class StubSendProvider:
    """Test-only now — see get_send_provider()'s docstring above."""

    async def send(self, *, mailbox_credentials_id: str, to_email: str, subject: str, body: str) -> ProviderSendResult:
        return ProviderSendResult(provider_message_id=f"stub-{uuid.uuid4()}")


def get_send_provider() -> SendProvider:
    from app.config import get_settings
    from app.outreach.smtp_provider import SmtpSendProvider

    settings = get_settings()
    return SmtpSendProvider(host=settings.smtp_host, port=settings.smtp_port, username=settings.smtp_username, password=settings.smtp_password)


def get_outreach_service(provider: SendProvider = Depends(get_send_provider)) -> MessagingFacade:
    db = get_database()
    return MessagingFacade(
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox),
        messages=CanonicalRepository(db["messages"], Message),
        send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        activities=CanonicalRepository(db["activities"], Activity),
        suppression=SuppressionService(CanonicalRepository(db["suppressions"], Suppression)),
        kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)),
        budget=BudgetService(db["outreach_budget_counters"]),
        provider=provider,
    )


def get_kill_switch_service() -> KillSwitchService:
    db = get_database()
    return KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch))


def get_suppression_service() -> SuppressionService:
    db = get_database()
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


class SendRequest(BaseModel):
    mailbox_id: str
    to_email: str
    idempotency_key: str
    subject: str | None = None
    body: str | None = None
    campaign_id: str | None = None
    transactional: bool = False


class PauseRequest(BaseModel):
    reason: str


class SuppressRequest(BaseModel):
    email: str
    reason: str


@router.post("/outreach/send", response_model=SendLogEntry)
async def send_message(
    body: SendRequest,
    identity: ResolvedIdentity = Depends(require_permission(OUTREACH_SEND)),
    svc: MessagingFacade = Depends(get_outreach_service),
) -> SendLogEntry:
    try:
        return await svc.send(
            org_id=identity.org_id, actor=identity.user_id, mailbox_id=body.mailbox_id, to_email=body.to_email,
            idempotency_key=body.idempotency_key, subject=body.subject, body=body.body,
            campaign_id=body.campaign_id, transactional=body.transactional,
        )
    except OutreachError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/outreach/kill-switch/pause", response_model=KillSwitch)
async def pause_outreach(
    body: PauseRequest,
    identity: ResolvedIdentity = Depends(require_permission(OUTREACH_ADMIN)),
    svc: KillSwitchService = Depends(get_kill_switch_service),
) -> KillSwitch:
    return await svc.pause(org_id=identity.org_id, actor=identity.user_id, reason=body.reason)


@router.post("/outreach/kill-switch/resume", response_model=KillSwitch)
async def resume_outreach(
    identity: ResolvedIdentity = Depends(require_permission(OUTREACH_ADMIN)),
    svc: KillSwitchService = Depends(get_kill_switch_service),
) -> KillSwitch:
    return await svc.resume(org_id=identity.org_id, actor=identity.user_id)


@router.post("/outreach/suppress", response_model=Suppression)
async def suppress_address(
    body: SuppressRequest,
    identity: ResolvedIdentity = Depends(require_permission(OUTREACH_SUPPRESS)),
    svc: SuppressionService = Depends(get_suppression_service),
) -> Suppression:
    return await svc.suppress(org_id=identity.org_id, actor=identity.user_id, email=body.email, reason=body.reason, source="manual")
