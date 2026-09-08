"""
HTTP surface for Person/Account — the first business-domain routers in v2. Every
route is permission-gated through `app.auth.dependencies.require_permission`, and
every write derives `org_id` from the resolved identity, never from the request body
— the same "authoritative org_id, never caller-selected" rule enforced since Slice 2.

Scope note: create/read/resolve/merge only. `PATCH` and the brand-relationship
sub-resource endpoints (`endpoint_catalogue.md` §1 lists both) are deferred — they
follow the same pattern already proven at the repository layer (`CanonicalRepository.update`,
tested in Slice 1) and don't need a fresh design, so they're not this slice's point.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_identity, require_permission
from app.db import get_database
from app.identity.service import AccountResolution, IdentityService, PersonResolution
from app.identity.models import Account, AccountBrandRelationship, Person
from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.rbac.identity import ResolvedIdentity
from app.rbac.permissions import (
    ACCOUNT_CREATE,
    ACCOUNT_MERGE,
    ACCOUNT_READ,
    ACCOUNT_RESOLVE,
    PERSON_CREATE,
    PERSON_READ,
    PERSON_RESOLVE,
)

router = APIRouter()


def get_identity_service() -> IdentityService:
    db = get_database()
    return IdentityService(
        people=CanonicalRepository(db["people"], Person),
        accounts=CanonicalRepository(db["accounts"], Account),
        brand_relationships=CanonicalRepository(db["account_brand_relationships"], AccountBrandRelationship),
        activities=CanonicalRepository(db["activities"], Activity),
    )


class PersonCreateRequest(BaseModel):
    primary_email: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    title: str | None = None


class PersonResolveRequest(BaseModel):
    linkedin_url: str | None = None
    email: str | None = None
    name: str | None = None


class AccountCreateRequest(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None
    segment: str | None = None
    parent_account_id: str | None = None


class AccountResolveRequest(BaseModel):
    domain: str | None = None
    name: str | None = None


class AccountMergeRequest(BaseModel):
    primary_id: str
    duplicate_id: str


@router.post("/people", response_model=Person)
async def create_person(
    body: PersonCreateRequest,
    identity: ResolvedIdentity = Depends(require_permission(PERSON_CREATE)),
    svc: IdentityService = Depends(get_identity_service),
) -> Person:
    return await svc.create_person(org_id=identity.org_id, actor=identity.user_id, **body.model_dump())


@router.get("/people/{person_id}", response_model=Person)
async def get_person(
    person_id: str,
    identity: ResolvedIdentity = Depends(require_permission(PERSON_READ)),
    svc: IdentityService = Depends(get_identity_service),
) -> Person:
    person = await svc.get_person(person_id)
    if person is None or person.org_id != identity.org_id:
        # 404, not 403: confirming a record exists in an org the caller can't see is
        # itself a disclosure. Same reasoning as the auth boundary's uniform
        # "invalid credentials" message (app/auth/service.py) — don't hand an
        # attacker a different response shape for "wrong org" vs. "doesn't exist."
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    return person


@router.post("/people/resolve", response_model=PersonResolution)
async def resolve_person(
    body: PersonResolveRequest,
    identity: ResolvedIdentity = Depends(require_permission(PERSON_RESOLVE)),
    svc: IdentityService = Depends(get_identity_service),
) -> PersonResolution:
    return await svc.resolve_person(org_id=identity.org_id, actor=identity.user_id, **body.model_dump())


@router.post("/accounts", response_model=Account)
async def create_account(
    body: AccountCreateRequest,
    identity: ResolvedIdentity = Depends(require_permission(ACCOUNT_CREATE)),
    svc: IdentityService = Depends(get_identity_service),
) -> Account:
    return await svc.create_account(org_id=identity.org_id, actor=identity.user_id, **body.model_dump())


@router.get("/accounts/{account_id}", response_model=Account)
async def get_account(
    account_id: str,
    identity: ResolvedIdentity = Depends(require_permission(ACCOUNT_READ)),
    svc: IdentityService = Depends(get_identity_service),
) -> Account:
    account = await svc.get_account(account_id)
    if account is None or account.org_id != identity.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    return account


@router.post("/accounts/resolve", response_model=AccountResolution)
async def resolve_account(
    body: AccountResolveRequest,
    identity: ResolvedIdentity = Depends(require_permission(ACCOUNT_RESOLVE)),
    svc: IdentityService = Depends(get_identity_service),
) -> AccountResolution:
    return await svc.resolve_account(org_id=identity.org_id, actor=identity.user_id, **body.model_dump())


@router.post("/accounts/merge", response_model=Account)
async def merge_accounts(
    body: AccountMergeRequest,
    identity: ResolvedIdentity = Depends(require_permission(ACCOUNT_MERGE)),
    svc: IdentityService = Depends(get_identity_service),
) -> Account:
    # endpoint_catalogue.md §1 marks this [APPROVAL-GATED]. Deferred here, explicitly:
    # RBACService.can_approve() requires a Money amount and an entity_type ceiling,
    # neither of which has a natural meaning for "merge two accounts" — wiring merge
    # into the approval-authority system needs its own (non-monetary) ceiling concept
    # designed, not a fake amount bolted on to reuse the existing check. Permission-gated
    # only for this slice; approval-gating is tracked as follow-up, not silently dropped.
    try:
        return await svc.merge_accounts(
            org_id=identity.org_id, primary_id=body.primary_id, duplicate_id=body.duplicate_id, actor=identity.user_id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
