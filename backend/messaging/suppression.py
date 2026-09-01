"""
ONE suppression list.

There were three, in three different databases, and no sender consulted more
than one of them (TOR-06):

    email_automation.suppression_list        campaigns/suppression.py — the
                                             "canonical" one, fed by explicit
                                             unsubscribe/complaint calls
    torpedo.outreach_bounce_suppression      11,508 docs; what
                                             cold_outreach_router and
                                             outreach_qualification actually read
    campaign_platform.panel_email_suppression
                                             what every panel sender reads

So a person who unsubscribed from cold outreach kept receiving panel invites,
and an address SES had already told us was dead stayed mailable from two of the
three channels.

MIGRATION SHAPE
---------------
`email_automation.suppression_list` becomes canonical — it is the one already
indexed in indexes.py and already described as canonical in the runbook.

Reads are READ-THROUGH: canonical first, then both legacy collections. That
ordering matters. It means turning this on can only ever suppress MORE mail
than before, never less — no address that is currently blocked becomes mailable
because a migration has not finished running. The legacy reads disappear once
`scripts/migrate_suppressions.py` has run and the legacy senders are migrated;
until then they are the safety net, and they are cheap (an indexed count on a
collection that is only consulted when the canonical lookup misses).

Writes go to canonical AND mirror into the panel list, because panel senders
still read that collection directly. Removing that mirror is safe only once
every panel sender calls this module.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CANONICAL_DB = "email_automation"
CANONICAL_COLLECTION = "suppression_list"

# Legacy stores, read-through only. Ordered by how likely they are to hold the
# answer, so the common case short-circuits early.
_LEGACY = (
    ("torpedo", "outreach_bounce_suppression"),
    ("campaign_platform", "panel_email_suppression"),
)

VALID_REASONS = ("unsubscribed", "bounced", "complaint", "manual", "ses_suppressed")


def _db(name: str):
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database(name)


def _canonical():
    return _db(CANONICAL_DB)[CANONICAL_COLLECTION]


def normalize(email: str) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def lookup(email: str) -> Optional[Dict[str, Any]]:
    """
    Return the suppression record for this address, or None if it is mailable.

    Checks canonical first, then the legacy stores. A legacy hit is returned
    with `legacy_source` set so callers (and the migration) can tell where the
    answer came from.
    """
    addr = normalize(email)
    if not addr:
        return None

    try:
        doc = _canonical().find_one({"email": addr})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception:
        # A suppression check that cannot run must NOT be treated as "clear to
        # send" — see is_suppressed(), which fails closed.
        logger.warning("canonical suppression lookup failed for %s", addr,
                       exc_info=True)
        raise

    for dbname, colname in _LEGACY:
        try:
            doc = _db(dbname)[colname].find_one({"email": addr})
        except Exception:
            logger.warning("legacy suppression lookup failed (%s.%s)",
                           dbname, colname, exc_info=True)
            continue
        if doc:
            doc.pop("_id", None)
            doc["legacy_source"] = f"{dbname}.{colname}"
            return doc

    return None


def is_suppressed(email: str) -> bool:
    """
    True when this address must not be mailed.

    FAILS CLOSED. If the lookup itself errors, the answer is "suppressed" —
    the cost of not sending one email is a missed touch; the cost of mailing a
    complained-about address because Mongo blinked is domain reputation.
    """
    try:
        return lookup(email) is not None
    except Exception:
        logger.error("suppression check failed for %s — treating as SUPPRESSED",
                     email, exc_info=True)
        return True


def reason_for(email: str) -> Optional[str]:
    """
    Why this address is suppressed, for logs and operator UI.

    Non-raising, unlike lookup(). This is informational — it is called AFTER
    is_suppressed() has already made the decision, so letting a failed lookup
    propagate here would turn a correctly-blocked send into an unhandled
    exception at the call site.
    """
    try:
        record = lookup(email)
    except Exception:
        logger.debug("suppression reason lookup failed for %s", email, exc_info=True)
        return None
    return (record or {}).get("reason")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def suppress(email: str, reason: str, source: Optional[str] = None,
             metadata: Optional[Dict[str, Any]] = None,
             suppressed_by: str = "system") -> bool:
    """
    Add an address to the canonical list. Idempotent; returns True if newly
    added.

    Also mirrors into campaign_platform.panel_email_suppression, because the
    panel senders still read that collection directly. Drop the mirror once
    they all call is_suppressed() here.
    """
    addr = normalize(email)
    if not addr:
        return False
    if reason not in VALID_REASONS:
        logger.warning("unknown suppression reason %r for %s; recording anyway",
                       reason, addr)

    now = datetime.utcnow()
    record = {
        "email": addr,
        "reason": reason,
        "source": source,
        "metadata": metadata or {},
        "suppressed_at": now,
        "suppressed_by": suppressed_by,
    }

    newly_added = False
    try:
        result = _canonical().update_one(
            {"email": addr},
            {"$set": {k: v for k, v in record.items() if k != "email"},
             "$setOnInsert": {"email": addr}},
            upsert=True,
        )
        newly_added = result.upserted_id is not None
    except Exception:
        logger.exception("failed to write canonical suppression for %s", addr)
        raise

    # Mirror for the not-yet-migrated panel senders.
    try:
        _db("campaign_platform")["panel_email_suppression"].update_one(
            {"email": addr},
            {"$set": {"reason": reason, "source": source or "unified",
                      "suppressed_at": now},
             "$setOnInsert": {"email": addr}},
            upsert=True,
        )
    except Exception:
        logger.warning("panel suppression mirror failed for %s", addr,
                       exc_info=True)

    if newly_added:
        logger.info("suppressed %s (reason=%s source=%s)", addr, reason, source)
    return newly_added


def unsuppress(email: str, removed_by: str = "system") -> bool:
    """
    Remove an address from every list. Deliberately removes from the legacy
    stores too — a half-removal would leave the address blocked by whichever
    list was missed, which is exactly the bug this module exists to fix.
    """
    addr = normalize(email)
    if not addr:
        return False
    removed = False
    try:
        removed = _canonical().delete_one({"email": addr}).deleted_count > 0
    except Exception:
        logger.exception("canonical unsuppress failed for %s", addr)
        raise
    for dbname, colname in _LEGACY:
        try:
            _db(dbname)[colname].delete_one({"email": addr})
        except Exception:
            logger.warning("legacy unsuppress failed (%s.%s) for %s",
                           dbname, colname, addr, exc_info=True)
    logger.info("unsuppressed %s by %s", addr, removed_by)
    return removed


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------
def stats() -> Dict[str, Any]:
    """Counts per store — the number that tells you whether migration is done."""
    out: Dict[str, Any] = {}
    try:
        out["canonical"] = _canonical().estimated_document_count()
    except Exception:
        out["canonical"] = None
    for dbname, colname in _LEGACY:
        key = f"{dbname}.{colname}"
        try:
            out[key] = _db(dbname)[colname].estimated_document_count()
        except Exception:
            out[key] = None
    try:
        by_reason = _canonical().aggregate([
            {"$group": {"_id": "$reason", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ])
        out["canonical_by_reason"] = {d["_id"] or "unknown": d["n"] for d in by_reason}
    except Exception:
        pass
    return out


def ensure_indexes() -> None:
    """Unique index on email — the constraint that stops duplicate rows."""
    try:
        _canonical().create_index("email", unique=True, background=True)
        _canonical().create_index("reason", background=True)
        _canonical().create_index("suppressed_at", background=True)
    except Exception:
        logger.warning("suppression index creation failed", exc_info=True)
