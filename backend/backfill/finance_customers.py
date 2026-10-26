"""Finance customers = the CRM accounts we quote or bill (owner, 2026-10-26).

  keep      one finance customer per CRM account that has an RFQ (so an
            estimate) or an invoice -- the one with invoices, else the oldest;
            an account with none gets one, created from the account
  name      the customer reads exactly as its account; the billed (Zoho legal)
            name stays as legal_name. An account named after a person
            ("Sheik Sikkander (Cint)") takes the billed company's name instead
  merge     the account's other customer records: merged_into the kept one;
            their invoices / estimates point at it (original_customer_id kept)
  hide      every other customer (no estimate, no invoice): is_deleted with a
            reason -- hidden from every list, never removed

Dry run unless apply. Stamped backfill.finance_customers.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId

PERSON_LIKE = re.compile(r"^[A-Z][a-z][A-Za-z'\-]*(?:,? [A-Z][a-z][A-Za-z'\-]*){1,2}$")
COMPANY_WORD = re.compile(r"(?i)\b(research|group|inc|ltd|llc|limited|pvt|private|solutions?|data|insights?|market\w*|"
                          r"exchange|international|global|consult\w*|services?|analytics|panel|surveys?|field\w*|media|"
                          r"labs?|partners?|corp\w*|company|co|agency|tech\w*|systems?|digital|studios?|ventures?|"
                          r"knowledge|intelligence|sampling|sample|strategy|strategies|associates|india|europe|asia)\b")
REASON = "no estimate or invoice -- finance customers are the accounts we quote or bill (owner 2026-10-26)"


def is_person(name: str) -> bool:
    """'Wael RMR (Rmr Research)', 'Teng, Josene (KWKAL) (Kantar)', 'Garret McDannald' -- a person, not a company."""
    n = (name or "").strip()
    if "(" in n:
        return True
    return bool(PERSON_LIKE.match(n)) and not COMPANY_WORD.search(n)


def company_name(billed: list, account: str, others: list) -> str:
    """The one name the account and its finance customer both carry."""
    cands = [*billed, account, *others]
    for n in cands:
        if n and n.strip() and not is_person(n):
            return n.strip()
    for n in cands:                                   # "Meghna Subba (Toluna)" -> "Toluna"
        inner = re.findall(r"\(([^()]{2,60})\)", n or "")
        if inner and not is_person(inner[-1]):
            return inner[-1].strip()
    return (account or "").strip()


def run(c, apply=False, now=None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    fin, crm = c.finance_db, c.crm_db
    stamp = {"backfill.finance_customers": now, "updated_at": now}
    live = list(fin.customers.find({"is_deleted": {"$ne": True}}))
    invoiced = Counter(str(x["customer_id"]) for x in fin.invoices.find({"is_deleted": {"$ne": True}}, {"customer_id": 1})
                       if x.get("customer_id"))
    rfq_accounts = {str(o["account_id"]) for o in crm.opportunities.find(
        {"metadata.rfq": {"$exists": True}, "is_deleted": {"$ne": True}, "account_id": {"$nin": [None, ""]}},
        {"account_id": 1})}
    by_acc = defaultdict(list)
    for cu in live:
        if cu.get("crm_account_id"):
            by_acc[str(cu["crm_account_id"])].append(cu)
    target = set(rfq_accounts) | {a for a, cs in by_acc.items() if any(invoiced[str(x["_id"])] for x in cs)}
    accounts = {str(a["_id"]): a for a in crm.accounts.find(
        {"_id": {"$in": [ObjectId(a) for a in target if ObjectId.is_valid(a)]}}, {"name": 1, "domain": 1, "bu": 1})}

    rep: Counter = Counter()
    samples = defaultdict(list)
    keep_ids = set()
    for aid in sorted(target):
        acc = accounts.get(aid)
        if not acc:
            rep["rfq account missing in crm (skipped)"] += 1
            continue
        group = by_acc.get(aid, [])
        acc_name = (acc.get("name") or "").strip()
        name = company_name([x.get("name") for x in group if invoiced[str(x["_id"])]], acc_name,
                            [x.get("name") for x in group])
        if name != acc_name:
            rep["account renamed (was a person / not the billed company)"] += 1
            if len(samples["account_renamed"]) < 12:
                samples["account_renamed"].append(f"{acc_name[:40]} -> {name[:40]}")
            if apply:
                crm.accounts.update_one({"_id": acc["_id"]}, {"$set": {"name": name, "previous_name": acc_name,
                                                                      **stamp}})
        cs = sorted(group, key=lambda x: (-invoiced[str(x["_id"])], (x.get("name") or "").strip() != name,
                                          x.get("created_at") or now))
        if not cs:
            rep["customer created from account"] += 1
            if len(samples["created"]) < 8:
                samples["created"].append(name)
            if apply:
                fin.customers.insert_one({"name": name, "company_name": name,
                                          "crm_account_id": aid, "domain": acc.get("domain"), "bu": acc.get("bu"),
                                          "source": "crm_account", "created_at": now, **stamp})
            continue
        primary = cs[0]
        keep_ids.add(str(primary["_id"]))
        rep["kept"] += 1
        billed = (primary.get("name") or "").strip()
        if billed != name:
            rep["customer renamed to the account's company name (old name kept)"] += 1
            if len(samples["renamed"]) < 12:
                samples["renamed"].append(f"{billed[:40]} -> {name[:40]}")
            if apply:
                keep = {"legal_name": primary.get("legal_name") or billed} if invoiced[str(primary["_id"])] \
                    else {"previous_name": billed}
                fin.customers.update_one({"_id": primary["_id"]}, {"$set": {"name": name, **keep, **stamp}})
        for dup in cs[1:]:
            rep["duplicate merged"] += 1
            n_inv = invoiced[str(dup["_id"])]
            rep["invoices re-pointed to the kept customer"] += n_inv
            if len(samples["merged"]) < 8:
                samples["merged"].append(f"{(dup.get('name') or '')[:35]} -> {(primary.get('name') or '')[:35]} ({n_inv} inv)")
            if apply:
                pid, did = str(primary["_id"]), str(dup["_id"])
                for col in (fin.invoices, fin.estimates):
                    col.update_many({"customer_id": did}, {"$set": {"customer_id": pid, "original_customer_id": did,
                                                                     **stamp}})
                fin.customers.update_one({"_id": dup["_id"]}, {"$set": {
                    "merged_into": pid, "is_deleted": True, "deleted_at": now,
                    "deleted_reason": "duplicate of the account's finance customer", **stamp}})
    for cu in live:
        cid = str(cu["_id"])
        if cid in keep_ids or str(cu.get("crm_account_id") or "") in target:
            continue
        if invoiced[cid]:
            rep["has invoices but no CRM account (kept, needs a person)"] += 1
            samples["invoiced_no_account"].append(cu.get("name"))
            continue
        rep["hidden (no estimate or invoice)"] += 1
        rep[f"hidden source {cu.get('source')}"] += 1
        if len(samples["hidden"]) < 10:
            samples["hidden"].append(f"{(cu.get('name') or '')[:45]} [{cu.get('source')}]")
        if apply:
            fin.customers.update_one({"_id": cu["_id"]}, {"$set": {
                "is_deleted": True, "deleted_at": now, "deleted_reason": REASON, "hidden_by": "finance_customers",
                **stamp}})
    # every RFQ estimate carries its account's customer
    if apply:
        cust_by_acc = {str(x["crm_account_id"]): x for x in fin.customers.find(
            {"is_deleted": {"$ne": True}, "crm_account_id": {"$in": list(target)}}, {"crm_account_id": 1, "name": 1})}
        opp_acc = {str(o["_id"]): str(o.get("account_id") or "") for o in crm.opportunities.find(
            {"metadata.rfq": {"$exists": True}}, {"account_id": 1})}
        for e in fin.estimates.find({"source": "rfq"}, {"opportunity_id": 1, "customer_id": 1}):
            cu = cust_by_acc.get(opp_acc.get(str(e.get("opportunity_id")), ""))
            if cu and e.get("customer_id") != str(cu["_id"]):
                fin.estimates.update_one({"_id": e["_id"]}, {"$set": {"customer_id": str(cu["_id"]),
                                                                       "customer_name": cu.get("name"), **stamp}})
                rep["rfq estimates given their customer"] += 1
    rep["finance customers after"] = rep["kept"] + rep["customer created from account"] \
        + rep["has invoices but no CRM account (kept, needs a person)"]
    return {**rep, "samples": dict(samples)}
