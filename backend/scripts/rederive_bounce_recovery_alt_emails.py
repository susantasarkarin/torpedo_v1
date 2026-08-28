"""
NULL-OUT AND RE-DERIVE: bounce_recovery_alt-sourced leads
===========================================================
The alt_format guesser (leads/bounce_recovery.py, disabled by default since
2026-08-03 after driving 45%/44% bounce rates — see _ALT_FORMAT_ENABLED)
produced 4,734 addresses now sitting in leads_enriched. Most passed the
outreach qualification gate ungated regardless of email_status, because the
gate didn't check provenance (email_source) until this session's fix.

Root-cause classification, not confidence tuning: these addresses were never
observed anywhere, only rendered from 6 fixed local-part templates against a
guessed domain. No confidence value can make that trustworthy. The right fix
is to throw the guess away and let the address get re-derived through the
same tiered EmailPatternSystem (DB pattern -> CSV analysis -> website scrape
-> Skrapp -> Hunter -> Claude web search -> last-resort guess) everything
else in the pipeline uses.

This script, per lead with email_source == "bounce_recovery_alt" and no
email_pattern_confidence recorded (i.e. not already re-derived by some other
path since):
  1. Nulls email, email_status, email_source, email_pattern_confidence, and
     bounce_recovery_status on BOTH leads_enriched and the linked leads_raw
     doc (via raw_lead_id).
  2. Immediately re-derives via EmailPatternSystem.build_email_with_source()
     using the lead's existing first_name/last_name/company_domain. NO
     re-classification — person/company classification isn't what's broken
     here, only the email was ever templated.
  3. A lead with no company_domain cannot be re-derived at all
     (build_email_with_source requires one) and is left with email=None —
     landing correctly in a blocked/no-email state, not silently re-guessed.

Safety:
  - Fingerprint guard matching scripts/rederive_dual_fit_baskets.py: refuses
    to run unless leads_raw is in the production size range.
  - --dry-run makes ZERO writes, including to email_patterns. It does NOT
    call EmailPatternSystem.get_pattern()/build_email_with_source() (those
    have real side effects even when they "just look something up" — a
    stored pattern gets discovered via a real website-scrape HTTP request
    and written to email_patterns via _store_pattern). Dry-run instead reads
    the email_patterns collection directly with find_one() to estimate
    whether each domain already has a stored pattern, with zero calls out.

Usage:
    python -m scripts.rederive_bounce_recovery_alt_emails --dry-run
    python -m scripts.rederive_bounce_recovery_alt_emails
    python -m scripts.rederive_bounce_recovery_alt_emails --limit 50
"""
import argparse
import logging
import os
import sys
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("rederive_bounce_alt")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

TARGET_EMAIL_SOURCE = "bounce_recovery_alt"

NULL_FIELDS = {
    "email": None,
    "email_status": None,
    "email_source": None,
    "email_pattern_confidence": None,
    "bounce_recovery_status": None,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = c["email_automation"]
    enr = db["leads_enriched"]
    raw = db["leads_raw"]
    patterns = db["email_patterns"]

    fp = raw.count_documents({})
    print("FINGERPRINT leads_raw =", fp)
    if not (19000 <= fp <= 25000):
        print("NOT PRODUCTION - refusing to run")
        return 2

    q = {
        "email_source": TARGET_EMAIL_SOURCE,
        "$or": [{"email_pattern_confidence": {"$exists": False}},
                {"email_pattern_confidence": None}],
    }
    total = enr.count_documents(q)
    print(f"target leads (email_source={TARGET_EMAIL_SOURCE!r}, not already re-derived): {total}")

    cur = enr.find(q)
    if args.limit:
        cur = cur.limit(args.limit)

    now = datetime.utcnow()
    n = 0
    re_derived = 0
    left_blocked_no_domain = 0
    left_blocked_no_result = 0
    web_search_calls = 0
    free_pattern_hits = 0

    ps = None
    if not args.dry_run:
        from leads.email_pattern_system import get_pattern_system
        ps = get_pattern_system()

    for doc in cur:
        n += 1
        first = doc.get("first_name") or ""
        last = doc.get("last_name") or ""
        domain = (doc.get("company_domain") or "").lower().strip()
        raw_lead_id = doc.get("raw_lead_id")

        if not domain:
            left_blocked_no_domain += 1
            if not args.dry_run:
                enr.update_one({"_id": doc["_id"]}, {"$set": {**NULL_FIELDS, "updated_at": now}})
                if raw_lead_id:
                    try:
                        raw.update_one({"_id": ObjectId(str(raw_lead_id))},
                                       {"$set": {"email": None, "email_status": None,
                                                 "email_source": None}})
                    except Exception:
                        pass
            if n % 500 == 0:
                print(f"   ...{n}/{total}")
            continue

        # Zero-side-effect estimate: a direct collection read, not get_pattern().
        stored = patterns.find_one({"domain": domain})
        has_confident_pattern = bool(
            stored and stored.get("confidence", 0) >= 0.5 and stored.get("source") != "guess"
        )

        if args.dry_run:
            if has_confident_pattern:
                free_pattern_hits += 1
                re_derived += 1
            else:
                web_search_calls += 1
                # Can't know without calling live whether the web search will
                # actually find something; dry-run reports it as a call that
                # WOULD be attempted, not a guaranteed re-derivation.
            if n % 500 == 0:
                print(f"   ...{n}/{total}")
            continue

        # LIVE: null first, then re-derive.
        enr.update_one({"_id": doc["_id"]}, {"$set": {**NULL_FIELDS, "updated_at": now}})
        if raw_lead_id:
            try:
                raw.update_one({"_id": ObjectId(str(raw_lead_id))},
                               {"$set": {"email": None, "email_status": None,
                                         "email_source": None}})
            except Exception:
                pass

        if not has_confident_pattern:
            web_search_calls += 1
        built_email, confidence, source = ps.build_email_with_source(
            first, last, domain, company_name=doc.get("company_name", ""),
        )
        if has_confident_pattern:
            free_pattern_hits += 1

        if built_email:
            enr.update_one({"_id": doc["_id"]}, {"$set": {
                "email": built_email,
                "email_status": "Predicted",
                "email_source": source,
                "email_pattern_confidence": confidence,
                "updated_at": datetime.utcnow(),
            }})
            if raw_lead_id:
                try:
                    raw.update_one({"_id": ObjectId(str(raw_lead_id))},
                                   {"$set": {"email": built_email}})
                except Exception:
                    pass
            re_derived += 1
        else:
            left_blocked_no_result += 1

        if n % 200 == 0:
            print(f"   ...{n}/{total}")

    print(f"\nprocessed {n}")
    print(f"  re-derived with a new email: {re_derived}")
    print(f"  ...of which, free stored-pattern hits: {free_pattern_hits}")
    print(f"  left blocked, no company_domain: {left_blocked_no_domain}")
    print(f"  left blocked, no result found: {left_blocked_no_result}")
    print(f"  web-search calls made (or, in dry-run, would be attempted): {web_search_calls}")
    if args.dry_run:
        print("\nDRY RUN - nothing written, no network calls made")
    else:
        print("\nremaining un-re-derived bounce_recovery_alt leads:",
              enr.count_documents(q))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
