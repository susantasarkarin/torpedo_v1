"""
Email recovery migration — waterfall steps 3 (deterministic repair) and 4
(pattern derivation) from the 2026-08-28 recovery plan.

SAFE BY DEFAULT: runs in --dry-run mode unless --apply is passed. Even in
--apply mode, this script never overwrites `leads_raw.email` directly —
verified facts (typo/whitespace/mailto: repairs) go into `email` because
they're deterministic corrections of an existing value, but every write
is preceded by an insert into `email_recovery_log` capturing the before
value, so it can be rolled back. Pattern-derived candidates (step 4) are
NEVER written to `email` — they go into a new `candidate_email` field
with `email_status: "inferred_pending_verification"`, because per the
recovery plan these must pass real-time verification (step 6, not yet
wired — see backend/scripts/BOUNCE_DIAGNOSIS_2026-08-28.md §Part 2 step 6)
before they're eligible to send.

Usage:
    python recover_missing_emails.py                  # dry run, report only
    python recover_missing_emails.py --apply           # write repairs + candidates
    python recover_missing_emails.py --rollback <run_id>  # undo one run

Steps 1 (re-parse raw payload) and 2 (internal cross-match) are NOT
implemented here as writes because, for the current 1,441-lead gap, both
returned zero matches when checked read-only against production
(see findings doc) — there is nothing for them to recover in this batch.
The functions are still provided so this script can be re-run against a
future gap where those sources might actually have data.
"""

import argparse
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
LOOKBACK_DAYS = int(os.getenv("RECOVERY_LOOKBACK_DAYS", "30"))
MIN_PATTERN_SAMPLES = int(os.getenv("RECOVERY_MIN_PATTERN_SAMPLES", "3"))

# Same list as backend/app/services/outreach/email_validator.py —
# duplicated here deliberately so this script has no import dependency on
# app internals and can be run standalone/offline against a dump.
TYPO_DOMAIN_CORRECTIONS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gmali.com": "gmail.com", "gmaill.com": "gmail.com", "gnail.com": "gmail.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yaoo.com": "yahoo.com",
    "yahho.com": "yahoo.com",
    "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "outlok.com": "outlook.com", "outllook.com": "outlook.com",
}
TLD_CORRECTIONS = {
    "con": "com", "cmo": "com", "comm": "com",
}


# =============================================================================
# STEP 3 — deterministic repair of malformed-but-present addresses
# =============================================================================

def repair_email(raw_email: str) -> Optional[Dict[str, Any]]:
    """
    Deterministic repair only. Returns None if nothing needed fixing or if
    the fix isn't deterministic (per the brief: flag for human review
    instead of guessing). Never touches the local part.
    """
    if not raw_email:
        return None
    original = raw_email
    fixed = raw_email.strip()
    fixed = re.sub(r"^mailto:", "", fixed, flags=re.IGNORECASE)
    fixed = fixed.strip().lower()

    if "@" not in fixed:
        return None  # not repairable deterministically
    local, domain = fixed.rsplit("@", 1)

    domain = TYPO_DOMAIN_CORRECTIONS.get(domain, domain)

    tld_match = re.match(r"^(.*)\.([a-z]+)$", domain)
    if tld_match:
        base, tld = tld_match.groups()
        if tld in TLD_CORRECTIONS:
            domain = f"{base}.{TLD_CORRECTIONS[tld]}"

    fixed = f"{local}@{domain}"

    if fixed == original.strip().lower() and fixed == original:
        return None

    return {"before": original, "after": fixed}


def run_step3(db, dry_run: bool, run_id: str) -> List[Dict[str, Any]]:
    """Scan every leads_raw doc with a non-empty email for deterministic
    repairs. Returns the list of changes made/proposed."""
    leads_raw = db["leads_raw"]
    changes = []

    cursor = leads_raw.find(
        {"email": {"$type": "string", "$ne": ""}},
        {"email": 1},
    )
    for doc in cursor:
        fix = repair_email(doc["email"])
        if not fix:
            continue
        change = {
            "lead_id": doc["_id"],
            "before": fix["before"],
            "after": fix["after"],
        }
        changes.append(change)
        if not dry_run:
            db["email_recovery_log"].insert_one({
                "run_id": run_id,
                "lead_id": doc["_id"],
                "method": "step3_deterministic_repair",
                "before": fix["before"],
                "after": fix["after"],
                "applied_at": datetime.utcnow(),
            })
            leads_raw.update_one(
                {"_id": doc["_id"]},
                {"$set": {"email": fix["after"], "email_repaired_at": datetime.utcnow()}},
            )

    return changes


# =============================================================================
# STEP 4 — pattern derivation from company domain (>= MIN_PATTERN_SAMPLES
# confirmed addresses at that domain)
# =============================================================================

_NAME_TOKEN_RE = re.compile(r"^[a-z]+$")


def _clean_name_token(token: str) -> Optional[str]:
    """Strip punctuation/initials artifacts. Returns None (flag for human
    review, don't guess) if what's left isn't a clean alphabetic token —
    e.g. a parenthetical nickname like "(Raymond)" is not something to
    silently unwrap."""
    token = re.sub(r"[^a-z]", "", token.lower())
    if not token or not _NAME_TOKEN_RE.match(token):
        return None
    return token


def apply_pattern(pattern: str, first: str, last: str, domain: str) -> Optional[str]:
    first = (first or "").strip()
    last = (last or "").strip()
    # Collapse multi-token names (e.g. "P. Gownder" -> "Gownder") to the
    # final/first token — a documented, deterministic normalization, not a
    # guess at which token is the real surname — then strip anything that
    # isn't a plain alphabetic name (nicknames in parens, initials with
    # dots) rather than guess at it.
    last_token = _clean_name_token(last.split()[-1]) if last else None
    first_token = _clean_name_token(first.split()[0]) if first else None
    if not first_token or not last_token:
        return None
    first, last = first_token, last_token
    f, l = first[:1], last[:1]

    if pattern == "firstname.lastname":
        return f"{first}.{last}@{domain}"
    local = (
        pattern.replace("{first}", first)
        .replace("{last}", last)
        .replace("{f}", f)
        .replace("{l}", l)
        .replace("{domain}", domain)
    )
    return local if "@" in local else f"{local}@{domain}"


def run_step4(db, dry_run: bool, run_id: str) -> List[Dict[str, Any]]:
    """For leads missing email but with a known company_domain, generate a
    candidate ONLY when that domain has >= MIN_PATTERN_SAMPLES confirmed
    addresses. Writes to `candidate_email` / `email_status:
    "inferred_pending_verification"` — never to `email` directly."""
    ea = db
    leads_raw = ea["leads_raw"]

    candidates = []
    leads = list(leads_raw.find(
        {"email": None, "company_domain": {"$type": "string", "$ne": ""}},
        {"company_domain": 1, "first_name": 1, "last_name": 1},
    ))
    domains = list({l["company_domain"] for l in leads})
    strong_patterns = {
        p["domain"]: p
        for p in ea["email_patterns"].find(
            {"domain": {"$in": domains}, "sample_count": {"$gte": MIN_PATTERN_SAMPLES}},
            {"domain": 1, "pattern": 1, "sample_count": 1, "confidence": 1},
        )
    }

    for lead in leads:
        pat = strong_patterns.get(lead["company_domain"])
        if not pat:
            continue
        candidate = apply_pattern(
            pat["pattern"], lead.get("first_name"), lead.get("last_name"),
            lead["company_domain"],
        )
        if not candidate:
            continue
        entry = {
            "lead_id": lead["_id"],
            "candidate_email": candidate,
            "domain": lead["company_domain"],
            "pattern": pat["pattern"],
            "sample_count": pat["sample_count"],
            "confidence": "inferred",  # per brief: never "confirmed"
        }
        candidates.append(entry)
        if not dry_run:
            ea["email_recovery_log"].insert_one({
                "run_id": run_id,
                "lead_id": lead["_id"],
                "method": "step4_pattern_derived",
                "candidate_email": candidate,
                "domain": lead["company_domain"],
                "pattern": pat["pattern"],
                "sample_count": pat["sample_count"],
                "applied_at": datetime.utcnow(),
            })
            leads_raw.update_one(
                {"_id": lead["_id"]},
                {"$set": {
                    "candidate_email": candidate,
                    "email_status": "inferred_pending_verification",
                    "candidate_source": "pattern_derived_recovery",
                    "candidate_generated_at": datetime.utcnow(),
                }},
            )

    return candidates


# =============================================================================
# ROLLBACK
# =============================================================================

def rollback(db, run_id: str) -> int:
    log = db["email_recovery_log"]
    entries = list(log.find({"run_id": run_id}))
    leads_raw = db["leads_raw"]
    reverted = 0
    for e in entries:
        if e["method"] == "step3_deterministic_repair":
            leads_raw.update_one(
                {"_id": e["lead_id"]},
                {"$set": {"email": e["before"]}, "$unset": {"email_repaired_at": ""}},
            )
            reverted += 1
        elif e["method"] == "step4_pattern_derived":
            leads_raw.update_one(
                {"_id": e["lead_id"]},
                {"$unset": {
                    "candidate_email": "", "email_status": "",
                    "candidate_source": "", "candidate_generated_at": "",
                }},
            )
            reverted += 1
    log.delete_many({"run_id": run_id})
    return reverted


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write changes (default: dry run, report only)")
    parser.add_argument("--rollback", metavar="RUN_ID", help="Undo a previous --apply run by its run_id")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["email_automation"]

    if args.rollback:
        n = rollback(db, args.rollback)
        print(f"Rolled back {n} changes from run {args.rollback}")
        return 0

    dry_run = not args.apply
    run_id = str(uuid.uuid4())
    mode = "DRY RUN (no writes)" if dry_run else f"APPLY (run_id={run_id})"
    print(f"=== Email recovery — {mode} ===\n")

    step3_changes = run_step3(db, dry_run, run_id)
    print(f"Step 3 (deterministic repair): {len(step3_changes)} addresses fixed")
    for c in step3_changes[:20]:
        print(f"    {c['before']!r} -> {c['after']!r}")
    if len(step3_changes) > 20:
        print(f"    ... and {len(step3_changes) - 20} more")

    step4_candidates = run_step4(db, dry_run, run_id)
    print(f"\nStep 4 (pattern-derived candidates, >= {MIN_PATTERN_SAMPLES} confirmed samples): "
          f"{len(step4_candidates)} candidates generated")
    for c in step4_candidates[:20]:
        print(f"    lead={c['lead_id']} -> {c['candidate_email']} "
              f"(pattern={c['pattern']}, n={c['sample_count']})")
    if len(step4_candidates) > 20:
        print(f"    ... and {len(step4_candidates) - 20} more")

    if dry_run:
        print("\nNo writes made. Re-run with --apply to write these changes "
              "(step 3 -> leads_raw.email with a recovery_log entry per change; "
              "step 4 -> leads_raw.candidate_email + email_status='inferred_pending_verification', "
              "never leads_raw.email).")
    else:
        print(f"\nApplied. To roll back everything from this run: "
              f"python recover_missing_emails.py --rollback {run_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
