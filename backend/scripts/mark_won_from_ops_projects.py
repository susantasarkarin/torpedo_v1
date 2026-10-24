"""
MARK RFQs WON THAT HAVE AN OPERATIONS PROJECT
=============================================
An RFQ whose study has a project in Operations (email_automation.projects)
was won: the study ran. 1,475 historical RFQs were closed as "outcome not
recorded" when they were rebuilt from mail, and the win evidence used so far
— invoices (app/services/win_evidence.py) and the client's live link / go-ahead
(rfq_from_mail.apply_live_links) — misses studies that ran without either
reaching us in that form.

Matching is won_handoff.find_existing_ops_project: same normalised study name
and same client. A win is recorded the way apply_live_links records history —
stage/status won, dated by the project — and handed off as historical, which
links the existing project instead of creating one.

    python -m scripts.mark_won_from_ops_projects            # dry run
    python -m scripts.mark_won_from_ops_projects --apply
"""

import argparse
import os
import re
import sys

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_FILLER = {"rfq", "sfw", "hrg", "follow", "up", "re", "fw", "fwd", "study", "research", "project", "the", "and", "for", "of"}


def word_overlap(a: str, b: str) -> float:
    """Share of distinctive words the two titles have in common (Jaccard)."""
    wa = {w for w in re.findall(r"[a-z0-9]{3,}", (a or "").lower()) if w not in _FILLER}
    wb = {w for w in re.findall(r"[a-z0-9]{3,}", (b or "").lower()) if w not in _FILLER}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def main() -> int:
    from app.services.won_handoff import find_existing_ops_project, handoff_won_opportunity

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    c = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    crm, ops = c["crm_db"], c["email_automation"]
    accounts = {a["_id"]: a.get("name") for a in crm["accounts"].find({}, {"name": 1})}

    found, used_projects = 0, set()
    # Quoted (proposal) first: when the same study has two RFQ records, the
    # one we priced is the one that was won, and a project is one win.
    opps = sorted(crm["opportunities"].find({"stage": {"$ne": "won"}},
                                            {"title": 1, "stage": 1, "status": 1, "account_id": 1, "metadata.rfq": 1}),
                  key=lambda o: o.get("stage") != "proposal")
    for o in opps:
        rfq = (o.get("metadata") or {}).get("rfq") or {}
        client = accounts.get(o.get("account_id")) or rfq.get("account_name") or ""
        title = o.get("title") or rfq.get("title") or ""
        project = find_existing_ops_project(ops["projects"], title, client, str(o["_id"]))
        if not project or project["_id"] in used_projects:
            continue
        # The shared matcher compares a normalised study key, which collapses
        # generic titles ("Follow up RFQ - …") to the same few words. Require
        # most of the distinctive words to agree as well.
        if word_overlap(title, project.get("projectName")) < 0.5:
            continue
        used_projects.add(project["_id"])
        full = ops["projects"].find_one({"_id": project["_id"]},
                                        {"projectLaunchDate": 1, "createdAt": 1, "created_at": 1, "projectName": 1})
        won_at = full.get("projectLaunchDate") or full.get("createdAt") or full.get("created_at")
        found += 1
        print(f"{o.get('stage'):9} {o.get('status'):7} {title[:55]:55} | {client[:25]:25} -> {full.get('projectName', '')[:45]}")
        if not args.apply:
            continue
        crm["opportunities"].update_one({"_id": o["_id"]}, {
            "$set": {"stage": "won", "status": "won", "won_at": won_at, "closed_at": won_at,
                     "won_via": "operations project exists (historical)"},
            "$unset": {"closed_reason": "", "closed_by": ""}})
        handoff_won_opportunity(crm["opportunities"].find_one({"_id": o["_id"]}), historical=True)

    print(f"\n{'MARKED WON' if args.apply else 'WOULD MARK WON'}: {found}")
    if not args.apply:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
