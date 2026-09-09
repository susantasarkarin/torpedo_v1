"""
CanonicalDocument and CanonicalRepository — the I-6 enforcement point.

`business_rules_register.md` §0.1, invariant I-6: "No write path may persist data that
has not passed through a canonical, collection-bound model." The lineage-map pass found
that 96% of v1's writes (319 of 331 insert sites) bypassed Pydantic entirely — endpoints
took `Dict[str, Any] = Body(...)` and called `insert_one` on the raw client payload
(entity_map.md §0.2). Critically, this was true *even where a correctly-typed Pydantic
model already existed*: `schemas.InvoiceCreate` had the right field types and was never
called by any endpoint. A model that exists but isn't the only way to write is not a
protection, it's decoration.

`CanonicalRepository` is the fix: it is the *only* way this codebase writes to Mongo.
There is no `insert_one`/`update_one` call anywhere outside this file — every other
module gets a `CanonicalRepository[SomeDocument]` and calls `.insert()`/`.update()`,
which only accept an already-validated `CanonicalDocument` subclass instance, never a
dict. `Dict[str, Any]` cannot reach this class's public methods; Pydantic validation
already ran before a caller could construct the argument.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    # v1 mixed `datetime.utcnow()` (naive) and `datetime.now()` (server-local, naive)
    # across importers and API paths for the *same field* (data_lineage_map.md D2/D3:
    # created_at was naive-vs-aware, and sortable date fields silently mis-ordered
    # under Mongo's BSON type rules as a result). One function, tz-aware, everywhere.
    return datetime.now(timezone.utc)


class CanonicalDocument(BaseModel):
    """
    Every canonical entity in v2 inherits this. Fields per schema_catalogue.md §0 —
    stated there as a catalogue rule, enforced here as a type.

    `org_id`: mandatory even in a single-tenant deployment today. v1 had zero tenancy
    fields anywhere (D-19/D-22) and paid for it specifically in the brand-relationship
    incident (register §4.5) — retrofitting a scoping field after data exists is far
    more expensive than declaring it unused-but-present from document one.

    `version`/`schema_version`: present in exactly 1 of 48 v1 models (and that one had
    non-standard, unrelated semantics). `updated_by` was present in 0 of 48. These are
    not aspirational — `CanonicalRepository.update()` below refuses to compile a write
    that omits them, because they're required fields on this base class.
    """

    model_config = ConfigDict(populate_by_name=True)

    # App-generated UUID4 string, always — never a Mongo-assigned ObjectId. v1's model
    # catalogue found FOUR coexisting id conventions (bare ObjectId-alias, a
    # client-generated `id` field shadowing `_id`, per-entity `<entity>_id` strings from
    # `default_factory=ObjectId`, and UUID4 strings in a fourth module), which meant
    # query code had to guess which convention a given collection used. One convention,
    # enforced by `CanonicalRepository.insert()` never delegating id assignment to Mongo.
    #
    # `validation_alias`/`serialization_alias` deliberately split, not one shared
    # `alias` (API contract audit, 2026-09-09): Mongo's own primary-key field is
    # genuinely named `_id` on the wire (`find_one({"_id": ...})`, `insert_one()`),
    # so *reading a raw Mongo document* still needs `_id` on the input side — that's
    # `validation_alias`. But every HTTP response was leaking that same storage
    # implementation detail outward as `"_id"` in the JSON body, because FastAPI's
    # response serialization defaults to using the model's alias too — a client had
    # no way to know this was a database artifact, not a deliberate public field
    # name. `serialization_alias="id"` fixes the *outward* contract without touching
    # storage: `to_mongo()` below no longer uses `by_alias=True` (that would now
    # write `id` instead of `_id` into Mongo, breaking every existing document's
    # primary key) — it renames explicitly instead, so storage is provably unchanged
    # while every HTTP response across the whole app now returns a clean `id` field,
    # for free, from this one base-class change.
    id: str | None = Field(default=None, validation_alias="_id", serialization_alias="id")
    org_id: str
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str
    updated_at: datetime = Field(default_factory=_utcnow)
    updated_by: str
    version: int = 1
    schema_version: int = 1
    deleted_at: datetime | None = None

    def to_mongo(self) -> dict:
        # No longer `by_alias=True` — since `id`'s serialization_alias is now the
        # outward-facing "id" (not "_id"), by_alias would write the wrong key into
        # Mongo. Dump by Python field name, then rename id -> _id explicitly, the
        # one field where storage's real wire name and the public API's name differ.
        data = self.model_dump(exclude_none=True)
        if "id" in data:
            data["_id"] = data.pop("id")
        return data


T = TypeVar("T", bound=CanonicalDocument)


class VersionConflict(Exception):
    """
    Raised when an update's expected `version` doesn't match the stored document —
    the structural fix for D-03/D-33's class of defect (payment recording as four
    independent, non-transactional Mongo operations; a read-after-write race that let
    two concurrent partial payments both see a stale balance). This is the `409` the
    endpoint catalogue's `If-Match` rule (endpoint_catalogue.md §0) turns into.
    """


class CanonicalRepository(Generic[T]):
    """One repository per collection. Never constructed with a raw collection name
    from a caller-supplied parameter — always `get_database()[literal_name]`, so a
    single grep for the collection name finds every place it's used (closes the
    "collection name built at runtime" inventory risk noted in entity_map.md §1)."""

    def __init__(self, collection: AsyncIOMotorCollection, model: type[T]):
        self._collection = collection
        self._model = model

    async def insert(self, doc: T) -> T:
        if doc.id is None:
            doc = doc.model_copy(update={"id": str(uuid.uuid4())})
        await self._collection.insert_one(doc.to_mongo())
        return doc

    async def get(self, doc_id: str) -> T | None:
        raw = await self._collection.find_one({"_id": doc_id, "deleted_at": None})
        return self._model.model_validate(raw) if raw else None

    async def find_one(self, query: dict) -> T | None:
        raw = await self._collection.find_one({**query, "deleted_at": None})
        return self._model.model_validate(raw) if raw else None

    async def find_all(self, query: dict) -> list[T]:
        cursor = self._collection.find({**query, "deleted_at": None})
        docs = await cursor.to_list(length=None)
        return [self._model.model_validate(d) for d in docs]

    async def update(self, doc_id: str, expected_version: int, changes: dict, *, updated_by: str) -> T:
        """
        Atomic optimistic-concurrency update: the filter requires the version the
        caller last read, and the write bumps it in the same operation. No
        read-then-write gap exists between the version check and the mutation —
        that gap is exactly what let v1's payment race double-apply an `$inc`.

        **Bug found and fixed while building Slice 8 (Finance)**: a `changes` value
        that is itself a `CanonicalDocument`'s nested `BaseModel` (e.g. `Money`) isn't
        BSON-encodable as-is — `insert()` already handles this via `to_mongo()`, but
        `update()` had no equivalent, and passing a live `Money` object straight into
        `$set` raised `bson.errors.InvalidDocument` the moment a finance service tried
        to update `amount_paid`/`balance_due`. Every top-level `BaseModel` value is
        now dumped to a plain dict before it reaches Mongo — the same discipline
        `insert()` already had, now applied here too rather than left as a footgun
        every future caller with a nested-model field would hit individually.
        """
        changes = {
            key: (value.model_dump(by_alias=True, exclude_none=True) if isinstance(value, BaseModel) else value)
            for key, value in changes.items()
        }
        changes = {**changes, "updated_at": _utcnow(), "updated_by": updated_by}
        result = await self._collection.find_one_and_update(
            {"_id": doc_id, "version": expected_version, "deleted_at": None},
            {"$set": changes, "$inc": {"version": 1}},
            return_document=True,
        )
        if result is None:
            raise VersionConflict(
                f"{self._model.__name__} {doc_id} was not at version {expected_version}"
            )
        return self._model.model_validate(result)

    async def soft_delete(self, doc_id: str, expected_version: int, *, deleted_by: str) -> None:
        result = await self._collection.find_one_and_update(
            {"_id": doc_id, "version": expected_version, "deleted_at": None},
            {"$set": {"deleted_at": _utcnow(), "updated_by": deleted_by}, "$inc": {"version": 1}},
        )
        if result is None:
            raise VersionConflict(f"{self._model.__name__} {doc_id} was not at version {expected_version}")
