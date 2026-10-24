"""Read-only foreign-key resolution check for the CRM audit (Phase 1.2).

For each (source field -> target collection) pair, samples up to 2000 docs that
carry the field and reports how many values resolve to a target _id (tried as
both string and ObjectId). Also counts docs per BU-like field. Writes nothing.
"""
import json
import os
import sys

from bson import ObjectId
from pymongo import MongoClient

N = 2000
LINKS = [
    ("crm_db.contacts.account_id", "crm_db.accounts"),
    ("crm_db.leads.account_id", "crm_db.accounts"),
    ("crm_db.leads.contact_id", "crm_db.contacts"),
    ("crm_db.opportunities.account_id", "crm_db.accounts"),
    ("crm_db.opportunities.contact_id", "crm_db.contacts"),
    ("crm_db.opportunities.project_id", "crm_db.projects"),
    ("crm_db.projects.account_id", "crm_db.accounts"),
    ("crm_db.projects.opportunity_id", "crm_db.opportunities"),
    ("crm_db.projects.ops_project_id", "email_automation.projects"),
    ("crm_db.activities.account_id", "crm_db.accounts"),
    ("crm_db.activities.contact_id", "crm_db.contacts"),
    ("crm_db.activities.lead_id", "crm_db.leads"),
    ("crm_db.invoices.account_id", "crm_db.accounts"),
    ("crm_db.invoices.project_id", "crm_db.projects"),
    ("finance_db.customers.crm_account_id", "crm_db.accounts"),
    ("finance_db.vendors.crm_account_id", "crm_db.accounts"),
    ("finance_db.invoices.customer_id", "finance_db.customers"),
    ("finance_db.invoices.opportunity_id", "crm_db.opportunities"),
    ("finance_db.invoices.ops_project_id", "email_automation.projects"),
    ("finance_db.invoices.work_order_id", "finance_db.work_orders"),
    ("finance_db.estimates.customer_id", "finance_db.customers"),
    ("finance_db.estimates.opportunity_id", "crm_db.opportunities"),
    ("finance_db.work_orders.project_id", "email_automation.projects"),
    ("finance_db.contracts.customer_id", "finance_db.customers"),
    ("email_automation.projects.customer_id", "finance_db.customers"),
    ("email_automation.projects.opportunity_id", "crm_db.opportunities"),
    ("email_automation.projects.crm_project_id", "crm_db.projects"),
    ("email_automation.projects.vendorId", "email_automation.vendors"),
    ("torpedo.outreach_sends_v2.outreach_lead_id", "torpedo.outreach_leads_v2"),
    ("torpedo.outreach_leads_v2.lead_id", "crm_db.leads"),
    ("torpedo_gmail.email_metadata.rfq_id", "crm_db.opportunities"),
]
BU_FIELDS = ["bu", "business_unit", "entity", "brand", "company_unit"]
BU_COLLS = ["crm_db.accounts", "crm_db.leads", "crm_db.opportunities", "crm_db.projects",
            "finance_db.invoices", "finance_db.customers", "email_automation.projects",
            "torpedo.outreach_leads_v2", "torpedo_gmail.email_metadata"]


def coll(client, path):
    db, c = path.split(".", 1)
    return client[db][c]


def variants(v):
    out = [v]
    if isinstance(v, str) and ObjectId.is_valid(v):
        out.append(ObjectId(v))
    if isinstance(v, ObjectId):
        out.append(str(v))
    return out


def main():
    client = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=10000)
    res = {"links": {}, "bu": {}}
    for src, tgt in LINKS:
        db, c, f = src.split(".", 2)
        docs = list(client[db][c].find({f: {"$nin": [None, ""]}}, {f: 1}).limit(N))
        vals = [d[f] for d in docs if not isinstance(d.get(f), (list, dict))]
        if not vals:
            res["links"][src] = {"target": tgt, "sampled": 0}
            continue
        probe = [x for v in set(map(str, vals)) for x in variants(v)]
        probe += [ObjectId(v) for v in vals if isinstance(v, str) and ObjectId.is_valid(v)]
        found = {str(d["_id"]) for d in coll(client, tgt).find({"_id": {"$in": list(set(probe, ))}}, {"_id": 1})}
        ok = sum(1 for v in vals if str(v) in found)
        res["links"][src] = {"target": tgt, "sampled": len(vals), "resolved": ok,
                             "pct": round(100 * ok / len(vals), 1)}
        print(src, res["links"][src], file=sys.stderr)
    for path in BU_COLLS:
        c = coll(client, path)
        for f in BU_FIELDS:
            vals = list(c.aggregate([{"$sample": {"size": 3000}}, {"$group": {"_id": f"${f}", "n": {"$sum": 1}}}]))
            vals = {str(v["_id"]): v["n"] for v in vals if v["_id"] is not None}
            if vals:
                res["bu"][f"{path}.{f}"] = dict(sorted(vals.items(), key=lambda x: -x[1])[:10])
    json.dump(res, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
