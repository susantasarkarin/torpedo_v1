"""
Slice 7 — Outreach/Messaging. P0 regression coverage for the register's outreach
section: D-05 (Pipeline 4 — no kill switch/budget/unified log/CAN-SPAM footer), D-06
(Pipeline 5 — zero suppression/budget/kill-switch), D-07 (bounce suppressions never
propagate to canonical), D-26 (plaintext secrets on Mailbox), D-27 (suppression
`reason` destructively overwritten), D-28 (kill switch has no writer). Fake
SendProvider/MessageDrafter implementations stand in for real adapters — same pattern
as Slice 6's fake AIClassifier implementations.
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.models.activity import Activity
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalDocument, CanonicalRepository
from app.outreach.budget import BudgetService
from app.outreach.drafting import DraftResult, DraftUnavailable
from app.outreach.kill_switch import KillSwitch, KillSwitchService
from app.outreach.models import Mailbox, Message, SendLogEntry
from app.outreach.providers import ProviderSendResult, SendFailed
from app.outreach.service import MessagingFacade, OutreachError
from app.outreach.suppression import Suppression, SuppressionService

ORG = "org-A"
ACTOR = "alice"
DAY = "2026-09-05"

BODY_OK = "Hi there — this is a message. Unsubscribe here: https://example.com/u"
BODY_NO_FOOTER = "Hi there, this is a message with no opt-out link at all."


class RecordingSendProvider:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        self.calls.append((to_email, subject, body))
        return ProviderSendResult(provider_message_id=f"pm-{len(self.calls)}")


class FailingSendProvider:
    async def send(self, *, mailbox_credentials_id, to_email, subject, body):
        raise SendFailed("simulated transport failure")


class FakeDrafter:
    def __init__(self, subject: str, body: str, confidence: float = 0.9):
        self._subject, self._body, self._confidence = subject, body, confidence
        self.calls = 0

    async def draft(self, *, to_email, context):
        self.calls += 1
        return DraftResult(subject=self._subject, body=self._body, model="fake", model_version="v1", confidence=self._confidence)


class FakeUnavailableDrafter:
    async def draft(self, *, to_email, context):
        raise DraftUnavailable("simulated outage")


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


def _build_facade(db, provider) -> MessagingFacade:
    return MessagingFacade(
        mailboxes=CanonicalRepository(db["mailboxes"], Mailbox),
        messages=CanonicalRepository(db["messages"], Message),
        send_logs=CanonicalRepository(db["send_log_entries"], SendLogEntry),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        activities=CanonicalRepository(db["activities"], Activity),
        suppression=SuppressionService(CanonicalRepository(db["suppressions"], Suppression)),
        kill_switch=KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch)),
        budget=BudgetService(db["budget_counters"]),
        provider=provider,
    )


@pytest.fixture
def provider() -> RecordingSendProvider:
    return RecordingSendProvider()


@pytest.fixture
def facade(db, provider) -> MessagingFacade:
    return _build_facade(db, provider)


@pytest.fixture
def kill_switch(db) -> KillSwitchService:
    return KillSwitchService(CanonicalRepository(db["kill_switches"], KillSwitch))


@pytest.fixture
def suppression(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def mailboxes(db) -> CanonicalRepository[Mailbox]:
    return CanonicalRepository(db["mailboxes"], Mailbox)


async def _make_mailbox(mailboxes: CanonicalRepository[Mailbox], *, daily_cap: int = 200) -> Mailbox:
    return await mailboxes.insert(
        Mailbox(
            org_id=ORG, created_by=ACTOR, updated_by=ACTOR,
            email_address="sender@example.com", provider="smtp", credentials_id="cred-1", daily_cap=daily_cap,
        )
    )


# --------------------------------------------------------------------- D-28: kill switch


@pytest.mark.asyncio
async def test_send_blocked_by_default_when_kill_switch_has_no_writer_yet(facade, mailboxes, provider):
    """No KillSwitch document exists for this org — the fail-safe-to-paused default
    from D-28, still standing even with a real writer now built."""
    mailbox = await _make_mailbox(mailboxes)
    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "kill_switch_active"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_kill_switch_resume_actually_writes_and_unblocks(facade, kill_switch, mailboxes, provider):
    """The D-28 fix, positively: an operator can now turn sending back on."""
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)
    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "sent"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_kill_switch_pause_blocks_a_previously_resumed_org(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    await kill_switch.pause(org_id=ORG, actor=ACTOR, reason="incident")
    mailbox = await _make_mailbox(mailboxes)
    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "kill_switch_active"
    assert provider.calls == []


# --------------------------------------------------------------------- D-06/D-27: suppression


@pytest.mark.asyncio
async def test_send_blocked_by_suppression(facade, kill_switch, suppression, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    await suppression.suppress(org_id=ORG, actor=ACTOR, email="blocked@b.com", reason="unsubscribed", source="manual")
    mailbox = await _make_mailbox(mailboxes)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="blocked@b.com",
        idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "suppressed"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_suppression_reason_is_appended_not_overwritten(suppression):
    """Direct D-27 regression: an opt-out followed by a later bounce must not
    destroy the record of the opt-out."""
    await suppression.suppress(org_id=ORG, actor=ACTOR, email="x@y.com", reason="unsubscribed", source="manual")
    record = await suppression.suppress(org_id=ORG, actor="system", email="x@y.com", reason="hard_bounce", source="bounce")

    reasons = [event["reason"] for event in record.events]
    assert reasons == ["unsubscribed", "hard_bounce"]


@pytest.mark.asyncio
async def test_record_bounce_propagates_to_canonical_suppression(facade, kill_switch, suppression, mailboxes, provider):
    """D-07: a provider-reported bounce becomes suppressed through the same
    SuppressionService every send path checks — not a side table other pipelines
    never consult."""
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)

    assert await suppression.is_suppressed("bounced@b.com") is False
    await facade.record_bounce(org_id=ORG, actor="system", to_email="bounced@b.com")
    assert await suppression.is_suppressed("bounced@b.com") is True

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="bounced@b.com",
        idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "suppressed"
    assert provider.calls == []


# --------------------------------------------------------------------- D-05/D-06: budget


@pytest.mark.asyncio
async def test_budget_cap_enforced_atomically_across_sends(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes, daily_cap=2)

    statuses = []
    for i in range(3):
        entry = await facade.send(
            org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email=f"user{i}@b.com",
            idempotency_key=f"k{i}", subject="hi", body=BODY_OK, day=DAY,
        )
        statuses.append(entry.status)

    assert statuses == ["sent", "sent", "budget_blocked"]
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_budget_reservation_released_after_provider_failure(db, kill_switch, mailboxes):
    """A failed send must not permanently consume cap a retry needs."""
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes, daily_cap=1)

    failing_facade = _build_facade(db, FailingSendProvider())
    with pytest.raises(OutreachError):
        await failing_facade.send(
            org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
            idempotency_key="attempt-1", subject="hi", body=BODY_OK, day=DAY,
        )

    failed_log = await CanonicalRepository(db["send_log_entries"], SendLogEntry).find_one({"idempotency_key": "attempt-1"})
    assert failed_log.status == "failed"
    assert failed_log.error is not None

    retry_provider = RecordingSendProvider()
    retry_facade = _build_facade(db, retry_provider)
    entry = await retry_facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="attempt-2", subject="hi", body=BODY_OK, day=DAY,
    )
    assert entry.status == "sent"
    assert len(retry_provider.calls) == 1


# --------------------------------------------------------------------- idempotency


@pytest.mark.asyncio
async def test_idempotent_replay_never_calls_the_provider_twice(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)

    first = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="same-key", subject="hi", body=BODY_OK, day=DAY,
    )
    second = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="same-key", subject="hi", body=BODY_OK, day=DAY,
    )
    assert first.id == second.id
    assert len(provider.calls) == 1


# --------------------------------------------------------------------- CAN-SPAM footer (D-05)


@pytest.mark.asyncio
async def test_non_transactional_send_blocked_without_unsubscribe_footer(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", subject="hi", body=BODY_NO_FOOTER, day=DAY,
    )
    assert entry.status == "compliance_blocked"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_transactional_send_is_exempt_from_footer_check(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", subject="receipt", body=BODY_NO_FOOTER, transactional=True, day=DAY,
    )
    assert entry.status == "sent"


# --------------------------------------------------------------------- AI drafting behind the gateway


@pytest.mark.asyncio
async def test_drafted_content_still_blocked_by_suppression(facade, kill_switch, suppression, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    await suppression.suppress(org_id=ORG, actor=ACTOR, email="blocked@b.com", reason="unsubscribed", source="manual")
    mailbox = await _make_mailbox(mailboxes)
    drafter = FakeDrafter(subject="hi", body=BODY_OK)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="blocked@b.com",
        idempotency_key="k1", drafter=drafter, day=DAY,
    )
    assert entry.status == "suppressed"
    assert drafter.calls == 0, "drafting must not run ahead of the suppression gate"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_drafted_content_still_subject_to_footer_check(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)
    drafter = FakeDrafter(subject="hi", body=BODY_NO_FOOTER)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", drafter=drafter, day=DAY,
    )
    assert entry.status == "compliance_blocked"
    assert provider.calls == [], "drafting is not a side door around the footer gate"


@pytest.mark.asyncio
async def test_draft_unavailable_is_a_status_not_an_exception(facade, kill_switch, mailboxes, provider):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", drafter=FakeUnavailableDrafter(), day=DAY,
    )
    assert entry.status == "draft_unavailable"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_successful_drafted_send_records_an_ai_proposal(db, kill_switch, mailboxes):
    await kill_switch.resume(org_id=ORG, actor=ACTOR)
    mailbox = await _make_mailbox(mailboxes)
    provider = RecordingSendProvider()
    facade = _build_facade(db, provider)
    drafter = FakeDrafter(subject="hi", body=BODY_OK, confidence=0.88)

    entry = await facade.send(
        org_id=ORG, actor=ACTOR, mailbox_id=mailbox.id, to_email="a@b.com",
        idempotency_key="k1", drafter=drafter, day=DAY,
    )
    assert entry.status == "sent"
    assert drafter.calls == 1

    proposal = await CanonicalRepository(db["ai_proposals"], AiProposal).find_one({"subject_id": "k1"})
    assert proposal is not None
    assert proposal.task == "message_drafting"
    assert proposal.confidence == 0.88


# --------------------------------------------------------------------- misc invariants


@pytest.mark.asyncio
async def test_send_to_unknown_mailbox_raises(facade):
    with pytest.raises(OutreachError):
        await facade.send(
            org_id=ORG, actor=ACTOR, mailbox_id="does-not-exist", to_email="a@b.com",
            idempotency_key="k1", subject="hi", body=BODY_OK, day=DAY,
        )


def test_mailbox_model_has_no_field_that_could_hold_a_secret():
    """D-26 regression: the model shape itself, not just this slice's runtime
    behavior — a secret field re-added here would be a silent regression no
    behavioral test would ever catch."""
    own_fields = set(Mailbox.model_fields.keys()) - set(CanonicalDocument.model_fields.keys())
    assert own_fields == {"email_address", "provider", "credentials_id", "daily_cap", "is_active"}
    forbidden_substrings = ("password", "secret", "access_key", "private_key", "refresh_token", "api_key")
    for field_name in own_fields:
        for forbidden in forbidden_substrings:
            assert forbidden not in field_name
