"""
Adds a parent/child hierarchy to crm_db.accounts so MNC divisions (e.g.
"Ipsos", "Ipsos India", "Ipsos North America") and per-contact accounts
(e.g. "Alicia Wong (Ipsos)") can be grouped under one canonical parent,
without touching any of the 5 separate app surfaces that read accounts.

Grouping is STRICT domain-based only: an account is grouped with others
only if it shares a contact/email/website root domain. No fuzzy name
matching, to avoid accidentally merging unrelated companies.

New fields added to crm_db.accounts (additive, non-breaking):
  - parent_account_id: str | None
  - is_parent: bool
  - location: str | None   (best-effort, regex-extracted from the account name)
  - root_domain: str | None

Usage (from backend/):
    python3 consolidate_accounts.py --dry-run
    python3 consolidate_accounts.py --apply
"""
import sys
import os
import re
import argparse
from collections import defaultdict, Counter

sys.path.insert(0, '.')

from pymongo import MongoClient
from bson import ObjectId


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from .database import get_client
    except ImportError:
        from database import get_client
    return get_client()


MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
mongo = _get_pooled_client()
crm_db = mongo['crm_db']
accounts_coll = crm_db['accounts']
contacts_coll = crm_db['contacts']
finance_db = mongo['finance_db']

FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "mail.com", "protonmail.com",
    "zoho.com", "yandex.com", "gmx.com", "rediffmail.com", "googlemail.com",
}

# Never group under our own domain — a finance record with our own team's
# email stored on it (data-entry artifact) should not pull an external
# vendor/client into an "internal" group.
OWN_DOMAINS = {"cogentixresearch.com", "surveyfieldwork.com"}

LOCATION_KEYWORDS = [
    "india", "north america", "south america", "latam", "apac", "emea",
    "uk", "united kingdom", "usa", "united states", "china", "japan",
    "europe", "australia", "canada", "germany", "france", "singapore",
    "middle east", "africa", "mexico", "brazil",
]


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def root_domain_of_account(account: dict, contacts: list) -> str:
    """Best-effort root domain: account.email/website, then linked contacts,
    then (for finance-mirrored accounts with no contact) the source
    finance_db.customers/vendors record's email."""
    for field in ("email", "website"):
        val = (account.get(field) or "").lower()
        if val:
            val = re.sub(r'^https?://(www\.)?', '', val).split('/')[0]
            d = val if "." in val and "@" not in val else domain_of(val)
            if d and d not in FREE_EMAIL_PROVIDERS and d not in OWN_DOMAINS:
                return d

    domains = Counter(domain_of(c.get("email", "")) for c in contacts if c.get("email"))
    domains = Counter({d: n for d, n in domains.items()
                       if d and d not in FREE_EMAIL_PROVIDERS and d not in OWN_DOMAINS})
    if domains:
        return domains.most_common(1)[0][0]

    meta = account.get("metadata") or {}
    source = meta.get("source", "")
    source_id = meta.get("source_id")
    if source.startswith("finance_") and source_id:
        finance_coll = finance_db["customers"] if source == "finance_client" else finance_db["vendors"]
        try:
            party = finance_coll.find_one({"_id": ObjectId(source_id)}, {"email": 1})
        except Exception:
            party = None
        if party and party.get("email"):
            d = domain_of(party["email"].lower())
            if d and d not in FREE_EMAIL_PROVIDERS and d not in OWN_DOMAINS:
                return d
    return ""


def infer_location(name: str) -> str:
    low = name.lower()
    for kw in LOCATION_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', low):
            return kw.title()
    return ""


def is_auto_generated_person_name(name: str) -> bool:
    """Matches the 'Person Name (Company)' pattern our own auto-import scripts produce —
    never a good parent/canonical name for the company itself."""
    return bool(re.search(r'\([^)]+\)\s*$', name.strip()))


def company_from_domain(domain: str) -> str:
    return domain.split(".")[0].replace("-", " ").title()


def choose_parent(accounts_in_group: list, domain: str):
    """
    Prefer, in order:
    1. A clean company-name account: no location keyword, not an auto-generated
       "Person (Company)" pattern.
    2. If none qualifies, synthesize a new parent name from the domain instead
       of picking an arbitrary person's account as the canonical company.
    Returns (parent_account_or_None, synthesized_name_or_None).
    """
    clean = [a for a in accounts_in_group
             if not infer_location(a.get("name", "")) and not is_auto_generated_person_name(a.get("name", ""))]
    if clean:
        return min(clean, key=lambda a: len(a.get("name", ""))), None
    return None, company_from_domain(domain)


def run(dry_run: bool):
    all_accounts = list(accounts_coll.find({}, {"name": 1, "email": 1, "website": 1, "account_type": 1,
                                                   "parent_account_id": 1, "metadata": 1}))
    print(f"=== total crm_db.accounts: {len(all_accounts)} ===")

    # Pull all contacts once, index by account_id
    contacts_by_account = defaultdict(list)
    for c in contacts_coll.find({}, {"account_id": 1, "email": 1}):
        aid = c.get("account_id")
        if aid:
            contacts_by_account[str(aid)].append(c)

    domain_groups = defaultdict(list)
    ungrouped = 0
    for a in all_accounts:
        if a.get("parent_account_id"):
            continue  # already grouped from a prior run
        contacts = contacts_by_account.get(str(a["_id"]), [])
        domain = root_domain_of_account(a, contacts)
        if domain:
            domain_groups[domain].append(a)
        else:
            ungrouped += 1

    print(f"=== domains with >=2 accounts (real fragmentation): "
          f"{sum(1 for g in domain_groups.values() if len(g) >= 2)} ===")
    print(f"=== accounts with no resolvable domain (left as-is): {ungrouped} ===\n")

    updates, groups_touched, synthesized = 0, 0, 0
    for domain, group in sorted(domain_groups.items(), key=lambda kv: -len(kv[1])):
        if len(group) < 2:
            continue
        groups_touched += 1
        parent, synth_name = choose_parent(group, domain)
        children = group if parent is None else [a for a in group if a["_id"] != parent["_id"]]

        if dry_run:
            tag = f"NEW SYNTHESIZED PARENT '{synth_name}'" if parent is None else f"parent='{parent['name']}'"
            print(f"[group] domain={domain} {tag} "
                  f"children=[{', '.join(c['name'] for c in children)}]")
            continue

        if parent is None:
            new_parent_id = accounts_coll.insert_one({
                "name": synth_name, "name_normalized": synth_name.lower(),
                "account_type": children[0].get("account_type", "client"),
                "is_parent": True, "root_domain": domain,
                "metadata": {"source": "consolidation_synthesized"},
            }).inserted_id
            synthesized += 1
        else:
            new_parent_id = parent["_id"]
            accounts_coll.update_one(
                {"_id": new_parent_id},
                {"$set": {"is_parent": True, "root_domain": domain}}
            )

        for child in children:
            location = infer_location(child.get("name", ""))
            accounts_coll.update_one(
                {"_id": child["_id"]},
                {"$set": {
                    "parent_account_id": str(new_parent_id),
                    "root_domain": domain,
                    "location": location or None,
                }}
            )
            updates += 1

    if dry_run:
        print(f"\n=== DONE dry_run=True: groups_found={groups_touched} ===")
    else:
        print(f"\n=== DONE dry_run=False: groups={groups_touched} children_linked={updates} "
              f"new_parents_synthesized={synthesized} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
