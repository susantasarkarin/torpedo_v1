"""
Ops: Operations dashboard (owner 2026-11-18 revamp).

One read-only endpoint answering "how is traffic doing and what needs attention":
  GET /api/ops/dashboard?days=7&source=all

  kpis       entrants, completes, conversion, termination %, quality-term %,
             quota-full %, live projects -- each with the previous equal period
  baseline   average entrants per period over the 8 weeks before the window,
             so a traffic collapse is flagged instead of shown as a small number
  daily      per IST day: entrants, completes, conversion
  statuses   the status split
  vendors    per vendor: entrants, completes, conversion, termination %, quality %
  countries  per country: entrants, completes, conversion
  links      per supplier link (pid) mapped to its project/survey
  attention  plain-language alerts built from the above
  projects   live projects with target and progress (same metrics as Projects)

Traffic comes from traffic_flow_db.url_parameters (createdAt index). Status
classes mirror app/services/traffic_service.py.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from routers.ops_surveys import (
    COL_OPS_PROJECTS, COL_OPS_SURVEYS, COL_SUPPLIERS, COL_VENDORS,
    _col, _project_rows, _traffic_col,
)
from session_state import verify_session

router = APIRouter(prefix="/api/ops", tags=["Ops Dashboard"])

IST = ZoneInfo("Asia/Kolkata")
SOURCES = ("all", "project", "cpx", "cint")
MAX_MS = 30000

# raw status (upper-cased) -> class
_COMPLETE = ["COMPLETE"]
_QUOTA = ["OVERQUOTA", "QUOTAFULL", "QUOTA_FULL"]
_QUALITY = ["QUALITY_TERM", "QUALITY_TERMINATE", "SECURITY_TERM", "SFW_BLOCKED"]
_TERMINATE = ["TERMINATED", "TERMINATE", "SCREENOUT", "OUT"]
_NOT_ROUTED = ["NOT_ROUTED"]
CLASSES = ("complete", "terminate", "quality", "quota", "notRouted", "incomplete")

# alert thresholds
DROP_RATIO = 0.5          # entrants below half of the 8-week average
ZERO_COMPLETE_MIN = 10    # link with this many entrants and no completes
HIGH_TERM_MIN = 30        # vendor with this many entrants ...
HIGH_TERM_RATE = 85.0     # ... and termination at or above this %


def _class_expr() -> Dict[str, Any]:
    s = {"$toUpper": {"$ifNull": ["$status", ""]}}
    return {"$switch": {"branches": [
        {"case": {"$in": [s, _COMPLETE]}, "then": "complete"},
        {"case": {"$in": [s, _QUOTA]}, "then": "quota"},
        {"case": {"$in": [s, _QUALITY]}, "then": "quality"},
        {"case": {"$in": [s, _TERMINATE]}, "then": "terminate"},
        {"case": {"$in": [s, _NOT_ROUTED]}, "then": "notRouted"},
    ], "default": "incomplete"}}


def _source_match(source: str) -> Dict[str, Any]:
    if source == "project":
        return {"params.api": "false"}
    if source == "cpx":
        return {"surveySource": "CPX"}
    if source == "cint":
        return {"surveySource": {"$regex": "^CINT"}}
    return {}


def _window(days: int, now: Optional[datetime] = None):
    """[start, end) in naive UTC: from IST midnight (days-1) days ago until now."""
    now = now or datetime.utcnow()
    ist_now = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    start_ist = (ist_now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start, now


def _rates(c: Dict[str, int]) -> Dict[str, Any]:
    n = sum(c.get(k, 0) for k in CLASSES)
    pct = (lambda x: round(100.0 * x / n, 1)) if n else (lambda x: None)
    return {
        "entrants": n,
        "completes": c.get("complete", 0),
        "conversion": pct(c.get("complete", 0)),
        "terminationRate": pct(c.get("terminate", 0)),
        "qualityRate": pct(c.get("quality", 0)),
        "quotaRate": pct(c.get("quota", 0)),
    }


def _grouped(match: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One pass: counts per (IST day, vendor, country, pid, status class)."""
    pipeline = [
        {"$match": match},
        {"$project": {
            "day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt", "timezone": "Asia/Kolkata"}},
            "vendor": {"$ifNull": ["$vendorId", ""]},
            "country": {"$toUpper": {"$ifNull": ["$countryCode", ""]}},
            "pid": {"$ifNull": ["$params.pid", ""]},
            "cls": _class_expr(),
        }},
        {"$group": {"_id": {"day": "$day", "vendor": "$vendor", "country": "$country",
                            "pid": "$pid", "cls": "$cls"}, "n": {"$sum": 1}}},
    ]
    return list(_traffic_col().aggregate(pipeline, maxTimeMS=MAX_MS, allowDiskUse=True))


def _period_counts(match: Dict[str, Any]) -> Dict[str, int]:
    pipeline = [{"$match": match}, {"$group": {"_id": _class_expr(), "n": {"$sum": 1}}}]
    return {r["_id"]: r["n"] for r in _traffic_col().aggregate(pipeline, maxTimeMS=MAX_MS)}


def _vendor_names(vids) -> Dict[str, str]:
    vids = [v for v in vids if v]
    if not vids:
        return {}
    variants = vids + [int(v) for v in vids if str(v).isdigit()]
    out = {}
    for v in _col(COL_VENDORS).find({"vid": {"$in": variants}}, {"vid": 1, "vendorName": 1}):
        out[str(v.get("vid"))] = v.get("vendorName") or str(v.get("vid"))
    return out


def _link_owners(pids) -> Dict[str, Dict[str, Any]]:
    """pid (supplier link number) -> {projectName, projectNumber, surveyName, ids, vendorName}."""
    pids = [p for p in pids if p]
    if not pids:
        return {}
    sups = list(_col(COL_SUPPLIERS).find({"surveyNo": {"$in": pids}, "removed": {"$ne": True}}))
    from bson import ObjectId
    sids = {s.get("surveyId") for s in sups if s.get("surveyId")}
    surveys = {str(d["_id"]): d for d in _col(COL_OPS_SURVEYS).find(
        {"_id": {"$in": [ObjectId(x) for x in sids if ObjectId.is_valid(x)]}})}
    pidset = {d.get("projectId") for d in surveys.values() if d.get("projectId")}
    projects = {str(d["_id"]): d for d in _col(COL_OPS_PROJECTS).find(
        {"_id": {"$in": [ObjectId(x) for x in pidset if ObjectId.is_valid(str(x))]}})}
    out = {}
    for s in sups:
        sv = surveys.get(str(s.get("surveyId")))
        pj = projects.get(str(sv.get("projectId"))) if sv else None
        out[str(s.get("surveyNo"))] = {
            "projectId": str(pj["_id"]) if pj else None,
            "projectName": pj.get("projectName") if pj else None,
            "projectNumber": pj.get("projectNumber") if pj else None,
            "surveyId": str(sv["_id"]) if sv else None,
            "surveyName": sv.get("surveyName") if sv else None,
            "vendorName": s.get("vendorName"),
        }
    return out


def _fold(rows, key) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        out[r["_id"][key]][r["_id"]["cls"]] += r["n"]
    return out


def _attention(kpis, baseline, vendors, links, projects, days) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    cur = kpis["current"]["entrants"]
    if baseline and baseline > 0 and cur < baseline * DROP_RATIO:
        drop = round(100 * (1 - cur / baseline))
        items.append({"level": "critical", "kind": "traffic_drop",
                      "title": f"Traffic is {drop}% below normal",
                      "detail": f"{cur:,} entrants in the last {days} days against an 8-week average of "
                                f"{round(baseline):,} for the same length of time."})
    for l in links:
        if l["entrants"] >= ZERO_COMPLETE_MIN and l["completes"] == 0:
            where = l.get("surveyName") or l.get("projectName") or f"link {l['pid']}"
            items.append({"level": "serious", "kind": "zero_completes",
                          "title": f"No completes on {where}",
                          "detail": f"Link {l['pid']} ({l.get('vendorName') or l.get('vendorId') or 'vendor ?'}) "
                                    f"had {l['entrants']:,} entrants and 0 completes.",
                          "projectId": l.get("projectId"), "surveyId": l.get("surveyId")})
    for v in vendors:
        if v["entrants"] >= HIGH_TERM_MIN and (v["terminationRate"] or 0) >= HIGH_TERM_RATE:
            items.append({"level": "warning", "kind": "high_termination",
                          "title": f"{v['vendorName']}: {v['terminationRate']}% terminated",
                          "detail": f"{v['entrants']:,} entrants, {v['completes']:,} completes in this period."})
    for p in projects:
        if p["target"] and p["completes"] >= p["target"]:
            items.append({"level": "warning", "kind": "target_reached",
                          "title": f"{p['projectName']} reached its target",
                          "detail": f"{p['completes']:,} of {p['target']:,} completes. Consider closing it.",
                          "projectId": p["id"]})
    order = {"critical": 0, "serious": 1, "warning": 2}
    return sorted(items, key=lambda i: order.get(i["level"], 9))[:12]


@router.get("/dashboard")
def ops_dashboard(
    user: str = Depends(verify_session),
    days: int = Query(7, ge=1, le=90),
    source: str = Query("all"),
):
    if source not in SOURCES:
        raise HTTPException(status_code=422, detail=f"source must be one of {', '.join(SOURCES)}")
    start, end = _window(days)
    prev_start = start - (end - start)
    src = _source_match(source)

    rows = _grouped({"createdAt": {"$gte": start, "$lt": end}, **src})
    current = defaultdict(int)
    for r in rows:
        current[r["_id"]["cls"]] += r["n"]
    previous = _period_counts({"createdAt": {"$gte": prev_start, "$lt": start}, **src})

    # 8 weeks before the window, scaled to the window length
    base_start = start - timedelta(days=56)
    base_n = _traffic_col().count_documents({"createdAt": {"$gte": base_start, "$lt": start}, **src},
                                            maxTimeMS=MAX_MS)
    span_days = (end - start).total_seconds() / 86400
    baseline = base_n / 56 * span_days if base_n else 0

    # daily (every IST day in the window, zero-filled)
    by_day = _fold(rows, "day")
    first_day = start.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST).date()
    daily = []
    for i in range(days):
        d = (first_day + timedelta(days=i)).isoformat()
        daily.append({"date": d, **_rates(by_day.get(d, {}))})

    names = _vendor_names({r["_id"]["vendor"] for r in rows})
    vendors = sorted(
        ({"vendorId": vid, "vendorName": names.get(vid, vid or "Unknown"), **_rates(c)}
         for vid, c in _fold(rows, "vendor").items()),
        key=lambda v: (-v["completes"], -v["entrants"]))
    # junk / placeholder codes (e.g. an unsubstituted [%CC%]) fold into "Unknown"
    by_country: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cc, c in _fold(rows, "country").items():
        key = cc if len(cc) == 2 and cc.isalpha() else "Unknown"
        for k, n in c.items():
            by_country[key][k] += n
    countries = sorted(({"country": cc, **_rates(c)} for cc, c in by_country.items()),
                       key=lambda c: -c["entrants"])

    link_counts = _fold(rows, "pid")
    owners = _link_owners(list(link_counts))
    link_vendor = {}
    for r in rows:
        link_vendor.setdefault(r["_id"]["pid"], r["_id"]["vendor"])
    links = sorted(
        ({"pid": pid, "vendorId": link_vendor.get(pid), **owners.get(pid, {}),
          **({"vendorName": names.get(link_vendor.get(pid))} if not owners.get(pid) else {}), **_rates(c)}
         for pid, c in link_counts.items() if pid),
        key=lambda l: -l["entrants"])

    live = list(_col(COL_OPS_PROJECTS).find({"is_deleted": {"$ne": True}, "status": "live"}))
    projects = [{
        "id": p["id"], "projectName": p["projectName"], "projectNumber": p["projectNumber"],
        "clientName": p.get("clientName"), "surveyCount": p["surveyCount"],
        "target": p["target"], "completes": p["completes"], "ir": p["ir"], "loi": p["loi"],
        "progress": round(100.0 * p["completes"] / p["target"], 1) if p["target"] else None,
    } for p in _project_rows(live, user, end)]
    # imported surveys carry no target, so progress is often unknown: completes first
    projects.sort(key=lambda p: (-(p["completes"] or 0), -(p["progress"] or 0)))

    kpis = {"current": _rates(current), "previous": _rates(previous), "liveProjects": len(live)}
    statuses = [{"status": k, "count": current.get(k, 0)} for k in CLASSES]
    return {
        "window": {"days": days, "source": source, "start": start.isoformat(), "end": end.isoformat(),
                   "timezone": "Asia/Kolkata"},
        "kpis": kpis,
        "baseline": {"entrants": round(baseline, 1), "weeks": 8},
        "daily": daily,
        "statuses": statuses,
        "vendors": vendors[:15],
        "countries": countries[:15],
        "links": links[:20],
        "attention": _attention(kpis, baseline, vendors, links, projects, days),
        "projects": projects[:20],
        "generatedAt": datetime.utcnow().isoformat(),
    }
