"""
PERSON IDENTITY UNDER CONCURRENCY
=================================

Guards the TOCTOU hole that produced three rows for one human.

This is the one Phase 1 finding that is provably live rather than inferred.
leads_enriched holds:

    linkedin.com/in/ericdohertygloballeader/es    _id 6952c7c1...cdce
    linkedin.com/in/ericdohertygloballeader/de    _id 6952c7c1...cddc
    linkedin.com/in/ericdohertygloballeader/fi    _id 6952c7c1...cddd

Same ObjectId timestamp second, consecutive counters: three parallel ICP
tasks under scheduler.py's asyncio.gather, one human, three rows.

Two defects stacked, and both must hold for the fix to work:

    1. the locale suffixes were not normalized  -> three DIFFERENT keys
    2. nothing serialized the writers           -> even one key would race

Fixing only (1) converts three rows into a race for one row. Fixing only (2)
serializes writers who still disagree about who they are. The tests below
cover each independently and then together.

REQUIRES A LIVE MONGO. The race cannot be demonstrated against a fake — the
whole question is whether the database enforces uniqueness. Skips cleanly if
mongo is unreachable so CI without a service container stays green.

Run with:
    pytest backend/tests/test_person_identity_concurrency.py -v
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import person_repo  # noqa: E402


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
TEST_DB = "torpedo_test_person_identity"

# The live shape, verbatim.
ERIC_VARIANTS = [
    "https://www.linkedin.com/in/ericdohertygloballeader/es",
    "https://www.linkedin.com/in/ericdohertygloballeader/de",
    "https://www.linkedin.com/in/ericdohertygloballeader/fi",
]


@pytest.fixture
def db():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        client.server_info()
    except ServerSelectionTimeoutError:
        pytest.skip("no mongo reachable; concurrency cannot be tested against a fake")

    client.drop_database(TEST_DB)
    d = client[TEST_DB]
    person_repo.ensure_indexes(d)
    yield d
    client.drop_database(TEST_DB)


def _lead(url, email=None, name="Eric Doherty"):
    return {"linkedin_url": url, "email": email, "name": name,
            "company": "Global Leader", "title": "Managing Partner"}


# ===========================================================================
# Defect 1 — identity
# ===========================================================================

def test_locale_variants_produce_one_fingerprint():
    """Prerequisite: without this the writers race over three distinct keys."""
    prints = {person_repo.fingerprint(None, u) for u in ERIC_VARIANTS}
    assert len(prints) == 1, f"three URLs for one human gave {len(prints)} fingerprints"


# ===========================================================================
# Defect 2 — serialization
# ===========================================================================

def test_concurrent_ingest_of_one_profile_creates_exactly_one_person(db):
    """
    THE TEST. 24 threads resolve the same profile simultaneously; the
    collection must hold exactly one person afterwards.

    Pre-fix this produced N rows — find_one/insert_one with no unique index.
    """
    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(
            lambda _: person_repo.resolve_person(db, _lead(ERIC_VARIANTS[0])),
            range(24)))

    assert db.persons.count_documents({}) == 1, (
        f"24 concurrent ingests produced "
        f"{db.persons.count_documents({})} persons")

    ids = {pid for pid, _ in results}
    assert len(ids) == 1, f"callers resolved to {len(ids)} different person_ids"
    assert sum(1 for _, created in results if created) == 1, (
        "exactly one caller should report created=True")


def test_concurrent_ingest_across_locale_variants_creates_one_person(db):
    """
    Both defects together, and the live shape exactly: three parallel ICP
    tasks, three locale spellings, one human.
    """
    leads = [_lead(u) for u in ERIC_VARIANTS] * 8
    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(lambda l: person_repo.resolve_person(db, l), leads))

    assert db.persons.count_documents({}) == 1, (
        f"the live three-row shape reproduced: "
        f"{db.persons.count_documents({})} persons")
    assert len({pid for pid, _ in results}) == 1


def test_losing_writer_resolves_rather_than_dropping_its_data(db):
    """
    Conflict handling must RESOLVE to the existing person, not silently drop
    the loser. ON CONFLICT DO NOTHING would discard the second address.
    """
    person_repo.resolve_person(db, _lead(ERIC_VARIANTS[0], email="eric@globalleader.com"))
    person_repo.resolve_person(db, _lead(ERIC_VARIANTS[1], email="e.doherty@globalleader.com"))

    assert db.persons.count_documents({}) == 1
    doc = db.persons.find_one({})
    assert set(doc["known_emails"]) == {
        "eric@globalleader.com", "e.doherty@globalleader.com"}, (
        "the losing writer's address was dropped instead of merged")


def test_identity_fields_are_not_overwritten_by_later_sightings(db):
    """
    A later, worse sighting must not clobber identity. $setOnInsert, not $set.
    """
    person_repo.resolve_person(db, _lead(ERIC_VARIANTS[0], name="Eric Doherty"))
    person_repo.resolve_person(db, _lead(ERIC_VARIANTS[1], name="E.D."))

    assert db.persons.find_one({})["full_name"] == "Eric Doherty"


def test_distinct_humans_are_never_merged(db):
    """
    The guard against over-merging. Two different profiles must stay two
    people — same principle as dots outside the gmail family.
    """
    person_repo.resolve_person(db, _lead("https://www.linkedin.com/in/asha-rao"))
    person_repo.resolve_person(db, _lead("https://www.linkedin.com/in/asha-rao-2"))
    person_repo.resolve_person(db, _lead("https://www.linkedin.com/in/asha-rao/dr"))

    assert db.persons.count_documents({}) == 3, (
        "distinct profiles were merged; /dr is not a locale and asha-rao-2 is "
        "a different person")


# ===========================================================================
# Suppression is keyed on the person, not one address
# ===========================================================================

def test_suppression_follows_the_human_across_address_changes(db):
    """
    Employer change: contacted at @celonis, unsubscribed, now @chainalysis.
    The old address must keep suppressing the human.
    """
    pid, _ = person_repo.resolve_person(
        db, _lead(ERIC_VARIANTS[0], email="m.chassot@celonis.com"))
    person_repo.resolve_person(
        db, _lead(ERIC_VARIANTS[0], email="m.chassot@chainalysis.com"))

    from datetime import datetime
    db.persons.update_one({"fingerprint": {"$exists": True}},
                          {"$set": {"suppressed_at": datetime.utcnow(),
                                    "suppression_reason": ["unsubscribed"]}})

    assert person_repo.is_suppressed(db, "m.chassot@celonis.com"), (
        "unsubscribe against the former address stopped suppressing the human")
    assert person_repo.is_suppressed(db, "m.chassot@chainalysis.com")


def test_index_assertion_fires_when_uniqueness_is_missing(db):
    """
    ensure_indexes must RAISE, not warn, if fingerprint uniqueness is absent.
    48 create_index calls in this repo swallow failure into logger.warning,
    which is how leads_raw.email ended up non-unique in production.
    """
    db.persons.drop_index("fingerprint_1")
    db.persons.create_index([("fingerprint", 1)], unique=False)

    with pytest.raises(RuntimeError, match="uniqueness NOT guaranteed|not UNIQUE"):
        person_repo.ensure_indexes(db)
