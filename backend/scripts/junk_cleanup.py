"""Junk records out of the working lists (owner, 2026-10-26). Flags only -- nothing is deleted.

    venv/bin/python scripts/junk_cleanup.py            # dry run
    venv/bin/python scripts/junk_cleanup.py --apply    # needs a mongodump < 3 h old

  bounced leads      AI Database / Leads records whose address bounced, that never
                     replied and never reached a pipeline stage -> junk.reason
                     "bounced" (the lead lists hide junk; a won client whose
                     address now bounces is kept: the person left, the company stays)
  vendor contacts    CRM contacts at a domain set to vendor in party_relationships
                     -> party "vendor" (they belong to the vendor, not sales)
  duplicate projects the same study opened once per mail of its thread
                     ("RE: RFQ_x" next to "RFQ_x"): the oldest copy is kept; a copy
                     with no survey number, live/entry link or invoice is hidden
                     (status duplicate, duplicate_of), any other copy is only flagged
Undo: unset junk / party / duplicate_of and restore is_deleted false.
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BOUNCED = ["bounced", "invalid", "undeliverable"]


def _key(name: str) -> str:
    n = re.sub(r"^((re|fw|fwd)\s*:\s*)+", "", (name or "").strip(), flags=re.I).lower()
    return re.sub(r"\s+", " ", n).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        from sync_zoho_invoices import backup_age_hours
        if backup_age_hours() > 3:
            sys.exit("refusing to apply: newest mongodump is older than 3 h")
    from database import get_database
    ea, crm = get_database("email_automation"), get_database("crm_db")
    now = datetime.utcnow()
    rep, samples = Counter(), defaultdict(list)

    q = {"email_status": {"$in": BOUNCED}, "outreach_replied_at": {"$exists": False},
         "stage": {"$in": [None, ""]}, "junk": {"$exists": False}}
    rep["bounced leads -> junk"] = ea.leads_enriched.count_documents(q)
    if a.apply:
        ea.leads_enriched.update_many(q, {"$set": {"junk": {"reason": "bounced", "at": now,
                                                            "by": "junk_cleanup 2026-10-26"}}})

    vendor = [r["key"].lower() for r in ea.party_relationships.find({"relationship": "vendor"}, {"key": 1})]
    for c in crm.contacts.find({"is_deleted": {"$ne": True}, "party": {"$ne": "vendor"}}, {"email": 1}):
        d = (c.get("email") or "").lower().rsplit("@", 1)[-1]
        if d and d in vendor:
            rep["contacts at vendor domains -> party vendor"] += 1
            if a.apply:
                crm.contacts.update_one({"_id": c["_id"]}, {"$set": {"party": "vendor", "party_set_at": now,
                                                                     "party_source": "party_relationships"}})

    groups = defaultdict(list)
    for p in ea.projects.find({"is_deleted": {"$ne": True}, "duplicate_of": {"$exists": False}},
                              {"projectName": 1, "client": 1, "createdAt": 1, "created_at": 1, "surveyNo": 1,
                               "liveLink": 1, "entryLink": 1, "invoice_ids": 1, "projectStatus": 1}):
        k = (_key(p.get("projectName")), (p.get("client") or "").strip().lower())
        if k[0] and k[0] not in ("rfq", "request for quote"):
            groups[k].append(p)
    for k, ps in groups.items():
        if len(ps) < 2:
            continue
        ps.sort(key=lambda p: p.get("createdAt") or p.get("created_at") or now)
        keep = ps[0]
        for p in ps[1:]:
            empty = not (p.get("surveyNo") or p.get("liveLink") or p.get("entryLink") or p.get("invoice_ids"))
            rep["duplicate projects " + ("hidden" if empty else "flagged (have links / invoices)")] += 1
            if len(samples["duplicates"]) < 10:
                samples["duplicates"].append(f"{(p.get('projectName') or '')[:50]} -> keep {str(keep['_id'])[-6:]}"
                                             + (" (hidden)" if empty else " (flagged)"))
            if a.apply:
                upd = {"duplicate_of": str(keep["_id"]), "duplicate_flagged_at": now}
                if empty:
                    upd.update(is_deleted=True, deleted_at=now, deleted_reason="duplicate project (same study, same client)")
                ea.projects.update_one({"_id": p["_id"]}, {"$set": upd})
    print(("APPLIED" if a.apply else "DRY RUN"), dict(rep))
    for s in samples["duplicates"]:
        print("   ", s)


if __name__ == "__main__":
    main()
