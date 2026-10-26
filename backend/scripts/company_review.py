"""Company master review: every CRM account gets a kind, a business unit and one clean name (owner, 2026-10-26).

    venv/bin/python scripts/company_review.py --limit 300            # dry run on a sample, writes a JSONL report
    venv/bin/python scripts/company_review.py                        # dry run, all accounts
    venv/bin/python scripts/company_review.py --apply REPORT.jsonl   # writes the report's verdicts (needs a dump < 3 h)

kind:  client | vendor | both | prospect | own | not_a_company
bu:    SFW | COGENTIX | BIM | none
Rules decide first (our domains, party_relationships the owner set, invoices,
Finance vendor records, accounts nobody ever mailed); Haiku -> Sonnet
(task company_review) only where the mail evidence needs reading. Nothing is
deleted: --apply sets kind / bu / company_review on the account, renames it
when the review found the real company (previous_name kept) and hides
not_a_company (status hidden, hidden_reason). Low-confidence AI verdicts are
written as needs_review, not applied.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KINDS = ["client", "vendor", "both", "prospect", "own", "not_a_company"]
BUS = ["SFW", "COGENTIX", "BIM", "none"]
SCHEMA = {"type": "object", "required": ["company_name", "kind", "bu", "confidence"],
          "properties": {"company_name": {"type": "string"}, "kind": {"type": "string", "enum": KINDS},
                         "bu": {"type": "string", "enum": BUS}, "confidence": {"type": "number"}}}
SYSTEM = (
    "You sort the CRM accounts of three related companies: Survey Fieldwork (SFW, online/offline survey fieldwork "
    "and panel sample), Cogentix Research (COGENTIX, market research projects for brands and agencies) and "
    "BIM Wave (BIM, building information modelling / CAD services).\n"
    "kind: client = buys from us (sends RFQs, briefs, POs, gets our invoices); vendor = sells to us (panel/sample "
    "supplier, fieldwork partner, tool or service we pay); both = clearly both; prospect = a company we only "
    "pitched or found, no business yet; own = one of our three companies; not_a_company = a person, a mailbox "
    "provider, a newsletter/notification sender or junk.\n"
    "company_name: the company's proper name (not a person, not an email address; keep the legal suffix if known).\n"
    "bu: which of our companies the relationship belongs to, from the mailboxes and subjects; none if unclear.\n"
    "confidence: 0-1, honest. Answer with the JSON only.")
# a verdict is applied at or above this confidence; below it waits for a person
MIN_CONF = {"prospect": 0.5, "client": 0.7, "vendor": 0.7, "both": 0.7, "own": 0.8, "not_a_company": 0.8}


def visible(acc) -> bool:
    return not acc.get("is_deleted") and acc.get("status") not in ("deleted", "merged", "hidden") \
        and not acc.get("merged_into")


def dom(e):
    e = (e or "").strip().lower()
    return e.rsplit("@", 1)[-1] if "@" in e else ""


def mail_evidence(md, mailbox_bu):
    """domain -> {in, out, bu Counter, subjects[]} from every mail's counterparty."""
    ev = defaultdict(lambda: {"in": 0, "out": 0, "bu": Counter(), "subjects": []})
    for m in md.find({"mail_counterparty": {"$type": "string"}},
                     {"mail_counterparty": 1, "direction": 1, "mailbox_id": 1, "subject": 1}):
        d = dom(m.get("mail_counterparty"))
        if not d:
            continue
        e = ev[d]
        e["in" if m.get("direction") == "inbound" else "out"] += 1
        b = mailbox_bu.get(str(m.get("mailbox_id")))
        if b:
            e["bu"][b] += 1
        s = (m.get("subject") or "").strip()
        if s and len(e["subjects"]) < 12 and s not in e["subjects"]:
            e["subjects"].append(s[:120])
    return ev


def rules(acc, d, ev, ctx):
    """-> (kind, bu, why) or None when the mail needs reading."""
    from app.services.mail_categorizer import OWN_DOMAINS, WEBMAIL
    aid = str(acc["_id"])
    e = ev.get(d) or {"in": 0, "out": 0, "bu": Counter()}
    bu = e["bu"].most_common(1)[0][0] if e["bu"] else (ctx["rfq_bu"].get(aid) or ctx["inv_bu"].get(aid) or "none")
    if d in OWN_DOMAINS:
        return "own", bu, "our domain"
    rel = ctx["relationships"].get(d)
    if rel:
        return rel, bu, "owner-set relationship"
    if ctx["invoiced"].get(aid):
        return ("both" if aid in ctx["vendor_accounts"] else "client"), ctx["inv_bu"].get(aid) or bu, "has invoices"
    if aid in ctx["vendor_accounts"] and not ctx["rfqs"].get(aid):
        return "vendor", bu, "Finance vendor record"
    if not e["in"] and not e["out"] and not ctx["rfqs"].get(aid):
        if d in WEBMAIL or not d:
            return None if acc.get("name") else ("not_a_company", "none", "no name, no domain")
        return "prospect", ctx["lead_bu"].get(d) or bu, "never mailed: found by lead generation / import"
    return None


def evidence_text(acc, d, ev, ctx):
    e = ev.get(d) or {"in": 0, "out": 0, "bu": Counter(), "subjects": []}
    aid = str(acc["_id"])
    lines = [f"Account name: {acc.get('name')}", f"Domain: {d or 'none'}", f"Source: {acc.get('source') or (acc.get('metadata') or {}).get('source')}",
             f"Mails from them: {e['in']}, mails from us: {e['out']}",
             f"Our mailboxes involved: {dict(e['bu']) or 'none'}",
             f"RFQs on this account: {ctx['rfqs'].get(aid, 0)}",
             f"Our invoices to them: {ctx['invoiced'].get(aid, 0)}; Finance vendor record: {aid in ctx['vendor_accounts']}",
             "Contacts: " + "; ".join(ctx["contacts"].get(aid, [])[:6]),
             "Recent subjects:\n- " + "\n- ".join(e["subjects"][:10] or ["(none)"])]
    if ctx["rfq_titles"].get(aid):
        lines.append("RFQ titles:\n- " + "\n- ".join(ctx["rfq_titles"][aid][:5]))
    return "\n".join(lines)


def check(data, _text):
    p = []
    if data.get("kind") not in KINDS:
        p.append("bad kind")
    n = (data.get("company_name") or "").strip()
    if not n or "@" in n or len(n) > 80:
        p.append("company_name must be a company name")
    return p


def context(crm, fin, ea):
    from crm360 import view
    ctx = {"relationships": {}, "invoiced": Counter(), "inv_bu": {}, "vendor_accounts": set(), "rfqs": Counter(),
           "rfq_bu": {}, "rfq_titles": defaultdict(list), "contacts": defaultdict(list), "lead_bu": {}}
    for r in ea.party_relationships.find({}, {"key": 1, "relationship": 1}):
        if r.get("key") and r.get("relationship") in KINDS:
            ctx["relationships"][r["key"].lower().lstrip("@")] = r["relationship"]
    cust_acc = {str(c["_id"]): str(c.get("crm_account_id") or "") for c in fin.customers.find({}, {"crm_account_id": 1})}
    for i in fin.invoices.find({"is_deleted": {"$ne": True}}, {"customer_id": 1, "invoice_number": 1}):
        a = cust_acc.get(str(i.get("customer_id")))
        if a:
            ctx["invoiced"][a] += 1
            ctx["inv_bu"][a] = "COGENTIX" if str(i.get("invoice_number", "")).upper().startswith("CR") else "SFW"
    ctx["vendor_accounts"] = {str(v["crm_account_id"]) for v in fin.vendors.find({"crm_account_id": {"$nin": [None, ""]}},
                                                                                  {"crm_account_id": 1})}
    for o in crm.opportunities.find({"metadata.rfq": {"$exists": True}, "is_deleted": {"$ne": True}},
                                    {"account_id": 1, "bu": 1, "title": 1}):
        a = str(o.get("account_id") or "")
        if a:
            ctx["rfqs"][a] += 1
            if o.get("bu"):
                ctx["rfq_bu"][a] = o["bu"]
            if o.get("title") and len(ctx["rfq_titles"][a]) < 5:
                ctx["rfq_titles"][a].append(o["title"][:100])
    for c in crm.contacts.find({"is_deleted": {"$ne": True}, "account_id": {"$nin": [None, ""]}},
                               {"account_id": 1, "title": 1, "email": 1}):
        a = str(c["account_id"])
        if len(ctx["contacts"][a]) < 8:
            ctx["contacts"][a].append(f"{c.get('title') or 'no title'} @{dom(c.get('email'))}")
    bmap = {"SFW": "SFW", "COGENTIX_RESEARCH": "COGENTIX", "BIM": "BIM"}
    for l in ea.leads_enriched.find({"outreach_bucket": {"$in": list(bmap)}}, {"email": 1, "outreach_bucket": 1}):
        if dom(l.get("email")):
            ctx["lead_bu"][dom(l["email"])] = bmap[l["outreach_bucket"]]
    return ctx


def _ask(ladder, body, acc, tiers):
    res = ladder.run(task="company_review", system=SYSTEM, body=body, schema=SCHEMA, code_check=check,
                     ref={"collection": "crm_db.accounts", "id": str(acc["_id"])}, enqueue_on_fail=False, tiers=tiers)
    return (res.get("data") if res.get("status") in ("ok", "review") else None), res.get("tier")


def account_domain(acc, crm):
    if acc.get("domain"):
        return acc["domain"].lower().removeprefix("www.")
    c = crm.contacts.find_one({"account_id": str(acc["_id"]), "email": {"$regex": "@"}}, {"email": 1})
    return dom((c or {}).get("email"))


def review(limit=None, out=None, with_ai=True):
    from database import get_database
    from platform_core import ladder
    from crm360 import view
    crm, fin, ea = get_database("crm_db"), get_database("finance_db"), get_database("email_automation")
    md = get_database("torpedo_gmail")["email_metadata"]
    t0 = time.time()
    ctx = context(crm, fin, ea)
    ev = mail_evidence(md, view._mailbox_bu())
    print(f"evidence loaded in {time.time() - t0:.0f}s: {len(ev)} mail domains", flush=True)
    accs = [a for a in crm.accounts.find({}, {"name": 1, "domain": 1, "source": 1, "metadata.source": 1, "status": 1,
                                              "is_deleted": 1, "merged_into": 1, "bu": 1}) if visible(a)]
    if limit:
        import random
        random.seed(7)
        accs = random.sample(accs, min(limit, len(accs)))
    counts, spend0 = Counter(), ladder.spent_this_month(__import__("platform_core.qwen_gateway", fromlist=["x"])._gov_db())
    with open(out, "w", encoding="utf-8") as fh:
        for n, acc in enumerate(accs, 1):
            d = account_domain(acc, crm)
            r = rules(acc, d, ev, ctx)
            rec = {"account_id": str(acc["_id"]), "name": acc.get("name"), "domain": d}
            from backfill.finance_customers import is_person
            name_ok = bool(acc.get("name")) and not is_person(acc.get("name")) and "@" not in acc.get("name", "")
            if r and name_ok:
                rec.update(kind=r[0], bu=r[1], company_name=acc.get("name"), method="rules", why=r[2], confidence=1.0)
            elif with_ai:
                body = evidence_text(acc, d, ev, ctx)
                data, tier = _ask(ladder, body, acc, ["haiku"])
                if data and data["kind"] != "prospect" and float(data.get("confidence") or 0) < MIN_CONF[data["kind"]]:
                    second, t2 = _ask(ladder, body, acc, ["sonnet"])      # a second opinion before anyone is moved
                    if second:
                        data, tier = second, t2
                if data:
                    rec.update(kind=data["kind"], bu=data["bu"], company_name=data["company_name"].strip(),
                               method=tier, confidence=float(data.get("confidence") or 0))
                    if r:                       # rules know the relationship; the model only fixed the name
                        rec.update(kind=r[0], why=r[2] + "; name by " + tier, confidence=1.0)
                        if rec["bu"] == "none":
                            rec["bu"] = r[1]
                    if rec["bu"] == "none":
                        rec["bu"] = ctx["lead_bu"].get(d) or ctx["rfq_bu"].get(rec["account_id"]) or "none"
                else:
                    rec.update(kind=r[0] if r else None, bu=r[1] if r else None, company_name=acc.get("name"),
                               method="rules" if r else "unresolved", why=r[2] if r else None, confidence=1.0 if r else 0)
            else:
                rec.update(kind=r[0] if r else None, bu=r[1] if r else None, method="rules" if r else "needs_ai",
                           company_name=acc.get("name"), confidence=1.0 if r else 0)
            rec["needs_review"] = rec.get("kind") is None or rec.get("confidence", 0) < MIN_CONF.get(rec.get("kind"), 1)
            counts[f"{rec['method']}:{rec.get('kind')}"] += 1
            fh.write(json.dumps(rec, default=str) + "\n")
            if n % 200 == 0:
                print(f"{n}/{len(accs)}", flush=True)
    spent = ladder.spent_this_month(__import__("platform_core.qwen_gateway", fromlist=["x"])._gov_db()) - spend0
    print(json.dumps({"accounts": len(accs), "by_method_kind": dict(counts.most_common()), "usd": round(spent, 4),
                      "secs": round(time.time() - t0), "report": out}, indent=1))


def apply(report):
    from database import get_database
    crm = get_database("crm_db")
    now = datetime.utcnow()
    c = Counter()
    for line in open(report, encoding="utf-8"):
        r = json.loads(line)
        if r.get("needs_review") or not r.get("kind"):
            crm.accounts.update_one({"_id": __import__("bson").ObjectId(r["account_id"])}, {"$set": {
                "company_review": {"at": now, "needs_review": True, "proposed": r}}})
            c["needs_review"] += 1
            continue
        from bson import ObjectId
        acc = crm.accounts.find_one({"_id": ObjectId(r["account_id"])}, {"name": 1})
        upd = {"kind": r["kind"], "bu": None if r["bu"] == "none" else r["bu"], "updated_at": now,
               "company_review": {"at": now, "method": r["method"], "confidence": r.get("confidence"), "why": r.get("why")}}
        name = (r.get("company_name") or "").strip()
        if name and acc and name != acc.get("name"):
            upd.update(name=name, previous_name=acc.get("name"))
            c["renamed"] += 1
        if r["kind"] == "not_a_company":
            upd.update(status="hidden", hidden_reason="company review: not a company (person / mailbox / junk)")
        crm.accounts.update_one({"_id": ObjectId(r["account_id"])}, {"$set": upd})
        c[r["kind"]] += 1
    print(json.dumps(dict(c), indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--apply")
    a = ap.parse_args()
    if a.apply:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sync_zoho_invoices import backup_age_hours
        if backup_age_hours() > 3:
            sys.exit("refusing to apply: newest mongodump is older than 3 h")
        apply(a.apply)
    else:
        out = f"/var/www/campaign_platform/backups/company_review_{datetime.utcnow():%Y%m%dT%H%M%SZ}.jsonl"
        review(limit=a.limit, out=out, with_ai=not a.no_ai)
