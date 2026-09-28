"""
Clear the RFQ section and rebuild it from the mail pool by rules (owner,
2026-09-28: "clean all the old RFQ records, then fill in the new ones";
everything goes, including the 9 wins made through mark-won).

  python scripts/rfq_reset_rebuild.py --backup                 # mongodump first
  python scripts/rfq_reset_rebuild.py --clean                  # dry run: what would go
  python scripts/rfq_reset_rebuild.py --clean --apply
  python scripts/rfq_reset_rebuild.py --rebuild                # dry run: how many RFQs
  python scripts/rfq_reset_rebuild.py --rebuild --apply

Removed by --clean:
  crm_db.opportunities         all (every one came from an RFQ flow)
  crm_db.projects              the stubs linked to an opportunity
  crm_db.invoices              the stubs linked to those projects
  crm_db.activities            entries about those opportunities/projects
                               (account and lead history stays)
  email_automation.rfqs        the old department-router RFQ list
  torpedo_gmail.email_metadata rfq_id / rfq_synced pointers are unset
Accounts, contacts, CRM tasks, Finance and Operations records are untouched.
Restore: mongorestore the --backup directory (see the printed command).
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

BACKUP_ROOT = "/var/backups/rfq-reset"


def _client():
    from pymongo import MongoClient
    return MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")


def backup() -> str:
    out = os.path.join(BACKUP_ROOT, datetime.utcnow().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)
    for db, col in (("crm_db", "opportunities"), ("crm_db", "projects"), ("crm_db", "invoices"),
                    ("crm_db", "activities"), ("email_automation", "rfqs")):
        subprocess.run(["mongodump", "--quiet", "--db", db, "--collection", col, "--out", out], check=True)
    em = _client()["torpedo_gmail"]["email_metadata"]
    pointers = [{"_id": str(d["_id"]), "rfq_id": d.get("rfq_id"), "rfq_synced": d.get("rfq_synced")}
                for d in em.find({"rfq_id": {"$exists": True}}, {"rfq_id": 1, "rfq_synced": 1})]
    with open(os.path.join(out, "email_metadata_rfq_pointers.json"), "w") as f:
        json.dump(pointers, f)
    print("backup:", out)
    print("restore: mongorestore --drop --dir", out, " (then re-apply email_metadata_rfq_pointers.json)")
    return out


def clean(apply: bool) -> None:
    c = _client()
    crm = c["crm_db"]
    opp_ids = [str(i) for i in crm["opportunities"].distinct("_id")]
    proj_q = {"opportunity_id": {"$exists": True, "$nin": [None, ""]}}
    proj_ids = [str(i) for i in crm["projects"].distinct("_id", proj_q)]
    inv_q = {"project_id": {"$in": proj_ids}}
    act_q = {"$or": [{"opportunity_id": {"$exists": True, "$nin": [None, ""]}},
                     {"type": "record_updated", "object_type": {"$in": ["opportunitie", "opportunity", "project"]}}]}
    counts = {
        "opportunities": len(opp_ids),
        "project stubs": len(proj_ids),
        "invoice stubs": crm["invoices"].count_documents(inv_q),
        "activities": crm["activities"].count_documents(act_q),
        "old rfqs collection": c["email_automation"]["rfqs"].count_documents({}),
        "mail rfq pointers": c["torpedo_gmail"]["email_metadata"].count_documents({"rfq_id": {"$exists": True}}),
        "left alone: projects without an opportunity": crm["projects"].count_documents({"$nor": [proj_q]}),
        "left alone: invoices not on those projects": crm["invoices"].count_documents({"$nor": [inv_q]}),
    }
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if not apply:
        print("dry run -- nothing removed (use --apply after --backup)")
        return
    from bson import ObjectId
    crm["invoices"].delete_many(inv_q)
    crm["activities"].delete_many(act_q)
    crm["projects"].delete_many({"_id": {"$in": [ObjectId(i) for i in proj_ids]}})
    crm["opportunities"].delete_many({})
    c["email_automation"]["rfqs"].delete_many({})
    c["torpedo_gmail"]["email_metadata"].update_many(
        {"rfq_id": {"$exists": True}}, {"$unset": {"rfq_id": "", "rfq_synced": "", "rfq_source": ""}})
    print("cleaned.")


def rebuild(apply: bool) -> None:
    c = _client()
    from app.services import rfq_from_mail as rb
    if not apply:
        docs = rb.candidates(c)
        from datetime import timedelta
        cut = datetime.utcnow() - timedelta(days=rb.OPEN_DAYS)
        print(f"  client-opened RFQ threads: {len(docs)} "
              f"(open, last {rb.OPEN_DAYS} days: {sum(1 for d in docs if d['timestamp'] >= cut)})")
        for d in docs[-8:]:
            print("   ", str(d.get("timestamp"))[:10], d.get("from_email"), "|", rb.clean_title(d.get("subject")))
        print("dry run -- nothing created (duplicates are folded on --apply)")
        return
    print("rebuilt:", rb.build(c))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.backup:
        backup()
    if a.clean:
        clean(a.apply)
    if a.rebuild:
        rebuild(a.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
