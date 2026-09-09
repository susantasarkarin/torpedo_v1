"""
Proves the two mechanisms this slice exists for:

1. I-6 — a document cannot be constructed, let alone persisted, without the seven
   governing fields schema_catalogue.md §0 requires (org_id, created_by, updated_by
   included — the three v1 had at 0-6/48 model coverage).
2. The optimistic-concurrency update path actually rejects a stale write, which is
   the structural fix for the payment read-after-write race (D-03/D-33).

Uses `mongomock-motor` so this suite runs with no real Mongo instance — appropriate
for a repository-layer unit test, not a substitute for an integration test against a
real replica set once transactions matter (Phase 3, finance).
"""

import pytest
from datetime import datetime, timezone
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.models.base import CanonicalDocument, CanonicalRepository, VersionConflict
from app.models.money import Money


class _Widget(CanonicalDocument):
    name: str
    price: Money


@pytest.fixture
def collection():
    client = AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)
    return client["test_db"]["widgets"]


@pytest.fixture
def repo(collection) -> CanonicalRepository[_Widget]:
    return CanonicalRepository(collection, _Widget)


def test_canonical_document_requires_org_id_and_actor_fields():
    with pytest.raises(ValidationError):
        _Widget(name="thing", price=Money(amount_minor=100, currency="INR"))


def test_canonical_document_defaults_version_and_schema_version():
    w = _Widget(
        name="thing",
        price=Money(amount_minor=100, currency="INR"),
        org_id="org1",
        created_by="user1",
        updated_by="user1",
    )
    assert w.version == 1
    assert w.schema_version == 1
    assert w.deleted_at is None


def test_money_rejects_mismatched_currency_addition():
    inr = Money(amount_minor=100, currency="INR")
    usd = Money(amount_minor=100, currency="USD")
    with pytest.raises(ValueError):
        inr + usd


def test_money_rejects_non_iso4217_currency():
    with pytest.raises(ValidationError):
        Money(amount_minor=100, currency="XX")


@pytest.mark.asyncio
async def test_insert_then_get_roundtrips(repo: CanonicalRepository[_Widget]):
    w = _Widget(
        name="thing",
        price=Money(amount_minor=500, currency="INR"),
        org_id="org1",
        created_by="user1",
        updated_by="user1",
    )
    saved = await repo.insert(w)
    assert saved.id is not None

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.name == "thing"
    assert fetched.price.amount_minor == 500


@pytest.mark.asyncio
async def test_update_with_correct_version_succeeds(repo: CanonicalRepository[_Widget]):
    w = _Widget(
        name="thing",
        price=Money(amount_minor=500, currency="INR"),
        org_id="org1",
        created_by="user1",
        updated_by="user1",
    )
    saved = await repo.insert(w)

    updated = await repo.update(saved.id, expected_version=1, changes={"name": "renamed"}, updated_by="user2")
    assert updated.name == "renamed"
    assert updated.version == 2


@pytest.mark.asyncio
async def test_update_with_stale_version_raises_version_conflict(repo: CanonicalRepository[_Widget]):
    """
    This is the test that proves the read-after-write race (register §1.4, D-03/D-33)
    cannot recur: two callers who both read version 1 cannot both successfully write.
    The second caller's stale `expected_version` is rejected, atomically, by the same
    `find_one_and_update` that would otherwise have silently applied both writes.
    """
    w = _Widget(
        name="thing",
        price=Money(amount_minor=500, currency="INR"),
        org_id="org1",
        created_by="user1",
        updated_by="user1",
    )
    saved = await repo.insert(w)

    await repo.update(saved.id, expected_version=1, changes={"name": "first writer"}, updated_by="user2")

    with pytest.raises(VersionConflict):
        await repo.update(saved.id, expected_version=1, changes={"name": "second writer"}, updated_by="user3")


# --------------------------------------------------------------------------- id / _id API contract (2026-09-09)
# Mongo's own primary key is genuinely named `_id` on the wire; every HTTP response
# was leaking that storage detail outward as `"_id"` in the JSON body too, because
# FastAPI's response serialization defaults to using the same alias storage needs.
# validation_alias="_id" / serialization_alias="id" splits the two directions —
# these tests prove storage is unaffected while the public contract now says "id".


def test_to_mongo_still_writes_the_real_id_field(repo: CanonicalRepository[_Widget]):
    w = _Widget(id="widget-1", name="thing", price=Money(amount_minor=500, currency="INR"), org_id="org1", created_by="user1", updated_by="user1")
    doc = w.to_mongo()
    assert doc["_id"] == "widget-1"
    assert "id" not in doc


@pytest.mark.asyncio
async def test_a_raw_mongo_document_with_underscore_id_still_reads_back_correctly(repo: CanonicalRepository[_Widget], collection):
    """Storage compatibility: an existing document shaped exactly like every
    document already in the real database (raw `_id`, no `id` key at all)
    must still validate and round-trip correctly — the split alias must not
    require a data migration."""
    now = datetime.now(timezone.utc)
    await collection.insert_one({
        "_id": "widget-2", "org_id": "org1", "created_by": "user1", "updated_by": "user1",
        "created_at": now, "updated_at": now, "version": 1, "schema_version": 1, "deleted_at": None,
        "name": "existing thing", "price": {"amount_minor": 100, "currency": "INR"},
    })

    fetched = await repo.get("widget-2")
    assert fetched is not None
    assert fetched.id == "widget-2"


def test_model_dump_for_http_responses_uses_id_not_underscore_id():
    """The exact call shape FastAPI's response serialization uses
    (by_alias=True) on a model returned from a route — proves the outward
    contract is really "id", not just that to_mongo() was left alone."""
    w = _Widget(id="widget-3", name="thing", price=Money(amount_minor=500, currency="INR"), org_id="org1", created_by="user1", updated_by="user1")
    dumped = w.model_dump(by_alias=True)
    assert dumped["id"] == "widget-3"
    assert "_id" not in dumped
