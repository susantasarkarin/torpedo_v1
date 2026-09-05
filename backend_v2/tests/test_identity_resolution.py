"""
Each test is named after the v1 identity failure it demonstrates is now handled
correctly — the same discipline as test_rbac.py and test_auth_service.py. Several
tests are deliberately honest about what automatic resolution *cannot* do (e.g. two
emails with no shared key don't magically become one person) — that's not a gap in
this slice, it's the correct boundary of what's resolvable without more data, and
pretending otherwise is exactly how v1 got duplicate-vs-merged wrong in both directions
(entity_map.md §2.2).
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.identity.models import Account, AccountBrandRelationship, Person
from app.identity.service import IdentityService
from app.models.activity import Activity
from app.models.base import CanonicalRepository

ORG = "org-A"
ACTOR = "system"


@pytest.fixture
def svc() -> IdentityService:
    db = AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]
    return IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )


# ---------------------------------------------------------------------------
# Person resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_email_ingested_twice_resolves_to_the_same_person(svc: IdentityService):
    first = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="Alice@Example.com", name="Alice Adams")
    second = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="alice@example.com", name="Alice Adams")

    assert first.is_new is True
    assert second.is_new is False
    assert second.person_id == first.person_id
    assert second.matched_rule == "email"
    assert second.confidence == 0.95


@pytest.mark.asyncio
async def test_person_with_no_shared_key_across_two_emails_is_not_silently_merged(svc: IdentityService):
    """The honest boundary case: the same real human using two unrelated email
    addresses, with no LinkedIn and no matching name+domain signal, cannot be
    unified automatically — and must NOT be silently merged on a guess. Two Person
    records is the correct outcome here, not a bug."""
    first = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="alice@personal.example", name="Alice Adams")
    second = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="alice@othercompany.example", name="Alice Zimmerman")

    assert first.person_id != second.person_id
    assert second.is_new is True


@pytest.mark.asyncio
async def test_linkedin_and_email_both_resolve_to_the_same_person_when_email_already_known(svc: IdentityService):
    first = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="alice@example.com", name="Alice Adams")

    # A second event carries a LinkedIn URL never seen before, but the SAME email —
    # resolution must find the existing person via the email tier.
    second = await svc.resolve_person(
        org_id=ORG, actor=ACTOR, email="alice@example.com", linkedin_url="https://www.linkedin.com/in/alice-adams/"
    )

    assert second.person_id == first.person_id
    assert second.matched_rule == "email"


@pytest.mark.asyncio
async def test_low_confidence_name_and_domain_match_routes_to_review_not_auto_merge(svc: IdentityService):
    """register §4.7's ported hash-index tier (name+company, confidence 0.85) —
    below AUTO_MATCH_THRESHOLD, so it must surface as a review candidate, not be
    applied. The two calls must NOT return the same person_id as their primary
    effect — resolve_person's job here is to flag, not to merge."""
    original = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="a.adams@acme.example", name="Alice Adams")

    candidate = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="a.adams@acme.example", name="Alice Adams")
    # (same email -> this actually hits the 0.95 email tier, not the 0.85 tier, by
    # design: email is checked first. To reach the 0.85 tier we need a DIFFERENT
    # email on the same domain with the same name and no email match.)
    another_email_same_domain = await svc.resolve_person(
        org_id=ORG, actor=ACTOR, email="alice.adams@acme.example", name="Alice Adams"
    )

    assert candidate.matched_rule == "email"  # sanity check on the tier ordering
    assert another_email_same_domain.matched_rule == "name_and_domain"
    assert another_email_same_domain.confidence == 0.85
    assert another_email_same_domain.needs_review is True
    assert another_email_same_domain.person_id == original.person_id  # flagged AS a candidate, not silently ignored


@pytest.mark.asyncio
async def test_person_identity_stable_across_multiple_identifier_lookups(svc: IdentityService):
    """Proxy for 'person simultaneously being lead/contact/panelist/vendor, etc.':
    full facet composition lands in a later slice, but the underlying claim this
    tests now is that asserting the same person's identity from two different
    contexts (an email-only signup, then a LinkedIn-only enrichment hit that also
    knows the email) never forces a second Person record."""
    from_signup = await svc.resolve_person(org_id=ORG, actor=ACTOR, email="carol@example.com", name="Carol Chen")
    from_enrichment = await svc.resolve_person(
        org_id=ORG, actor=ACTOR, email="carol@example.com", linkedin_url="https://linkedin.com/in/carolchen"
    )

    assert from_signup.person_id == from_enrichment.person_id


# ---------------------------------------------------------------------------
# Account resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_match_auto_resolves_account(svc: IdentityService):
    first = await svc.resolve_account(org_id=ORG, actor=ACTOR, domain="Acme.com", name="Acme Inc")
    second = await svc.resolve_account(org_id=ORG, actor=ACTOR, domain="acme.com", name="Something Else Entirely")

    assert first.is_new is True
    assert second.account_id == first.account_id
    assert second.matched_rule == "domain"
    assert second.confidence == 1.0
    assert second.needs_review is False


@pytest.mark.asyncio
async def test_company_name_variation_routes_to_review_not_duplicate_or_auto_merge(svc: IdentityService):
    """entity_map.md §2.2: v1's company matching, where it existed, treated
    normalized-name equality as reliable. Here 'Acme Inc.' vs 'ACME, Inc' must
    surface as a reviewable candidate — never silently create a second account,
    and never silently treat them as definitely the same company either."""
    original = await svc.resolve_account(org_id=ORG, actor=ACTOR, name="Acme Inc.")
    variant = await svc.resolve_account(org_id=ORG, actor=ACTOR, name="ACME, Inc")

    assert variant.account_id == original.account_id  # surfaced as the candidate
    assert variant.matched_rule == "name"
    assert variant.confidence == 0.75
    assert variant.needs_review is True


@pytest.mark.asyncio
async def test_account_hierarchy_parent_child(svc: IdentityService):
    parent = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Global")
    child = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme India", parent_account_id=parent.id)

    fetched_child = await svc._accounts.get(child.id)
    assert fetched_child.parent_account_id == parent.id


# ---------------------------------------------------------------------------
# Brand relationships — no "first brand wins"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_can_have_multiple_concurrent_brand_relationships(svc: IdentityService):
    """locked principle 5 / D-19: the direct opposite of v1's 'first brand wins.'"""
    account = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc")

    rel1 = await svc.add_brand_relationship(
        org_id=ORG, actor=ACTOR, account_id=account.id, brand_id="sfw", relationship_type="client"
    )
    rel2 = await svc.add_brand_relationship(
        org_id=ORG, actor=ACTOR, account_id=account.id, brand_id="cogentix", relationship_type="prospect"
    )

    all_rels = await svc._brand_relationships.find_all({"account_id": account.id})
    assert {r.id for r in all_rels} == {rel1.id, rel2.id}
    assert {r.brand_id for r in all_rels} == {"sfw", "cogentix"}


@pytest.mark.asyncio
async def test_unknown_brand_id_is_rejected(svc: IdentityService):
    account = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc")

    with pytest.raises(ValueError):
        await svc.add_brand_relationship(
            org_id=ORG, actor=ACTOR, account_id=account.id, brand_id="not-a-real-brand", relationship_type="client"
        )


# ---------------------------------------------------------------------------
# Merge — repointing, resurrection prevention, guardrails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_repoints_brand_relationships_to_primary(svc: IdentityService):
    primary = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc")
    duplicate = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Incorporated")
    rel = await svc.add_brand_relationship(
        org_id=ORG, actor=ACTOR, account_id=duplicate.id, brand_id="sfw", relationship_type="client"
    )

    await svc.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor=ACTOR)

    refetched_rel = await svc._brand_relationships.get(rel.id)
    assert refetched_rel.account_id == primary.id


@pytest.mark.asyncio
async def test_post_merge_loser_cannot_be_resurrected_by_resolution(svc: IdentityService):
    """The direct fix for register D-18: v1's nightly reconcile re-adopted
    merged-away accounts as fresh ones because nothing checked merge status. Here,
    resolving against the LOSER's own domain must redirect to the primary, not
    return the loser as a live match."""
    primary = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc", domain="acme.com")
    duplicate = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Duplicate", domain="acme-dup.example")
    await svc.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor=ACTOR)

    resolution = await svc.resolve_account(org_id=ORG, actor=ACTOR, domain="acme-dup.example")

    assert resolution.account_id == primary.id
    assert resolution.is_new is False


@pytest.mark.asyncio
async def test_cannot_merge_an_account_into_itself(svc: IdentityService):
    account = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc")

    with pytest.raises(ValueError):
        await svc.merge_accounts(primary_id=account.id, duplicate_id=account.id, actor=ACTOR)


@pytest.mark.asyncio
async def test_cannot_merge_an_already_merged_account(svc: IdentityService):
    a = await svc.create_account(org_id=ORG, actor=ACTOR, name="A")
    b = await svc.create_account(org_id=ORG, actor=ACTOR, name="B")
    c = await svc.create_account(org_id=ORG, actor=ACTOR, name="C")
    await svc.merge_accounts(primary_id=a.id, duplicate_id=b.id, actor=ACTOR)

    with pytest.raises(ValueError):
        await svc.merge_accounts(primary_id=c.id, duplicate_id=b.id, actor=ACTOR)


@pytest.mark.asyncio
async def test_merge_records_an_activity(svc: IdentityService):
    primary = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Inc")
    duplicate = await svc.create_account(org_id=ORG, actor=ACTOR, name="Acme Duplicate")

    await svc.merge_accounts(primary_id=primary.id, duplicate_id=duplicate.id, actor="admin-bob")

    activities = await svc._activities.find_all({"type": "account_merged", "subject_id": primary.id})
    assert len(activities) == 1
    assert activities[0].actor_id == "admin-bob"
    assert activities[0].payload["merged_from"] == duplicate.id
