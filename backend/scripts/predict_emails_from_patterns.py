"""
Predict missing email addresses by LEARNING each company's pattern from
addresses we have already proven deliverable — not by guessing formats.

WHY NOT THE EXISTING APPROACH
-----------------------------
bounce_recovery's alt_format step walks six common formats in order and sends
to the first untried one. That is guessing, and the recorded bounces show what
it costs: of 11,508 bounces, the great majority are format guesses that were
simply wrong, and the 2026-08 incident put the bounce rate at 45%.

Every wrong guess is charged to the sending domain's reputation, so a guess is
not free — it is the most expensive kind of send.

THE EVIDENCE WE ALREADY HAVE
----------------------------
22,117 leads include 6,984 addresses marked Delivered and 570 Valid. Each one
proves what that company's address format actually is. Across 4,674 distinct
domains, that is ground truth sitting unused while the recovery chain guessed.

    ipsos.com     249 proven-deliverable addresses
    bms.com        11
    usbank.com      3

METHOD
------
For each domain, derive the format from its known-good addresses (first.last,
flast, first_last, first, firstlast, f.last). Require agreement: a domain whose
proven addresses disagree teaches nothing, so it is skipped rather than guessed
at. Then apply that format to colleagues at the same domain who have no
address, marking them email_status="pattern_derived" and recording the
evidence count so the confidence is auditable.

This is deliberately narrow. It only serves leads that already have a company
domain AND a colleague with a proven address — 394 leads on current data. The
~8,500 remaining emailless leads have no company domain at all and need the
company inferred first, which is a model's job, not a pattern's.

    python -m scripts.predict_emails_from_patterns --dry-run
    python -m scripts.predict_emails_from_patterns
"""

import argparse
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

from database import get_database
from leads.bounce_recovery import is_unsendable_domain

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("predict_emails")

PROVEN = ["Delivered", "Valid"]

# Domains that look real but are ours-invented; never learn or apply a pattern.
JUNK_DOMAINS = {"unknown.com", "company.com", "domain.com", "example.com",
                "none.com", "null.com", "n/a", "na.com"}

# Minimum proven addresses before we trust a domain's pattern. One is enough
# when it is unambiguous, but two agreeing is materially safer.
MIN_EVIDENCE = 1


def _norm(value: str) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def _derive_format(local: str, first: str, last: str) -> str:
    """Which known format produces `local` from this person's name?"""
    f, l = _norm(first), _norm(last)
    if not f or not l:
        return ""
    local = local.lower()
    candidates = {
        "{first}.{last}": f"{f}.{l}",
        "{first}_{last}": f"{f}_{l}",
        "{first}{last}": f"{f}{l}",
        "{f}{last}": f"{f[0]}{l}",
        "{f}.{last}": f"{f[0]}.{l}",
        "{first}": f,
        "{last}{f}": f"{l}{f[0]}",
        "{first}-{last}": f"{f}-{l}",
    }
    for fmt, rendered in candidates.items():
        if rendered == local:
            return fmt
    return ""


def _render(fmt: str, first: str, last: str, domain: str) -> str:
    f, l = _norm(first), _norm(last)
    if not f or not l:
        return ""
    local = (fmt.replace("{first}", f).replace("{last}", l)
                .replace("{f}", f[0]).replace("{l}", l[0]))
    return f"{local}@{domain}"


def _domain_of(doc) -> str:
    dom = (doc.get("company_domain") or "").strip().lower()
    if not dom and doc.get("company_website"):
        dom = re.sub(r"^https?://", "", str(doc["company_website"])).split("/")[0].lower()
    return dom.replace("www.", "").strip()


def _split_name(doc):
    first = (doc.get("first_name") or "").strip()
    last = (doc.get("last_name") or "").strip()
    if not (first and last):
        parts = (doc.get("name") or "").strip().split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
    return first, last


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    E = get_database("email_automation")["leads_enriched"]

    # ---- learn ----------------------------------------------------------
    votes = defaultdict(Counter)
    for doc in E.find({"email_status": {"$in": PROVEN},
                       "email": {"$nin": [None, ""]}},
                      {"email": 1, "first_name": 1, "last_name": 1, "name": 1}):
        email = (doc.get("email") or "").lower()
        if "@" not in email:
            continue
        local, domain = email.split("@", 1)
        if domain in JUNK_DOMAINS or is_unsendable_domain(email):
            continue
        first, last = _split_name(doc)
        fmt = _derive_format(local, first, last)
        if fmt:
            votes[domain][fmt] += 1

    patterns = {}
    ambiguous = 0
    for domain, counter in votes.items():
        top, n = counter.most_common(1)[0]
        if n < MIN_EVIDENCE:
            continue
        # A domain whose proven addresses disagree teaches nothing. Require the
        # leading format to be a strict majority rather than merely first.
        if sum(counter.values()) > 1 and n <= sum(counter.values()) / 2:
            ambiguous += 1
            continue
        patterns[domain] = (top, n)

    logger.info("domains with proven addresses : %d", len(votes))
    logger.info("domains with a usable pattern : %d", len(patterns))
    logger.info("domains skipped as ambiguous  : %d", ambiguous)

    # ---- apply ----------------------------------------------------------
    stats = Counter()
    selector = {"$or": [{"email": None}, {"email": ""}, {"email": {"$exists": False}}]}
    cursor = E.find(selector)
    if args.limit:
        cursor = cursor.limit(args.limit)

    for doc in cursor:
        stats["scanned"] += 1
        domain = _domain_of(doc)
        if not domain or domain in JUNK_DOMAINS:
            stats["no_domain"] += 1
            continue
        entry = patterns.get(domain)
        if not entry:
            stats["no_pattern_for_domain"] += 1
            continue
        fmt, evidence = entry
        first, last = _split_name(doc)
        predicted = _render(fmt, first, last, domain)
        if not predicted or is_unsendable_domain(predicted):
            stats["unrenderable"] += 1
            continue
        if E.count_documents({"email": predicted}, limit=1):
            stats["collision"] += 1
            continue

        stats["predicted"] += 1
        if not args.dry_run:
            E.update_one({"_id": doc["_id"]}, {"$set": {
                "email": predicted,
                "email_status": "pattern_derived",
                "email_source": "domain_pattern_learned",
                "email_pattern_used": fmt,
                "email_pattern_evidence": evidence,
                "email_predicted_at": datetime.utcnow(),
            }})

    logger.info("=== %s ===", "DRY RUN" if args.dry_run else "complete")
    for key in sorted(stats):
        logger.info("  %-24s %d", key, stats[key])
    if args.dry_run:
        logger.info("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
