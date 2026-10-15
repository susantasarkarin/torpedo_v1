"""
Skrapp.io email finder for the lead-gen MCP server (owner, 2026-10-15:
Hunter removed, Skrapp in its place).

The MCP server runs in its own venv and package, so it has this small async
client instead of importing backend/leads/skrapp_client.py (which needs the
backend's Mongo setup). Same API (https://skrapp.io/api):

    GET https://api.skrapp.io/api/v2/find?firstName=&lastName=&domain= (or company=)
    header X-Access-Key: <key>; includeCompanyData=true adds companyData
    200 -> {"email", "pattern", "quality": {"status": valid|invalid|catch-all|unknown}}
    404 -> not found, not charged

Keys: SKRAPP_API_KEY_1..3 or SKRAPP_API_KEY in the backend .env (the service
loads it as its EnvironmentFile). A key that answers 402/429 is skipped for
the rest of the process.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

FIND_URL = "https://api.skrapp.io/api/v2/find"
_spent: set = set()


def _keys() -> List[str]:
    ks = [os.getenv(f"SKRAPP_API_KEY_{i}", "").strip() for i in range(1, 4)]
    ks.append(os.getenv("SKRAPP_API_KEY", "").strip())
    seen, out = set(), []
    for k in ks:
        if k and k not in seen and k not in _spent:
            seen.add(k)
            out.append(k)
    return out


async def find(client: httpx.AsyncClient, first: str, last: str, domain: str = "",
               company: str = "", company_data: bool = False) -> Optional[Dict[str, Any]]:
    """{"email", "pattern", "quality", "company"} for one person, or None."""
    if not first or not last or not (domain or company):
        return None
    params: Dict[str, Any] = {"firstName": first, "lastName": last}
    if domain:
        params["domain"] = domain
    else:
        params["company"] = company
    if company_data:
        params["includeCompanyData"] = "true"
    for key in _keys():
        try:
            r = await client.get(FIND_URL, params=params, headers={"X-Access-Key": key}, timeout=30)
        except Exception:
            return None
        if r.status_code in (402, 429):
            _spent.add(key)
            continue
        if r.status_code != 200:
            return None
        data = r.json() or {}
        email = (data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return None
        return {"email": email, "pattern": data.get("pattern") or "",
                "quality": ((data.get("quality") or {}).get("status") or "unknown").lower(),
                "company": data.get("companyData") or {}}
    return None
