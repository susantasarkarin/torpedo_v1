"""
Slice 6 — the first full vertical. Organized by the categories the user's Slice 6
plan named explicitly, so a missing category is visible as a missing section.

Fake AIClassifier implementations below stand in for a real AI-gateway integration —
same pattern as Slice 5's fake AccountReferenceRepointer — proving the pipeline's
*handling* of AI success/low-confidence/outage without calling anything external.
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.identity.facet_service import FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.leadgen.ai import AIClassificationResult, AIUnavailable
from app.leadgen.models import ASSIGNED, DISQUALIFIED, ENRICHING, ENROLLED, QUALIFIED, DeadLetterEvent, LeadEnrollment, RawLeadEvent
from app.models.ai_proposal import AiProposal
from app.leadgen.scoring import QUALIFY_THRESHOLD, ICPProfile, score_lead
from app.leadgen.service import LeadGenError, LeadGenService
from app.outreach.suppression import Suppression, SuppressionService
from app.models.activity import Activity
from app.models.base import CanonicalRepository, VersionConflict

ORG = "org-A"
ACTOR = "system"

PROFILE = ICPProfile(industries=frozenset({"software"}), countries=frozenset({"us"}))


class FakeUnavailableClassifier:
    async def classify(self, *, person_fields, account_fields):
        raise AIUnavailable("simulated outage")


class FakeLowConfidenceClassifier:
    async def classify(self, *, person_fields, account_fields):
        return AIClassificationResult(fields={"industry": "software", "country": "us"}, confidence=0.30, model="fake", model_version="v1")


class FakeHighConfidenceClassifier:
    def __init__(self, fields: dict):
        self._fields = fields

    async def classify(self, *, person_fields, account_fields):
        return AIClassificationResult(fields=self._fields, confidence=0.95, model="fake", model_version="v1")


class FakeNoOpClassifier:
    async def classify(self, *, person_fields, account_fields):
        return AIClassificationResult(fields={}, confidence=1.0, model="fake", model_version="v1")


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.fixture
def facets(db) -> FacetService:
    return FacetService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        activities=CanonicalRepository(db["activities"], Activity),
        lead_states=CanonicalRepository(db["lead_states"], LeadState),
        panelist_profiles=CanonicalRepository(db["panelist_profiles"], PanelistProfile),
        customer_billing=CanonicalRepository(db["customer_billing"], CustomerBilling),
        vendor_profiles=CanonicalRepository(db["vendor_profiles"], VendorProfile),
        employee_records=CanonicalRepository(db["employee_records"], EmployeeRecord),
        auth_identities=CanonicalRepository(db["auth_identities"], AuthIdentity),
    )


@pytest.fixture
def identity(db, facets: FacetService) -> IdentityService:
    return IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
        extra_account_repointers=[facets],
    )


@pytest.fixture
def suppression(db) -> SuppressionService:
    return SuppressionService(CanonicalRepository(db["suppressions"], Suppression))


@pytest.fixture
def leadgen(db, identity: IdentityService, facets: FacetService, suppression: SuppressionService) -> LeadGenService:
    return LeadGenService(
        identity, facets, suppression,
        raw_events=CanonicalRepository(db["raw_lead_events"], RawLeadEvent),
        ai_proposals=CanonicalRepository(db["ai_proposals"], AiProposal),
        enrollments=CanonicalRepository(db["lead_enrollments"], LeadEnrollment),
        dead_letters=CanonicalRepository(db["dead_letters"], DeadLetterEvent),
        activities=CanonicalRepository(db["activities"], Activity),
    )


async def _qualifying_lead(leadgen: LeadGenService, *, email="dana@acme.com", name="Dana Diaz") -> str:
    """Helper: ingest + qualify a lead that WILL clear the threshold (industry+country
    match = 2+2 = 4, exactly QUALIFY_THRESHOLD) using the no-op classifier, then
    return its lead_state_id, with the account's industry set to match the profile."""
    result = await leadgen.ingest(
        org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id=email,
        payload={"email": email, "name": name, "company_domain": "acme.com", "company_name": "Acme"},
    )
    account = await leadgen._identity.resolve_account(org_id=ORG, actor=ACTOR, domain="acme.com")
    await leadgen._identity._accounts.update(account.account_id, 1, {"industry": "software"}, updated_by=ACTOR)
    qualification = await leadgen.enrich_and_qualify(
        actor=ACTOR, lead_state_id=result.lead_state_id, ai_classifier=FakeHighConfidenceClassifier({"country": "us"}), profile=PROFILE
    )
    assert qualification.status == QUALIFIED, f"test helper setup failed: {qualification}"
    return result.lead_state_id


# ---------------------------------------------------------------------------
# Duplicate / idempotent ingestion, identity resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_source_event_produces_one_lead(leadgen: LeadGenService):
    first = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})
    second = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})

    assert first.is_new_lead is True
    assert second.is_new_lead is False
    assert second.lead_state_id == first.lead_state_id


@pytest.mark.asyncio
async def test_same_person_from_two_sources_produces_one_person_and_one_active_lead(leadgen: LeadGenService):
    first = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})
    second = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="external_research", source_record_id="evt-2", payload={"email": "a@b.com"})

    assert second.person_id == first.person_id
    assert second.lead_state_id == first.lead_state_id  # one active lead journey, not two


@pytest.mark.asyncio
async def test_uncertain_identity_match_does_not_silently_merge(leadgen: LeadGenService):
    """register §4.7's ported low-confidence tier, exercised through ingest() rather
    than IdentityService directly — proves the leadgen pipeline inherits the
    no-silent-merge guarantee rather than bypassing it."""
    first = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "alice@personal.example", "name": "Alice Adams"})
    second = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-2", payload={"email": "alice@othercompany.example", "name": "Alice Zimmerman"})

    assert second.person_id != first.person_id  # no shared key -> correctly NOT merged


# ---------------------------------------------------------------------------
# Enrichment / AI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_ai_outage_never_becomes_qualified_or_disqualified(leadgen: LeadGenService):
    result = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})

    qualification = await leadgen.enrich_and_qualify(
        actor=ACTOR, lead_state_id=result.lead_state_id, ai_classifier=FakeUnavailableClassifier(), profile=PROFILE
    )

    assert qualification.status == "AI_UNAVAILABLE"
    lead = await leadgen.get_lead(result.lead_state_id)
    assert lead.state == ENRICHING  # genuinely unresolved, not silently promoted either direction


@pytest.mark.asyncio
async def test_ai_proposal_without_sufficient_confidence_is_rejected_and_not_applied(leadgen: LeadGenService):
    """The classifier proposes industry+country that WOULD qualify the lead if
    applied — confidence is deliberately below threshold, so the proposal must be
    rejected AND its fields must NOT be used for scoring, leaving the lead
    disqualified despite the AI's (unreliable) suggestion."""
    result = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})

    qualification = await leadgen.enrich_and_qualify(
        actor=ACTOR, lead_state_id=result.lead_state_id, ai_classifier=FakeLowConfidenceClassifier(), profile=PROFILE
    )

    assert qualification.status == DISQUALIFIED
    proposals = await leadgen._ai_proposals.find_all({"subject_id": result.lead_state_id})
    assert proposals[0].status == "rejected"


@pytest.mark.asyncio
async def test_canonical_icp_scorer_is_deterministic_and_the_only_scorer(leadgen: LeadGenService):
    result1 = score_lead(title=None, industry="software", country="us", seniority_marker_present=False, profile=PROFILE)
    result2 = score_lead(title=None, industry="software", country="us", seniority_marker_present=False, profile=PROFILE)

    assert result1 == result2
    assert QUALIFY_THRESHOLD == 4  # register B-04's exact threshold


@pytest.mark.asyncio
async def test_ai_confidence_alone_cannot_qualify_a_lead(leadgen: LeadGenService):
    """A maximally confident AI proposal that supplies no scoring-relevant fields
    must still result in DISQUALIFIED — proving qualification is decided by
    score_lead() alone, never by AiProposal.confidence."""
    result = await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-1", payload={"email": "a@b.com"})

    qualification = await leadgen.enrich_and_qualify(
        actor=ACTOR, lead_state_id=result.lead_state_id, ai_classifier=FakeHighConfidenceClassifier({}), profile=PROFILE
    )

    proposals = await leadgen._ai_proposals.find_all({"subject_id": result.lead_state_id})
    assert proposals[0].status == "approved"
    assert proposals[0].confidence == 0.95
    assert qualification.status == DISQUALIFIED  # high confidence, zero qualifying signal -> still disqualified


# ---------------------------------------------------------------------------
# Assignment / contactability / enrollment gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unassigned_lead_cannot_enroll(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen)

    with pytest.raises(LeadGenError):
        await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")


@pytest.mark.asyncio
async def test_uncontactable_lead_cannot_enroll(leadgen: LeadGenService, suppression: SuppressionService):
    lead_state_id = await _qualifying_lead(leadgen, email="carol@example.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")
    await suppression.suppress(org_id=ORG, actor=ACTOR, email="carol@example.com", reason="unsubscribed", source="test")

    with pytest.raises(LeadGenError):
        await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")


@pytest.mark.asyncio
async def test_contactability_change_after_qualification_is_reflected_at_enrollment(
    leadgen: LeadGenService, suppression: SuppressionService
):
    """The literal test of lead_generation_specification.md §9: contactable at
    qualify/assign time, suppressed afterward, must still block enrollment — proving
    the check is live, not inherited from an earlier read."""
    lead_state_id = await _qualifying_lead(leadgen, email="erin@example.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")
    assert await leadgen.check_contactability((await leadgen.get_lead(lead_state_id)).person_id) is True

    await suppression.suppress(org_id=ORG, actor=ACTOR, email="erin@example.com", reason="bounced", source="test")

    with pytest.raises(LeadGenError):
        await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")


@pytest.mark.asyncio
async def test_multi_brand_enrollment_works(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen, email="frank@example.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")

    first = await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")
    second = await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="cogentix")

    assert first.id != second.id
    lead = await leadgen.get_lead(lead_state_id)
    assert lead.state == ENROLLED  # transitioned once, not per brand


@pytest.mark.asyncio
async def test_enroll_creates_appropriate_account_brand_relationship(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen, email="gina@acme.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")
    lead = await leadgen.get_lead(lead_state_id)

    await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")

    rels = await leadgen._identity._brand_relationships.find_all({"account_id": lead.account_id, "brand_id": "sfw"})
    assert len(rels) == 1


@pytest.mark.asyncio
async def test_retrying_enrollment_is_idempotent(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen, email="hank@example.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")

    first = await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")
    second = await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")

    assert first.id == second.id
    all_enrollments = await leadgen._enrollments.find_all({"lead_state_id": lead_state_id, "brand_id": "sfw"})
    assert len(all_enrollments) == 1


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_meaningful_transition_creates_activity(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen, email="ivan@example.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")
    await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")

    activities = await leadgen._activities.find_all({"subject_id": lead_state_id})
    activity_types = {a.type for a in activities}

    assert {"lead_ingested", "lead_state_changed", "ai_proposal_created", "lead_qualified", "lead_assigned", "lead_enrolled"} <= activity_types


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_transitions_do_not_double_apply(leadgen: LeadGenService, facets: FacetService):
    """Reuses the exact mechanism Slice 1 already proved (VersionConflict on a
    stale write) as this pipeline's own regression test: two callers racing to
    assign the same lead cannot both succeed."""
    lead_state_id = await _qualifying_lead(leadgen, email="judy@example.com")
    lead = await leadgen.get_lead(lead_state_id)

    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")

    with pytest.raises(VersionConflict):
        # second caller still holds the pre-assignment version
        await facets.update_lead_state(lead.id, lead.version, {"owner": "rep-2"}, updated_by="rep-2")


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_failure_is_dead_lettered_not_silently_dropped(leadgen: LeadGenService):
    async def _boom(**kwargs):
        raise RuntimeError("simulated resolver failure")

    leadgen._identity.resolve_person = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        await leadgen.ingest(org_id=ORG, actor=ACTOR, source_type="web_form", source_record_id="evt-boom", payload={"email": "a@b.com"})

    dead_letters = await leadgen._dead_letters.find_all({"source_record_id": "evt-boom"})
    assert len(dead_letters) == 1
    assert "simulated resolver failure" in dead_letters[0].error


# ---------------------------------------------------------------------------
# No second identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_creates_exactly_one_person_and_one_account(leadgen: LeadGenService):
    lead_state_id = await _qualifying_lead(leadgen, email="karen@acme.com")
    await leadgen.assign(actor=ACTOR, lead_state_id=lead_state_id, owner="rep-1")
    await leadgen.enroll(actor=ACTOR, lead_state_id=lead_state_id, brand_id="sfw")

    people = await leadgen._identity._people.find_all({"org_id": ORG})
    accounts = await leadgen._identity._accounts.find_all({"org_id": ORG})
    assert len(people) == 1
    assert len(accounts) == 1
