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


_CREDIT_CHECK: Dict[str, Any] = {}


def _has_credits(client, now: datetime) -> bool:
    """The account's email credits, read (free) at most hourly: no lookup is
    sent while none are left."""
    if _CREDIT_CHECK.get("at") and _CREDIT_CHECK["at"] > now - timedelta(hours=1):
        return _CREDIT_CHECK["ok"]
    left = email_credits_left(client)
    _CREDIT_CHECK.update(at=now, ok=left is None or left > 0)
    return _CREDIT_CHECK["ok"]


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
    if not _has_credits(client, now):
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
    elif r.status_code == 401:
        logger.error("skrapp: key %d rejected (HTTP 401)", acct["index"])
        return {"status": "key_rejected"}
    elif r.status_code == 403:
        # Skrapp answers 403 "Not enough credits" (2026-10-23: plan credits
        # 14000/14000 used) -- out of credits for now, not a bad key
        _count(client, acct["index"], now, exhausted=True)
        return {"status": "monthly_limit"}
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


# ---------------------------------------------------------------------------
# Free endpoints (no email credits; checked 2026-10-22 against skrapp.io/api)
# ---------------------------------------------------------------------------
SNAPSHOT_URL = "https://api.skrapp.io/api/v3/companies/snapshot"
ACCOUNT_URL = "https://api.skrapp.io/api/v2/account"
LISTS_URL = "https://api.skrapp.io/api/v2/account-lists"
SNAPSHOT_CACHE_DAYS = 90


def company_snapshot(client, domain: str = "", name: str = "",
                     now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Skrapp's free company card -- LinkedIn's own industry, size, HQ:
    {"company_name", "industry", "employees_range", "type", "hq_country",
     "linkedin_url", ...}. None when Skrapp has no card (or no key).
    Cached per domain/name in email_automation.skrapp_companies."""
    now = now or datetime.utcnow()
    ident = ("domain", domain.strip().lower()) if domain else ("name", (name or "").strip())
    if not ident[1]:
        return None
    cache = client["email_automation"]["skrapp_companies"]
    ck = f"{ident[0]}:{ident[1].lower()}"
    hit = cache.find_one({"_id": ck})
    if hit and hit.get("at") and hit["at"] > now - timedelta(days=SNAPSHOT_CACHE_DAYS):
        return hit.get("card")
    ks = keys(client)
    if not ks:
        return None
    try:
        r = requests.get(SNAPSHOT_URL, params={ident[0]: ident[1]}, headers={"X-Access-Key": ks[0]}, timeout=20)
    except Exception as e:
        logger.warning("skrapp snapshot failed for %s: %s", ck, e)
        return None
    if r.status_code == 429:
        return None  # rate limited: not an answer, asked again later
    card = None
    if r.status_code == 200:
        data = r.json() or {}
        card = data if data.get("company_name") or data.get("industry") else None
    cache.update_one({"_id": ck}, {"$set": {"card": card, "at": now, "http": r.status_code}}, upsert=True)
    return card


def email_credits_left(client) -> Optional[int]:
    """Email-finder credits left on the first key (quota - used); None if unknown."""
    ks = keys(client)
    if not ks:
        return None
    try:
        r = requests.get(ACCOUNT_URL, headers={"X-Access-Key": ks[0]}, timeout=20)
        c = ((r.json() or {}).get("credit") or {}).get("email") or {}
        return int(c.get("quota") or 0) - int(c.get("used") or 0)
    except Exception:
        return None


def list_leads(client):
    """Every lead in every Skrapp list on the account (free): dicts with
    name, first_n, last_n, email, email_status, title, company, domain,
    company_industry, linkedin_url, location, list_id, list_name."""
    ks = keys(client)
    if not ks:
        return
    h = {"X-Access-Key": ks[0]}
    lists, page = [], 1
    while True:
        r = requests.get(LISTS_URL, params={"page": page, "pageSize": 100}, headers=h, timeout=30)
        d = r.json() or {}
        batch = d.get("data") if isinstance(d, dict) else d
        if not batch:
            break
        lists += batch
        if isinstance(d, dict) and len(lists) >= int(d.get("total_count") or 0):
            break
        page += 1
    for lst in lists:
        start = None
        while True:
            params = {"size": 500}
            if start:
                params["start"] = start
            r = requests.get(f"https://api.skrapp.io/api/v2/list/{lst['id']}/leads", params=params,
                             headers=h, timeout=60)
            d = r.json() or {}
            for lead in d.get("data") or []:
                yield {**lead, "list_id": lst["id"], "list_name": lst.get("name")}
            start = d.get("next_start")
            if not start or not d.get("data"):
                break
