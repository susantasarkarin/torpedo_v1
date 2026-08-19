"""
INDEX GUARD TESTS

An index whose absence breaks a correctness guarantee must ASSERT, not warn.
leads_raw.email is supposed to be unique and is not, live, because its
creation failure was swallowed by a logger.warning — these pin that the guard
would have caught it.
"""

import os
import sys

import pytest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import index_guard as ig  # noqa: E402


TEST_DB = "torpedo_test_index_guard"


@pytest.fixture
def db():
    try:
        c = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
                        serverSelectionTimeoutMS=1500)
        c.server_info()
    except ServerSelectionTimeoutError:
        pytest.skip("no mongo reachable")
    c.drop_database(TEST_DB)
    yield c[TEST_DB]
    c.drop_database(TEST_DB)


def test_the_critical_list_is_small_and_enumerable():
    """
    A list that grows to cover every index stops being read. This is the
    uniqueness-guarding subset of 48 swallowed create_index calls, not all 48.
    """
    assert 0 < len(ig.CRITICAL_INDEXES) <= 12
    for spec in ig.CRITICAL_INDEXES:
        assert spec.why.strip(), f"{spec.collection}.{spec.field} needs a reason"


def test_leads_raw_email_is_on_the_list():
    """The index that actually lapsed in production."""
    pairs = {(s.collection, s.field) for s in ig.CRITICAL_INDEXES}
    assert ("leads_raw", "email") in pairs
    assert ("persons", "fingerprint") in pairs


def test_a_non_unique_index_is_reported_as_not_unique(db):
    db.leads_raw.insert_one({"email": "a@x.com"})
    db.leads_raw.create_index([("email", 1)], unique=False)
    row = next(r for r in ig.audit(db)
               if r["collection"] == "leads_raw" and r["field"] == "email")
    assert row["status"] == "not_unique"


def test_a_unique_index_is_reported_ok(db):
    db.leads_raw.insert_one({"email": "a@x.com"})
    db.leads_raw.create_index([("email", 1)], unique=True, sparse=True)
    row = next(r for r in ig.audit(db)
               if r["collection"] == "leads_raw" and r["field"] == "email")
    assert row["status"] == "ok"


def test_assert_raises_on_a_lapsed_guarantee(db):
    """
    THE POINT. A populated collection whose unique index is non-unique must
    raise, not warn. This is the exact live state of leads_raw.email.
    """
    db.leads_raw.insert_one({"email": "a@x.com"})
    db.leads_raw.create_index([("email", 1)], unique=False)
    with pytest.raises(ig.MissingCriticalIndex, match="leads_raw.email"):
        ig.assert_critical_indexes(db)


def test_the_raised_message_explains_why_it_asserts(db):
    db.leads_raw.insert_one({"email": "a@x.com"})
    db.leads_raw.create_index([("email", 1)], unique=False)
    with pytest.raises(ig.MissingCriticalIndex) as exc:
        ig.assert_critical_indexes(db)
    assert "logger.warning" in str(exc.value), (
        "the message must say why warning was not enough")


def test_an_empty_collection_does_not_raise(db):
    """
    A collection that has not been created yet is a different situation from
    one whose guarantee lapsed — persons arrives via migration 003.
    """
    ig.assert_critical_indexes(db)


def test_a_populated_collection_missing_the_index_entirely_raises(db):
    db.persons.insert_one({"fingerprint": "abc"})
    with pytest.raises(ig.MissingCriticalIndex, match="persons.fingerprint"):
        ig.assert_critical_indexes(db)


def test_all_guarantees_in_place_passes(db):
    db.leads_raw.insert_one({"email": "a@x.com", "linkedin_url": "u1"})
    db.leads_raw.create_index([("email", 1)], unique=True, sparse=True)
    db.leads_raw.create_index([("linkedin_url", 1)], unique=True, sparse=True)
    ig.assert_critical_indexes(db)   # must not raise


def test_audit_never_writes(db):
    db.leads_raw.insert_one({"email": "a@x.com"})
    before = db.leads_raw.count_documents({})
    names_before = set(db.leads_raw.index_information())
    ig.audit(db)
    assert db.leads_raw.count_documents({}) == before
    assert set(db.leads_raw.index_information()) == names_before
