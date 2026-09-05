"""
FacetService — the only thing that constructs a facet, and the enforcement point for
"a facet can never create an independent identity."

Every attach_* method validates its parent (`Person` and/or `Account`) exists and is
not itself a merged-away record before creating anything — a facet attached to a
merged record would be exactly the kind of silent resurrection register D-18 already
named as v1's failure (identity_service.py's `_follow_merge_chain` fixes it for
resolution; the same check here fixes it for attachment, which is a different code
path that needed its own guard, not an inherited one).

`org_id` on every facet is taken from the parent record, never accepted as a
caller-supplied parameter — the same "authoritative, never client-selected" rule
already enforced for identity resolution and for every permission check since Slice 2.
"""

from __future__ import annotations

from app.identity.facets import AuthIdentity, CustomerBilling, EmployeeRecord, LeadState, PanelistProfile, VendorProfile
from app.identity.models import MERGED, Account, Person
from app.models.activity import Activity
from app.models.base import CanonicalRepository


class FacetAttachmentError(Exception):
    """Parent missing, parent in the wrong org, parent merged-away, or a
    mutual-exclusivity rule violated (e.g. VendorProfile with both or neither
    reference set)."""


class FacetService:
    def __init__(
        self,
        people: CanonicalRepository[Person],
        accounts: CanonicalRepository[Account],
        activities: CanonicalRepository[Activity],
        *,
        lead_states: CanonicalRepository[LeadState],
        panelist_profiles: CanonicalRepository[PanelistProfile],
        customer_billing: CanonicalRepository[CustomerBilling],
        vendor_profiles: CanonicalRepository[VendorProfile],
        employee_records: CanonicalRepository[EmployeeRecord],
        auth_identities: CanonicalRepository[AuthIdentity],
    ):
        self._people = people
        self._accounts = accounts
        self._activities = activities
        self._lead_states = lead_states
        self._panelist_profiles = panelist_profiles
        self._customer_billing = customer_billing
        self._vendor_profiles = vendor_profiles
        self._employee_records = employee_records
        self._auth_identities = auth_identities

    # ------------------------------------------------------------- parent guards

    async def _require_person(self, person_id: str) -> Person:
        person = await self._people.get(person_id)
        if person is None:
            raise FacetAttachmentError(f"person {person_id} does not exist")
        if person.status == MERGED:
            raise FacetAttachmentError(
                f"person {person_id} has been merged into {person.merged_into} — attach to the primary instead"
            )
        return person

    async def _require_account(self, account_id: str) -> Account:
        account = await self._accounts.get(account_id)
        if account is None:
            raise FacetAttachmentError(f"account {account_id} does not exist")
        if account.status == MERGED:
            raise FacetAttachmentError(
                f"account {account_id} has been merged into {account.merged_into} — attach to the primary instead"
            )
        return account

    # --------------------------------------------------------------------- lead

    async def attach_lead_state(
        self, *, actor: str, person_id: str, source_type: str, account_id: str | None = None
    ) -> LeadState:
        person = await self._require_person(person_id)
        if account_id:
            account = await self._require_account(account_id)
            if account.org_id != person.org_id:
                raise FacetAttachmentError("person and account belong to different orgs")

        facet = LeadState(
            org_id=person.org_id, created_by=actor, updated_by=actor,
            person_id=person_id, account_id=account_id, source_type=source_type,
        )
        saved = await self._lead_states.insert(facet)
        await self._record_attachment(org_id=person.org_id, facet_name="LeadState", facet_id=saved.id, parent_id=person_id, actor=actor)
        return saved

    # ----------------------------------------------------------------- panelist

    async def attach_panelist_profile(self, *, actor: str, person_id: str, **fields) -> PanelistProfile:
        person = await self._require_person(person_id)
        facet = PanelistProfile(org_id=person.org_id, created_by=actor, updated_by=actor, person_id=person_id, **fields)
        saved = await self._panelist_profiles.insert(facet)
        await self._record_attachment(org_id=person.org_id, facet_name="PanelistProfile", facet_id=saved.id, parent_id=person_id, actor=actor)
        return saved

    # -------------------------------------------------------------- billing

    async def attach_customer_billing(self, *, actor: str, account_id: str, **fields) -> CustomerBilling:
        account = await self._require_account(account_id)
        facet = CustomerBilling(org_id=account.org_id, created_by=actor, updated_by=actor, account_id=account_id, **fields)
        saved = await self._customer_billing.insert(facet)
        await self._record_attachment(org_id=account.org_id, facet_name="CustomerBilling", facet_id=saved.id, parent_id=account_id, actor=actor)
        return saved

    # --------------------------------------------------------------- vendor

    async def attach_vendor_profile(
        self, *, actor: str, person_id: str | None = None, account_id: str | None = None
    ) -> VendorProfile:
        if bool(person_id) == bool(account_id):  # both set, or neither set
            raise FacetAttachmentError("vendor profile requires exactly one of person_id or account_id")

        if person_id:
            parent = await self._require_person(person_id)
        else:
            parent = await self._require_account(account_id)

        facet = VendorProfile(
            org_id=parent.org_id, created_by=actor, updated_by=actor, person_id=person_id, account_id=account_id
        )
        saved = await self._vendor_profiles.insert(facet)
        await self._record_attachment(
            org_id=parent.org_id, facet_name="VendorProfile", facet_id=saved.id,
            parent_id=person_id or account_id, actor=actor,
        )
        return saved

    # ------------------------------------------------------------- employee

    async def attach_employee_record(self, *, actor: str, person_id: str, **fields) -> EmployeeRecord:
        person = await self._require_person(person_id)
        facet = EmployeeRecord(org_id=person.org_id, created_by=actor, updated_by=actor, person_id=person_id, **fields)
        saved = await self._employee_records.insert(facet)
        await self._record_attachment(org_id=person.org_id, facet_name="EmployeeRecord", facet_id=saved.id, parent_id=person_id, actor=actor)
        return saved

    # ---------------------------------------------------------- auth identity

    async def link_auth_identity(self, *, actor: str, person_id: str, username: str) -> AuthIdentity:
        person = await self._require_person(person_id)
        existing = await self._auth_identities.find_one({"username": username})
        if existing:
            raise FacetAttachmentError(f"username {username!r} is already linked to a person")

        facet = AuthIdentity(org_id=person.org_id, created_by=actor, updated_by=actor, person_id=person_id, username=username)
        saved = await self._auth_identities.insert(facet)
        await self._record_attachment(org_id=person.org_id, facet_name="AuthIdentity", facet_id=saved.id, parent_id=person_id, actor=actor)
        return saved

    # ------------------------------------------------ LeadState query surface

    # Generic, deliberately: FacetService knows nothing about the qualification
    # state machine (DISCOVERED/QUALIFIED/etc. are app.leadgen concepts) — that
    # knowledge stays in LeadGenService, which builds the query. Keeps the
    # dependency direction the same as AccountReferenceRepointer above: leadgen
    # depends on identity/facets, never the reverse.

    async def find_lead_state(self, query: dict) -> LeadState | None:
        return await self._lead_states.find_one(query)

    async def get_lead_state(self, lead_state_id: str) -> LeadState | None:
        return await self._lead_states.get(lead_state_id)

    async def update_lead_state(self, lead_state_id: str, expected_version: int, changes: dict, *, updated_by: str) -> LeadState:
        return await self._lead_states.update(lead_state_id, expected_version, changes, updated_by=updated_by)

    # --------------------------------------------------- merge integration

    async def repoint_account_references(self, *, old_account_id: str, new_account_id: str, actor: str) -> int:
        """Satisfies `IdentityService.AccountReferenceRepointer` — see that module's
        docstring for why this is a protocol implementation rather than a hardcoded
        list of facet repositories inside the identity layer."""
        count = 0
        for repo in (self._customer_billing, self._vendor_profiles):
            rows = await repo.find_all({"account_id": old_account_id})
            for row in rows:
                await repo.update(row.id, row.version, {"account_id": new_account_id}, updated_by=actor)
                count += 1
        return count

    # ---------------------------------------------------------------- activity

    async def _record_attachment(self, *, org_id: str, facet_name: str, facet_id: str, parent_id: str, actor: str) -> None:
        activity = Activity(
            org_id=org_id, created_by=actor, updated_by=actor,
            type="facet_attached", subject_type="identity", subject_id=parent_id,
            actor_type="system" if actor == "system" else "user", actor_id=actor,
            payload={"facet": facet_name, "facet_id": facet_id},
        )
        await self._activities.insert(activity)
