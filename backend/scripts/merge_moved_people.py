"""
ONE PERSON, ONE RECORD — PEOPLE WHO CHANGED COMPANY
===================================================
A person who moves company gets a second lead record under the new address:
ramiz.jasnaik@ipsos.com (an old CSV import, AI Database) and
ramiz.jasnaik@hansaresearch.com (Gmail, a won Contact) are the same man, so
he showed on two pages. The page split (leads.service.lead_view_clause) is per
record and cannot see that.

Two records are the same person when the email's name part AND the full name
both match — `ramiz.jasnaik` + "Ramiz Jasnaik" — and the name is rare enough
to identify someone: at least one of its words belongs to no more than
RARE_NAME_MAX distinct people across all leads. Without that, amit.singh@ at
Luxottica and amit.singh@ at Nielsen (two different men) were merged. The record furthest along the
pipeline (Contact, then Lead, then AI Database; newest on a tie) is kept; the
others get `superseded_by` and drop off every list. Nothing is deleted —
unsetting `superseded_by` restores a record.

    python -m scripts.merge_moved_people            # dry run
    python -m scripts.merge_moved_people --apply
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONTACT_STAGES = {"discovery_call", "presentation", "rfq_pricing", "negotiation", "won", "lost",
                  "onboarding", "project_execution", "payment", "retention"}
TWO_WAY_SOURCES = {"gmail", "gmail_workspace", "email_sync", "email_import", "email_classification",
                   "gmail_api", "gmail_archive", "classified_gmail", "gmail_contact", "gmail_calendar",
                   "gmail_reply", "outreach_reply"}


def person_key(lead: Dict) -> Optional[Tuple[str, str]]:
    """(email name part, normalised full name), or None when either is too weak to match on."""
    email = (lead.get("email") or "").strip().lower()
    if email.count("@") != 1:
        return None
    local = email.split("@")[0]
    name = re.sub(r"\s*[|(<].*$", "", lead.get("name") or "")      # "Ramiz Jasnaik | Hansa" -> "Ramiz Jasnaik"
    if "," in name:                                                # "Jasnaik, Ramiz" -> "Ramiz Jasnaik"
        last, _, first = name.partition(",")
        name = f"{first} {last}"
    tokens = re.findall(r"[a-z]+", name.lower())
    # A name part like "info" or "j" is shared by unrelated people; require a
    # real one, and a first + last name.
    if len(re.sub(r"[^a-z]", "", local)) < 5 or len(tokens) < 2:
        return None
    return local, " ".join(sorted(tokens))


def page_rank(lead: Dict) -> int:
    if (lead.get("stage") or "") in CONTACT_STAGES:
        return 0
    if lead.get("source") in TWO_WAY_SOURCES or lead.get("outreach_replied_at"):
        return 1
    return 2


RARE_NAME_MAX = 3


def plan(leads: List[Dict]) -> List[Tuple[Dict, Dict]]:
    """(superseded, keeper) pairs."""
    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for lead in leads:
        key = person_key(lead)
        if key:
            groups[key].append(lead)
    # How many distinct people (full names) carry each name word.
    word_people: Dict[str, int] = defaultdict(int)
    for _, name in groups:
        for word in set(name.split()):
            word_people[word] += 1
    pairs = []
    for (_, name), members in groups.items():
        if min(word_people[w] for w in name.split()) > RARE_NAME_MAX:
            continue
        emails = {(m.get("email") or "").lower() for m in members}
        if len(emails) < 2:
            continue  # same address twice is the duplicate-email problem, not a move
        members.sort(key=lambda m: (page_rank(m), -(m.get("updated_at") or m.get("created_at") or datetime.min).timestamp()
                                    if isinstance(m.get("updated_at") or m.get("created_at"), datetime) else 0))
        keeper = members[0]
        pairs.extend((m, keeper) for m in members[1:])
    return pairs


def main() -> int:
    from pymongo import MongoClient

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    c = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    col = c["email_automation"]["leads_enriched"]
    leads = list(col.find({"superseded_by": {"$exists": False}, "transferred_to_vendor_leads": {"$ne": True}},
                          {"email": 1, "name": 1, "stage": 1, "source": 1, "outreach_replied_at": 1,
                           "updated_at": 1, "created_at": 1}))
    pairs = plan(leads)
    now = datetime.utcnow()
    for old, keeper in pairs:
        print(f"{old.get('email'):45} -> {keeper.get('email'):45} ({keeper.get('name')})")
        if args.apply:
            col.update_one({"_id": old["_id"]}, {"$set": {
                "superseded_by": str(keeper["_id"]), "superseded_at": now,
                "superseded_reason": "same person, newer address (email name part and full name match)"}})
    print(f"\n{'SUPERSEDED' if args.apply else 'WOULD SUPERSEDE'} {len(pairs)} records")
    if not args.apply:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
