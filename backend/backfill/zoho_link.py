"""Zoho invoices -> accounts and Operations projects (owner, 2026-10-24).

Zoho bills under formal legal names and the client's PO numbers, so name
matching against CRM accounts misses. Two parts:

aliases()        each Zoho customer -> one CRM account, strongest evidence
                 first: GSTIN, billing-email domain, normalised name, fuzzy
                 name >= 0.85. The customer's name is added to the account's
                 `legal_names`. Ambiguous -> ONE Review Queue question per Zoho
                 customer; confirming it applies to every invoice of that
                 customer (resume handler "zoho_alias").
link_invoices()  invoice -> project(s): (a) client PO on the invoice = PO on
                 the project / RFQ, or found in that project's mail thread;
                 (b) our project code / RFQ reference in the invoice notes,
                 line items or reference; (c) same account (via alias) +
                 amount within +-2% of completes x CPI (project value when
                 completes are not recorded) + invoice dated 0-60 days after
                 field close. Many-to-many: one invoice may settle several
                 projects of the same account and one project several invoices.

Source: finance_db.zoho_invoices / zoho_contacts (API mirror) when populated,
else the Zoho export already imported into finance_db.invoices / customers.
Dry run by default; apply writes project.invoice_links, invoice.ops_project_ids
and account.legal_names (added to, never replaced), stamped backfill.zoho_link.
"""
import itertools
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backfill.steps import business_domain, norm_name

AMOUNT_TOL = 0.02
WINDOW_DAYS = 60
FUZZY_AUTO = 0.85
FUZZY_REVIEW = 0.75
MAX_COMBO = 3
_PO_CLEAN = re.compile(r"[^A-Z0-9]")
_REF = re.compile(r"\b([A-Z]{0,4}[-/]?\d{3,}[A-Z0-9\-/]*)\b")


def po_key(v) -> Optional[str]:
    k = _PO_CLEAN.sub("", str(v or "").upper())
    return k if len(k) >= 4 else None


def refs_in(text: str) -> set:
    """Project codes / RFQ references: tokens with 3+ digits (e.g. AA8423, 872657-B1, VB-1e8c37-1)."""
    return {po_key(m) for m in _REF.findall((text or "").upper()) if po_key(m) and not re.fullmatch(r"(19|20)\d\d", m)}


# ---------------------------------------------------------------- data


def load(c) -> Dict[str, Any]:
    fin = c.finance_db
    if fin.zoho_invoices.estimated_document_count():
        customers = [{"id": str(z["_id"]), "name": z.get("company_name") or z.get("contact_name"), "email": z.get("email"),
                      "gstin": z.get("gst_no"), "crm_account_id": None} for z in fin.zoho_contacts.find({})]
        invoices = [{"id": str(z["_id"]), "number": z.get("invoice_number"), "customer": str(z.get("customer_id")),
                     "date": _dt(z.get("date")), "amount": float(z.get("total") or 0), "currency": z.get("currency_code"),
                     "po": z.get("reference_number"), "text": " ".join(str(z.get(k) or "") for k in ("reference_number", "notes")),
                     "linked_projects": []} for z in fin.zoho_invoices.find({})]
        return {"source": "zoho_api_mirror", "customers": customers, "invoices": invoices}
    customers = [{"id": str(x["_id"]), "name": x.get("company_name") or x.get("name"), "email": x.get("email"),
                  "gstin": x.get("gstin"), "crm_account_id": str(x.get("crm_account_id") or "") or None}
                 for x in fin.customers.find({"is_deleted": {"$ne": True}})]
    invoices = []
    for i in fin.invoices.find({"status": {"$nin": ["draft", "void"]}, "is_deleted": {"$ne": True}}):
        items = " ".join(" ".join(str(v) for v in (it or {}).values()) for it in (i.get("items") or []))
        invoices.append({"id": str(i["_id"]), "number": i.get("invoice_number"), "customer": str(i.get("customer_id")),
                         "date": i.get("invoice_date"), "amount": float(i.get("subtotal") or i.get("total") or 0),
                         "currency": (i.get("currency_code") or "INR").upper(), "po": i.get("po_reference"),
                         "text": " ".join([str(i.get("po_reference") or ""), str(i.get("notes") or ""), items,
                                           str(i.get("reference_number") or "")]),
                         "linked_projects": [str(x) for x in ([i.get("ops_project_id")] + list(i.get("ops_project_ids") or [])) if x]})
    return {"source": "finance_db.invoices (Zoho export import)", "customers": customers, "invoices": invoices}


def _dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10])
    except Exception:
        return None


# ---------------------------------------------------------------- aliases


def resolve_customer(cu: Dict[str, Any], accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """-> {'outcome': auto|review|none, 'account_id', 'how', 'candidates'}"""
    def one(ids, how):
        ids = sorted(set(ids))
        if len(ids) == 1:
            return {"outcome": "auto", "account_id": ids[0], "how": how}
        if len(ids) > 1:
            return {"outcome": "review", "how": f"{how} matches {len(ids)} accounts", "candidates": ids[:5]}
        return None
    g = (cu.get("gstin") or "").strip().upper()
    if g:
        r = one([str(a["_id"]) for a in accounts if (a.get("gstin") or "").strip().upper() == g], "gstin")
        if r:
            return r
    d = business_domain(cu.get("email"))
    if d:
        r = one([str(a["_id"]) for a in accounts if business_domain(a.get("domain")) == d or d in (a.get("domains") or [])],
                "billing_email_domain")
        if r:
            return r
    nn = norm_name(cu.get("name"))
    if not nn:
        return {"outcome": "none", "how": "no name"}
    names = {str(a["_id"]): {norm_name(x) for x in [a.get("name"), *(a.get("legal_names") or [])] if x} for a in accounts}
    r = one([aid for aid, ns in names.items() if nn in ns], "normalised_name")
    if r:
        return r
    scored = sorted(((max(SequenceMatcher(None, nn, n).ratio() for n in ns), aid) for aid, ns in names.items() if ns),
                    reverse=True)[:3]
    if scored and scored[0][0] >= FUZZY_AUTO and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.03):
        return {"outcome": "auto", "account_id": scored[0][1], "how": f"fuzzy {scored[0][0]:.2f}"}
    if scored and scored[0][0] >= FUZZY_REVIEW:
        return {"outcome": "review", "how": f"fuzzy {scored[0][0]:.2f}", "candidates": [s[1] for s in scored]}
    return {"outcome": "none", "how": "no match"}


def aliases(c, data, apply=False, now=None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    accounts = list(c.crm_db.accounts.find({"merged_into": {"$exists": False}},
                                           {"name": 1, "domain": 1, "domains": 1, "gstin": 1, "legal_names": 1}))
    out: Dict[str, Any] = {"by_customer": {}, "counts": Counter(), "samples": defaultdict(list)}
    for cu in data["customers"]:
        if not cu.get("name"):
            continue
        r = resolve_customer(cu, accounts)
        # an existing crm_account_id link is evidence too: keep it when nothing stronger disagrees
        if r["outcome"] != "auto" and cu.get("crm_account_id") and ObjectId.is_valid(cu["crm_account_id"]):
            r = {"outcome": "auto", "account_id": cu["crm_account_id"], "how": "existing_link"}
        out["by_customer"][cu["id"]] = r
        out["counts"][f"{r['outcome']}:{r['how'].split()[0]}"] += 1
        if len(out["samples"][r["outcome"]]) < 10:
            out["samples"][r["outcome"]].append(f"{(cu['name'] or '')[:50]} -> {r.get('account_id') or r.get('candidates') or '-'} ({r['how']})")
        if not apply:
            continue
        if r["outcome"] == "auto":
            c.crm_db.accounts.update_one({"_id": ObjectId(r["account_id"])},
                                         {"$addToSet": {"legal_names": cu["name"]}, "$set": {"backfill.zoho_link": now}})
        elif r["outcome"] == "review":
            from platform_core import review_queue
            review_queue.enqueue(type="entity_link", module="finance",
                                 ref={"collection": "zoho_customer", "id": cu["id"]},
                                 reason=f"Which account is the Zoho customer \"{cu['name'][:60]}\"? ({r['how']})",
                                 suggested={"account_id": (r.get("candidates") or [None])[0]},
                                 payload={"zoho_customer": cu["id"], "name": cu["name"], "candidates": r.get("candidates")},
                                 resume={"handler": "zoho_alias", "ref": {"customer": cu["id"], "name": cu["name"]}})
    out["counts"] = dict(out["counts"])
    out["samples"] = dict(out["samples"])
    return out


def apply_confirmed_alias(item: Dict[str, Any], decision: Dict[str, Any]):
    """Review resume: the owner picked the account -> alias for every invoice of that customer."""
    from database import get_database
    aid = ((decision.get("correction") or {}).get("account_id") or (item.get("suggested") or {}).get("account_id"))
    if not aid:
        return None
    ref = (item.get("resume") or {}).get("ref") or {}
    get_database("crm_db")["accounts"].update_one({"_id": ObjectId(aid)}, {"$addToSet": {"legal_names": ref.get("name")}})
    if ObjectId.is_valid(str(ref.get("customer"))):
        get_database("finance_db")["customers"].update_one({"_id": ObjectId(ref["customer"]), "crm_account_id": {"$in": [None, ""]}},
                                                          {"$set": {"crm_account_id": aid}})
    return {"alias_for": aid}


# ---------------------------------------------------------------- invoice -> project


def _project_rows(c, only_ids: Optional[set]) -> List[Dict[str, Any]]:
    opps = {}
    for o in c.crm_db.opportunities.find({}, {"po_number": 1, "metadata.rfq.po_number": 1, "metadata.rfq.gmail_thread_ids": 1,
                                             "metadata.rfq.gmail_thread_id": 1, "title": 1, "account_id": 1}):
        r = (o.get("metadata") or {}).get("rfq") or {}
        opps[str(o["_id"])] = {"po": o.get("po_number") or r.get("po_number"), "title": o.get("title"),
                               "threads": [t for t in ([r.get("gmail_thread_id")] + list(r.get("gmail_thread_ids") or [])) if t],
                               "account_id": str(o.get("account_id") or "") or None}
    cust_acc = {str(x["_id"]): str(x.get("crm_account_id") or "") for x in c.finance_db.customers.find({}, {"crm_account_id": 1})}
    rows = []
    for p in c.email_automation.projects.find({"is_deleted": {"$ne": True}}):
        pid = str(p["_id"])
        if only_ids is not None and pid not in only_ids:
            continue
        o = opps.get(str(p.get("opportunity_id") or p.get("rfqId") or ""), {})
        comp, cpi = p.get("actualCompletes") or p.get("totalCompletes"), p.get("cpi")
        expected = float(comp) * float(cpi) if comp and cpi else float(p.get("projectValue") or 0)
        rows.append({"id": pid, "name": p.get("projectName") or "", "account_id": o.get("account_id") or cust_acc.get(str(p.get("customer_id"))),
                     "po": p.get("po_number") or o.get("po"), "threads": o.get("threads") or [],
                     "refs": refs_in((p.get("projectName") or "") + " " + (o.get("title") or "")),
                     "expected": expected, "expected_basis": "completes x CPI" if comp and cpi else "project value",
                     "currency": (p.get("currency") or "").upper() or None, "closed": _dt(p.get("projectCloseDate"))})
    return rows


def _thread_tokens(c, threads, cache) -> set:
    """PO-like tokens in the project's mail thread (whole tokens only)."""
    key = tuple(sorted(threads))
    if key not in cache:
        text = " ".join((m.get("subject") or "") + " " + (m.get("body_plain") or "")[:5000]
                        for m in c.torpedo_gmail.email_metadata.find({"gmail_thread_id": {"$in": list(threads)}},
                                                                      {"subject": 1, "body_plain": 1}).limit(50)).upper()
        cache[key] = {po_key(t) for t in re.findall(r"[A-Z0-9][A-Z0-9/\-]{3,}", text)} - {None}
    return cache[key]


def _close(a, b):
    return b > 0 and abs(a - b) <= AMOUNT_TOL * b


def match(c, data, alias_map, projects, *, dry=True) -> Dict[str, Any]:
    """-> {project_id: [{'invoice', 'method', 'detail'}]}"""
    inv_by_acc = defaultdict(list)
    for i in data["invoices"]:
        a = (alias_map.get(i["customer"]) or {}).get("account_id")
        i["account_id"] = a
        if a:
            inv_by_acc[a].append(i)
    links: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    cache: Dict[Any, str] = {}
    by_po = defaultdict(list)
    for i in data["invoices"]:
        k = po_key(i.get("po"))
        if k:
            by_po[k].append(i)
    for p in projects:
        # (a) PO
        k = po_key(p.get("po"))
        hits = list(by_po.get(k, [])) if k else []
        if not hits and p["threads"]:
            tokens = _thread_tokens(c, p["threads"], cache)
            hits = [i for pk, invs in by_po.items() if pk in tokens for i in invs
                    if not p["account_id"] or i.get("account_id") in (None, p["account_id"])]
        if hits:
            links[p["id"]] += [{"invoice": i["number"], "invoice_id": i["id"], "method": "po", "detail": f"PO {i['po']}"} for i in hits]
            continue
        # (b) our project code / RFQ reference in the invoice text
        if p["refs"]:
            hits = [i for i in data["invoices"] if p["refs"] & refs_in(i.get("text"))]
            if hits:
                links[p["id"]] += [{"invoice": i["number"], "invoice_id": i["id"], "method": "reference",
                                    "detail": ", ".join(sorted(p["refs"] & refs_in(i.get("text"))))} for i in hits]
                continue
        # (c) account + amount + date window (one or several invoices)
        if not (p["account_id"] and p["expected"] and p["closed"]):
            continue
        cands = [i for i in inv_by_acc.get(p["account_id"], []) if i["date"] and
                 timedelta(0) <= i["date"] - p["closed"] <= timedelta(days=WINDOW_DAYS) and
                 (not p["currency"] or i["currency"] == p["currency"])]
        found = None
        for n in range(1, min(MAX_COMBO, len(cands)) + 1):
            for combo in itertools.combinations(cands, n):
                if _close(sum(i["amount"] for i in combo), p["expected"]):
                    found = combo
                    break
            if found:
                break
        if found:
            links[p["id"]] += [{"invoice": i["number"], "invoice_id": i["id"], "method": "amount_date",
                                "detail": f"{len(found)} invoice(s) = {sum(x['amount'] for x in found):.2f} vs {p['expected_basis']} {p['expected']:.2f}"}
                               for i in found]
    # one invoice covering several projects of the same account (c, reverse direction)
    unlinked = [p for p in projects if p["id"] not in links and p["account_id"] and p["expected"] and p["closed"]]
    by_acc = defaultdict(list)
    for p in unlinked:
        by_acc[p["account_id"]].append(p)
    for acc, ps in by_acc.items():
        for i in inv_by_acc.get(acc, []):
            for n in range(2, min(MAX_COMBO, len(ps)) + 1):
                for combo in itertools.combinations(ps, n):
                    if any(q["id"] in links for q in combo):
                        continue
                    if all(i["date"] and timedelta(0) <= i["date"] - q["closed"] <= timedelta(days=WINDOW_DAYS) for q in combo) \
                            and _close(i["amount"], sum(q["expected"] for q in combo)):
                        for q in combo:
                            links[q["id"]].append({"invoice": i["number"], "invoice_id": i["id"], "method": "amount_date",
                                                   "detail": f"one invoice for {n} projects"})
    return dict(links)


def run(c, project_ids: Optional[set] = None, apply=False, now=None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    data = load(c)
    al = aliases(c, data, apply=apply, now=now)
    projects = _project_rows(c, project_ids)
    links = match(c, data, al["by_customer"], projects)
    by_method = Counter()
    samples = defaultdict(list)
    names = {p["id"]: p["name"] for p in projects}
    for pid, ls in links.items():
        m = ls[0]["method"]
        by_method[m] += 1
        if len(samples[m]) < 10:
            samples[m].append(f"{names[pid][:50]} -> {', '.join(sorted({x['invoice'] for x in ls}))} ({ls[0]['detail']})")
    rep = {"source": data["source"], "zoho_customers": len(data["customers"]), "zoho_invoices": len(data["invoices"]),
           "aliases": al["counts"], "alias_samples": al["samples"], "projects_checked": len(projects),
           "linked_by": dict(by_method), "unlinked": len(projects) - len(links), "link_samples": dict(samples)}
    if apply:
        from pymongo import UpdateOne
        pops, iops = [], []
        for pid, ls in links.items():
            pops.append(UpdateOne({"_id": ObjectId(pid)}, {"$addToSet": {"invoice_links": {"$each": [
                {k: x[k] for k in ("invoice", "invoice_id", "method", "detail")} for x in ls]},
                "invoice_ids": {"$each": [x["invoice_id"] for x in ls]}}, "$set": {"backfill.zoho_link": now}}))
            for x in ls:
                if ObjectId.is_valid(x["invoice_id"]):
                    iops.append(UpdateOne({"_id": ObjectId(x["invoice_id"])}, {"$addToSet": {"ops_project_ids": pid}}))
        if pops:
            c.email_automation.projects.bulk_write(pops, ordered=False)
        if iops and data["source"].startswith("finance_db"):
            c.finance_db.invoices.bulk_write(iops, ordered=False)
        rep["review_items_resolved"] = resolve_linked_reviews(c, set(links), now)
    return rep


def resolve_linked_reviews(c, linked_ids: set, now) -> int:
    """Close the 'completed project with no invoice' items whose project is now linked."""
    n = 0
    for it in c.email_automation.review_queue_items.find({"status": "pending", "type": "invoice_request",
                                                          "ref.collection": "email_automation.projects"}):
        if str((it.get("ref") or {}).get("id")) in linked_ids:
            c.email_automation.review_queue_items.update_one({"_id": it["_id"]}, {"$set": {
                "status": "resolved", "resolution": {"action": "approve", "by": "system:zoho_link",
                                                     "note": "invoice found in Zoho (PO / reference / amount+date)"},
                "resolved_at": now, "updated_at": now}})
            n += 1
    return n
