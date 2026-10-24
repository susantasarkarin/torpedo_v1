"""KPI values, the "Needs attention" list and nightly snapshots (CRM plan 3.14).

Every function takes gd (database getter), the period [since, until) and a BU
(None = all). BU is known for invoices (branch) and ops/service projects;
where a source has no BU yet the value is all-BU and says so (`bu_scope`).
Money is INR at the latest locked rate in finance_db.invoice_fx.
"""
import statistics
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from kpi import definitions

BRANCH_BU = {"Survey Fieldwork": "SFW", "Cogentix Research": "COGENTIX", "BIM Wave Solutions": "BIM"}
BU_BRANCH = {v: k for k, v in BRANCH_BU.items()}


def _fx(gd) -> Dict[str, float]:
    out = {"INR": 1.0}
    for cur in ("USD", "EUR", "GBP", "SGD", "AUD"):
        r = gd("finance_db")["invoice_fx"].find_one({"currency": cur}, sort=[("rate_date", -1)])
        if r and r.get("rate"):
            out[cur] = float(r["rate"])
    return out


def _inr(doc, field, fx) -> float:
    return float(doc.get(field) or 0) * fx.get((doc.get("currency_code") or doc.get("currency") or "INR").upper(), 0.0)


def _inv_q(bu, extra=None):
    q = {"status": {"$nin": ["draft", "void"]}, "is_deleted": {"$ne": True}, **(extra or {})}
    if bu:
        q["branch"] = BU_BRANCH.get(bu, bu)
    return q


def revenue_invoiced(gd, since, until, bu):
    fx = _fx(gd)
    return round(sum(_inr(i, "total", fx) for i in gd("finance_db")["invoices"].find(
        _inv_q(bu, {"invoice_date": {"$gte": since, "$lt": until}}), {"total": 1, "currency_code": 1})), 2)


def cash_collected(gd, since, until, bu):
    fx = _fx(gd)
    return round(sum(_inr(i, "total", fx) for i in gd("finance_db")["invoices"].find(
        _inv_q(bu, {"status": "paid", "updated_at": {"$gte": since, "$lt": until}}), {"total": 1, "currency_code": 1})), 2)


def _overdue(gd, until, bu):
    fx = _fx(gd)
    return [(i, _inr(i, "balance_due", fx)) for i in gd("finance_db")["invoices"].find(
        _inv_q(bu, {"balance_due": {"$gt": 0}, "status": {"$nin": ["draft", "void", "paid", "written_off"]},
                    "due_date": {"$lt": until}}),
        {"balance_due": 1, "currency_code": 1, "due_date": 1, "customer_id": 1, "invoice_number": 1})]


def overdue_receivables(gd, since, until, bu):
    return round(sum(v for _, v in _overdue(gd, until, bu)), 2)


def dso(gd, since, until, bu):
    fx = _fx(gd)
    open_ar = sum(_inr(i, "balance_due", fx) for i in gd("finance_db")["invoices"].find(
        _inv_q(bu, {"balance_due": {"$gt": 0}, "status": {"$nin": ["draft", "void", "paid", "written_off"]}}),
        {"balance_due": 1, "currency_code": 1}))
    rev = revenue_invoiced(gd, until - timedelta(days=90), until, bu)
    return round(open_ar / rev * 90, 1) if rev else None


def receivables_aging(gd, since, until, bu):
    out = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    for i, v in _overdue(gd, until, bu):
        d = (until - i["due_date"]).days
        out["0-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"] += v
    return {k: round(x, 2) for k, x in out.items()}


def credit_hold_accounts(gd, since, until, bu):
    return len({str(i.get("customer_id")) for i, _ in _overdue(gd, until, bu) if (until - i["due_date"]).days > 60})


def open_pipeline(gd, since, until, bu):
    return round(sum(float(o.get("amount") or 0) for o in gd("crm_db")["opportunities"].find(
        {"stage": "proposal", "status": "open"}, {"amount": 1})), 2)


def win_rate_90d(gd, since, until, bu):
    won = lost = 0.0
    for o in gd("crm_db")["opportunities"].find({"status": {"$in": ["won", "closed"]},
                                                 "updated_at": {"$gte": until - timedelta(days=90), "$lt": until}},
                                                {"status": 1, "amount": 1, "closed_reason": 1}):
        if "historical" in (o.get("closed_reason") or ""):
            continue
        if o["status"] == "won":
            won += float(o.get("amount") or 0)
        else:
            lost += float(o.get("amount") or 0)
    return round(100 * won / (won + lost), 1) if won + lost else None


def _proj_q(bu):
    q = {"is_deleted": {"$ne": True}}
    if bu:
        q["bu"] = bu
    return q


def projects_live(gd, since, until, bu):
    return gd("email_automation")["projects"].count_documents(
        {**_proj_q(bu), "$or": [{"lifecycle_status": {"$in": ["live", "soft_launch"]}},
                                {"lifecycle_status": {"$exists": False}, "status": "active", "projectStatus": "live"}]})


def projects_by_status(gd, since, until, bu):
    from ops.lifecycle import legacy_status
    out: Dict[str, int] = {}
    for p in gd("email_automation")["projects"].find(_proj_q(bu), {"lifecycle_status": 1, "status": 1, "projectStatus": 1,
                                                                   "invoice_ids": 1, "actualCompletes": 1, "liveLink": 1}):
        s = legacy_status(p)
        out[s] = out.get(s, 0) + 1
    return out


def closed_not_invoiced(gd, since, until, bu):
    return gd("email_automation")["projects"].count_documents(
        {**_proj_q(bu), "$or": [{"lifecycle_status": "closed"}, {"status": "completed"}],
         "invoice_ids": {"$in": [None, []]}})


def leads_added(gd, since, until, bu):
    return gd("email_automation")["leads_raw"].count_documents({"created_at": {"$gte": since, "$lt": until}})


def _sends(gd, since, until):
    return gd("torpedo")["outreach_sends_v2"]


def mails_sent(gd, since, until, bu):
    return _sends(gd, since, until).count_documents({"sent_at": {"$gte": since, "$lt": until}})


def reply_rate(gd, since, until, bu):
    s = _sends(gd, since, until)
    n = s.count_documents({"sent_at": {"$gte": since, "$lt": until}})
    r = s.count_documents({"sent_at": {"$gte": since, "$lt": until}, "reply_received": True})
    return round(100 * r / n, 2) if n else None


def bounce_rate(gd, since, until, bu):
    s = _sends(gd, since, until)
    n = s.count_documents({"sent_at": {"$gte": since, "$lt": until}})
    b = s.count_documents({"sent_at": {"$gte": since, "$lt": until}, "status": "bounced"})
    return round(100 * b / n, 2) if n else None


def mailboxes_paused(gd, since, until, bu):
    return gd("torpedo_gmail")["workspace_mailboxes"].count_documents({"outreach_paused": {"$nin": [None, False, {}]}})


def visitors(gd, since, until, bu):
    q = {"at": {"$gte": since, "$lt": until}}
    if bu:
        q["bu"] = bu
    return len(gd("email_automation")["web_events"].distinct("visitor_id", q))


def identified_pct(gd, since, until, bu):
    v = gd("email_automation")["web_visitors"]
    n = v.count_documents({"last_seen": {"$gte": since, "$lt": until}})
    k = v.count_documents({"last_seen": {"$gte": since, "$lt": until}, "contact_id": {"$exists": True}})
    return round(100 * k / n, 1) if n else None


def inbound_processed(gd, since, until, bu):
    return gd("email_automation")["mail_decisions"].count_documents({"decided_at": {"$gte": since, "$lt": until}})


def auto_handled_pct(gd, since, until, bu):
    d = gd("email_automation")["mail_decisions"]
    n = d.count_documents({"decided_at": {"$gte": since, "$lt": until}})
    rv = d.count_documents({"decided_at": {"$gte": since, "$lt": until}, "actions.type": "review"})
    return round(100 * (n - rv) / n, 1) if n else None


def rfqs_received(gd, since, until, bu):
    return gd("crm_db")["opportunities"].count_documents({"metadata.rfq.received_at": {"$gte": since, "$lt": until}})


def median_hours_to_quote(gd, since, until, bu):
    hrs = []
    for o in gd("crm_db")["opportunities"].find({"quoted_at": {"$gte": since, "$lt": until}},
                                                {"quoted_at": 1, "metadata.rfq.received_at": 1}):
        rec = ((o.get("metadata") or {}).get("rfq") or {}).get("received_at")
        if isinstance(rec, datetime) and isinstance(o.get("quoted_at"), datetime) and o["quoted_at"] >= rec:
            hrs.append((o["quoted_at"] - rec).total_seconds() / 3600)
    return round(statistics.median(hrs), 1) if hrs else None


def rfqs_awaiting_info(gd, since, until, bu):
    return gd("email_automation")["rfq_decisions"].count_documents({"status": "awaiting_info"})


def sd_active(gd, since, until, bu):
    q = {"status": {"$ne": "closed"}}
    if bu:
        q["bu"] = bu
    return gd("crm_db")["service_projects"].count_documents(q)


def bids_requested(gd, since, until, bu):
    return gd("crm_db")["vendor_bids"].count_documents({"requested_at": {"$gte": since, "$lt": until}})


def accounts_by_engagement(gd, since, until, bu):
    s = gd("email_automation")["reengagement_decisions"].find_one({"kind": "summary"}, sort=[("at", -1)])
    return {k: s[k] for k in ("active", "dormant", "lost", "dnd") if s and k in s} if s else None


def review_queue_open(gd, since, until, bu):
    q = {"status": "pending"}
    if bu:
        q["bu"] = bu
    return gd("email_automation")["review_queue_items"].count_documents(q)


def qwen_failed(gd, since, until, bu):
    return gd("ai_governance")["qwen_jobs"].count_documents({"status": "failed"})


def jobs_failing(gd, since, until, bu):
    return gd("torpedo_settings")["job_runs"].count_documents({"status": {"$in": ["error", "missed"]}})


def mail_sync_lag_min(gd, since, until, bu):
    m = gd("torpedo_gmail")["email_metadata"].find_one({}, {"timestamp": 1}, sort=[("timestamp", -1)])
    return round((datetime.utcnow() - m["timestamp"]).total_seconds() / 60) if m and m.get("timestamp") else None


FUNCS: Dict[str, Callable] = {n: f for n, f in globals().items() if callable(f) and not n.startswith("_")}


def period(name: str, now: datetime) -> tuple:
    """(since, until, previous_since, previous_until); IST calendar, stored UTC."""
    ist = now + timedelta(hours=5, minutes=30)
    day0 = ist.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "today":
        s = day0
        ps = s - timedelta(days=1)
    elif name == "week":
        s = day0 - timedelta(days=day0.weekday())
        ps = s - timedelta(days=7)
    elif name == "qtd":
        q = (day0.month - 1) // 3 * 3 + 1
        s = day0.replace(month=q, day=1)
        ps = (s - timedelta(days=1)).replace(day=1)
        ps = ps.replace(month=(ps.month - 1) // 3 * 3 + 1)
    elif name == "ytd":     # financial year from 1 April
        y = day0.year if day0.month >= 4 else day0.year - 1
        s = day0.replace(year=y, month=4, day=1)
        ps = s.replace(year=y - 1)
    else:                   # mtd
        s = day0.replace(day=1)
        ps = (s - timedelta(days=1)).replace(day=1)
    off = timedelta(hours=5, minutes=30)
    length = ist - s
    return s - off, now, ps - off, ps - off + length


def value(gd, key: str, since, until, bu) -> Any:
    d = next((x for x in definitions.all_definitions() if x["key"] == key), None)
    if not d or not d["compute"]:
        return None
    try:
        return FUNCS[d["compute"]](gd, since, until, bu)
    except Exception as e:      # one broken source must not blank the dashboard
        return {"error": str(e)[:120]}


def tiles(gd, module: str, period_name: str, bu: Optional[str], now: Optional[datetime] = None,
          kpi_cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow()
    s, u, ps, pu = period(period_name, now)
    targets = (kpi_cfg or definitions.config_defaults())["targets"]
    out = []
    for d in definitions.all_definitions():
        if d["module"] != module:
            continue
        v = value(gd, d["key"], s, u, bu)
        prev = value(gd, d["key"], ps, pu, bu) if d["compute"] and module != "system" else None
        change = round(v - prev, 2) if isinstance(v, (int, float)) and isinstance(prev, (int, float)) else None
        t = targets.get(d["key"]) or {}
        out.append({**{k: d[k] for k in ("key", "name", "definition", "unit", "higher_is_better", "sources")},
                    "value": v, "previous": prev, "change": change, "target": t.get("target"),
                    "status": definitions.rag(v, t, d["higher_is_better"]),
                    "available": d["compute"] is not None})
    return out


# ---------------------------------------------------------------- needs attention


def needs_attention(gd, now: Optional[datetime] = None, cfg: Optional[Dict[str, Any]] = None, limit: int = 15) -> Dict[str, Any]:
    """Ranked by INR at risk x days waiting; red before amber."""
    now = now or datetime.utcnow()
    cfg = cfg or definitions.config_defaults()
    fx = _fx(gd)
    items: List[Dict[str, Any]] = []

    def add(module, what, inr, since, owner, link, red):
        days = max(0.0, (now - since).total_seconds() / 86400) if isinstance(since, datetime) else 0.0
        items.append({"module": module, "what": what, "at_stake_inr": round(inr or 0, 2), "waiting_days": round(days, 1),
                      "owner": owner, "link": link, "severity": "red" if red else "amber",
                      "rank": (inr or 1000) * max(days, 0.1)})

    for r in gd("email_automation")["review_queue_items"].find(
            {"status": "pending", "created_at": {"$lt": now - timedelta(hours=4)}}).sort("created_at", 1).limit(200):
        add(r.get("module") or "review", f"Review Queue: {r.get('reason') or r.get('type')}", r.get("value_inr"),
            r.get("created_at"), r.get("owner"), f"/admin/review-queue?id={r['_id']}", now - r["created_at"] > timedelta(days=1))
    tat = timedelta(hours=float(cfg.get("rfq_turnaround_hours") or 24))
    for o in gd("crm_db")["opportunities"].find({"stage": "rfq", "status": "open",
                                                 "metadata.rfq.received_at": {"$lt": now - tat, "$gte": now - timedelta(days=60)}},
                                                {"title": 1, "metadata.rfq.received_at": 1, "account_id": 1}).limit(200):
        add("rfq", f"RFQ not quoted: {o.get('title')}", None, o["metadata"]["rfq"]["received_at"], None,
            f"/admin/rfq?id={o['_id']}", now - o["metadata"]["rfq"]["received_at"] > 3 * tat)
    for p in gd("email_automation")["projects"].find(
            {"is_deleted": {"$ne": True}, "$or": [{"lifecycle_status": "closed"}, {"status": "completed"}],
             "invoice_ids": {"$in": [None, []]}, "updated_at": {"$lt": now - timedelta(days=2), "$gte": now - timedelta(days=180)}},
            {"projectName": 1, "projectValue": 1, "currency": 1, "updated_at": 1}).limit(200):
        inr = float(p.get("projectValue") or 0) * fx.get((p.get("currency") or "INR").upper(), 0)
        add("finance", f"Closed, not invoiced: {p.get('projectName')}", inr, p.get("updated_at"), None,
            f"/admin/operations/projects/{p['_id']}", True)
    for i, v in _overdue(gd, now, None):
        if (now - i["due_date"]).days > 60:
            add("finance", f"Receivable > 60 days: {i.get('invoice_number')}", v, i["due_date"], None,
                f"/admin/finance/invoices/{i['_id']}", True)
    for m in gd("torpedo_gmail")["workspace_mailboxes"].find({"outreach_paused": {"$nin": [None, False, {}]}},
                                                             {"email": 1, "outreach_paused": 1}):
        add("deliverability", f"Mailbox auto-paused: {(m.get('outreach_paused') or {}).get('reason', '')}", None,
            (m.get("outreach_paused") or {}).get("at"), None, "/admin/deliverability", True)
    for j in gd("torpedo_settings")["job_runs"].find({"status": {"$in": ["error", "missed"]}}):
        add("system", f"Scheduled job {j['_id']}: {j['status']} {j.get('last_error') or ''}".strip(), None,
            j.get("last_run_at") or j.get("last_missed_at"), None, "/admin/dashboards/system", True)
    nfail = gd("ai_governance")["qwen_jobs"].count_documents({"status": "failed"})
    if nfail:
        add("system", f"{nfail} Qwen jobs failed", None, now, None, "/admin/review-queue?tab=failed", nfail > 10)
    for s in gd("crm_db")["service_projects"].find({"status": {"$ne": "closed"}, "milestones.due": {"$lt": now}},
                                                  {"title": 1, "milestones": 1, "owner": 1, "value": 1}).limit(100):
        late = [m for m in s.get("milestones") or [] if isinstance(m.get("due"), datetime) and m["due"] < now and not m.get("signed_off_at")]
        if late:
            add("service_delivery", f"Milestone overdue: {s.get('title')} / {late[0].get('deliverable')}",
                float(s.get("value") or 0) * float(late[0].get("billing_pct") or 0) / 100, late[0]["due"], s.get("owner"),
                f"/admin/service-delivery/{s['_id']}", True)
    items.sort(key=lambda x: (x["severity"] != "red", -x["rank"]))
    return {"items": items[:limit], "total": len(items)}


def snapshot(gd, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Nightly: yesterday's value per KPI and BU into email_automation.kpi_snapshots."""
    now = now or datetime.utcnow()
    s, u, _, _ = period("today", now - timedelta(days=1))
    u = s + timedelta(days=1)
    rows = 0
    for bu in (None, "SFW", "COGENTIX", "BIM"):
        vals = {d["key"]: value(gd, d["key"], s, u, bu) for d in definitions.all_definitions() if d["compute"]}
        gd("email_automation")["kpi_snapshots"].update_one({"day": s, "bu": bu or "ALL"},
                                                           {"$set": {"values": vals, "taken_at": now}}, upsert=True)
        rows += 1
    return {"day": s, "rows": rows}
