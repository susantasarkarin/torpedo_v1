"""
Real, enforced idempotency at the database layer (Phase 1 production-
foundations audit). Proves `ensure_indexes()` doesn't just create indexes —
they actually reject the exact race `app.outreach.service`'s own module
docstring named ("no index infrastructure exists yet in backend_v2").
"""

from datetime import timezone

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError

from app.indexes import ensure_indexes


@pytest.fixture
def db():
    return AsyncMongoMockClient(tz_aware=True, tzinfo=timezone.utc)["test_db"]


@pytest.mark.asyncio
async def test_ensure_indexes_is_itself_idempotent(db):
    await ensure_indexes(db)
    await ensure_indexes(db)  # a second app-process start — must not raise


@pytest.mark.asyncio
async def test_duplicate_send_log_idempotency_key_within_the_same_org_is_rejected(db):
    await ensure_indexes(db)
    await db["send_log_entries"].insert_one({"org_id": "org-A", "idempotency_key": "key-1"})
    with pytest.raises(DuplicateKeyError):
        await db["send_log_entries"].insert_one({"org_id": "org-A", "idempotency_key": "key-1"})


@pytest.mark.asyncio
async def test_same_idempotency_key_in_a_different_org_is_not_a_conflict(db):
    await ensure_indexes(db)
    await db["send_log_entries"].insert_one({"org_id": "org-A", "idempotency_key": "key-1"})
    await db["send_log_entries"].insert_one({"org_id": "org-B", "idempotency_key": "key-1"})  # must not raise


@pytest.mark.asyncio
async def test_duplicate_payment_idempotency_key_within_the_same_org_is_rejected(db):
    await ensure_indexes(db)
    await db["payments"].insert_one({"org_id": "org-A", "idempotency_key": "pay-1"})
    with pytest.raises(DuplicateKeyError):
        await db["payments"].insert_one({"org_id": "org-A", "idempotency_key": "pay-1"})


@pytest.mark.asyncio
async def test_duplicate_event_dedupe_key_is_rejected(db):
    await ensure_indexes(db)
    await db["events"].insert_one({"dedupe_key": "ar_followup_due:inv-1:2026-09-06"})
    with pytest.raises(DuplicateKeyError):
        await db["events"].insert_one({"dedupe_key": "ar_followup_due:inv-1:2026-09-06"})
