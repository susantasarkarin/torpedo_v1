"""
PERSON REPOSITORY
=================

The only module permitted to write `persons`. Everything else asks it to
resolve a human and gets back a person_id.

WHY THIS EXISTS
---------------
canonical_ingestion says "NO EXCEPTIONS. NO BYPASSES." in a comment. A comment
is not an invariant. This module makes it structural: `persons` is written
here or not at all, and test_person_repo_is_the_only_writer greps for direct
writes elsewhere.

THE RACE THIS CLOSES
--------------------
ingest_lead resolved duplicates with find_one() followed by insert_one(), with
no unique constraint underneath. The scheduler fans ICPs out under one
asyncio.gather, so N tasks can all miss the find_one and all insert.

That is not hypothetical. leads_enriched holds three rows for one human:

    linkedin.com/in/ericdohertygloballeader/es
    linkedin.com/in/ericdohertygloballeader/de
    linkedin.com/in/ericdohertygloballeader/fi

ObjectIds 6952c7c1...cdce / ...cddc / ...cddd — same timestamp second,
consecutive counters. Three parallel ICP tasks, one human, three rows.

Two defects stacked: the locale suffixes were not normalized (fixed in
deduplication.normalize_linkedin_url), AND nothing serialized the writers.
Fixing normalization alone would have converted three rows into a race for
one row, which fails differently rather than correctly.

The fix is a single atomic upsert keyed on a UNIQUE fingerprint. Losers of the
race resolve to the winner's document instead of creating a second one or
silently dropping their data. `ON CONFLICT DO NOTHING` would be wrong here —
it discards the losing writer's fields.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure

from .canonical_ingestion import identity_email, identity_linkedin_url

logger = logging.getLogger(__name__)

PERSONS = "persons"


# ---------------------------------------------------------------------------
# Fingerprint — must match migrations/003_person_identity.fingerprint exactly
# ---------------------------------------------------------------------------

def fingerprint(email: Optional[str], linkedin_url: Optional[str]) -> Optional[str]:
    """
    Global identity key. LinkedIn URL beats email: people change employer —
    and therefore address — more often than they change profile. Confirmed in
    the data (matthieu.chassot@celonis.com -> @chainalysis.com, one human).

    Returns None when a row carries neither identifier. Callers must treat
    that as unresolvable rather than inventing an identity.
    """
    ident_url = identity_linkedin_url(linkedin_url or "")
    if ident_url:
        return hashlib.sha256(f"li:{ident_url}".encode()).hexdigest()
    ident_email = identity_email(email or "")
    if ident_email:
        return hashlib.sha256(f"em:{ident_email}".encode()).hexdigest()
    return None


def ensure_indexes(db) -> None:
    """
    Global uniqueness on persons. ASSERTS — does not warn.

    48 create_index calls in this repo swallow their failure into a
    logger.warning. leads_raw.email is supposed to be unique because of one of
    them and is not, live, which is how three rows for one human survived. The
    atomic upsert below is only atomic because of the fingerprint index; if it
    is missing, resolve_person degrades silently back into the race it exists
    to close. So this raises.
    """
    try:
        db[PERSONS].create_index([("fingerprint", ASCENDING)], unique=True)
        db[PERSONS].create_index(
            [("email_identity", ASCENDING)], unique=True,
            partialFilterExpression={"email_identity": {"$type": "string"}})
        db[PERSONS].create_index(
            [("linkedin_identity", ASCENDING)], unique=True,
            partialFilterExpression={"linkedin_identity": {"$type": "string"}})
    except OperationFailure as exc:
        # Mongo refuses to redefine an existing index name with different
        # options (IndexKeySpecsConflict), so a pre-existing NON-unique
        # fingerprint_1 surfaces here rather than at the check below. Both
        # paths must end in RuntimeError — the caller's contract is "this
        # raises if uniqueness is not guaranteed", and which mongo error code
        # revealed it is not the caller's problem.
        raise RuntimeError(
            f"persons index creation failed, uniqueness NOT guaranteed: {exc}. "
            f"An existing non-unique index of the same name is the usual "
            f"cause; drop it and re-run. resolve_person() is only atomic with "
            f"a unique fingerprint index."
        ) from exc

    info = db[PERSONS].index_information()
    if not info.get("fingerprint_1", {}).get("unique"):
        raise RuntimeError(
            "persons.fingerprint is not UNIQUE. resolve_person() cannot be "
            "atomic without it and would silently reopen the duplicate-person "
            "race. Refusing to proceed.")


# ---------------------------------------------------------------------------
# The single door
# ---------------------------------------------------------------------------

def resolve_person(db, lead: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """
    Resolve a lead to exactly one person. Returns (person_id, created).

    Safe under parallel ICP execution: concurrent callers with the same
    fingerprint all converge on one document. The loser of a race resolves to
    the winner rather than creating a second person or dropping its fields.

    Identity fields use $setOnInsert so a later, worse-quality sighting cannot
    overwrite them. Observational fields use $addToSet so nothing is lost —
    in particular known_emails, which keeps stale addresses attached to the
    human so an unsubscribe recorded against an old mailbox keeps suppressing.
    """
    fp = fingerprint(lead.get("email"), lead.get("linkedin_url"))
    if not fp:
        return None, False

    now = datetime.utcnow()
    email = (lead.get("email") or "").lower().strip() or None
    url = lead.get("linkedin_url") or None

    set_on_insert: Dict[str, Any] = {
        "fingerprint": fp,
        "email": email,
        "linkedin_url": url,
        "email_identity": identity_email(email or ""),
        "linkedin_identity": identity_linkedin_url(url or ""),
        "full_name": lead.get("name"),
        "company": lead.get("company"),
        "title": lead.get("title"),
        "location": lead.get("location"),
        "created_at": now,
    }
    set_on_insert = {k: v for k, v in set_on_insert.items() if v is not None}

    # known_emails: DEAD FOR SENDING, LIVE FOR SUPPRESSION.
    #
    # Every address this human has ever been known by, including ones that are
    # now stale (employer change: @celonis -> @chainalysis, one person). Never
    # select a send address from this field — persons.email is the current one.
    # DO read it when checking suppression: an unsubscribe or bounce recorded
    # against a former mailbox must keep suppressing the human, not just that
    # string. The whole class of bug in this workstream is a value being read
    # by a path that should not have it, so the two uses are named apart.
    add_to_set: Dict[str, Any] = {}
    if email:
        add_to_set["known_emails"] = email
        ident = identity_email(email)
        if ident:
            add_to_set["known_email_identities"] = ident

    update: Dict[str, Any] = {
        "$setOnInsert": set_on_insert,
        "$set": {"updated_at": now},
    }
    if add_to_set:
        update["$addToSet"] = add_to_set

    try:
        # update_one rather than find_one_and_update specifically for
        # upserted_id, which is the only authoritative "did I create this?"
        # signal. Comparing a round-tripped created_at against the timestamp
        # we sent does NOT work: mongo stores datetimes at millisecond
        # precision and python's are microsecond, so the value read back is
        # truncated and never compares equal. That bug reported created=False
        # for all 24 racers in the first draft of this function.
        res = db[PERSONS].update_one({"fingerprint": fp}, update, upsert=True)
        if res.upserted_id is not None:
            return str(res.upserted_id), True
        doc = db[PERSONS].find_one({"fingerprint": fp}, {"_id": 1})
        if doc is None:
            raise RuntimeError(f"person {fp[:12]} vanished between upsert and read")
        return str(doc["_id"]), False
    except DuplicateKeyError:
        # Two writers upserted in the same instant; the index rejected one.
        # Re-read rather than retrying the write — the winner's document is
        # already correct and this caller's $addToSet is the only thing that
        # might be missing.
        doc = db[PERSONS].find_one({"fingerprint": fp})
        if doc is None:
            raise
        if add_to_set:
            db[PERSONS].update_one({"fingerprint": fp}, {"$addToSet": add_to_set})
        logger.debug("resolve_person: lost upsert race on %s, resolved to existing", fp[:12])
        return str(doc["_id"]), False


def is_suppressed(db, lead_or_email) -> bool:
    """
    Global suppression check, keyed on the PERSON rather than one address.

    Matches on any address the human has ever been known by, so an unsubscribe
    against a former employer's mailbox still suppresses. Entity is never part
    of this query — that is the whole point.
    """
    if isinstance(lead_or_email, str):
        ident = identity_email(lead_or_email)
        query = {"known_email_identities": ident} if ident else None
    else:
        fp = fingerprint(lead_or_email.get("email"), lead_or_email.get("linkedin_url"))
        query = {"fingerprint": fp} if fp else None
    if not query:
        return False
    doc = db[PERSONS].find_one(query, {"suppressed_at": 1})
    return bool(doc and doc.get("suppressed_at"))
