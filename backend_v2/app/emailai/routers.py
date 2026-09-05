"""
HTTP surface for Email AI. Composes existing domain services rather than
reconstructing them — `get_leadgen_service()`/`get_outreach_service()`/
`get_reconciliation_service()` are the same provider functions their own routers
already use, called directly here rather than duplicated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.ai.decision_engine import Decision, DecisionEngine
from app.ai.gpu_broker import GpuBroker
from app.ai.llm import GpuBrokerLLMProvider
from app.ai.tools import ToolRegistry
from app.auth.dependencies import require_permission
from app.db import get_database
from app.emailai.drafting import EmailMessageDrafter
from app.emailai.models import InboundEmail
from app.emailai.service import EmailAIError, EmailAIService
from app.finance.routers import get_reconciliation_service
from app.leadgen.routers import get_leadgen_service
from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository
from app.outreach.routers import get_outreach_service, get_send_provider, get_suppression_service
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import EMAIL_ANALYZE, EMAIL_INGEST, EMAIL_READ

router = APIRouter()


def get_email_ai_service() -> EmailAIService:
    db = get_database()
    ai_proposals = CanonicalRepository(db["ai_proposals"], AiProposal)
    llm = GpuBrokerLLMProvider(GpuBroker(db["ai_gpu_leases"]))
    decision_engine = DecisionEngine(llm, ToolRegistry(), ai_proposals)
    return EmailAIService(
        emails=CanonicalRepository(db["inbound_emails"], InboundEmail),
        ai_proposals=ai_proposals,
        activities=CanonicalRepository(db["activities"], Activity),
        decision_engine=decision_engine,
        leadgen=get_leadgen_service(),
        suppression=get_suppression_service(),
        reconciliation=get_reconciliation_service(),
        outreach=get_outreach_service(get_send_provider()),
        drafter=EmailMessageDrafter(llm),
    )


class IngestEmailRequest(BaseModel):
    provider: str
    provider_message_id: str
    from_address: str
    to_address: str
    subject: str
    body: str
    thread_id: str | None = None


class FollowupRequest(BaseModel):
    mailbox_id: str


@router.post("/emails/ingest", response_model=InboundEmail)
async def ingest_email(body: IngestEmailRequest, identity: ResolvedIdentity = Depends(require_permission(EMAIL_INGEST)), svc: EmailAIService = Depends(get_email_ai_service)) -> InboundEmail:
    return await svc.ingest_email(
        org_id=identity.org_id, actor=identity.user_id, provider=body.provider, provider_message_id=body.provider_message_id,
        from_address=body.from_address, to_address=body.to_address, subject=body.subject, body=body.body, thread_id=body.thread_id,
    )


@router.post("/emails/{email_id}/analyze", response_model=Decision)
async def analyze_email(email_id: str, identity: ResolvedIdentity = Depends(require_permission(EMAIL_ANALYZE)), svc: EmailAIService = Depends(get_email_ai_service)) -> Decision:
    try:
        return await svc.analyze_and_route(org_id=identity.org_id, actor=identity.user_id, email_id=email_id)
    except EmailAIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/emails/{email_id}/followup", response_model=Decision)
async def decide_email_followup(email_id: str, body: FollowupRequest, identity: ResolvedIdentity = Depends(require_permission(EMAIL_ANALYZE)), svc: EmailAIService = Depends(get_email_ai_service)) -> Decision:
    try:
        return await svc.decide_followup(org_id=identity.org_id, actor=identity.user_id, email_id=email_id, mailbox_id=body.mailbox_id)
    except EmailAIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/emails/{email_id}", response_model=InboundEmail)
async def get_email(email_id: str, identity: ResolvedIdentity = Depends(require_permission(EMAIL_READ)), svc: EmailAIService = Depends(get_email_ai_service)) -> InboundEmail:
    email = await svc._emails.get(email_id)
    if email is None or email.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "email not found")
    return email
