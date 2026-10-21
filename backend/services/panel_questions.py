"""
The SurveyFieldwork Panel's profiling questions, for project qualifications (2026-10-21).

Served by the Panel (GET {SFW_PANEL_API_BASE}/profiling-catalog, x-internal-key):
single / multi-choice questions with their answer codes per country (IN / UK / US).
A project picks questions and the codes that qualify:

    qualification.panelQuestions = [{"id": "CORE_24", "qualifying": [1, 3]}]

Panel members are matched on the answers already in their profile (same codes);
everyone else is asked the question on the survey landing page, as "pq_<id>".
"""
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

_CACHE: Dict[str, Any] = {"until": 0.0, "byId": {}}
_TTL = 10 * 60
ANSWER_ID = re.compile(r"^[A-Z]{2,5}_\d+[A-Z]?$")
LANDING_PREFIX = "pq_"


def _base() -> str:
    return os.getenv("SFW_PANEL_API_BASE", "https://surveyfieldwork.com/api/admin").rstrip("/")


async def load(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """{id: {id, section, type, countries: {IN: {text, options: [{code, label}]}}}}, cached 10 min.
    On failure the last good copy (or {}) is returned -- matching on stored codes still works."""
    if not force and _CACHE["until"] > time.time():
        return _CACHE["byId"]
    key = os.getenv("SFW_INTERNAL_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_base()}/profiling-catalog", headers={"X-Internal-Key": key})
        if resp.status_code == 200:
            questions = (resp.json() or {}).get("questions") or []
            _CACHE.update(byId={q["id"]: q for q in questions if q.get("id")}, until=time.time() + _TTL)
        else:
            print(f"[warn] panel question catalogue: HTTP {resp.status_code}")
            _CACHE["until"] = time.time() + 60
    except Exception as e:
        print(f"[warn] panel question catalogue unavailable: {e}")
        _CACHE["until"] = time.time() + 60
    return _CACHE["byId"]


def cached() -> Dict[str, Dict[str, Any]]:
    return _CACHE["byId"]


def member_answers(profile_answers: Dict[str, Any]) -> Dict[str, Any]:
    """The panel answers kept on a traffic record: question codes only (no phone / free text)."""
    out = {}
    for k, v in (profile_answers or {}).items():
        if not ANSWER_ID.match(str(k)) or str(k).startswith("CONTACT_"):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            out[k] = v
    return out


def criteria(raw: Any) -> List[Dict[str, Any]]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not ANSWER_ID.match(str(item.get("id") or "")):
            continue
        qualifying = [str(c) for c in (item.get("qualifying") or []) if str(c).strip()]
        if qualifying:
            out.append({"id": str(item["id"]), "qualifying": qualifying})
    return out[:30]


def reasons(crit: List[Dict[str, Any]], answers: Dict[str, Any]) -> List[str]:
    """answers: {id: code | [codes]} -- the panel profile's, plus what the landing page asked."""
    out = []
    for c in crit:
        value = (answers or {}).get(c["id"])
        if value is None or value == [] or value == "":
            out.append(f"{c['id']}_missing")
            continue
        given = {str(v) for v in (value if isinstance(value, list) else [value])}
        if not given & set(c["qualifying"]):
            out.append(c["id"])
    return out


def questions(crits: List[List[Dict[str, Any]]], known: Dict[str, Any], country: str,
              catalog: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Landing questions for picked panel questions this person has not answered (country wording and codes)."""
    catalog = catalog if catalog is not None else cached()
    out, seen = [], set()
    for crit in crits:
        for c in crit:
            qid = c["id"]
            if qid in seen or (known or {}).get(qid) not in (None, "", []):
                continue
            seen.add(qid)
            q = catalog.get(qid)
            if not q:
                continue
            per = q["countries"].get((country or "").upper()) or q["countries"].get("IN") or next(iter(q["countries"].values()))
            out.append({"id": LANDING_PREFIX + qid, "type": "multi" if q["type"] == "multi" else "select",
                        "text": per["text"], "options": [{"value": str(o["code"]), "label": o["label"]} for o in per["options"]]})
    return out


def clean_answers(raw: Dict[str, Any]) -> Dict[str, Any]:
    """pq_<id> landing answers -> {pq_<id>: code | [codes]} (strings of digits only)."""
    out: Dict[str, Any] = {}
    for k, v in (raw or {}).items():
        k = str(k)
        if not k.startswith(LANDING_PREFIX) or not ANSWER_ID.match(k[len(LANDING_PREFIX):]):
            continue
        if isinstance(v, list):
            codes = [str(x) for x in v if re.fullmatch(r"-?\d{1,4}", str(x))][:30]
            if codes:
                out[k] = codes
        elif re.fullmatch(r"-?\d{1,4}", str(v or "")):
            out[k] = str(v)
    return out


def landing_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    """{CORE_24: "3", ...} from the cleaned pq_ answers."""
    return {k[len(LANDING_PREFIX):]: v for k, v in (answers or {}).items() if k.startswith(LANDING_PREFIX)}
