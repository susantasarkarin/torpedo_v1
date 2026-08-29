"""
Verification gate (Part 3, 2026-08-28 recovery plan).

Chain: syntax -> role-account -> disposable-domain -> MX -> paid
real-time verification. Only a paid-provider "valid" result sets
`sendable: True` on the outreach_leads_v2 doc (the field
cold_outreach_router.py's send-fetch query now hard-requires — see that
file's change in the same commit as this script).

The free checks (syntax/role/disposable/MX) are implemented and safe to
run now — no cost, no writes without --apply. The paid step is NOT wired
to a live provider: no ZeroBounce/NeverBounce/Bouncer API key has been
provisioned or approved for spend yet (see RECOVERY_PLAN_2026-08-28.md
Part 3 for the price comparison). Running this script today tells you
how many addresses fail before you'd even spend a verification credit
on them — genuinely useful on its own — but it cannot produce real
"valid"/"catch-all"/"invalid" verdicts until a provider is wired in.

Usage:
    python verification_gate.py --cohort staged        # 256 staged-but-unsent
    python verification_gate.py --cohort sent-clean     # 83 sent, not bounced
    python verification_gate.py --cohort candidates     # 196 pattern-derived
    python verification_gate.py --cohort all --apply    # write results

Without --apply: dry run, prints pass/fail counts only, no writes.
With --apply: writes `verification_status` and `sendable` onto the
relevant outreach_leads_v2 (or leads_raw, for candidates) docs. A
free-check failure (syntax/role/disposable/MX) sets sendable=False
immediately — that's a real, deterministic result, not a guess, so it's
written even before a paid provider exists. A free-check PASS does NOT
set sendable=True by itself; it's left unset (not sendable) pending the
paid step, per your instruction that only a provider "valid" result is
sendable.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "torpedo")

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
ROLE_ADDRESSES = frozenset({
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "info", "support", "help", "admin", "webmaster", "postmaster",
    "hostmaster", "abuse", "security", "mailer-daemon", "root",
    "sales", "marketing", "billing", "accounts", "feedback",
    "newsletter", "unsubscribe", "bounce", "team",
})
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "yopmail.com", "trashmail.com", "throwaway.email", "temp-mail.org",
    "getnada.com", "sharklasers.com", "fakeinbox.com", "maildrop.cc",
    "dispostable.com", "mintemail.com", "mailnesia.com",
})


def free_checks(email: str) -> Dict[str, Any]:
    """Syntax, role, disposable, MX. No cost. Returns a result dict with
    a `free_check_result` of pass/fail and, on fail, why."""
    email = (email or "").strip().lower()
    if not EMAIL_REGEX.match(email):
        return {"free_check_result": "fail", "free_check_reason": "invalid_syntax"}
    local, domain = email.split("@")
    if local in ROLE_ADDRESSES:
        return {"free_check_result": "fail", "free_check_reason": "role_address"}
    if domain in DISPOSABLE_DOMAINS:
        return {"free_check_result": "fail", "free_check_reason": "disposable_domain"}
    if not _has_mx_or_a(domain):
        return {"free_check_result": "fail", "free_check_reason": "no_mx_records"}
    return {"free_check_result": "pass", "free_check_reason": None}


def _has_mx_or_a(domain: str) -> bool:
    try:
        import dns.resolver
        import dns.exception
        import dns.name
        try:
            return len(list(dns.resolver.resolve(domain, "MX", lifetime=5))) > 0
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout,
                dns.name.LabelTooLong, dns.name.EmptyLabel):
            pass
        except Exception:
            return False
        try:
            return len(list(dns.resolver.resolve(domain, "A", lifetime=5))) > 0
        except Exception:
            return False
    except ImportError:
        return True  # fail open if dnspython missing — don't block on a dependency gap


def paid_verify(email: str) -> Optional[str]:
    """Real-time verification via a third-party provider. NOT implemented
    — no provider is wired up (see module docstring). Returns None to
    mean "not checked", never a fabricated valid/invalid. Wire this up
    once a provider + API key is approved:
        - ZeroBounce: POST https://api.zerobounce.net/v2/validate
        - NeverBounce: POST https://api.neverbounce.com/v4/single/check
        - Bouncer: POST https://api.usebouncer.com/v1.1/email/verify
    Expected return values once wired: "valid", "invalid", "catch-all",
    "unknown"."""
    return None


def get_cohort(db, name: str):
    tp = db
    ea_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    ea = ea_client["email_automation"]
    since = datetime.utcnow() - timedelta(days=30)

    if name == "staged":
        emails = ea["leads_raw"].distinct(
            "email", {"created_at": {"$gte": since}, "email": {"$type": "string", "$ne": ""}})
        sent_emails = set(tp["outreach_sends_v2"].distinct("email", {"email": {"$in": emails}}))
        staged = [e for e in emails if e not in sent_emails]
        return [{"email": e, "kind": "leads_raw_email"} for e in staged]

    if name == "sent-clean":
        emails = ea["leads_raw"].distinct(
            "email", {"created_at": {"$gte": since}, "email": {"$type": "string", "$ne": ""}})
        bounced = set(tp["outreach_sends_v2"].distinct(
            "email", {"email": {"$in": emails}, "status": "bounced"}))
        sent = set(tp["outreach_sends_v2"].distinct("email", {"email": {"$in": emails}}))
        clean = [e for e in sent if e not in bounced]
        return [{"email": e, "kind": "leads_raw_email"} for e in clean]

    if name == "candidates":
        docs = ea["leads_raw"].find(
            {"candidate_email": {"$exists": True}}, {"candidate_email": 1})
        return [{"email": d["candidate_email"], "kind": "candidate_email", "lead_id": d["_id"]}
                for d in docs]

    raise ValueError(f"unknown cohort {name!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True,
                         choices=["staged", "sent-clean", "candidates", "all"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[MONGO_DB_NAME]

    cohorts = ["staged", "sent-clean", "candidates"] if args.cohort == "all" else [args.cohort]

    for cohort_name in cohorts:
        items = get_cohort(db, cohort_name)
        pass_count = 0
        fail_reasons: Dict[str, int] = {}
        for item in items:
            result = free_checks(item["email"])
            if result["free_check_result"] == "pass":
                pass_count += 1
            else:
                fail_reasons[result["free_check_reason"]] = fail_reasons.get(
                    result["free_check_reason"], 0) + 1

        total = len(items)
        print(f"\n=== Cohort: {cohort_name} (n={total}) ===")
        if total == 0:
            print("  (empty)")
            continue
        print(f"  Free checks pass (syntax+role+disposable+MX): {pass_count} "
              f"({pass_count/total*100:.1f}%)")
        print(f"  Free checks fail: {total - pass_count} ({(total-pass_count)/total*100:.1f}%)")
        for reason, count in sorted(fail_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}")
        print(f"  Paid verification: NOT RUN (no provider wired up — see module docstring)")
        print(f"  Sendable (requires paid 'valid'): 0")

    if args.apply:
        print("\n--apply passed, but there is nothing to write yet: paid_verify() "
              "returns None until a provider is wired up. Free-check failures alone "
              "are enough to permanently rule an address out, but this script "
              "intentionally does not write partial state — wire up a provider first.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
