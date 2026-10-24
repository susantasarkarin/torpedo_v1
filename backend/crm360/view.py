"""One page per account or contact (CRM plan 3.8.3), read-only:

  communication   every mail in and out with the account's contacts or domain,
                  grouped by Gmail thread, filterable by category; plus CRM
                  activities (calls, notes, tasks)
  rfqs            crm_db.opportunities for the account, with status
  projects        Operations projects (email_automation.projects) and the
                  spine stubs that point at them
  quotations      finance_db.estimates / contracts for the account's customers
  invoices        finance_db.invoices + payments received, with outstanding
                  balance per currency (never summed across currencies)
  dnd             account flag + each contact's suppression state
  bu              derived: invoice branch / RFQ mailbox majority; null when
                  there is no evidence (never guessed)

Mail is matched by exact contact address (indexed mail_counterparty) and by
the account's domain; webmail domains never match a whole account.
"""
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from bson import ObjectId

WEBMAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com", "icloud.com",
           "rediffmail.com", "aol.com", "protonmail.com", "msn.com"}
BU_OF_BRANCH = {"survey fieldwork": "SFW", "cogentix research": "COGENTIX"}
BU_OF_DOMAIN = {"surveyfieldwork.com": "SFW", "cogentixresearch.com": "COGENTIX", "bimwavesolutions.com": "BIM"}


def _gd(name):
    from database import get_database
    return get_database(name)


def _oid(v):
    try:
        return ObjectId(str(v))
    except Exception:
        return None


def _ids(v) -> List[Any]:
    """Both forms of an id, because the spine stores some as strings."""
    o = _oid(v)
    return [x for x in (str(v), o) if x is not None]


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            v = str(v)
        out[k] = v
    return out


def _domain(addr: str) -> str:
    return (addr or "").rsplit("@", 1)[-1].lower().strip()


def _account_domains(acc: Dict[str, Any], contacts: List[Dict[str, Any]]) -> List[str]:
    doms = Counter()
    for f in ("domain", "root_domain"):
        d = (acc.get(f) or "").lower().strip()
        if d:
            doms[d] += 100
    for c in contacts:
        d = _domain(c.get("email"))
        if d and d not in WEBMAIL and d not in BU_OF_DOMAIN:
            doms[d] += 1
    return [d for d, _ in doms.most_common(3)]


def communication(emails: List[str], domains: List[str], category: Optional[str] = None,
                  limit: int = 300) -> Dict[str, Any]:
    md = _gd("torpedo_gmail")["email_metadata"]
    proj = {"subject": 1, "direction": 1, "from_email": 1, "to_emails": 1, "timestamp": 1, "gmail_thread_id": 1,
            "snippet": 1, "mail_party": 1, "ai_tier1_category": 1, "has_attachments": 1, "mailbox_id": 1}
    ors: List[Dict[str, Any]] = []
    if emails:
        ors.append({"mail_counterparty": {"$in": emails}})
    for d in domains:
        ors.append({"mail_counterparty": {"$regex": f"@{re.escape(d)}$"}})
    if not ors:
        return {"threads": [], "messages": 0, "categories": {}}
    q: Dict[str, Any] = {"$or": ors}
    if category:
        q["ai_tier1_category"] = category
    msgs = list(md.find(q, proj).sort("timestamp", -1).limit(limit))
    threads: Dict[str, Dict[str, Any]] = {}
    cats = Counter()
    for m in msgs:
        tid = m.get("gmail_thread_id") or str(m["_id"])
        cats[m.get("ai_tier1_category") or "uncategorised"] += 1
        t = threads.setdefault(tid, {"thread_id": tid, "subject": m.get("subject"), "last_at": m.get("timestamp"),
                                     "messages": [], "categories": set()})
        t["messages"].append(_clean({k: m.get(k) for k in ("_id", "direction", "from_email", "timestamp",
                                                           "snippet", "ai_tier1_category", "has_attachments")}))
        t["categories"].add(m.get("ai_tier1_category") or "uncategorised")
    out = []
    for t in threads.values():
        t["categories"] = sorted(t["categories"])
        t["messages"].sort(key=lambda x: x.get("timestamp") or 0)
        out.append(t)
    out.sort(key=lambda t: t["last_at"] or 0, reverse=True)
    return {"threads": out, "messages": len(msgs), "categories": dict(cats), "truncated": len(msgs) >= limit}


def finance(account_id: str) -> Dict[str, Any]:
    fin = _gd("finance_db")
    customers = list(fin["customers"].find({"crm_account_id": {"$in": _ids(account_id)}, "is_deleted": {"$ne": True}},
                                           {"name": 1, "company_name": 1, "payment_terms": 1, "currency": 1}))
    cids = [x for c in customers for x in _ids(c["_id"])]
    invoices = [_clean(i) for i in fin["invoices"].find(
        {"customer_id": {"$in": cids}, "is_deleted": {"$ne": True}},
        {"invoice_number": 1, "invoice_date": 1, "due_date": 1, "status": 1, "total": 1, "balance_due": 1,
         "amount_paid": 1, "currency_code": 1, "branch": 1, "ops_project_id": 1, "opportunity_id": 1}).sort("invoice_date", -1)]
    payments = [_clean(p) for p in fin["payments_received"].find({"customer_id": {"$in": cids}}).sort("date", -1).limit(200)]
    estimates = [_clean(e) for e in fin["estimates"].find({"customer_id": {"$in": cids}},
                 {"estimate_number": 1, "status": 1, "total_amount": 1, "currency_code": 1, "created_at": 1}).sort("created_at", -1).limit(100)]
    contracts = [_clean(c) for c in fin["contracts"].find({"customer_id": {"$in": cids}},
                 {"contract_number": 1, "status": 1, "value": 1, "currency": 1, "start_date": 1})]
    outstanding: Dict[str, float] = defaultdict(float)
    for i in invoices:
        if (i.get("status") or "") not in ("paid", "void", "written_off", "draft"):
            outstanding[i.get("currency_code") or "INR"] += float(i.get("balance_due") or 0)
    return {"customers": [_clean(c) for c in customers], "invoices": invoices, "payments": payments,
            "quotations": estimates, "contracts": contracts,
            "outstanding_by_currency": {k: round(v, 2) for k, v in outstanding.items() if v}}


def derive_bu(invoices: List[Dict[str, Any]], rfqs: List[Dict[str, Any]], mailbox_bu: Dict[str, str]) -> Dict[str, Any]:
    """The billing entity decides. Measured 2026-10-24: Hansa's RFQs land in a
    Cogentix mailbox (440) but their subjects end _SFW and SFW invoices them,
    so the receiving mailbox is only a fallback when nothing has been billed,
    and a disagreement is surfaced, not resolved by a vote."""
    inv, mbx = Counter(), Counter()
    for i in invoices:
        b = BU_OF_BRANCH.get((i.get("branch") or "").strip().lower())
        if b:
            inv[b] += 1
    for r in rfqs:
        b = mailbox_bu.get(str(((r.get("metadata") or {}).get("rfq") or {}).get("mailbox_id")))
        if b:
            mbx[b] += 1
    evidence = {"invoice_branch": dict(inv), "rfq_mailbox": dict(mbx)}
    source = inv or mbx
    if not source:
        return {"bu": None, "evidence": evidence, "note": "no invoice or RFQ evidence"}
    top = source.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return {"bu": None, "evidence": evidence, "note": "tie: a person decides (Review Queue)"}
    out = {"bu": top[0][0], "evidence": evidence, "decided_by": "invoice_branch" if inv else "rfq_mailbox"}
    if inv and mbx and mbx.most_common(1)[0][0] != top[0][0]:
        out["note"] = "RFQs arrive in another BU's mailbox than the one that invoices"
    return out


def _mailbox_bu() -> Dict[str, str]:
    g = _gd("torpedo_gmail")
    out = {}
    for col in ("workspace_mailboxes", "mailboxes"):
        for b in g[col].find({}, {"email": 1}):
            bu = BU_OF_DOMAIN.get(_domain(b.get("email")))
            if bu:
                out[str(b["_id"])] = bu
    return out


def account_view(account_id: str, category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    crm = _gd("crm_db")
    acc = crm["accounts"].find_one({"_id": {"$in": _ids(account_id)}})
    if not acc:
        return None
    aid = str(acc["_id"])
    contacts = [_clean(c) for c in crm["contacts"].find({"account_id": {"$in": _ids(aid)}},
                                                         {"name": 1, "email": 1, "title": 1, "phone": 1, "lead_id": 1})]
    emails = sorted({(c.get("email") or "").lower() for c in contacts if c.get("email")})
    from messaging import suppression
    for c in contacts:
        try:
            c["dnd"] = bool(c.get("email")) and suppression.is_suppressed(c["email"])
            c["dnd_reason"] = suppression.reason_for(c["email"]) if c["dnd"] else None
        except Exception:
            c["dnd"], c["dnd_reason"] = None, "suppression list unreadable"
    domains = _account_domains(acc, contacts)
    rfqs = list(crm["opportunities"].find({"account_id": {"$in": _ids(aid)}},
                                          {"title": 1, "stage": 1, "status": 1, "amount": 1, "created_at": 1,
                                           "metadata.rfq.mailbox_id": 1, "metadata.rfq.cpi": 1,
                                           "metadata.rfq.currency": 1, "metadata.rfq.received_at": 1}).sort("created_at", -1))
    opp_ids = [x for r in rfqs for x in _ids(r["_id"])]
    ops_projects = [_clean(p) for p in _gd("email_automation")["projects"].find(
        {"opportunity_id": {"$in": opp_ids}}, {"name": 1, "projectName": 1, "status": 1, "createdAt": 1, "opportunity_id": 1})]
    fin = finance(aid)
    activities = [_clean(a) for a in crm["activities"].find({"account_id": {"$in": _ids(aid)}}).sort("created_at", -1).limit(100)]
    return {
        "account": _clean({k: acc.get(k) for k in ("_id", "name", "domain", "root_domain", "status", "industry",
                                                   "country", "dnd", "dnd_reason", "credit_hold", "engagement_status",
                                                   "payment_terms")}),
        "bu": derive_bu(fin["invoices"], rfqs, _mailbox_bu()),
        "dnd": {"account": bool(acc.get("dnd")), "contacts_dnd": sum(1 for c in contacts if c.get("dnd"))},
        "contacts": contacts,
        "communication": communication(emails, domains, category),
        "activities": activities,
        "rfqs": [_clean({**{k: r.get(k) for k in ("_id", "title", "stage", "status", "amount", "created_at")},
                         "cpi": ((r.get("metadata") or {}).get("rfq") or {}).get("cpi"),
                         "currency": ((r.get("metadata") or {}).get("rfq") or {}).get("currency")}) for r in rfqs],
        "projects": ops_projects,
        **{k: fin[k] for k in ("quotations", "contracts", "invoices", "payments", "outstanding_by_currency")},
        "matched_on": {"emails": len(emails), "domains": domains},
    }


def contact_view(contact_id: str, category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    crm = _gd("crm_db")
    c = crm["contacts"].find_one({"_id": {"$in": _ids(contact_id)}})
    if not c:
        return None
    acc = account_view(str(c["account_id"]), category) if c.get("account_id") else None
    email = (c.get("email") or "").lower()
    mine = communication([email] if email else [], [], category)
    return {"contact": _clean({k: c.get(k) for k in ("_id", "name", "email", "title", "phone", "account_id", "lead_id")}),
            "communication": mine, "account": acc, "web_visits": web_visits(str(c["_id"]))}


def web_visits(contact_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Landing-page visits tied to this contact (3.12 step 8)."""
    ea = _gd("email_automation")
    vids = [v["visitor_id"] for v in ea["web_visitors"].find({"contact_id": contact_id}, {"visitor_id": 1})]
    if not vids:
        return []
    return [{"at": e.get("at"), "type": e.get("type"), "host": e.get("host"), "path": e.get("path"), "value": e.get("value")}
            for e in ea["web_events"].find({"visitor_id": {"$in": vids}, "type": {"$in": ["page_view", "cta_click", "form_submit"]}})
            .sort("at", -1).limit(limit)]
