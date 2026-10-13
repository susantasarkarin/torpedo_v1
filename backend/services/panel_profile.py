"""
Date of birth, gender and postcode for SurveyFieldwork Panel members, read from
the Panel's internal allocation-profile API, so the survey landing page doesn't
ask panel members again for what their profile already holds.
"""
import os
import time
from typing import Optional

import httpx

_CACHE: dict = {}
_TTL = 10 * 60


def _base() -> str:
    return os.getenv("SFW_PANEL_API_BASE", "https://surveyfieldwork.com/api/admin").rstrip("/")


async def fetch(panel_id: str) -> Optional[dict]:
    """{birthday_day, birthday_month, birthday_year, gender ('m'/'f'), zip_code} or None."""
    panel_id = str(panel_id or "").strip()
    key = os.getenv("SFW_INTERNAL_KEY", "")
    if not panel_id or not key:
        return None
    hit = _CACHE.get(panel_id)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    result = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{_base()}/allocation-profile/{panel_id}", headers={"X-Internal-Key": key})
        if resp.status_code == 200:
            profile = (resp.json() or {}).get("profile") or {}
            dob = str(profile.get("dateOfBirth") or "")[:10]
            answers = profile.get("profileAnswers") or {}
            gender = {"male": "m", "female": "f"}.get(str(profile.get("gender") or "").strip().lower(), "")
            if len(dob) == 10 and gender:
                y, m, d = dob.split("-")
                result = {
                    "birthday_day": int(d), "birthday_month": int(m), "birthday_year": int(y),
                    "gender": gender, "zip_code": str(answers.get("CORE_07") or "").strip(),
                }
    except Exception as e:  # never block the survey on this lookup
        print(f"[warn] panel profile lookup failed for {panel_id}: {e}")
    _CACHE[panel_id] = (time.time(), result)
    return result
