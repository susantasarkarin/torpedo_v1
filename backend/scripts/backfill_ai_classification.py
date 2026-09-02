"""
Backfill AI classification fields onto existing leads_enriched documents.

Selects on the MISSING FIELD, not classification_status, for two reasons:

  * the APScheduler "Rule-Based ICP Lead Classification" job flips
    Pending -> Classified after assigning only an ICP basket, so a
    status-driven runner loses leads to it and can never see them again;
  * `leads.service.classify_single_lead` CREATES a leads_enriched document
    and therefore raises DuplicateKeyError on anything already enriched. It
    is a first-classification path. This calls the pure `classify_lead()` and
    updates the existing document, which is idempotent.

TWO SAFEGUARDS, both learned the expensive way
----------------------------------------------
An earlier version of this script consumed the entire 50,000/day AI budget on
two consecutive days. Both causes are fixed here:

  1. TRANSIENT vs PERMANENT failures. That version marked every failure by
     writing seniority_level="Unknown" — but "Unknown" is inside its own
     selection filter, so the same batch was re-selected and retried forever.
     Once the daily cap was hit, every call failed instantly and the loop
     spun, burning the remainder of the budget in minutes. A transient failure
     (quota, throttling, timeout) now STOPS the run; only a permanent one
     (unusable input, model returned nothing) marks the document, and it marks
     it with a field the query excludes.

  2. A CALL BUDGET. classify_lead() fans out into company enrichment and email
     lookup, so one lead costs several model calls, not one. --max-calls caps
     the run so it cannot silently consume a day's allowance.

    python -m scripts.backfill_ai_classification --dry-run --limit 20
    python -m scripts.backfill_ai_classification --max-calls 5000
"""

import argparse
import logging
import sys
import time
from collections import Counter
from datetime import datetime

from database import get_database
from leads.ai_classifier import classify_lead
from leads.models import LeadRaw

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_ai")

# Errors that mean "try again later", never "this lead is unclassifiable".
TRANSIENT = (
    "daily limit", "dailylimitexceeded", "aidailylimitexceeded",
    "throttl", "rate limit", "toomanyrequests", "429",
    "timeout", "timed out", "503", "502", "serviceunavailable",
    "connection", "unavailable",
)

# Written when a lead is genuinely unclassifiable, so the selector skips it on
# the next run. Deliberately NOT "Unknown": that value is inside the selector.
DONE_MARK = "ai_classification_attempted_at"

FIELDS = ("seniority_level", "department", "persona", "buying_role", "gender",
          "company_size", "region", "inferred_location", "company_name",
          "company_domain", "company_website", "company_industry",
          "company_type", "company_headquarters", "company_revenue_range",
          "company_employee_count", "company_employee_count_range",
          "company_founded", "company_linkedin_url", "confidence_score")


def _is_transient_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in TRANSIENT)


def _is_transient(exc: Exception) -> bool:
    return _is_transient_text(f"{type(exc).__name__} {exc}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N leads")
    ap.add_argument("--max-calls", type=int, default=20000,
                    help="hard ceiling on leads processed, so a run cannot "
                         "consume the whole daily AI allowance")
    ap.add_argument("--abort-after", type=int, default=25,
                    help="stop after this many CONSECUTIVE failures — the "
                         "backstop for an outage the error text does not name")
    args = ap.parse_args(argv)

    E = get_database("email_automation")["leads_enriched"]

    selector = {
        "$and": [
            {"$or": [{"seniority_level": {"$in": [None, "", "Unknown"]}},
                     {"seniority_level": {"$exists": False}}]},
            {DONE_MARK: {"$exists": False}},
        ]
    }

    total = E.count_documents(selector)
    logger.info("leads needing AI classification: %d", total)
    budget = min(args.limit or args.max_calls, args.max_calls)
    logger.info("this run will process at most %d", budget)

    stats = Counter()
    t0 = time.time()

    # CIRCUIT BREAKER.
    #
    # Matching error strings has now failed twice. First the guard only
    # inspected exceptions, and classify_lead swallows its own — so a quota
    # outage arrived as an ordinary empty result. Then the strings themselves
    # did not match: Bedrock answered ValidationException "Operation not
    # allowed" (an account-level model-access refusal), which is in no
    # transient word list, and 5,956 leads were marked unclassifiable in 156
    # seconds by an infrastructure failure that had nothing to do with them.
    #
    # The robust signal is not the wording, it is the SHAPE: a per-lead verdict
    # affects some leads, an outage affects every lead in a row. Consecutive
    # failures are therefore the backstop, whatever the text says.
    consecutive_failures = 0
    # Ids marked during the CURRENT failure streak. If the streak turns out to
    # be an outage, these marks were wrong — a lead is not unclassifiable
    # because the provider was down — so they are rolled back on abort.
    streak_marked: list = []

    while stats["processed"] < budget:
        batch = list(E.find(selector).limit(100))
        if not batch:
            logger.info("nothing left to process")
            break

        for doc in batch:
            if stats["processed"] >= budget:
                break
            name = (doc.get("name") or "").strip()
            title = (doc.get("title") or "").strip()

            if not name and not title:
                stats["unusable"] += 1
                stats["processed"] += 1
                if not args.dry_run:
                    E.update_one({"_id": doc["_id"]},
                                 {"$set": {DONE_MARK: datetime.utcnow(),
                                           "ai_classification_result": "no_input"}})
                continue

            if args.dry_run:
                stats["would_process"] += 1
                stats["processed"] += 1
                continue

            try:
                lead = LeadRaw(
                    name=name or "Unknown",
                    title=title or "Unknown",
                    linkedin_url=doc.get("linkedin_url") or f"urn:enriched:{doc['_id']}",
                    snippet=doc.get("snippet") or "",
                    source=doc.get("source") or "backfill",
                    company_name=doc.get("company_name") or doc.get("company") or None,
                    email=doc.get("email") or None,
                    location=doc.get("location") or None,
                )
                result, call_log = classify_lead(lead, source="background")
            except Exception as exc:
                if _is_transient(exc):
                    logger.error(
                        "TRANSIENT failure after %d leads (%s: %s) — stopping "
                        "rather than spinning. Re-run when it clears.",
                        stats["processed"], type(exc).__name__, str(exc)[:160])
                    stats["stopped_transient"] += 1
                    _report(stats, t0, args)
                    return 2
                stats["error"] += 1
                stats["processed"] += 1
                consecutive_failures += 1
                if consecutive_failures >= args.abort_after:
                    logger.error(
                        "%d CONSECUTIVE failures — stopping. Last: %s: %s",
                        consecutive_failures, type(exc).__name__, str(exc)[:160])
                    _rollback_streak(E, streak_marked, stats)
                    _report(stats, t0, args)
                    return 2
                E.update_one({"_id": doc["_id"]},
                             {"$set": {DONE_MARK: datetime.utcnow(),
                                       "ai_classification_result":
                                           f"error:{type(exc).__name__}"}})
                continue

            stats["processed"] += 1
            if not result:
                # classify_lead CATCHES its own exceptions and returns
                # (None, log) — so a quota or throttling failure arrives here
                # as an ordinary empty result, not as a raised exception. The
                # first version of this guard only inspected exceptions and
                # therefore marked 5 leads permanently "empty" during a run
                # where the real cause was the daily cap. Inspect the log too.
                err = getattr(call_log, "error_message", "") or ""
                consecutive_failures += 1
                if _is_transient_text(err) or consecutive_failures >= args.abort_after:
                    if consecutive_failures >= args.abort_after:
                        logger.error(
                            "%d CONSECUTIVE failures — this is an outage, not "
                            "a property of these leads. Last error: %s",
                            consecutive_failures, err[:200])
                    _rollback_streak(E, streak_marked, stats)
                    logger.error(
                        "TRANSIENT failure after %d leads (%s) — stopping "
                        "rather than marking leads unclassifiable. Re-run when "
                        "it clears.", stats["processed"], err[:160])
                    stats["stopped_transient"] += 1
                    _report(stats, t0, args)
                    return 2
                stats["no_result"] += 1
                streak_marked.append(doc["_id"])
                E.update_one({"_id": doc["_id"]},
                             {"$set": {DONE_MARK: datetime.utcnow(),
                                       "ai_classification_result": "empty"}})
                continue

            out = result.model_dump()
            update = {f: getattr(out[f], "value", out[f])
                      for f in FIELDS if out.get(f) not in (None, "")}
            update[DONE_MARK] = datetime.utcnow()
            update["ai_classification_result"] = "ok"
            update.setdefault("seniority_level", "Unknown")
            E.update_one({"_id": doc["_id"]}, {"$set": update})
            stats["ok"] += 1
            consecutive_failures = 0
            streak_marked.clear()

            if stats["processed"] % 100 == 0:
                el = time.time() - t0
                logger.info("  processed=%d ok=%d err=%d %.2f/s",
                            stats["processed"], stats["ok"], stats["error"],
                            stats["processed"] / max(el, 1))

    _report(stats, t0, args)
    return 0


def _rollback_streak(collection, ids, stats) -> None:
    """
    Un-mark the leads written during a failure streak that turned out to be an
    outage. Without this the run leaves them permanently skipped for a reason
    that had nothing to do with them — which is exactly how 5,956 leads were
    written off in 156 seconds by a Bedrock "Operation not allowed".
    """
    if not ids:
        return
    result = collection.update_many(
        {"_id": {"$in": list(ids)}},
        {"$unset": {DONE_MARK: "", "ai_classification_result": ""}})
    stats["rolled_back"] = result.modified_count
    logger.info("rolled back %d marks written during the failed streak",
                result.modified_count)
    ids.clear()


def _report(stats, t0, args):
    logger.info("=== %s ===", "DRY RUN" if args.dry_run else "complete")
    for key in sorted(stats):
        logger.info("  %-20s %d", key, stats[key])
    logger.info("  elapsed %.0fs", time.time() - t0)


if __name__ == "__main__":
    sys.exit(main())
