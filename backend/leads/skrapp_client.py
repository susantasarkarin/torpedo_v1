"""
Skrapp.io email finder -- the one lookup service for lead email addresses
(owner, 2026-10-15: Hunter removed, Skrapp in its place).

API (https://skrapp.io/api, checked 2026-10-15):
    GET https://api.skrapp.io/api/v2/find?firstName=&lastName=&domain=   (or company=)
    header X-Access-Key: <key>
    200 -> {"email", "pattern", "quality": {"status": valid|invalid|catch-all|unknown}}
    404 -> no email found, not charged.

Skrapp verifies the address it returns, so this is a person lookup, not a
pattern guess. Only "valid" is treated as usable.

Keys: SKRAPP_API_KEY_1..3 (env) or skrapp_api_key_1..3 in
torpedo_settings.app_settings, or a single SKRAPP_API_KEY. Each key's month is
capped at SKRAPP_MONTHLY_LIMIT (default 150) lookups; usage lives in
email_automation.skrapp_usage. Every answer (found or not) is cached in
email_automation.skrapp_lookups, so a person costs at most one credit.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

FIND_URL = "https://api.skrapp.io/api/v2/find"
USABLE = {"valid"}
NOT_FOUND_RETRY_DAYS = 60


def monthly_limit() -> int:
    try:
        return max(0, int(os.getenv("SKRAPP_MONTHLY_LIMIT", "150")))
    except ValueError:
        return 150


def keys(client) -> List[str]:
    found: List[str] = []
    cfg: Dict[str, Any] = {}
    try:  # read only the key fields of the settings doc
        cfg = client["torpedo_settings"]["app_settings"].find_one(
            {"_id": "app_config"}, {f"skrapp_api_key_{i}": 1 for i in range(1, 4)}) or {}
    except Exception:
        pass
    for i in range(1, 4):
        k = (os.getenv(f"SKRAPP_API_KEY_{i}") or cfg.get(f"skrapp_api_key_{i}") or "").strip()
        if k:
            found.append(k)
    single = (os.getenv("SKRAPP_API_KEY") or "").strip()
    if single and single not in found:
        found.append(single)
    return found


def is_configured(client) -> bool:
    return bool(keys(client))


def _account(client, now: datetime) -> Optional[Dict[str, Any]]:
    """The key with the most lookups left this month, or None."""
    usage = client["email_automation"]["skrapp_usage"]
    month = now.strftime("%Y-%m")
    best = None
    for i, key in enumerate(keys(client), start=1):
        doc = usage.find_one({"account_id": str(i), "month": month}) or {}
        left = min(monthly_limit(), int(doc.get("searches_limit") or monthly_limit())) - int(doc.get("searches_used") or 0)
        if doc.get("exhausted"):
            left = 0
        if left > 0 and (best is None or left > best["left"]):
            best = {"index": i, "key": key, "left": left}
    return best


def _count(client, index: int, now: datetime, exhausted: bool = False) -> None:
    usage = client["email_automation"]["skrapp_usage"]
    month = now.strftime("%Y-%m")
    update: Dict[str, Any] = {"$setOnInsert": {"account_id": str(index), "month": month,
                                               "searches_limit": monthly_limit()}}
    if exhausted:
        update["$set"] = {"exhausted": True, "exhausted_at": now}
    else:
        update["$inc"] = {"searches_used": 1}
    usage.update_one({"account_id": str(index), "month": month}, update, upsert=True)


def _cache_key(first: str, last: str, domain: str, company: str) -> str:
    return "|".join(x.strip().lower() for x in (first, last, domain or "", company or ""))


def find(client, first: str, last: str, domain: str = "", company: str = "",
         now: Optional[datetime] = None) -> Dict[str, Any]:
    """Look one person up. Returns
        {"status": "found", "email", "pattern", "quality": valid|catch-all|...}
      | {"status": "not_found"} | {"status": <reason it could not ask>}.
    Never raises."""
    now = now or datetime.utcnow()
    if not first or not last or not (domain or company):
        return {"status": "missing_input"}
    cache = client["email_automation"]["skrapp_lookups"]
    ck = _cache_key(first, last, domain, company)
    hit = cache.find_one({"_id": ck})
    if hit and (hit.get("status") == "found" or (hit.get("at") and hit["at"] > now - timedelta(days=NOT_FOUND_RETRY_DAYS))):
        return {k: v for k, v in hit.items() if k not in ("_id", "at")}
    if not is_configured(client):
        return {"status": "not_configured"}
    acct = _account(client, now)
    if not acct:
        return {"status": "monthly_limit"}
    params = {"firstName": first, "lastName": last}
    if domain:
        params["domain"] = domain
    else:
        params["company"] = company
    try:
        r = requests.get(FIND_URL, params=params, headers={"X-Access-Key": acct["key"]}, timeout=30)
    except Exception as e:
        logger.warning("skrapp: request failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}
    if r.status_code == 404:
        out = {"status": "not_found"}
    elif r.status_code in (401, 403):
        logger.error("skrapp: key %d rejected (HTTP %d)", acct["index"], r.status_code)
        return {"status": "key_rejected"}
    elif r.status_code in (402, 429):
        _count(client, acct["index"], now, exhausted=True)
        return {"status": "monthly_limit"}
    elif r.status_code != 200:
        return {"status": f"http_{r.status_code}"}
    else:
        _count(client, acct["index"], now)
        data = r.json() or {}
        email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            out = {"status": "not_found"}
        else:
            out = {"status": "found", "email": email, "pattern": data.get("pattern") or "",
                   "quality": ((data.get("quality") or {}).get("status") or "unknown").lower()}
    cache.update_one({"_id": ck}, {"$set": {**out, "at": now}}, upsert=True)
    return out
