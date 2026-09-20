"""
EXTRACTION STASH -- keep raw search results when lead extraction is down
========================================================================

Lead extraction reads raw Google CSE results with a model. When the model is
unreachable the extractor must NOT fall back to regex parsing (that path reads
a LinkedIn headline as the company name and feeds domain/email guessing, which
is how undeliverable rows like `zach.whitman@opentable...ship.com` got
enrolled). But the raw results cost CSE quota (~100 queries/day) and are not
cached anywhere -- only extracted leads are -- so simply discarding them would
waste that quota on every outage.

So on an outage the results are stashed here, keyed by (query, start). The next
time the same search runs, `take_stashed_results()` hands the stored results
back instead of calling Google again; everything downstream (extraction,
caching, dedup, the caller's own persistence) is unchanged. If extraction fails
again the results are simply stashed again.

Nothing here can raise into the caller: a stash failure is logged and the
search proceeds exactly as it would have without a stash.
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COLLECTION_NAME = "extraction_backlog"
DB_NAME = "email_automation"

# Search results describe a person's current role; past this age the stored
# snippet is more likely stale than the cost of one fresh CSE call is worth.
MAX_AGE_DAYS = 14


def _collection():
    from database import get_client
    return get_client()[DB_NAME][COLLECTION_NAME]


def _key(query: str, start: int) -> str:
    return hashlib.sha1(f"{(query or '').strip().lower()}|{int(start)}".encode("utf-8")).hexdigest()


def stash_unextracted_results(query: str, results: List[Dict[str, Any]], reason: str,
                              start: int = 1, collection=None) -> bool:
    """Persist raw results for a later re-run of the same query. Returns True on success."""
    if not results:
        return False
    try:
        coll = collection if collection is not None else _collection()
        now = datetime.utcnow()
        coll.update_one(
            {"_id": _key(query, start)},
            {
                "$set": {
                    "query": query, "start": int(start), "results": results,
                    "reason": str(reason)[:500], "status": "pending", "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
                "$inc": {"attempts": 1},
            },
            upsert=True,
        )
        logger.warning("[extraction stash] kept %d raw results for %r (start=%s) until the model is back",
                       len(results), query[:80], start)
        return True
    except Exception as e:  # never let bookkeeping mask the real failure
        logger.error("[extraction stash] could not persist results for %r: %s", query[:80], e)
        return False


def take_stashed_results(query: str, start: int = 1, collection=None) -> List[Dict[str, Any]]:
    """
    Claim and return stashed results for this query, or [] if there are none.

    The claim (pending -> consumed) is atomic so two workers replaying the same
    query cannot both process it. A failed extraction re-stashes the results.
    """
    try:
        coll = collection if collection is not None else _collection()
        cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
        doc = coll.find_one_and_update(
            {"_id": _key(query, start), "status": "pending", "updated_at": {"$gte": cutoff}},
            {"$set": {"status": "consumed", "consumed_at": datetime.utcnow()}},
        )
        results: Optional[list] = (doc or {}).get("results")
        if results:
            logger.info("[extraction stash] replaying %d stashed results for %r instead of calling Google",
                        len(results), query[:80])
            return results
    except Exception as e:
        logger.error("[extraction stash] could not read stash for %r: %s", query[:80], e)
    return []
