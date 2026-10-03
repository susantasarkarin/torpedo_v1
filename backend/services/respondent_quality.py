"""
SFW respondent quality score (0-100) for project (adhoc) traffic.

Scored at entry (/api/store, before the respondent is sent to the client) and
again at completion (/surveycomplete: speeder check). Client reconciliation
rejects drop a record to 0 and count against that respondent's future entries.

Switches (backend/.env):
  SFW_SCORE_ENABLED   score and store (default off: needs migration 007 indexes)
  SFW_SCORE_ENFORCE   actually turn away "block" band entries (default off =
                      flag-only; review the flags before enforcing)
  SFW_BLOCK_BELOW     score below this = "block" band   (default 40)
  SFW_REVIEW_BELOW    score below this = "review" band  (default 70)
  IPQS_API_KEY        IPQualityScore key for VPN/proxy/datacenter checks; unset = skipped
  IPQS_MONTHLY_LIMIT  lookup budget per calendar month (default 5000, the free tier)

Identity keys, strongest first. The device fingerprint alone is NOT one:
it is UA + screen + locale only, and thousands of phones of one model share it.
  sfwVisitorId           our own first-party cookie set on the landing page
  adTracking.fbp         Meta's _fbp cookie (ad traffic)
  respondentId+vendorId  the id the vendor passed in
"""
import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

VISITOR_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
DONE_BAD = {"TERMINATED", "OVERQUOTA"}

# Penalties (subtracted from 100). Kept in one table so thresholds can be tuned from data.
PENALTIES = {
    "already_completed": 60,      # same person already completed this project
    "reentry": 35,                # same person entered this project before
    "reentry_after_terminate": 20,  # ...and was terminated / over quota (on top of reentry)
    "answer_change": 30,          # DOB/gender differs from their earlier entry
    "device_ip_repeat": 10,       # same device+IP in this project (weak: shared phones/NAT)
    "bot_webdriver": 60,
    "bot_headless": 60,
    "bot_no_languages": 15,
    "ip_velocity_high": 25,       # >20 entries from this IP in the last hour
    "ip_velocity": 10,            # >5 entries from this IP in the last hour
    "visitor_velocity": 15,       # >3 entries by this visitor in the last hour
    "geo_mismatch": 30,           # IP country != project country
    "vpn_proxy": 40,
    "tor": 60,
    "datacenter_ip": 40,
    "ip_high_fraud": 20,          # IPQS fraud_score >= 85
    "ip_recent_abuse": 15,
    "prior_client_reject": 50,    # a client rejected this person before
    "terminate_history": 10,      # >=5 terminates in 30 days
    "speeder": 40,                # completed in < 1/3 of the project LOI
}


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    return _truthy(os.getenv("SFW_SCORE_ENABLED"))


def is_enforced() -> bool:
    return is_enabled() and _truthy(os.getenv("SFW_SCORE_ENFORCE"))


def _threshold(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def band_for(score: int) -> str:
    if score < _threshold("SFW_BLOCK_BELOW", 40):
        return "block"
    if score < _threshold("SFW_REVIEW_BELOW", 70):
        return "review"
    return "good"


def score_from_flags(flags: List[str]) -> int:
    if "client_reject" in flags:
        return 0
    return max(0, 100 - sum(PENALTIES.get(f, 0) for f in set(flags)))


def clean_visitor_id(value: Any) -> str:
    value = str(value or "").strip()
    return value if VISITOR_ID_PATTERN.match(value) else ""


def entry_quality_fields(body: Dict[str, Any]) -> Dict[str, Any]:
    """Fields /api/store stores on every new record (cheap; no DB reads)."""
    signals = body.get("botSignals") if isinstance(body.get("botSignals"), dict) else {}
    fields: Dict[str, Any] = {}
    visitor_id = clean_visitor_id(body.get("sfwVisitorId"))
    if visitor_id:
        fields["sfwVisitorId"] = visitor_id
    if signals:
        fields["sfwSignals"] = {
            "webdriver": bool(signals.get("webdriver")),
            "headlessUA": bool(signals.get("headlessUA")),
            "languages": int(signals.get("languages") or 0) if str(signals.get("languages", "")).isdigit() else 0,
        }
    return fields


def _strong_key_clauses(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    clauses = []
    if record.get("sfwVisitorId"):
        clauses.append({"sfwVisitorId": record["sfwVisitorId"]})
    fbp = (record.get("adTracking") or {}).get("fbp")
    if fbp:
        clauses.append({"adTracking.fbp": fbp})
    if record.get("respondentId") and record.get("vendorId"):
        clauses.append({"respondentId": record["respondentId"], "vendorId": record["vendorId"]})
    return clauses


def _profile(record: Dict[str, Any]) -> tuple:
    p = record.get("profilingData") or {}
    return (p.get("birthday_year"), p.get("birthday_month"), p.get("birthday_day"), (p.get("gender") or "").lower())


def _norm_country(value: Any) -> str:
    value = str(value or "").strip().upper()
    return "UK" if value == "GB" else value


# ---------------------------------------------------------------------------
# IP intelligence (phase 2) — IPQualityScore, cached per IP for 7 days
# ---------------------------------------------------------------------------

async def _ip_intel(db, ip: str) -> Optional[Dict[str, Any]]:
    key = (os.getenv("IPQS_API_KEY") or "").strip()
    if not key or not ip:
        return None
    cache = db["ip_intel"]
    cached = await cache.find_one({"_id": ip})
    if cached and cached.get("checkedAt") and cached["checkedAt"] > datetime.utcnow() - timedelta(days=7):
        return cached.get("result")

    month = datetime.utcnow().strftime("%Y-%m")
    limit = _threshold("IPQS_MONTHLY_LIMIT", 5000)
    usage = await db["ip_intel_usage"].find_one_and_update(
        {"_id": month}, {"$inc": {"lookups": 1}}, upsert=True, return_document=True,
    )
    if usage and usage.get("lookups", 0) > limit:
        return None  # budget spent: skip, never block on it

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(
                f"https://ipqualityscore.com/api/json/ip/{key}/{ip}",
                params={"strictness": 1, "allow_public_access_points": "true"},
            )
        data = resp.json()
    except Exception as e:
        print(f"[warn] IPQS lookup failed for {ip}: {e}")
        return None
    if not data.get("success"):
        print(f"[warn] IPQS error for {ip}: {data.get('message')}")
        return None

    result = {
        "proxy": bool(data.get("proxy")), "vpn": bool(data.get("vpn") or data.get("active_vpn")),
        "tor": bool(data.get("tor") or data.get("active_tor")),
        "connection_type": data.get("connection_type"), "fraud_score": data.get("fraud_score"),
        "recent_abuse": bool(data.get("recent_abuse")), "country_code": data.get("country_code"),
        "region": data.get("region"), "isp": data.get("ISP"),
    }
    await cache.update_one({"_id": ip}, {"$set": {"result": result, "checkedAt": datetime.utcnow()}}, upsert=True)
    return result


def _ip_intel_flags(intel: Optional[Dict[str, Any]]) -> List[str]:
    if not intel:
        return []
    flags = []
    if intel.get("tor"):
        flags.append("tor")
    elif intel.get("vpn") or intel.get("proxy"):
        flags.append("vpn_proxy")
    if str(intel.get("connection_type") or "").lower() == "data center":
        flags.append("datacenter_ip")
    if (intel.get("fraud_score") or 0) >= 85:
        flags.append("ip_high_fraud")
    if intel.get("recent_abuse"):
        flags.append("ip_recent_abuse")
    return flags


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

async def score_entry(collection, record_id, project_doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Score a project-flow entry and store sfwScore/sfwBand/sfwFlags on it."""
    record = await collection.find_one({"_id": record_id})
    if not record:
        return None
    survey_no = record.get("assignedSurveyId")
    flags: List[str] = []
    now = datetime.utcnow()
    strong = _strong_key_clauses(record)

    # 1. Same person, same project, earlier entries
    if strong and survey_no:
        prior = await collection.find(
            {"surveySource": "PROJECT", "assignedSurveyId": survey_no, "_id": {"$ne": record_id}, "$or": strong},
            {"status": 1, "profilingData": 1},
        ).limit(20).to_list(length=20)
        if prior:
            flags.append("reentry")
            statuses = {p.get("status") for p in prior}
            if "COMPLETE" in statuses:
                flags.append("already_completed")
            if statuses & DONE_BAD:
                flags.append("reentry_after_terminate")
            mine = _profile(record)
            if any(all(mine) and all(_profile(p)) and _profile(p) != mine for p in prior):
                flags.append("answer_change")

    # 2. Weak repeat: same device + IP in this project (only if no strong match)
    if "reentry" not in flags and record.get("deviceFingerprint") and record.get("clientIp") and survey_no:
        if await collection.find_one(
            {"surveySource": "PROJECT", "deviceFingerprint": record["deviceFingerprint"],
             "clientIp": record["clientIp"], "assignedSurveyId": survey_no, "_id": {"$ne": record_id}},
            {"_id": 1},
        ):
            flags.append("device_ip_repeat")

    # 3. Bot signals from the browser
    signals = record.get("sfwSignals") or {}
    if signals.get("webdriver"):
        flags.append("bot_webdriver")
    if signals.get("headlessUA") or "HeadlessChrome" in str(record.get("userAgent") or ""):
        flags.append("bot_headless")
    if signals and not signals.get("languages"):
        flags.append("bot_no_languages")

    # 4. Velocity (last hour)
    hour_ago = now - timedelta(hours=1)
    if record.get("clientIp"):
        ip_count = await collection.count_documents(
            {"clientIp": record["clientIp"], "createdAt": {"$gte": hour_ago}}, limit=25)
        if ip_count > 20:
            flags.append("ip_velocity_high")
        elif ip_count > 5:
            flags.append("ip_velocity")
    if record.get("sfwVisitorId"):
        if await collection.count_documents(
                {"sfwVisitorId": record["sfwVisitorId"], "createdAt": {"$gte": hour_ago}}, limit=5) > 3:
            flags.append("visitor_velocity")

    # 5. Geography: IP country vs project country
    # Country source, most trusted first: Cloudflare's CF-IPCountry (server-side),
    # IPQualityScore, then the browser-reported geoIpCountry.
    project_cc = _norm_country((project_doc or {}).get("countryCode"))
    intel = await _ip_intel(collection.database, record.get("clientIp") or "")
    ip_cc = (_norm_country(record.get("cfIpCountry"))
             or _norm_country((intel or {}).get("country_code"))
             or _norm_country(record.get("geoIpCountry")))
    if project_cc and ip_cc and project_cc != ip_cc:
        flags.append("geo_mismatch")
    flags.extend(_ip_intel_flags(intel))
    if record.get("cfIpTor") and "tor" not in flags:
        flags.append("tor")

    # 6. History across all projects
    if strong:
        if await collection.find_one({"clientRejected": True, "$or": strong}, {"_id": 1}):
            flags.append("prior_client_reject")
        terminates = await collection.count_documents(
            {"surveySource": "PROJECT", "status": {"$in": list(DONE_BAD)},
             "createdAt": {"$gte": now - timedelta(days=30)}, "$or": strong}, limit=5)
        if terminates >= 5:
            flags.append("terminate_history")

    score = score_from_flags(flags)
    result = {"sfwScore": score, "sfwBand": band_for(score), "sfwFlags": sorted(set(flags)),
              "sfwScoredAt": now, "sfwEnforced": is_enforced()}
    if intel:
        result["sfwIpIntel"] = intel
    await collection.update_one({"_id": record_id}, {"$set": result})
    return result


async def score_completion(collection, record: Dict[str, Any], project_doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Speeder check at completion: elapsed since entry < 1/3 of the project's LOI (minutes)."""
    created = record.get("createdAt")
    try:
        loi_min = float(str((project_doc or {}).get("loi") or "").strip())
    except ValueError:
        loi_min = 0
    if not isinstance(created, datetime) or loi_min <= 0:
        return None
    elapsed = (datetime.utcnow() - created).total_seconds()
    flags = list(record.get("sfwFlags") or [])
    if elapsed < loi_min * 60 / 3 and "speeder" not in flags:
        flags.append("speeder")
    score = score_from_flags(flags)
    result = {"sfwScore": score, "sfwBand": band_for(score), "sfwFlags": sorted(set(flags)),
              "sfwCompleteSeconds": int(elapsed)}
    await collection.update_one({"_id": record["_id"]}, {"$set": result})
    return result


async def apply_client_rejects(collection, survey_no: str, ids: List[str], reason: str = "") -> Dict[str, Any]:
    """Mark a project's client-rejected respondents (ids = our RID/SFWID or the vendor respondent id)."""
    from bson import ObjectId

    ids = [str(i).strip() for i in ids if str(i).strip()][:5000]
    object_ids = [ObjectId(i) for i in ids if re.match(r"^[0-9a-fA-F]{24}$", i)]
    query = {"assignedSurveyId": str(survey_no),
             "$or": [{"_id": {"$in": object_ids}}, {"respondentId": {"$in": ids}}]}
    now = datetime.utcnow()
    matched = await collection.find(query, {"_id": 1, "respondentId": 1, "sfwFlags": 1}).to_list(length=len(ids) * 2 + 10)
    for doc in matched:
        flags = sorted(set((doc.get("sfwFlags") or []) + ["client_reject"]))
        await collection.update_one({"_id": doc["_id"]}, {"$set": {
            "clientRejected": True, "clientRejectedAt": now, "clientRejectReason": reason[:200],
            "sfwFlags": flags, "sfwScore": 0, "sfwBand": "block",
        }})
    found = {str(d["_id"]) for d in matched} | {str(d.get("respondentId")) for d in matched}
    return {"matched": len(matched), "unmatched": [i for i in ids if i not in found][:200]}
