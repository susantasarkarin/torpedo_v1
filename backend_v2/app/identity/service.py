"""
IdentityService — resolution, creation, and merge for Person and Account.

The three rules this module exists to enforce, each traceable to a specific v1
failure:

1. **Resolution priority is fixed and confidence-tiered; low confidence never
   auto-merges** (lead_generation_specification.md §3; register §4.7's hash-index
   priority — LinkedIn 1.0 > email 0.95 > name+domain 0.85 — is the one piece of v1
   dedup logic mature enough to port forward). A candidate match below
   `AUTO_MATCH_THRESHOLD` is returned with `needs_review=True` and is *not* applied —
   the caller decides what to do with a review candidate; this service never merges
   on its own initiative below that threshold.

2. **Merge repoints every known external reference and marks the loser, in one
   service call — never partially.** v1's only merge function (`crm_service.merge_accounts`)
   updated nothing outside the spine database and left every external `crm_account_id`
   dangling (register D-18). This module's merge is the reference implementation for
   what v1's should have been, scoped to the references that exist as of this slice
   (`AccountBrandRelationship`) — extending the repoint list is mandatory, not
   optional, whenever a future slice adds a new collection that references an
   `account_id`.

3. **A merged record can never be silently resurrected as a live match.** v1's
   nightly reconcile re-adopted merged-away accounts as fresh ones because nothing
   checked merge status before treating a match as authoritative (register D-18).
   `_follow_merge_chain()` is the fix: any resolution that lands on a merged record
   redirects to its primary before being returned, so a merge cannot be quietly
   undone by the next resolution that happens to hit the loser's own record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.identity.models import ACTIVE, MERGED, Account, AccountBrandRelationship, Person


class AccountReferenceRepointer(Protocol):
    """
    Anything that holds a reference to an `account_id` and needs to survive a merge
    implements this. `IdentityService` knows nothing about *what* a repointer
    repoints — `FacetService` (app/identity/facet_service.py) is the first
    implementation, covering `CustomerBilling`/`VendorProfile`. This is deliberately
    a protocol, not a hardcoded list of facet repositories inside `IdentityService`:
    the identity layer must not depend on facet models, or every new facet would
    require editing this file — the same I-1 reasoning already applied to merge
    itself (one merge implementation, not one per referencing collection).
    """

    async def repoint_account_references(self, *, old_account_id: str, new_account_id: str, actor: str) -> int:
        """Repoints every reference it owns from old_account_id to new_account_id.
        Returns the count repointed, folded into the merge's Activity payload."""
        ...

AUTO_MATCH_THRESHOLD = 0.90

KNOWN_BRANDS = frozenset({"sfw", "cogentix", "bimwave"})


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_linkedin(url: str) -> str:
    s = url.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


_LEGAL_SUFFIXES = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co"}


def _normalize_name(name: str) -> str:
    """
    Strips punctuation and common legal suffixes ("Acme Inc." / "ACME, Inc" / "Acme
    Corporation" all normalize to "acme"). This is deliberately the *review-tier*
    match key, never the auto-match key — entity_map.md §2.2's finding was that v1's
    company matching, when it existed at all, was almost always this exact heuristic
    used as if it were reliable, and it wasn't: over-collapse and under-collapse are
    both live risks at scale. Here it can only ever produce a reviewable candidate.
    """
    s = re.sub(r"[^\w\s]", "", name.strip().lower())
    words = [w for w in s.split() if w not in _LEGAL_SUFFIXES]
    return " ".join(words)


@dataclass(frozen=True)
class PersonResolution:
    person_id: str
    is_new: bool
    matched_rule: str
    confidence: float
    needs_review: bool


@dataclass(frozen=True)
class AccountResolution:
    account_id: str
    is_new: bool
    matched_rule: str
    confidence: float
    needs_review: bool


class IdentityService:
    def __init__(
        self,
        people: CanonicalRepository[Person],
        accounts: CanonicalRepository[Account],
        brand_relationships: CanonicalRepository[AccountBrandRelationship],
        activities: CanonicalRepository[Activity],
        *,
        extra_account_repointers: list[AccountReferenceRepointer] | None = None,
    ):
        self._people = people
        self._accounts = accounts
        self._brand_relationships = brand_relationships
        self._activities = activities
        self._extra_account_repointers = extra_account_repointers or []

    # ------------------------------------------------------------------ people

    async def create_person(self, *, org_id: str, actor: str, **fields) -> Person:
        if fields.get("primary_email"):
            fields["primary_email"] = _normalize_email(fields["primary_email"])
        if fields.get("linkedin_url"):
            fields["linkedin_url"] = _normalize_linkedin(fields["linkedin_url"])
        person = Person(org_id=org_id, created_by=actor, updated_by=actor, **fields)
        saved = await self._people.insert(person)
        await self._record_activity(
            org_id=org_id, type="person_created", subject_id=saved.id, actor=actor, payload={}
        )
        return saved

    async def resolve_person(
        self,
        *,
        org_id: str,
        actor: str,
        linkedin_url: str | None = None,
        email: str | None = None,
        name: str | None = None,
        title: str | None = None,
    ) -> PersonResolution:
        """Priority: LinkedIn (1.0, auto) -> email (0.95, auto) -> name+email-domain
        (0.85, review-only) -> new person. See module docstring, rule 1."""
        if linkedin_url:
            norm = _normalize_linkedin(linkedin_url)
            match = await self._people.find_one({"org_id": org_id, "linkedin_url": norm, "status": ACTIVE})
            if match:
                return await self._finalize_person_match(match, "linkedin", 1.0, needs_review=False, actor=actor)

        if email:
            norm_email = _normalize_email(email)
            match = await self._people.find_one({"org_id": org_id, "primary_email": norm_email, "status": ACTIVE})
            if match:
                return await self._finalize_person_match(match, "email", 0.95, needs_review=False, actor=actor)

        if name and email and "@" in email:
            # Ports v1's "name+company" tier (register §4.7) using email domain as the
            # company proxy, since Person doesn't carry a company field independently.
            # O(n) scan over the org's people — acceptable at this slice's scale, not
            # at production scale; a real implementation needs an indexed normalized
            # name+domain lookup before this tier sees real traffic.
            norm_name = _normalize_name(name)
            candidate_domain = email.strip().lower().split("@")[-1]
            candidates = await self._people.find_all({"org_id": org_id, "status": ACTIVE})
            for candidate in candidates:
                candidate_name = _normalize_name(f"{candidate.given_name or ''} {candidate.family_name or ''}")
                candidate_email_domain = (
                    candidate.primary_email.split("@")[-1] if candidate.primary_email and "@" in candidate.primary_email else None
                )
                if candidate_name and candidate_name == norm_name and candidate_email_domain == candidate_domain:
                    return await self._finalize_person_match(
                        candidate, "name_and_domain", 0.85, needs_review=True, actor=actor
                    )

        given, _, family = (name or "").partition(" ") if name else ("", "", "")
        new_person = await self.create_person(
            org_id=org_id, actor=actor,
            primary_email=email, linkedin_url=linkedin_url, title=title,
            given_name=given or None, family_name=family or None,
        )
        return PersonResolution(person_id=new_person.id, is_new=True, matched_rule="none", confidence=0.0, needs_review=False)

    async def get_person(self, person_id: str) -> Person | None:
        return await self._people.get(person_id)

    async def find_person_by_email(self, *, org_id: str, email: str) -> Person | None:
        """A pure, read-only lookup — unlike `resolve_person()`, never creates
        a new `Person` when nothing matches. For callers (Phase 4's outreach-
        reply detection) that need to know "does this address belong to
        someone we already know," not "resolve or create an identity for
        this address"."""
        return await self._people.find_one({"org_id": org_id, "primary_email": _normalize_email(email), "status": ACTIVE})

    async def _finalize_person_match(
        self, person: Person, rule: str, confidence: float, *, needs_review: bool, actor: str
    ) -> PersonResolution:
        await self._record_activity(
            org_id=person.org_id, type="identity_resolved", subject_id=person.id, actor=actor,
            payload={"matched_rule": rule, "confidence": confidence, "needs_review": needs_review, "entity": "person"},
        )
        return PersonResolution(
            person_id=person.id, is_new=False, matched_rule=rule, confidence=confidence, needs_review=needs_review
        )

    # ----------------------------------------------------------------- accounts

    async def create_account(self, *, org_id: str, actor: str, name: str, **fields) -> Account:
        domain = fields.pop("domain", None)
        account = Account(
            org_id=org_id, created_by=actor, updated_by=actor,
            name=name, name_normalized=_normalize_name(name),
            domain=domain.strip().lower() if domain else None,
            **fields,
        )
        saved = await self._accounts.insert(account)
        await self._record_activity(
            org_id=org_id, type="account_created", subject_id=saved.id, actor=actor, payload={}
        )
        return saved

    async def resolve_account(
        self, *, org_id: str, actor: str, domain: str | None = None, name: str | None = None
    ) -> AccountResolution:
        """Priority: domain (1.0, auto) -> normalized name (0.75, review-only) -> new
        account. Domain is preferred deliberately (entity_map.md §2.2: "domain is the
        safer key where available") — name-only matching can never auto-merge here."""
        if domain:
            norm_domain = domain.strip().lower()
            match = await self._accounts.find_one({"org_id": org_id, "domain": norm_domain})
            if match:
                primary = await self._follow_merge_chain(match)
                return await self._finalize_account_match(primary, "domain", 1.0, needs_review=False, actor=actor)

        if name:
            norm_name = _normalize_name(name)
            match = await self._accounts.find_one({"org_id": org_id, "name_normalized": norm_name})
            if match:
                primary = await self._follow_merge_chain(match)
                return await self._finalize_account_match(primary, "name", 0.75, needs_review=True, actor=actor)

        new_account = await self.create_account(org_id=org_id, actor=actor, name=name or "", domain=domain)
        return AccountResolution(account_id=new_account.id, is_new=True, matched_rule="none", confidence=0.0, needs_review=False)

    async def get_account(self, account_id: str) -> Account | None:
        return await self._accounts.get(account_id)

    async def _finalize_account_match(
        self, account: Account, rule: str, confidence: float, *, needs_review: bool, actor: str
    ) -> AccountResolution:
        await self._record_activity(
            org_id=account.org_id, type="identity_resolved", subject_id=account.id, actor=actor,
            payload={"matched_rule": rule, "confidence": confidence, "needs_review": needs_review, "entity": "account"},
        )
        return AccountResolution(
            account_id=account.id, is_new=False, matched_rule=rule, confidence=confidence, needs_review=needs_review
        )

    async def _follow_merge_chain(self, account: Account) -> Account:
        """See module docstring, rule 3. Bounded by `seen` against a cyclical or
        very long chain — a real chain longer than a couple of hops would itself be
        a data-quality signal worth surfacing, not silently walking forever."""
        seen: set[str] = set()
        current = account
        while current.status == MERGED and current.merged_into and current.id not in seen:
            seen.add(current.id)
            nxt = await self._accounts.get(current.merged_into)
            if nxt is None:
                break
            current = nxt
        return current

    # -------------------------------------------------------------------- merge

    async def merge_accounts(self, *, primary_id: str, duplicate_id: str, actor: str) -> Account:
        if primary_id == duplicate_id:
            raise ValueError("cannot merge an account into itself")

        primary = await self._accounts.get(primary_id)
        duplicate = await self._accounts.get(duplicate_id)
        if primary is None or duplicate is None:
            raise ValueError("both accounts must exist")
        if primary.status == MERGED or duplicate.status == MERGED:
            raise ValueError("cannot merge an already-merged account")

        # Repoint every known external reference BEFORE marking the loser merged, so
        # a crash mid-merge leaves the loser still independently resolvable (and thus
        # still correct, just not yet merged) rather than orphaning its relationships
        # with no account to fall back on. See module docstring, rule 2.
        brand_rels = await self._brand_relationships.find_all({"account_id": duplicate_id})
        for rel in brand_rels:
            await self._brand_relationships.update(
                rel.id, rel.version, {"account_id": primary_id}, updated_by=actor
            )

        extra_repointed = 0
        for repointer in self._extra_account_repointers:
            extra_repointed += await repointer.repoint_account_references(
                old_account_id=duplicate_id, new_account_id=primary_id, actor=actor
            )

        await self._accounts.update(
            duplicate_id, duplicate.version, {"status": MERGED, "merged_into": primary_id}, updated_by=actor
        )
        await self._record_activity(
            org_id=primary.org_id, type="account_merged", subject_id=primary_id, actor=actor,
            payload={
                "merged_from": duplicate_id,
                "brand_relationships_repointed": len(brand_rels),
                "other_references_repointed": extra_repointed,
            },
        )
        return await self._accounts.get(primary_id)

    # ------------------------------------------------------------ brand links

    async def add_brand_relationship(
        self, *, org_id: str, actor: str, account_id: str, brand_id: str, relationship_type: str
    ) -> AccountBrandRelationship:
        if brand_id not in KNOWN_BRANDS:
            raise ValueError(f"unknown brand_id: {brand_id!r}")
        rel = AccountBrandRelationship(
            org_id=org_id, created_by=actor, updated_by=actor,
            account_id=account_id, brand_id=brand_id, relationship_type=relationship_type,
        )
        return await self._brand_relationships.insert(rel)

    async def ensure_brand_relationship(
        self, *, org_id: str, actor: str, account_id: str, brand_id: str, relationship_type: str
    ) -> AccountBrandRelationship:
        """Find-or-create, idempotent — the leadgen enrollment flow needs "this
        account has *a* relationship with this brand," not "create a duplicate one
        every time a lead re-enrolls." Locked principle 5 still applies: this never
        touches or replaces any *other* brand relationship the account holds."""
        existing = await self._brand_relationships.find_one({"account_id": account_id, "brand_id": brand_id})
        if existing:
            return existing
        return await self.add_brand_relationship(
            org_id=org_id, actor=actor, account_id=account_id, brand_id=brand_id, relationship_type=relationship_type
        )

    # --------------------------------------------------------------- activity

    async def _record_activity(self, *, org_id: str, type: str, subject_id: str, actor: str, payload: dict) -> None:
        activity = Activity(
            org_id=org_id, created_by=actor, updated_by=actor,
            type=type, subject_type="identity", subject_id=subject_id,
            actor_type="system" if actor == "system" else "user", actor_id=actor,
            payload=payload,
        )
        await self._activities.insert(activity)
