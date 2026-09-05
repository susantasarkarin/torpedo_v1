"""
Person, Account, and AccountBrandRelationship — the canonical identity layer
(v2_locked_principles.md §1, §3, §5). Everything else — lead state, panelist profile,
customer billing, vendor profile, employee record — becomes a facet attached to one
of these, never a copy (locked principle 4). No facet is built in this slice; this is
the foundation they attach to.
"""

from __future__ import annotations

from app.models.base import CanonicalDocument

# "active" is the only status a caller may set directly. "merged" is set exclusively
# by IdentityService.merge_accounts()/merge_people() — never accept it from a request
# body, or a client could forge a merge without going through the repointing logic
# that keeps external references (and the merge-chain redirect) correct.
ACTIVE = "active"
MERGED = "merged"


class Person(CanonicalDocument):
    primary_email: str | None = None  # normalized: lowercased, trimmed
    given_name: str | None = None
    family_name: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None  # normalized: protocol/www/query stripped
    title: str | None = None

    status: str = ACTIVE
    merged_into: str | None = None


class Account(CanonicalDocument):
    name: str
    name_normalized: str  # derived at write time — never trust a client-supplied value
    domain: str | None = None  # normalized: lowercased
    industry: str | None = None
    segment: str | None = None
    parent_account_id: str | None = None

    status: str = ACTIVE
    merged_into: str | None = None


class AccountBrandRelationship(CanonicalDocument):
    """
    No v1 precedent (entity_map.md §2.3, register D-19) — v1 modeled brand as a
    single recomputed field on the lead, which is exactly what produced the
    41,746-enrollment incident. An account may hold any number of concurrent
    relationships; there is deliberately no "one brand per account" constraint
    anywhere in this model or in IdentityService.
    """

    account_id: str
    brand_id: str  # closed set for now: "sfw" | "cogentix" | "bimwave" — see service.py
    relationship_type: str  # "prospect" | "client" | "vendor" | "churned"
    status: str = "active"  # "active" | "paused" | "ended"
    owner: str | None = None
