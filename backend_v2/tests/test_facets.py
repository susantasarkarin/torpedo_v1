"""
Slice 5 — canonical facets & relationships. Organized by the same five categories the
slice was scoped against (Identity / Organisation / Brand / Lifecycle / Merge), so a
missing category is visible as a missing section, not just a missing test.
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.identity.facet_service import FacetAttachmentError, FacetService
from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.models.activity import Activity
from app.models.base import CanonicalRepository

ORG_A = "org-A"
ORG_B = "org-B"
ACTOR = "system"


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


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_can_have_multiple_facets_simultaneously(identity: IdentityService, facets: FacetService):
    """The exact scenario named: the same person is a lead, a panelist, and an
    employee at once — v1 could only express this as three separate people."""
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")

    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="web_form")
    panelist = await facets.attach_panelist_profile(actor=ACTOR, person_id=person.id, country="IN")
    employee = await facets.attach_employee_record(actor=ACTOR, person_id=person.id, department="Sales")

    assert lead.person_id == panelist.person_id == employee.person_id == person.id


@pytest.mark.asyncio
async def test_attaching_a_facet_never_creates_another_person(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")

    await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="web_form")
    await facets.attach_panelist_profile(actor=ACTOR, person_id=person.id)
    await facets.attach_employee_record(actor=ACTOR, person_id=person.id)

    all_people = await identity._people.find_all({"org_id": ORG_A})
    assert len(all_people) == 1


@pytest.mark.asyncio
async def test_removing_a_facet_does_not_delete_the_person(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")
    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="web_form")

    await facets._lead_states.soft_delete(lead.id, lead.version, deleted_by=ACTOR)

    still_there = await identity._people.get(person.id)
    assert still_there is not None
    assert still_there.status == "active"


# ---------------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facet_inherits_org_id_from_parent_never_from_caller(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")

    lead = await facets.attach_lead_state(actor=ACTOR, person_id=person.id, source_type="web_form")

    assert lead.org_id == ORG_A  # derived from the person, not passed as a parameter — there is none


@pytest.mark.asyncio
async def test_cross_org_facet_attachment_is_rejected(identity: IdentityService, facets: FacetService):
    person_a = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")
    account_b = await identity.create_account(org_id=ORG_B, actor=ACTOR, name="Acme B")

    with pytest.raises(FacetAttachmentError):
        await facets.attach_lead_state(actor=ACTOR, person_id=person_a.id, source_type="web_form", account_id=account_b.id)


@pytest.mark.asyncio
async def test_attaching_to_nonexistent_parent_is_rejected(facets: FacetService):
    with pytest.raises(FacetAttachmentError):
        await facets.attach_panelist_profile(actor=ACTOR, person_id="does-not-exist")


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_participates_in_multiple_brands_independently_of_its_facets(
    identity: IdentityService, facets: FacetService
):
    account = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")
    await identity.add_brand_relationship(org_id=ORG_A, actor=ACTOR, account_id=account.id, brand_id="sfw", relationship_type="client")
    await identity.add_brand_relationship(org_id=ORG_A, actor=ACTOR, account_id=account.id, brand_id="cogentix", relationship_type="prospect")

    await facets.attach_customer_billing(actor=ACTOR, account_id=account.id)
    await facets.attach_vendor_profile(actor=ACTOR, account_id=account.id)

    brand_rels = await identity._brand_relationships.find_all({"account_id": account.id})
    assert {r.brand_id for r in brand_rels} == {"sfw", "cogentix"}  # unaffected by facet attachment


def test_no_scalar_brand_field_exists_on_any_facet():
    """Structural guard against the exact regression that produced the 41,746-
    enrollment incident (register §4.5): brand must never sneak back in as a field
    directly on a facet instead of a relationship."""
    for model in (LeadState, PanelistProfile, CustomerBilling, VendorProfile, EmployeeRecord, AuthIdentity):
        field_names = set(model.model_fields.keys())
        assert "brand" not in field_names
        assert "brand_id" not in field_names


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_lead_state_has_no_stored_contactability_field():
    """lead_generation_specification.md §7's corrected diagram: CONTACTABLE is a
    live-evaluated gate, never a persisted state. Guards against the exact
    self-contradiction the Phase 0 reconciliation pass found and fixed in the spec
    from recurring in the actual model."""
    field_names = set(LeadState.model_fields.keys())
    assert "contactable" not in field_names
    assert "is_contactable" not in field_names


@pytest.mark.asyncio
async def test_panelist_status_is_independent_of_person_status(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")
    panelist = await facets.attach_panelist_profile(actor=ACTOR, person_id=person.id)

    await facets._panelist_profiles.update(panelist.id, panelist.version, {"status": "suspended"}, updated_by=ACTOR)

    unaffected_person = await identity._people.get(person.id)
    assert unaffected_person.status == "active"


@pytest.mark.asyncio
async def test_vendor_profile_attachment_does_not_create_a_second_account(identity: IdentityService, facets: FacetService):
    account = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")

    await facets.attach_vendor_profile(actor=ACTOR, account_id=account.id)

    all_accounts = await identity._accounts.find_all({"org_id": ORG_A})
    assert len(all_accounts) == 1


@pytest.mark.asyncio
async def test_vendor_profile_requires_exactly_one_parent(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="carol@example.com")
    account = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")

    with pytest.raises(FacetAttachmentError):
        await facets.attach_vendor_profile(actor=ACTOR)  # neither
    with pytest.raises(FacetAttachmentError):
        await facets.attach_vendor_profile(actor=ACTOR, person_id=person.id, account_id=account.id)  # both


@pytest.mark.asyncio
async def test_auth_identity_links_person_to_existing_login_identity(identity: IdentityService, facets: FacetService):
    person = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="alice@example.com")

    link = await facets.link_auth_identity(actor=ACTOR, person_id=person.id, username="alice")

    assert link.person_id == person.id
    assert link.username == "alice"


@pytest.mark.asyncio
async def test_username_cannot_be_linked_to_two_people(identity: IdentityService, facets: FacetService):
    person1 = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="alice@example.com")
    person2 = await identity.create_person(org_id=ORG_A, actor=ACTOR, primary_email="alice2@example.com")
    await facets.link_auth_identity(actor=ACTOR, person_id=person1.id, username="alice")

    with pytest.raises(FacetAttachmentError):
        await facets.link_auth_identity(actor=ACTOR, person_id=person2.id, username="alice")


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_merge_repoints_facet_references_too(identity: IdentityService, facets: FacetService):
    """Extends Slice 4's brand-relationship repointing test to the facets this
    slice adds — proving the AccountReferenceRepointer protocol actually works
    end-to-end through IdentityService.merge_accounts, not just in isolation."""
    primary = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")
    duplicate = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Duplicate")
    billing = await facets.attach_customer_billing(actor=ACTOR, account_id=duplicate.id)
    vendor = await facets.attach_vendor_profile(actor=ACTOR, account_id=duplicate.id)

    await identity.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor=ACTOR)

    refetched_billing = await facets._customer_billing.get(billing.id)
    refetched_vendor = await facets._vendor_profiles.get(vendor.id)
    assert refetched_billing.account_id == primary.id
    assert refetched_vendor.account_id == primary.id


@pytest.mark.asyncio
async def test_merged_account_cannot_be_resurrected_through_facet_creation(identity: IdentityService, facets: FacetService):
    """The facet-attachment-specific version of D-18: a merged-away account must
    reject a NEW facet attachment too, not just resolution."""
    primary = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")
    duplicate = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Duplicate")
    await identity.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor=ACTOR)

    with pytest.raises(FacetAttachmentError):
        await facets.attach_customer_billing(actor=ACTOR, account_id=duplicate.id)


@pytest.mark.asyncio
async def test_merge_activity_records_repointed_facet_count(identity: IdentityService, facets: FacetService):
    primary = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Inc")
    duplicate = await identity.create_account(org_id=ORG_A, actor=ACTOR, name="Acme Duplicate")
    await facets.attach_customer_billing(actor=ACTOR, account_id=duplicate.id)
    await facets.attach_vendor_profile(actor=ACTOR, account_id=duplicate.id)

    await identity.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor=ACTOR)

    activities = await identity._activities.find_all({"type": "account_merged", "subject_id": primary.id})
    assert activities[0].payload["other_references_repointed"] == 2
