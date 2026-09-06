"""
ensure_indexes() — real, enforced idempotency at the database layer.

Every idempotency-key check in this codebase (`MessagingFacade.send()`,
`PaymentService.record_payment()`, `EventDetectionService`'s dedupe-key
creation) has always been a `find_one` before `insert` — correct for the
practical failure mode (a sequential retry after a crash/restart), but with a
real, documented TOCTOU race window between the read and the write under true
concurrency. `app.outreach.service`'s own module docstring already named this
exact gap: "no index infrastructure exists yet in backend_v2." This module is
that infrastructure.

**A unique index turns a silent race into a loud one, which is the correct
direction.** Before this: two concurrent calls with the same idempotency key
could both pass the `find_one` check and both insert — a duplicate email
sent, or worse, a duplicate payment recorded. After this: MongoDB itself
rejects the second `insert_one` with `DuplicateKeyError` — a real,
unswallowed exception, never silent duplicate data. Each call site's own
`find_one`-based fast path still handles the common case (a sequential
retry finds the existing record immediately, no exception involved at all);
this index is the backstop for the genuinely concurrent case that path can't
cover.

**Compound on `(org_id, <key>)`, not the key alone** — the same multi-tenant
safety default every other index/query in this codebase already applies;
two different orgs legitimately constructing the same key string (unlikely,
since every caller embeds a real entity id in the key, but not architecturally
prevented) must never collide.

Called once, at application startup (`app.main`'s FastAPI startup event) —
`create_index` is itself idempotent (a no-op if the index already exists with
the same spec), so this is safe to run on every process start, not just the
first.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["send_log_entries"].create_index([("org_id", 1), ("idempotency_key", 1)], unique=True, name="uniq_org_idempotency_key")
    await db["payments"].create_index([("org_id", 1), ("idempotency_key", 1)], unique=True, name="uniq_org_idempotency_key")
    await db["events"].create_index([("dedupe_key", 1)], unique=True, name="uniq_dedupe_key")
