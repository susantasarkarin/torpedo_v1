"""Weekly marketing report (MARKETING_PLAN 6.4), Monday 09:00 IST.

Built from the same KPI functions as dashboard 13 and stored in
email_automation.marketing_reports (week key, JSON + rendered HTML). Mail delivery
needs config marketing.report_recipients and a sending mailbox (owner); until then
the report is read on Marketing > Weekly report.
"""
import html
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from marketing import kpis as K, schema


def _week(now: datetime):
    ist = now + timedelta(hours=5, minutes=30)
    monday = (ist - timedelta(days=ist.weekday())).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=5, minutes=30)
    return monday - timedelta(days=7), monday, monday - timedelta(days=14)


def build(gd: Optional[Callable] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    s, u, ps = _week(now)
    ea = gd(schema.DB)
    lines = []
    for bu in ("SFW", "COGENTIX", "BIM"):
        row = {"bu": bu}
        for key, fn in (("leads", K.mkt_leads), ("rfqs", K.mkt_rfqs), ("won_inr", K.mkt_won_inr), ("spend_inr", K.mkt_spend_inr),
                        ("roas", K.mkt_roas)):
            cur, prev = fn(gd, s, u, bu), fn(gd, ps, s, bu)
            row[key] = cur
            row[f"{key}_prev"] = prev
        lines.append(row)
    weekly = ea["decisions"].find_one({"decision_type": "D14", "created_at": {"$gte": s}}, sort=[("created_at", -1)])
    if weekly:
        top = [{**a, "review_item": weekly.get("review_item")} for a in (weekly.get("final_parameters") or {}).get("actions", [])]
    else:
        top = [{"type": d["decision_type"], "entity": d.get("entity_label"), "action": d.get("final_action") or d.get("action"),
                "impact_inr": d.get("impact_inr") or 0, "review_item": d.get("review_item")}
               for d in ea["decisions"].find({"status": "in_review"}).sort("impact_inr", -1).limit(5)]
    last = list(ea["decisions"].find({"created_at": {"$gte": s, "$lt": u}}))
    by_status: Dict[str, int] = {}
    for d in last:
        by_status[d["status"]] = by_status.get(d["status"], 0) + 1
    outcomes = list(ea["decision_outcomes"].find({"measured_at": {"$gte": s, "$lt": u}}))
    new_issues = list(ea["seo_issues"].find({"first_seen": {"$gte": s}, "status": "open"}).limit(50))
    fixed = ea["seo_issues"].count_documents({"fixed_at": {"$gte": s, "$lt": u}})
    movers = []
    att: List[tuple] = []
    K.attention(gd, now, lambda *a: att.append(a))
    movers = [a[1] for a in att if a[1].startswith("Organic clicks down")][:5]
    scheduled = [{"bu": c.get("bu"), "channel": c["channel"], "title": c.get("title"), "at": c.get("scheduled_for")}
                 for c in ea["content_items"].find({"status": "scheduled", "scheduled_for": {"$gte": u, "$lt": u + timedelta(days=7)}})]
    try:
        from marketing import content
        best = content.performance(gd, days=7, now=now)[:3]
    except Exception:
        best = []
    rep = {"week_start": s, "week_end": u, "built_at": now, "bu_lines": lines, "top_actions": top[:5],
           "engine": {"decisions": len(last), "by_status": by_status, "measured": len(outcomes),
                      "better_than_baseline": sum(1 for o in outcomes if o.get("better_than_baseline"))},
           "seo": {"new_issues": len(new_issues), "new_high": sum(1 for i in new_issues if i.get("severity") in ("high", "critical")),
                   "fixed": fixed, "movers_down": movers, "fix_package": None},
           "content": {"scheduled_next_week": scheduled, "best_last_week": best}}
    rep["html"] = render(rep)
    key = f"{(s + timedelta(hours=5, minutes=30)):%G-W%V}"
    ea["marketing_reports"].update_one({"week": key}, {"$set": schema.stamp({**rep, "week": key}, bu=None, source="weekly_report", now=now)},
                                       upsert=True)
    rep["week"] = key
    return rep


def _fmt(v, unit=""):
    if v is None:
        return "—"
    if isinstance(v, float) and unit == "INR":
        return f"₹{v:,.0f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"


def render(r: Dict[str, Any]) -> str:
    e = html.escape
    rows = "".join(f"<tr><td>{e(l['bu'])}</td>" + "".join(
        f"<td>{_fmt(l[k], 'INR' if k.endswith('_inr') else '')} <small>(prev {_fmt(l[k + '_prev'], 'INR' if k.endswith('_inr') else '')})</small></td>"
        for k in ("leads", "rfqs", "won_inr", "spend_inr", "roas")) + "</tr>" for l in r["bu_lines"])
    acts = "".join(f"<li>{e(str(a.get('type')))} · {e(str(a.get('entity')))}: <b>{e(str(a.get('action')))}</b> "
                   f"(≈ ₹{float(a.get('impact_inr') or 0):,.0f})</li>" for a in r["top_actions"]) or "<li>No open recommendations.</li>"
    eng = r["engine"]
    seo = r["seo"]
    movers = "".join(f"<li>{e(m)}</li>" for m in seo["movers_down"]) or "<li>none</li>"
    sched = "".join(f"<li>{e(str(c['bu']))} {e(c['channel'])}: {e(str(c.get('title') or ''))}</li>" for c in r["content"]["scheduled_next_week"]) or "<li>nothing scheduled</li>"
    return (f"<h2>Marketing week {r['week_start'] + timedelta(hours=5, minutes=30):%d %b} – {r['week_end'] + timedelta(hours=5, minutes=30) - timedelta(days=1):%d %b %Y}</h2>"
            f"<h3>1. By company</h3><table border='1' cellpadding='4' cellspacing='0'><tr><th>BU</th><th>Leads</th><th>RFQs</th><th>Won</th>"
            f"<th>Spend</th><th>ROAS</th></tr>{rows}</table>"
            f"<h3>2. Top actions this week</h3><ol>{acts}</ol><p>Approve or reject them in the Review Queue (Marketing decisions).</p>"
            f"<h3>3. Decision Engine last week</h3><p>{eng['decisions']} decisions ({', '.join(f'{k} {v}' for k, v in eng['by_status'].items()) or 'none'}); "
            f"{eng['measured']} measured, {eng['better_than_baseline']} better than baseline.</p>"
            f"<h3>4. SEO</h3><p>{seo['new_issues']} new issues ({seo['new_high']} high), {seo['fixed']} fixed.</p><ul>{movers}</ul>"
            f"<h3>5. Content</h3><ul>{sched}</ul>")
