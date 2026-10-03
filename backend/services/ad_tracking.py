"""
Ad-platform attribution and the respondent thank-you page.

Flow: Ad (Meta now; Google/TikTok later) -> landing page (/api/store creates the
traffic record, whose ObjectId is the RID) -> client survey -> /surveycomplete.

Entry side:  extract_ad_tracking() turns the landing URL params + Meta cookies
             into `adTracking` + `traffic_source` on the traffic record.
Exit side:   the React thank-you page (/adpixel) asks GET /api/adpixel, which
             calls claim_pixel_fire(): every check runs server-side and the
             fire is stamped atomically, at most once per respondent.

Adding a platform later = enable it in AD_PLATFORMS (env vars) + add its
loader to Campaign_platform/src/utils/adPixels.js. Nothing else changes.
"""
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional

RID_PATTERN = re.compile(r"^[0-9a-fA-F]{24}$")  # traffic record ObjectId (SFWID)
# What /adpixel accepts: the SFWID above, the rid from the ad URL, or Meta's fbclid.
PIXEL_RID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{6,255}$")

# Platform config. `enabled_env` overrides `enabled_default`; a platform only
# renders when it is enabled and has a valid ID (and a loader in adPixels.js).
AD_PLATFORMS: Dict[str, Dict[str, Any]] = {
    "meta": {
        "enabled_env": "META_PIXEL_ENABLED",
        "enabled_default": True,
        "id_env": "META_PIXEL_ID",
        "id_pattern": r"^\d{5,20}$",
    },
    "google_ads": {
        "enabled_env": "GOOGLE_ADS_ENABLED",
        "enabled_default": False,
        "id_env": "GOOGLE_ADS_TAG_ID",
        "id_pattern": r"^AW-\d{5,20}$",
    },
    "tiktok": {
        "enabled_env": "TIKTOK_PIXEL_ENABLED",
        "enabled_default": False,
        "id_env": "TIKTOK_PIXEL_ID",
        "id_pattern": r"^[A-Z0-9]{10,30}$",
    },
}

# utm_source values (lower-cased) -> canonical traffic_source
_UTM_SOURCE_ALIASES = {
    "facebook": "meta", "fb": "meta", "meta": "meta", "instagram": "meta", "ig": "meta",
    "messenger": "meta", "audience_network": "meta", "an": "meta",
    "google": "google_ads", "google_ads": "google_ads", "googleads": "google_ads", "adwords": "google_ads",
    "tiktok": "tiktok", "tiktok_ads": "tiktok",
}
# Click IDs identify the platform even when UTMs are missing.
_CLICK_ID_SOURCES = (("fbclid", "meta"), ("gclid", "google_ads"), ("ttclid", "tiktok"))

_AD_PARAM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "campaign_id", "adset_id", "ad_id", "placement")
_MAX_PARAM_LEN = 200


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_platform_config(platform: str) -> Optional[Dict[str, Any]]:
    """Resolved config for an enabled platform with a valid ID, else None. Read per call so env changes apply."""
    spec = AD_PLATFORMS.get(platform)
    if not spec:
        return None
    raw_enabled = os.getenv(spec["enabled_env"])
    enabled = _truthy(raw_enabled) if raw_enabled is not None else spec["enabled_default"]
    pixel_id = (os.getenv(spec["id_env"]) or "").strip()
    if not enabled or not pixel_id or not re.match(spec["id_pattern"], pixel_id):
        return None
    return {"platform": platform, "pixel_id": pixel_id}


def is_ad_platform(traffic_source: Any) -> bool:
    return isinstance(traffic_source, str) and traffic_source in AD_PLATFORMS


def derive_traffic_source(params: Dict[str, Any]) -> str:
    """Canonical traffic source: ad platform key, the raw utm_source, or 'direct'."""
    utm_source = str(params.get("utm_source") or "").strip().lower()
    if utm_source in _UTM_SOURCE_ALIASES:
        return _UTM_SOURCE_ALIASES[utm_source]
    for click_key, platform in _CLICK_ID_SOURCES:
        if params.get(click_key):
            return platform
    return utm_source[:50] if utm_source else "direct"


def _clean(value: Any) -> str:
    return str(value or "").strip()[:_MAX_PARAM_LEN]


def extract_ad_tracking(
    params: Dict[str, Any],
    body: Dict[str, Any],
    cookies: Dict[str, str],
) -> Dict[str, Any]:
    """
    Fields to store on the traffic record at entry. IP and user agent are not
    repeated here: the record already holds them as clientIp / userAgent.
    """
    params = params or {}
    traffic_source = derive_traffic_source(params)
    if not is_ad_platform(traffic_source):
        return {"traffic_source": traffic_source}

    tracking = {key: _clean(params.get(key)) for key in _AD_PARAM_KEYS if params.get(key)}
    for click_key, _ in _CLICK_ID_SOURCES:
        if params.get(click_key):
            tracking[click_key] = _clean(params.get(click_key))

    if traffic_source == "meta":
        # Body first (frontend reads document.cookie), then cookies sent with the request.
        fbp = _clean(body.get("fbp") or cookies.get("_fbp"))
        fbc = _clean(body.get("fbc") or cookies.get("_fbc"))
        if not fbc and tracking.get("fbclid"):
            # Meta's documented _fbc format when the cookie isn't set yet.
            fbc = f"fb.1.{int(time.time() * 1000)}.{tracking['fbclid']}"
        if fbp:
            tracking["fbp"] = fbp
        if fbc:
            tracking["fbc"] = fbc

    return {"traffic_source": traffic_source, "adTracking": tracking}


_PIXEL_PROJECTION = {"traffic_source": 1, "assignedSurveyId": 1, "ad_pixel_fired_at": 1,
                     "status": 1, "respondentId": 1}


async def _find_ad_record(collection, rid: str) -> Optional[Dict[str, Any]]:
    """
    Resolve the identifier on /adpixel to exactly one traffic record:
    SFWID (_id) first, then the rid that arrived on the ad URL (respondentId),
    then Meta's fbclid. Ambiguous matches resolve to nothing.
    """
    from bson import ObjectId

    if RID_PATTERN.match(rid):
        record = await collection.find_one({"_id": ObjectId(rid)}, _PIXEL_PROJECTION)
        if record:
            return record

    ad_sources = {"$in": list(AD_PLATFORMS)}
    for field in ("respondentId", "adTracking.fbclid"):
        cursor = collection.find({field: rid, "traffic_source": ad_sources}, _PIXEL_PROJECTION).limit(2)
        matches = await cursor.to_list(length=2)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"[warn] Ad pixel: {field}={rid} matches several records, not firing")
            return None
    return None


def _firing_statuses() -> set:
    """
    Record statuses that may fire the pixel. COMPLETE only, unless
    AD_PIXEL_FIRE_ON_TERMINATE is on — a TEMPORARY setup-testing switch
    (2026-10-03): terminates also fire, so the pixel can be checked end to end
    without a real complete. Turn it off once Meta shows SurveyComplete.
    """
    statuses = {"COMPLETE"}
    if _truthy(os.getenv("AD_PIXEL_FIRE_ON_TERMINATE", "false")):
        statuses.add("TERMINATED")
    return statuses


async def claim_pixel_fire(collection, rid: str) -> Optional[Dict[str, Any]]:
    """
    Run every server-side check and, if they pass, atomically stamp
    ad_pixel_fired_at. Returns {platform, pixel_id, survey_id, event_id} or None.
    Callers must not reveal which check failed.
    """
    if not isinstance(rid, str) or not PIXEL_RID_PATTERN.match(rid):
        return None

    record = await _find_ad_record(collection, rid)
    # Only a completion recorded by /surveycomplete counts — /adpixel is public,
    # so a RID seen mid-survey must not be able to fire a conversion.
    statuses = _firing_statuses()
    if not record or record.get("ad_pixel_fired_at") or record.get("status") not in statuses:
        return None

    platform = record.get("traffic_source")
    config = get_platform_config(platform) if is_ad_platform(platform) else None
    survey_id = _clean(record.get("assignedSurveyId"))
    if not config or not survey_id:
        return None

    # Atomic claim: concurrent refreshes race here and only one wins.
    now = datetime.utcnow()
    claimed = await collection.find_one_and_update(
        {"_id": record["_id"], "ad_pixel_fired_at": {"$exists": False},
         "traffic_source": platform, "status": {"$in": sorted(statuses)}},
        {"$set": {"ad_pixel_fired_at": now, "ad_pixel_platform": platform}},
    )
    if not claimed:
        return None

    # One event ID per respondent whichever identifier reached the page, so the
    # future Conversions API call can dedupe against it.
    canonical_rid = _clean(record.get("respondentId")) or str(record["_id"])
    event_id = f"complete_{canonical_rid}"
    try:
        await collection.database["ad_pixel_fires"].insert_one({
            "rid": rid,
            "record_id": str(record["_id"]),
            "platform": platform,
            "survey_id": survey_id,
            "event_id": event_id,
            "firedAt": now,
        })
    except Exception as e:  # audit log must never block the respondent's page
        print(f"[warn] ad pixel audit log failed for rid={rid}: {e}")
    print(f"[ok] Ad pixel fire: rid={rid} platform={platform} at={now.isoformat()}Z")

    send_server_side_conversion(claimed, platform, event_id, survey_id)
    return {**config, "survey_id": survey_id, "event_id": event_id}


def send_server_side_conversion(record: Dict[str, Any], platform: str, event_id: str, survey_id: str) -> None:
    """
    TODO(meta-capi): send the same SurveyComplete event via Meta Conversions API.
      - POST https://graph.facebook.com/<ver>/<META_PIXEL_ID>/events with META_CAPI_ACCESS_TOKEN
      - event_name='SurveyComplete', event_id=event_id  (same as the browser
        pixel's eventID, so Meta deduplicates the pair)
      - user_data: fbp/fbc from record['adTracking'], client_ip_address from
        record['clientIp'], client_user_agent from record['userAgent']
      - custom_data: {'survey_id': survey_id} only — no PII, no survey answers
      - run it off the request path (background task / Celery), never inline
    """
    return None
