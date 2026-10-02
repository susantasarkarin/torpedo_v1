"""
SLM re-ranking of CINT survey candidates for SurveyFieldwork panelists.

The existing allocation (quality floors, age filter, `_score_cint_survey`) stays
the gate: this module only *reorders* candidates that already passed it, using
the panelist's profile from the Panel backend and the self-hosted Qwen model
served by Ollama. It never adds a survey, never removes one, and on any failure
(Ollama down, timeout, bad JSON, unknown panelist) returns the original order.

Rollout is controlled by AI_ALLOCATION_SHARE (0.0-1.0, default 0 = off): that
fraction of panel traffic is re-ranked, and the traffic record is tagged
`aiAllocation.ranked` so conversion can be compared against the rest.

Env:
  AI_ALLOCATION_SHARE   fraction of panel traffic to re-rank (default 0)
  OLLAMA_URL            e.g. http://10.0.0.5:11434
  OLLAMA_MODEL          default qwen2.5:7b
  AI_ALLOCATION_TIMEOUT seconds for the whole re-rank, default 2.5
  PANEL_API_URL         SurveyFieldwork Panel backend base URL
  PANEL_INTERNAL_KEY    matches the Panel's INTERNAL_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from typing import Any, Dict, List, Optional

import httpx

TOP_K = 10
PROFILE_CACHE_TTL = 600  # seconds

_profile_cache: Dict[str, tuple] = {}
_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    # One pooled client for the process: building a client loads the SSL
    # context synchronously, which would block the event loop on every redirect.
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=float(os.getenv("AI_ALLOCATION_TIMEOUT", "2.5")))
    return _http_client

SYSTEM_PROMPT = (
    "You rank online surveys for one survey-panel member. Every survey listed already "
    "passed quality and eligibility checks. Order them by how likely this person is to "
    "qualify AND complete, using their profile answers, demographics and past behaviour. "
    "Prefer shorter surveys for low-engagement members. Use only the survey numbers given. "
    'Respond with JSON only: {"order": ["<survey number>", ...]}'
)


def _share() -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv("AI_ALLOCATION_SHARE", "0"))))
    except ValueError:
        return 0.0


def is_enabled() -> bool:
    return bool(_share() > 0 and os.getenv("OLLAMA_URL") and os.getenv("PANEL_API_URL"))


async def _fetch_panelist_profile(client: httpx.AsyncClient, panel_id: str) -> Optional[dict]:
    cached = _profile_cache.get(panel_id)
    if cached and time.time() - cached[0] < PROFILE_CACHE_TTL:
        return cached[1]

    base = os.getenv("PANEL_API_URL", "").rstrip("/")
    resp = await client.get(
        f"{base}/api/admin/allocation-profile/{panel_id}",
        headers={"x-internal-key": os.getenv("PANEL_INTERNAL_KEY", "")},
    )
    profile = resp.json().get("profile") if resp.status_code == 200 else None
    _profile_cache[panel_id] = (time.time(), profile)
    return profile


def _survey_summary(survey: dict) -> dict:
    quals = survey.get("survey_qualifications") or []
    return {
        "survey": str(survey.get("SurveyNumber")),
        "name": survey.get("SurveyName"),
        "industryId": survey.get("IndustryID"),
        "studyTypeId": survey.get("StudyTypeID"),
        "loiMinutes": survey.get("LengthOfInterview") or survey.get("LOI"),
        "incidencePct": survey.get("IR") or survey.get("BidIncidence"),
        "conversion": survey.get("Conversion"),
        "qualificationQuestionIds": sorted({q.get("question_id") or q.get("QuestionID") for q in quals} - {None}),
    }


def _profile_summary(profile: dict) -> dict:
    return {
        "country": profile.get("country"),
        "gender": profile.get("gender"),
        "dateOfBirth": (profile.get("dateOfBirth") or "")[:10] or None,
        "profileAnswers": profile.get("profileAnswers") or {},
        "profileCompletionPct": profile.get("profileQuestionCompletion"),
        "surveyAttempts": profile.get("attempts"),
        "surveyCompletes": profile.get("completes"),
        "daysSinceLastSurvey": profile.get("daysSinceLastAttempt"),
        "engagementSegment": profile.get("segment"),
    }


async def _ask_qwen(client: httpx.AsyncClient, profile: dict, surveys: List[dict]) -> List[str]:
    resp = await client.post(
        f"{os.getenv('OLLAMA_URL', '').rstrip('/')}/api/chat",
        json={
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(
                    {"member": _profile_summary(profile), "surveys": surveys}, default=str)},
            ],
        },
    )
    resp.raise_for_status()
    content = (resp.json().get("message") or {}).get("content") or "{}"
    order = json.loads(content).get("order") or []
    return [str(x) for x in order]


def _merge_order(original: List[str], ai_order: List[str]) -> List[str]:
    """AI order for the top-K, keeping only known ids once; anything the model
    dropped keeps its original relative position after them."""
    head = original[:TOP_K]
    seen, ranked = set(), []
    for sid in ai_order:
        if sid in head and sid not in seen:
            ranked.append(sid)
            seen.add(sid)
    ranked += [sid for sid in head if sid not in seen]
    return ranked + original[TOP_K:]


async def rerank_cint_candidates(
    panel_id: str, candidates: List[str], survey_lookup: Dict[str, dict]
) -> tuple[List[str], Dict[str, Any]]:
    """Returns (ordered candidates, metadata for the traffic record). Never raises."""
    meta: Dict[str, Any] = {"ranked": False}
    if not panel_id or len(candidates) < 2 or not is_enabled():
        return candidates, meta
    if random.random() >= _share():
        meta["reason"] = "control_group"
        return candidates, meta

    started = time.time()
    try:
        timeout = float(os.getenv("AI_ALLOCATION_TIMEOUT", "2.5"))

        client = _client()

        async def _run() -> List[str]:
            profile = await _fetch_panelist_profile(client, panel_id)
            if not profile:
                raise LookupError("panelist profile not found")
            surveys = [_survey_summary(survey_lookup[sid]) for sid in candidates[:TOP_K] if sid in survey_lookup]
            if len(surveys) < 2:
                raise LookupError("survey metadata not cached")
            return await _ask_qwen(client, profile, surveys)

        try:
            ai_order = await asyncio.wait_for(_run(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"no answer within {timeout}s")
        ordered = _merge_order(candidates, ai_order)
        meta.update({"ranked": True, "model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
                     "originalTop": candidates[:TOP_K], "aiTop": ordered[:TOP_K]})
        return ordered, meta
    except Exception as e:  # any failure keeps the rule-based order
        meta["reason"] = f"fallback: {type(e).__name__}: {str(e)[:120]}"
        return candidates, meta
    finally:
        meta["latencyMs"] = int((time.time() - started) * 1000)
