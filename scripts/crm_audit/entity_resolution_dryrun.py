"""Entity resolution DRY RUN (Phase 2 task 2, CRM plan Section 5). Read-only.

Reports, per entity: linked automatically / ambiguous (-> Review Queue) / orphan
or new. Writes nothing to MongoDB. Prints one JSON document; samples masked.

  1 companies   domain first, then normalised name; fuzzy >= 0.90 auto,
                0.75-0.90 review, below -> new record
  2 contacts    exact email, then name + company domain
  3 mails       counterparty address -> contact, else domain -> account;
                internal and free-mail counted separately
  4 RFQ -> project -> invoice  existing ids; gaps counted
  5 Zoho        customers/invoices already carry crm_account_id (checked)
  6 BU          derivation rules and how many records they place

Run from backend/: venv/bin/python /tmp/entity_resolution_dryrun.py > er.json
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from pymongo import MongoClient

OURS = {"surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com"}
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "rediffmail.com",
        "yahoo.co.in", "aol.com", "protonmail.com", "msn.com", "ymail.com", "googlemail.com", "zoho.com"}
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}
SUFFIXES = r"\b(private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|company|co|gmbh|plc|pte|sa|ag|bv|srl|the)\b"
BU_OF_DOMAIN = {"surveyfieldwork.com": "SFW", "cogentixresearch.com": "COGENTIX", "bimwavesolutions.com": "BIM"}
BU_OF_BRANCH = {"survey fieldwork": "SFW", "cogentix research": "COGENTIX"}
BU_OF_BUCKET = {"SFW": "SFW", "COGENTIX_RESEARCH": "COGENTIX", "BIM": "BIM"}


def mask(e):
    u, _, d = (e or "").partition("@")
    return f"{u[:2]}***@{d}" if d else e


def reg_domain(v):
    """Registrable domain from an email, URL or bare domain."""
    if not v or not isinstance(v, str):
        return None
    v = v.strip().lower()
    if "@" in v:
        v = v.rsplit("@", 1)[1]
    v = re.sub(r"^[a-z]+://", "", v).split("/")[0].split(":")[0]
    v = re.sub(r"^www\d?\.", "", v).strip(".")
    parts = [p for p in v.split(".") if p]
    if len(parts) < 2 or not re.fullmatch(r"[a-z0-9.-]+", v):
        return None
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def norm_name(n):
    if not n or not isinstance(n, str):
        return ""
    n = n.lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(SUFFIXES, " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"(^and\s+|\s+and$)", "", n).strip()


class AccountIndex:
    def __init__(self, accounts):
        self.by_domain, self.by_name, self.by_token = {}, defaultdict(set), defaultdict(set)
        for a in accounts:
            aid = str(a["_id"])
            for f in ("domain", "root_domain", "website"):
                d = reg_domain(a.get(f))
                if d and d not in FREE:
                    self.by_domain.setdefault(d, set()).add(aid)
            nn = norm_name(a.get("name"))
            if nn:
                self.by_name[nn].add(aid)
                self.by_token[nn.split()[0]].add(nn)

    def resolve(self, name, domain):
        if domain and domain not in FREE and domain not in OURS:
            hit = self.by_domain.get(domain)
            if hit:
                return ("auto", "domain", len(hit) > 1)
        nn = norm_name(name)
        if not nn:
            return ("orphan", "no name or domain", False)
        if nn in self.by_name:
            return ("auto", "name_exact", len(self.by_name[nn]) > 1)
        best = 0.0
        for cand in self.by_token.get(nn.split()[0], ()):
            best = max(best, SequenceMatcher(None, nn, cand).ratio())
        if best >= 0.90:
            return ("auto", "name_fuzzy", False)
        if best >= 0.75:
            return ("review", f"name_fuzzy {best:.2f}", False)
        return ("new", "no match", False)


def resolve_companies(c, idx, out):
    sources = {
        "finance_db.customers": (c.finance_db.customers.find({"is_deleted": {"$ne": True}}, {"name": 1, "company_name": 1, "email": 1, "crm_account_id": 1}),
                                 lambda d: (d.get("company_name") or d.get("name"), reg_domain(d.get("email")))),
        "finance_db.vendors": (c.finance_db.vendors.find({}, {"name": 1, "email": 1}),
                               lambda d: (d.get("name"), reg_domain(d.get("email")))),
        "email_automation.sales_accounts": (c.email_automation.sales_accounts.find({}, {"name": 1, "company_name": 1, "domain": 1, "website": 1}),
                                            lambda d: (d.get("company_name") or d.get("name"), reg_domain(d.get("domain") or d.get("website")))),
        "email_automation.leads_enriched (companies)": (c.email_automation.leads_enriched.find({}, {"company": 1, "company_name": 1, "company_domain": 1, "website": 1, "email": 1}),
                                                        lambda d: (d.get("company_name") or d.get("company"), reg_domain(d.get("company_domain") or d.get("website") or d.get("email")))),
    }
    for label, (cur, get) in sources.items():
        cnt, how, amb_multi, samples, seen = Counter(), Counter(), 0, defaultdict(list), set()
        for d in cur:
            name, dom = get(d)
            key = dom or norm_name(name)
            if label.endswith("(companies)"):
                if not key or key in seen:
                    continue
                seen.add(key)
            outcome, why, multi = idx.resolve(name, dom)
            if multi:
                outcome, why = "review", why + " (matches >1 account)"
            cnt[outcome] += 1
            how[why.split(" ")[0] if outcome == "auto" else outcome] += 1
            if len(samples[outcome]) < 3 and outcome != "auto":
                samples[outcome].append(f"{(name or '')[:40]} | {dom or '-'} | {why}")
        out["companies"][label] = {"total": sum(cnt.values()), **cnt, "auto_by": dict(how), "samples": dict(samples)}


def resolve_contacts(c, out):
    crm = {(x.get("email") or "").strip().lower(): x for x in c.crm_db.contacts.find({}, {"email": 1, "name": 1, "account_id": 1}) if x.get("email")}
    by_name_dom = {(norm_name(x.get("name")), reg_domain(e)): e for e, x in crm.items() if x.get("name")}
    srcs = {"email_automation.contacts": c.email_automation.contacts.find({}, {"email": 1, "name": 1, "first_name": 1, "last_name": 1}),
            "crm_db.leads": c.crm_db.leads.find({"email": {"$nin": [None, ""]}}, {"email": 1, "name": 1, "contact_id": 1}),
            "torpedo.outreach_leads_v2": c.torpedo.outreach_leads_v2.find({}, {"email": 1, "name": 1})}
    for label, cur in srcs.items():
        cnt, seen = Counter(), set()
        for d in cur:
            e = (d.get("email") or "").strip().lower()
            if not e or e in seen:
                continue
            seen.add(e)
            if e in crm:
                cnt["auto_email"] += 1
                continue
            nm = norm_name(d.get("name") or f"{d.get('first_name') or ''} {d.get('last_name') or ''}")
            if nm and (nm, reg_domain(e)) in by_name_dom:
                cnt["review_name_domain"] += 1      # same person, different address -> a person confirms
            elif reg_domain(e) in OURS:
                cnt["internal"] += 1
            else:
                cnt["new_contact_or_lead_only"] += 1
        out["contacts"][label] = {"distinct_emails": len(seen), **cnt}


def resolve_mail(c, idx, out):
    contacts = {(x.get("email") or "").strip().lower() for x in c.crm_db.contacts.find({}, {"email": 1})}
    leads = {(x.get("email") or "").strip().lower() for x in c.crm_db.leads.find({}, {"email": 1})}
    vend = {reg_domain(x.get("email")) for x in c.finance_db.vendors.find({}, {"email": 1})} - {None}
    cnt = Counter()
    pipeline = [{"$project": {"direction": 1, "from_email": 1, "to0": {"$arrayElemAt": ["$to_emails", 0]}}}]
    for d in c.torpedo_gmail.email_metadata.aggregate(pipeline, allowDiskUse=True):
        addr = (d.get("from_email") if d.get("direction") == "inbound" else d.get("to0")) or ""
        addr = addr.strip().lower()
        dom = reg_domain(addr)
        if not dom:
            cnt["no_address"] += 1
        elif dom in OURS:
            cnt["internal"] += 1
        elif addr in contacts:
            cnt["contact_by_email"] += 1
        elif addr in leads:
            cnt["lead_by_email"] += 1
        elif dom in vend:
            cnt["vendor_by_domain"] += 1
        elif dom in FREE:
            cnt["free_mail_unknown"] += 1
        elif dom in idx.by_domain:
            cnt["account_by_domain"] += 1
        else:
            cnt["unlinked_domain"] += 1
    total = sum(cnt.values())
    out["mails"] = {"messages": total, **cnt,
                    "linked_pct": round(100 * (cnt["contact_by_email"] + cnt["lead_by_email"] + cnt["vendor_by_domain"] + cnt["account_by_domain"]) / max(total, 1), 1)}


def resolve_chain(c, out):
    opp = c.crm_db.opportunities
    ops = c.email_automation.projects
    won = list(opp.find({"stage": "won"}, {"_id": 1}))
    won_ids = {str(o["_id"]) for o in won}
    ops_by_opp = {str(p.get("opportunity_id")) for p in ops.find({"opportunity_id": {"$nin": [None, ""]}}, {"opportunity_id": 1})}
    inv_ops = {str(i.get("ops_project_id")) for i in c.finance_db.invoices.find({}, {"ops_project_id": 1})}
    completed = list(ops.find({"status": "completed"}, {"_id": 1}))
    out["rfq_project_invoice"] = {
        "rfqs_won": len(won_ids), "won_with_ops_project": len(won_ids & ops_by_opp),
        "won_without_ops_project": len(won_ids - ops_by_opp),
        "ops_projects_completed": len(completed),
        "completed_without_invoice": sum(1 for p in completed if str(p["_id"]) not in inv_ops),
        "estimates_unlinked_to_rfq": c.finance_db.estimates.count_documents({}) and sum(
            1 for e in c.finance_db.estimates.find({}, {"opportunity_id": 1}).limit(20000)
            if not opp.find_one({"_id": e.get("opportunity_id")}, {"_id": 1})),
        "ops_projects_vendorId_unresolved": ops.count_documents({"vendorId": {"$nin": [None, ""]}}),
    }


def resolve_bu(c, out):
    inv = Counter(BU_OF_BRANCH.get((i.get("branch") or "").strip().lower(), "unknown")
                  for i in c.finance_db.invoices.find({}, {"branch": 1}))
    md = c.torpedo_gmail.email_metadata
    boxes = {}
    for col in ("workspace_mailboxes", "mailboxes"):
        for b in c.torpedo_gmail[col].find({}, {"email": 1}):
            boxes[str(b["_id"])] = BU_OF_DOMAIN.get(reg_domain(b.get("email")) or "")
    rfq = Counter()
    from bson import ObjectId
    for o in c.crm_db.opportunities.find({}, {"metadata.rfq.source_email_id": 1, "metadata.rfq.mailbox_id": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        bu = boxes.get(str(r.get("mailbox_id")))
        if not bu and r.get("source_email_id"):
            try:
                m = md.find_one({"_id": ObjectId(r["source_email_id"])}, {"mailbox_id": 1})
                bu = boxes.get(str((m or {}).get("mailbox_id")))
            except Exception:
                pass
        rfq[bu or "unknown"] += 1
    leads = Counter(BU_OF_BUCKET.get(d["_id"], "review_or_reject") for d in c.email_automation.leads_raw.aggregate(
        [{"$group": {"_id": "$outreach_bucket", "n": {"$sum": 1}}}]) for _ in range(d["n"]))
    out["bu_derivation"] = {
        "invoices_by_branch": dict(inv),
        "rfqs_by_receiving_mailbox": dict(rfq),
        "leads_raw_by_outreach_bucket": dict(leads),
        "rule_order": ["invoice.branch", "RFQ receiving mailbox domain", "lead outreach_bucket",
                       "account = BU of its won RFQs/invoices (majority); tie or none -> Review Queue",
                       "project/quotation/invoice inherit from their RFQ"],
    }


def main():
    c = MongoClient(os.environ["MONGO_URI"])
    accounts = list(c.crm_db.accounts.find({"status": {"$nin": ["deleted", "merged"]}}, {"name": 1, "domain": 1, "root_domain": 1, "website": 1}))
    idx = AccountIndex(accounts)
    out = {"mode": "dry-run (no writes)", "live_accounts": len(accounts), "accounts_with_domain": len({a for s in idx.by_domain.values() for a in s}),
           "companies": {}, "contacts": {}}
    for step in (lambda: resolve_companies(c, idx, out), lambda: resolve_contacts(c, out),
                 lambda: resolve_chain(c, out), lambda: resolve_bu(c, out), lambda: resolve_mail(c, idx, out)):
        step()
        print("step done", file=sys.stderr, flush=True)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
