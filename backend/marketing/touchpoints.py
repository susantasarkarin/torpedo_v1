"""One person, many touchpoints (MARKETING_PLAN 3.8.1-3.8.4).

Deterministic links only (no fingerprinting) from a CRM lead to:
  web visitors  web_visitors.lead_id / contact_id (mail token ?r=) / form_email
  sessions      web_sessions of those visitors (consented visits only exist)
  forms         lead.web_submissions (with their own utm / click IDs / first touch)
  mail          torpedo_gmail.email_metadata by counterparty = lead email
  conversions   crm_db.opportunities by contact (rfq at created_at, won at won_at)
Ad clicks, social, WhatsApp and lead-form touchpoints are written by their
integrations (M3) into the same collection with their own `kind`.

Revenue = invoiced INR for the won project (finance_db.invoices.ops_project_id),
else the won amount; a non-INR value without a stored rate is not guessed
(fx_missing). Dry run unless apply=True: touchpoints + attribution_results.
"""
import hashlib
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from bson import ObjectId

from marketing import attribution, schema

MAIL_LIMIT = 200


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


def _ids(v) -> List[Any]:
    s = str(v)
    return [s, ObjectId(s)] if ObjectId.is_valid(s) else [s]


def visitor_ids(ea, lead: Dict[str, Any]) -> List[str]:
    ors: List[Dict[str, Any]] = [{"lead_id": str(lead["_id"])}]
    if lead.get("contact_id"):
        ors.append({"contact_id": str(lead["contact_id"])})
    if lead.get("email"):
        ors.append({"form_email": lead["email"]})
    return sorted({v["visitor_id"] for v in ea["web_visitors"].find({"$or": ors}, {"visitor_id": 1}) if v.get("visitor_id")})


def build(gd: Callable, lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    ea, lid = gd(schema.DB), str(lead["_id"])
    bu = lead.get("bu") if lead.get("bu") in schema.BUS else None
    out: List[Dict[str, Any]] = []
    vids = visitor_ids(ea, lead)
    for s in ea["web_sessions"].find({"visitor_id": {"$in": vids}}) if vids else []:
        out.append({"kind": "visit", "at": s.get("started_at"), "ref": s["session_id"], "visitor_id": s["visitor_id"],
                    "utm": s.get("utm") or {}, "click_ids": s.get("click_ids") or {}, "referrer": s.get("referrer"),
                    "landing": s.get("landing"), "bu": s.get("bu") or bu, "source": "web_tracker"})
    for v in ea["web_visitors"].find({"visitor_id": {"$in": vids}, "first_touch": {"$exists": True}}) if vids else []:
        ft = v["first_touch"]
        at = _parse_ts(ft.get("ts"))
        if at and not any(t["kind"] == "visit" and t["visitor_id"] == v["visitor_id"] and t["at"] and t["at"] <= at
                          for t in out):
            out.append({"kind": "visit", "at": at, "ref": f"first:{v['visitor_id']}", "visitor_id": v["visitor_id"],
                        "utm": {k: x for k, x in ft.items() if k.startswith("utm_")},
                        "click_ids": {k: ft[k] for k in ("gclid", "gbraid", "wbraid", "li_fat_id", "fbclid") if ft.get(k)},
                        "referrer": ft.get("referrer"), "landing": ft.get("landing"), "mail_token": bool(ft.get("mail_token")),
                        "bu": bu, "source": "web_tracker"})
    for i, sub in enumerate(lead.get("web_submissions") or []):
        out.append({"kind": "form", "at": sub.get("at"), "ref": f"{lid}:form:{i}", "visitor_id": sub.get("visitor_id") or None,
                    "utm": sub.get("utm") or {}, "click_ids": sub.get("click_ids") or {}, "referrer": sub.get("referrer"),
                    "landing": sub.get("page"), "heard_from": sub.get("heard_from"), "bu": bu, "source": "website_form"})
    if lead.get("email"):
        md = gd("torpedo_gmail")["email_metadata"]
        for m in md.find({"mail_counterparty": lead["email"]}, {"direction": 1, "timestamp": 1, "subject": 1})\
                .sort("timestamp", -1).limit(MAIL_LIMIT):
            out.append({"kind": "mail_in" if m.get("direction") == "inbound" else "mail_out", "at": m.get("timestamp"),
                        "ref": str(m["_id"]), "subject": (m.get("subject") or "")[:120], "bu": bu, "source": "gmail"})
    for t in out:
        t.update(lead_id=lid, contact_id=str(lead["contact_id"]) if lead.get("contact_id") else None,
                 tp_key=_key(lid, t["kind"], t["ref"]))
        t["channel"] = attribution.channel(t)
    return [t for t in out if isinstance(t.get("at"), datetime)]


def conversions(gd: Callable, lead: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not lead.get("contact_id"):
        return []
    crm, fin = gd("crm_db"), gd("finance_db")
    out = []
    for o in crm["opportunities"].find({"contact_id": {"$in": _ids(lead["contact_id"])}},
                                       {"created_at": 1, "status": 1, "won_at": 1, "amount": 1, "currency": 1, "project_id": 1}):
        oid = str(o["_id"])
        out.append({"id": f"{oid}:rfq", "opportunity_id": oid, "event": "rfq", "at": o.get("created_at"), "value_inr": 0})
        if o.get("status") == "won":
            v = revenue_inr(fin, o)
            out.append({"id": f"{oid}:won", "opportunity_id": oid, "event": "won", "at": o.get("won_at") or o.get("created_at"),
                        **v})
    return out


def revenue_inr(fin, opp: Dict[str, Any]) -> Dict[str, Any]:
    if opp.get("project_id"):
        inv = list(fin["invoices"].find({"ops_project_id": {"$in": _ids(opp["project_id"])}, "status": {"$ne": "void"}},
                                        {"subtotal": 1, "total": 1, "currency_code": 1, "exchange_rate": 1}))
        if inv:
            tot, missing = 0.0, False
            for i in inv:
                amt = float(i.get("subtotal") or i.get("total") or 0)
                if (i.get("currency_code") or "INR") == "INR":
                    tot += amt
                elif i.get("exchange_rate"):
                    tot += amt * float(i["exchange_rate"])
                else:
                    missing = True
            return {"value_inr": round(tot, 2), "value_basis": "invoiced", "fx_missing": missing}
    amt, cur = float(opp.get("amount") or 0), (opp.get("currency") or "INR")
    if cur == "INR":
        return {"value_inr": amt, "value_basis": "won_amount", "fx_missing": False}
    return {"value_inr": 0, "value_basis": "won_amount", "fx_missing": bool(amt), "value": amt, "currency": cur}


def run(gd: Callable, *, apply: bool = False, since: Optional[datetime] = None, limit: Optional[int] = None,
        now: Optional[datetime] = None) -> Dict[str, Any]:
    """Leads that have a web link, a form, or an RFQ contact. `since` = leads updated since (incremental)."""
    from pymongo import UpdateOne
    now = now or datetime.utcnow()
    crm, ea = gd("crm_db"), gd(schema.DB)
    q: Dict[str, Any] = {"$or": [{"web_submissions.0": {"$exists": True}}, {"contact_id": {"$nin": [None, ""]}}]}
    if since:
        q["updated_at"] = {"$gte": since}
    cur = crm["leads"].find(q, {"email": 1, "contact_id": 1, "bu": 1, "web_submissions": 1})
    if limit:
        cur = cur.limit(limit)
    rep: Dict[str, Any] = {"leads": 0, "touchpoints": 0, "by_kind": {}, "conversions": {"rfq": 0, "won": 0},
                           "won_value_inr": 0.0, "fx_missing": 0, "channel_last_non_direct": {}, "apply": apply}
    tp_ops, at_ops = [], []
    for lead in cur:
        rep["leads"] += 1
        tps = build(gd, lead)
        rep["touchpoints"] += len(tps)
        for t in tps:
            rep["by_kind"][t["kind"]] = rep["by_kind"].get(t["kind"], 0) + 1
            f, u = schema.upsert_ops(t, ["tp_key"], bu=t.get("bu"), source=t["source"], now=now)
            tp_ops.append(UpdateOne(f, u, upsert=True))
        for c in conversions(gd, lead):
            rep["conversions"][c["event"]] += 1
            if c["event"] == "won":
                rep["won_value_inr"] += c.get("value_inr") or 0
            rep["fx_missing"] += 1 if c.get("fx_missing") else 0
            res = attribution.attribute(tps, c)
            for ch, x in res["models"][attribution.DEFAULT_MODEL].items():
                rep["channel_last_non_direct"][f"{c['event']}:{ch}"] = rep["channel_last_non_direct"].get(f"{c['event']}:{ch}", 0) + x["credit"]
            for m in attribution.MODELS:
                doc = {"lead_id": str(lead["_id"]), "conversion_id": c["id"], "event": c["event"], "model": m,
                       "conversion_at": c["at"], "value_inr": c.get("value_inr") or 0, "value_basis": c.get("value_basis"),
                       "credits": res["models"][m], "touches": res["touches"], "path": res["path"],
                       "days_to_convert": res["days_to_convert"]}
                bu = lead.get("bu") if lead.get("bu") in schema.BUS else None
                f, u = schema.upsert_ops(doc, ["lead_id", "conversion_id", "model"], bu=bu, source="attribution", now=now)
                at_ops.append(UpdateOne(f, u, upsert=True))
        if apply and len(tp_ops) >= 1000:
            ea["touchpoints"].bulk_write(tp_ops, ordered=False); tp_ops = []
        if apply and len(at_ops) >= 1000:
            ea["attribution_results"].bulk_write(at_ops, ordered=False); at_ops = []
    if apply and tp_ops:
        ea["touchpoints"].bulk_write(tp_ops, ordered=False)
    if apply and at_ops:
        ea["attribution_results"].bulk_write(at_ops, ordered=False)
    rep["won_value_inr"] = round(rep["won_value_inr"], 2)
    rep["channel_last_non_direct"] = {k: round(v, 2) for k, v in sorted(rep["channel_last_non_direct"].items())}
    return rep


def _parse_ts(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
