"""
Survey allocation: which eligible survey a routed respondent is offered first (2026-10-19).

Before this, the router took the first eligible project by routingPriority / age.
On the first day with routing on (19 Oct), 9 of 18 routed people were sent to
surveys the client had already closed (quota full) and none completed.

Each eligible project now gets an expected value for this respondent:

    value = CPI x P(complete for this person)

  P(complete)  last 48 h of client outcomes for the project, smoothed towards a
               prior (a quarter of the client's stated IR -- 46973 claims 80% and
               converts 7% -- or 10%), then narrowed to the
               respondent's segment (gender + age band) -- a project that keeps
               terminating men 18-24 stops getting them, without anyone writing
               that rule down. Entries still open after 60 min count as drop-outs.
  quota closed skipped altogether: recent returns (last 45 min) are quota-full with
               no complete, or 10+ returns in 48 h are 80%+ quota-full with no
               complete (21390 on 19 Oct: 18 returns, 18 quota-full).

routingPriority still wins where set (lower = first); value orders within it.
Projects with no CPI get the median CPI of the other candidates.
The decision is stored on the traffic record as "allocation".

Switch (backend/.env):
  SURVEY_ALLOCATION   "score" (default) or "priority" (previous behaviour)
"""
import os
import time
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

STATS_HOURS = 48
RECENT_MINUTES = 45
STALE_MINUTES = 60
PROJECT_WEIGHT = 20   # pseudo-entries behind the prior
SEGMENT_WEIGHT = 8    # pseudo-entries behind the project rate
CLOSED_MIN_OVERQUOTA = 3
CLOSED_MIN_RETURNS_48H = 10
CLOSED_OQ_SHARE_48H = 0.8
CACHE_SECONDS = 120

REACHED_CLIENT = ("COMPLETE", "TERMINATED", "OVERQUOTA", "SECURITY_TERM", "INCOMPLETE")

_CACHE: Dict[Tuple[str, ...], Tuple[float, Dict[str, Any]]] = {}


def mode() -> str:
    return "priority" if os.getenv("SURVEY_ALLOCATION", "score").strip().lower() == "priority" else "score"


def _num(value: Any) -> Optional[float]:
    try:
        n = float(str(value).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def age_band(age: Optional[int]) -> str:
    if age is None:
        return "?"
    for top, label in ((24, "18-24"), (34, "25-34"), (44, "35-44"), (54, "45-54")):
        if age <= top:
            return label
    return "55+"


def segment_of(profile: Dict[str, Any], today: Optional[date] = None) -> str:
    profile = profile or {}
    gender = str(profile.get("gender") or "").lower()[:1] or "?"
    try:
        age = (today or date.today()).year - int(profile.get("birthday_year"))
    except (TypeError, ValueError):
        age = None
    return f"{gender}|{age_band(age)}"


def _empty() -> Dict[str, Any]:
    return {"completes": 0, "decided": 0, "overquota": 0, "recent_oq": 0, "recent_completes": 0, "segments": {}}


async def project_stats(url_col, survey_nos: List[str], now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Per survey: completes / decided outcomes (48 h), recent quota-fulls, per-segment counts."""
    key = tuple(sorted(survey_nos))
    cached = _CACHE.get(key)
    if cached and cached[0] > time.time():
        return cached[1]
    now = now or datetime.utcnow()
    since, recent, stale = (now - timedelta(hours=STATS_HOURS), now - timedelta(minutes=RECENT_MINUTES),
                            now - timedelta(minutes=STALE_MINUTES))
    pipeline = [
        {"$match": {"params.pid": {"$in": list(key)}, "params.api": "false",
                    "createdAt": {"$gte": since}, "status": {"$in": list(REACHED_CLIENT)}}},
        {"$group": {"_id": {
            "pid": "$params.pid", "status": "$status",
            "g": {"$toLower": {"$substrCP": [{"$ifNull": [{"$toString": "$profilingData.gender"}, ""]}, 0, 1]}},
            "y": "$profilingData.birthday_year",
            "recent": {"$gte": ["$createdAt", recent]},
            "stale": {"$lt": ["$createdAt", stale]},
        }, "n": {"$sum": 1}}},
    ]
    out = {no: _empty() for no in key}
    today = now.date()
    async for row in url_col.aggregate(pipeline):
        k, n = row["_id"], row["n"]
        s = out.get(str(k.get("pid")))
        if s is None:
            continue
        status = k.get("status")
        if status == "INCOMPLETE" and not k.get("stale"):
            continue  # still in the survey
        if k.get("recent") and status == "OVERQUOTA":
            s["recent_oq"] += n
        if k.get("recent") and status == "COMPLETE":
            s["recent_completes"] += n
        seg = segment_of({"gender": k.get("g"), "birthday_year": k.get("y")}, today)
        seg_stats = s["segments"].setdefault(seg, [0, 0])
        s["decided"] += n
        seg_stats[1] += n
        if status == "OVERQUOTA":
            s["overquota"] += n
        if status == "COMPLETE":
            s["completes"] += n
            seg_stats[0] += n
    _CACHE[key] = (time.time() + CACHE_SECONDS, out)
    return out


def quota_closed(stats: Dict[str, Any]) -> bool:
    if stats["recent_oq"] >= CLOSED_MIN_OVERQUOTA and stats["recent_completes"] == 0:
        return True
    return (stats["completes"] == 0 and stats["decided"] >= CLOSED_MIN_RETURNS_48H
            and stats["overquota"] >= CLOSED_OQ_SHARE_48H * stats["decided"])


def prior_rate(project: Dict[str, Any]) -> float:
    ir = _num(project.get("clientIR"))
    return min(0.5, max(0.02, ir / 100.0 * 0.25)) if ir else 0.10


def score(project: Dict[str, Any], stats: Dict[str, Any], segment: str, cpi: float) -> Dict[str, Any]:
    prior = prior_rate(project)
    p_project = (stats["completes"] + PROJECT_WEIGHT * prior) / (stats["decided"] + PROJECT_WEIGHT)
    seg_c, seg_n = stats["segments"].get(segment, [0, 0])
    p_segment = (seg_c + SEGMENT_WEIGHT * p_project) / (seg_n + SEGMENT_WEIGHT)
    return {"surveyNo": str(project.get("surveyNo")), "cpi": round(cpi, 2), "pProject": round(p_project, 4),
            "pSegment": round(p_segment, 4), "value": round(cpi * p_segment, 4), "segment": segment,
            "completes48h": stats["completes"], "decided48h": stats["decided"], "segmentN": seg_n}


def _priority(project: Dict[str, Any]) -> int:
    try:
        return int(str(project.get("routingPriority")).strip())
    except (TypeError, ValueError):
        return 1000


async def rank(url_col, projects: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Eligible projects best-first; quota-closed ones dropped. Each gets project["_alloc"]."""
    if len(projects) == 0 or mode() == "priority":
        return projects
    try:
        stats = await project_stats(url_col, [str(p.get("surveyNo")) for p in projects])
    except Exception as err:  # never block a respondent over the scoring
        print(f"[warn] allocation stats failed, using priority order: {err}")
        return projects
    cpis = [c for c in (_num(p.get("cpi")) for p in projects) if c]
    fallback_cpi = median(cpis) if cpis else 1.0
    segment = segment_of(profile)
    ranked = []
    for p in projects:
        s = stats.get(str(p.get("surveyNo"))) or _empty()
        if quota_closed(s):
            print(f"[info] allocation: skipping {p.get('surveyNo')} -- quota closed at client "
                  f"({s['recent_oq']} quota-full in {RECENT_MINUTES} min, {s['overquota']}/{s['decided']} in 48 h, no completes)")
            continue
        p["_alloc"] = score(p, s, segment, _num(p.get("cpi")) or fallback_cpi)
        ranked.append(p)
    ranked.sort(key=lambda p: (_priority(p), -p["_alloc"]["value"]))
    for i, p in enumerate(ranked):
        p["_alloc"]["rank"] = i + 1
        p["_alloc"]["of"] = len(ranked)
    return ranked
