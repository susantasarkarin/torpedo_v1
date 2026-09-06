"""
EventDetectionService — the deterministic half of Phase 14, same discipline as
every prior slice's "offer the walls, don't ask the AI to build them": nothing
in here calls a model. Each `detect_*` method finds a real, already-existing
condition (reusing an existing detector/query, never reimplementing one) and
creates an idempotent `Event` for it, skipping if one already exists per
`Event`'s own dedupe-key rules (see models.py).

**Seven real, computable triggers — not the fuller wishlist, and that's
deliberate**:

- `survey_operations_trigger` — reuses `OperationsAIService.detect_triggers()`
  (Slice 16) wholesale; this method does not re-detect no-traffic/low-conversion/
  high-dropout, it just turns each already-detected `(Survey, trigger_type)`
  pair into an `Event`.
- `ar_followup_due` / `ap_followup_due` — reuse `InvoiceService.list_open()`/
  `BillService.list_open()` (Slice 17's own deterministic candidate sets).
- `reconciliation_unmatched` — reuses `ReconciliationService.list_unmatched()`
  (added this slice, same pattern as the two methods above).
- `lead_icp_evaluation_due` — a `LeadState` that has reached a qualified-or-
  further state but has never been AI-ICP-evaluated (`ai_decision_subject_id`
  is still `None` — the Slice 18 traceability field, read here rather than a
  new one invented for this purpose).
- `email_classification_due` — an `InboundEmail` never classified.
- `outreach_followup_due` — a `LeadEnrollment` not in a terminal sequence
  state, stale for longer than `OUTREACH_STALENESS_WINDOW`. Needs a real,
  active `Mailbox` to send through; an org with none configured yet simply
  produces no events for this trigger — never a fabricated mailbox_id.

**Deliberately NOT built, honestly, same discipline as every prior slice's
gaps**: a "new GSC opportunity" trigger (no site-registry entity exists in the
schema to iterate — inventing one now would be exactly the kind of decoration
this rebuild's discipline exists to avoid, and GSC is credential-blocked
regardless), a "pending panelist allocation" trigger (allocation happens
per-respondent at the moment of a real traffic-redirect request, not on a
schedule — there is no queryable "panelist waiting" queue in this data model),
and quota-stagnation/provider-failure-rate triggers (no persisted metric exists
— `app.panel.ai_operations`'s own module docstring already recorded this same
gap for Slice 16, unchanged here).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.emailai.models import InboundEmail
from app.finance.service import BillService, InvoiceService, ReconciliationService
from app.identity.models import Account, Person
from app.identity.facets import LeadState
from app.leadgen.models import ASSIGNED, ENROLLED, LeadEnrollment, QUALIFIED
from app.models.base import CanonicalRepository
from app.outreach.models import Mailbox
from app.panel.ai_operations import OperationsAIService
from app.scheduler.models import Event

# A lead ready for a broader AI commercial opinion, not still being
# enriched/disqualified/converted-away. Mirrors the same states
# LeadGenService.ingest()'s "reuse a non-terminal LeadState" check treats as
# still-open (app/leadgen/service.py), narrowed to "actually qualified or
# further" since ICP evaluation on a not-yet-qualified lead has nothing real
# to reason about yet.
_ICP_ELIGIBLE_LEAD_STATES = (QUALIFIED, ASSIGNED, ENROLLED)

# A non-terminal outreach enrollment gets re-evaluated at most once per this
# window — an operational cadence choice (like Slice 10's 7-day inactivity
# window), not a locked business rule from the spec. Tunable without touching
# any other module.
OUTREACH_STALENESS_WINDOW = timedelta(days=3)


class EventDetectionService:
    def __init__(
        self, *, events: CanonicalRepository[Event], operations_ai: OperationsAIService,
        invoice_service: InvoiceService, bill_service: BillService, reconciliation_service: ReconciliationService,
        lead_states: CanonicalRepository[LeadState], accounts: CanonicalRepository[Account], people: CanonicalRepository[Person],
        inbound_emails: CanonicalRepository[InboundEmail], lead_enrollments: CanonicalRepository[LeadEnrollment],
        mailboxes: CanonicalRepository[Mailbox],
    ):
        self._events = events
        self._operations_ai = operations_ai
        self._invoice_service = invoice_service
        self._bill_service = bill_service
        self._reconciliation_service = reconciliation_service
        self._lead_states = lead_states
        self._accounts = accounts
        self._people = people
        self._inbound_emails = inbound_emails
        self._lead_enrollments = lead_enrollments
        self._mailboxes = mailboxes

    async def run_all(self, *, org_id: str, as_of: datetime | None = None) -> dict[str, int]:
        """Runs every detector once, returns how many *new* Events each one
        created — not how many candidates it found, so an already-queued or
        already-decided condition never inflates the count."""
        as_of = as_of or datetime.now(timezone.utc)
        return {
            "survey_operations_trigger": len(await self.detect_survey_operations(org_id=org_id, as_of=as_of)),
            "ar_followup_due": len(await self.detect_ar_followup(org_id=org_id)),
            "ap_followup_due": len(await self.detect_ap_followup(org_id=org_id)),
            "reconciliation_unmatched": len(await self.detect_reconciliation_unmatched(org_id=org_id)),
            "lead_icp_evaluation_due": len(await self.detect_lead_icp_evaluation(org_id=org_id)),
            "email_classification_due": len(await self.detect_email_classification(org_id=org_id)),
            "outreach_followup_due": len(await self.detect_outreach_followup(org_id=org_id, as_of=as_of)),
        }

    async def _create_if_new(self, *, org_id: str, event_type: str, entity_type: str, entity_id: str, occurred_at: datetime, dedupe_key: str, payload: dict) -> Event | None:
        existing = await self._events.find_one({"dedupe_key": dedupe_key})
        if existing:
            return None
        return await self._events.insert(
            Event(org_id=org_id, created_by="system", updated_by="system", event_type=event_type, entity_type=entity_type, entity_id=entity_id, occurred_at=occurred_at, dedupe_key=dedupe_key, payload=payload)
        )

    async def detect_survey_operations(self, *, org_id: str, as_of: datetime | None = None) -> list[Event]:
        triggered = await self._operations_ai.detect_triggers(org_id=org_id, as_of=as_of)
        created = []
        for survey, trigger_type in triggered:
            dedupe_key = f"survey_operations_trigger:{survey.id}:{trigger_type}:{date.today().isoformat()}"
            event = await self._create_if_new(org_id=org_id, event_type="survey_operations_trigger", entity_type="survey", entity_id=survey.id, occurred_at=as_of or datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={"trigger_type": trigger_type})
            if event:
                created.append(event)
        return created

    async def detect_ar_followup(self, *, org_id: str) -> list[Event]:
        invoices = await self._invoice_service.list_open(org_id=org_id)
        created = []
        for invoice in invoices:
            dedupe_key = f"ar_followup_due:{invoice.id}:{date.today().isoformat()}"
            event = await self._create_if_new(org_id=org_id, event_type="ar_followup_due", entity_type="invoice", entity_id=invoice.id, occurred_at=datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={})
            if event:
                created.append(event)
        return created

    async def detect_ap_followup(self, *, org_id: str) -> list[Event]:
        bills = await self._bill_service.list_open(org_id=org_id)
        created = []
        for bill in bills:
            dedupe_key = f"ap_followup_due:{bill.id}:{date.today().isoformat()}"
            event = await self._create_if_new(org_id=org_id, event_type="ap_followup_due", entity_type="bill", entity_id=bill.id, occurred_at=datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={})
            if event:
                created.append(event)
        return created

    async def detect_reconciliation_unmatched(self, *, org_id: str) -> list[Event]:
        records = await self._reconciliation_service.list_unmatched(org_id=org_id)
        created = []
        for record in records:
            dedupe_key = f"reconciliation_unmatched:{record.id}:{date.today().isoformat()}"
            event = await self._create_if_new(org_id=org_id, event_type="reconciliation_unmatched", entity_type="reconciliation_record", entity_id=record.id, occurred_at=datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={})
            if event:
                created.append(event)
        return created

    async def detect_lead_icp_evaluation(self, *, org_id: str) -> list[Event]:
        leads = await self._lead_states.find_all({"org_id": org_id, "state": {"$in": list(_ICP_ELIGIBLE_LEAD_STATES)}, "ai_decision_subject_id": None})
        created = []
        for lead in leads:
            dedupe_key = f"lead_icp_evaluation_due:{lead.id}"
            account = await self._accounts.get(lead.account_id) if lead.account_id else None
            person = await self._people.get(lead.person_id) if lead.person_id else None
            prospect_context = {
                "industry": account.industry if account else None, "company_domain": account.domain if account else None,
                "title": person.title if person else None,
            }
            event = await self._create_if_new(org_id=org_id, event_type="lead_icp_evaluation_due", entity_type="lead_state", entity_id=lead.id, occurred_at=datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={"prospect_context": prospect_context})
            if event:
                created.append(event)
        return created

    async def detect_email_classification(self, *, org_id: str) -> list[Event]:
        emails = await self._inbound_emails.find_all({"org_id": org_id, "classification": None})
        created = []
        for email in emails:
            dedupe_key = f"email_classification_due:{email.id}"
            event = await self._create_if_new(org_id=org_id, event_type="email_classification_due", entity_type="inbound_email", entity_id=email.id, occurred_at=datetime.now(timezone.utc), dedupe_key=dedupe_key, payload={})
            if event:
                created.append(event)
        return created

    async def detect_outreach_followup(self, *, org_id: str, as_of: datetime | None = None) -> list[Event]:
        as_of = as_of or datetime.now(timezone.utc)
        mailbox = await self._mailboxes.find_one({"org_id": org_id, "is_active": True})
        if mailbox is None:
            return []  # no configured mailbox to send through — an honest gap, never a fabricated mailbox_id

        cutoff = as_of - OUTREACH_STALENESS_WINDOW
        enrollments = await self._lead_enrollments.find_all({"org_id": org_id, "sequence_state": {"$ne": "STOPPED"}})
        created = []
        for enrollment in enrollments:
            if enrollment.updated_at > cutoff:
                continue  # already re-evaluated (or created) recently enough
            dedupe_key = f"outreach_followup_due:{enrollment.id}:{date.today().isoformat()}"
            event = await self._create_if_new(org_id=org_id, event_type="outreach_followup_due", entity_type="lead_enrollment", entity_id=enrollment.id, occurred_at=as_of, dedupe_key=dedupe_key, payload={"mailbox_id": mailbox.id})
            if event:
                created.append(event)
        return created
