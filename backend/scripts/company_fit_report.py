"""
Who in the live outreach chains works at a company the campaign does not sell
to, and which companies the emailless leads sit at (leads/company_fit.py).

    python scripts/company_fit_report.py            # report only, writes nothing
                                                    # except queueing unknown companies
    python scripts/company_fit_report.py --apply    # retire mismatched/excluded rows

--apply sets workflow_status "skipped_icp_mismatch" and keeps the old status in
pre_company_fit_status. Undo:
    db.outreach_leads_v2.find({pre_company_fit_status: {$exists: true}}).forEach(d =>
      db.outreach_leads_v2.updateOne({_id: d._id}, {$set: {workflow_status: d.pre_company_fit_status},
                                                    $unset: {pre_company_fit_status: ""}}))
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from pymongo import MongoClient  # noqa: E402

from leads import company_fit  # noqa: E402

ACTIVE = ["not_started", "pending_scheduled", "in_sequence"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    tdb = client[os.getenv("MONGO_DB_NAME") or "torpedo"]
    campaigns = {c["campaign_id"]: c.get("business") for c in tdb["outreach_campaigns_v2"].find(
        {}, {"campaign_id": 1, "business": 1})}

    verdicts: Counter = Counter()
    by_company = defaultdict(Counter)
    retire = []
    for row in tdb["outreach_leads_v2"].find({"workflow_status": {"$in": ACTIVE}},
                                             {"email": 1, "company_name": 1, "title": 1, "campaign_id": 1}):
        business = campaigns.get(row.get("campaign_id"), "")
        email = (row.get("email") or "").lower()
        v, why = company_fit.check(business, row.get("company_name") or "", email.split("@")[-1],
                                   row.get("title") or "", client=client)
        verdicts[(business, v)] += 1
        by_company[(business, v)][(row.get("company_name") or email.split("@")[-1])[:40]] += 1
        if v in ("mismatch", "excluded"):
            retire.append((row["_id"], why))

    print("Active outreach rows by campaign and company verdict:")
    for (b, v), n in sorted(verdicts.items()):
        print(f"  {b:10} {v:9} {n:6}   top: {by_company[(b, v)].most_common(6)}")

    le = client["email_automation"]["leads_enriched"]
    print("\nLeads with no email, by company (top 25):")
    for g in le.aggregate([
            {"$match": {"$or": [{"email": {"$in": [None, ""]}}, {"email": {"$exists": False}}]}},
            {"$group": {"_id": {"$toLower": {"$ifNull": ["$company_name", "?"]}}, "n": {"$sum": 1}}},
            {"$sort": {"n": -1}}, {"$limit": 25}], allowDiskUse=True):
        print(f"  {g['n']:5}  {g['_id']}")
    ct = client["email_automation"][company_fit.COLLECTION]
    print("\nCompanies by status / type:")
    for g in ct.aggregate([{"$group": {"_id": {"status": "$status", "type": "$type"}, "n": {"$sum": 1}}},
                           {"$sort": {"n": -1}}]):
        print(f"  {g['n']:6}  {g['_id']}")
    print("\nWaiting for a person (industry found, AI did not confirm), top 20:")
    for d in ct.find({"status": "review"}).sort("priority", -1).limit(20):
        print(f"  {d.get('name') or d['_id']:35} found {d.get('proposed_type')} via {d.get('proposed_source')}"
              f"  | {(d.get('evidence') or '')[:60]}")
    checks = tdb["contact_icp_checks"]
    print("\nPeople decided:")
    for g in checks.aggregate([{"$group": {"_id": "$reconciled", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]):
        print(f"  {g['n']:6}  {g['_id']}")

    if args.apply and retire:
        now = datetime.utcnow()
        for _id, why in retire:
            row = tdb["outreach_leads_v2"].find_one({"_id": _id}, {"workflow_status": 1})
            tdb["outreach_leads_v2"].update_one({"_id": _id}, {"$set": {
                "pre_company_fit_status": row.get("workflow_status"),
                "workflow_status": "skipped_icp_mismatch",
                "last_send_error": f"company fit: {why}"[:300], "updated_at": now}})
        print(f"\nRetired {len(retire)} rows (undo: see this script's docstring).")
    elif retire:
        print(f"\n{len(retire)} rows would be retired with --apply.")


if __name__ == "__main__":
    main()
