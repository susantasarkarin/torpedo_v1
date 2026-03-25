"""
Survey API routes - India OTC Discovery Intelligence Study v2.0
Sections: S (Screener Q1-Q7) | A (Discovery Q8-Q16,Q41,Q43,Q44) | B (Trust Q17-Q24,Q42)
          C (Competitive per-category blocks Q25-Q35) | D (Demographics Q36-Q40)
n=1,760  |  8 Tier 2 cities (unequal allocation)  |  max 3 category blocks per respondent

New questions in v2.0:
  Q41 - App usage by purpose grid (after Q12, before Q13)
  Q43 - Purchase channel by situation type grid (after Q15, before Q16/Q44)
  Q44 - Online purchase motivation, max 2 (conditional: Q14 codes 1-3, before Q17)
  Q42 - Language of health content preference (after Q17, before Q18)

Quality controls built-in:
  - IP deduplication  : one completed/locked slot per IP address
  - Straight-liner    : identical scores on Q12 AND Q17 grids -> terminate
  - Speeder           : complete in < MIN_COMPLETE_SECONDS -> terminate
"""
import re
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from models import AnswerPayload, StartSurveyResponse, RoutingDecision, ResumeSurveyResponse
from services.quota_service import try_claim_quota, release_quota
from services.nccs import classify_nccs
from config import (
    CITY_CODE_MAP, CATEGORY_PRIORITY,
    MIN_COMPLETE_SECONDS, STRAIGHT_LINE_FLAGS_TO_TERMINATE,
)

router = APIRouter(prefix="/api/survey", tags=["survey"])


def _db():
    from main import db
    return db


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Q1 industry disqualifiers: codes 1-6 all terminate.
# Code 7 = "None of the above" → continue.
# Matches QRE frontend options (v2.0): 1=Advertising/Marketing, 2=Market Research,
# 3=Pharma/Pharmacy, 4=Health Insurance, 5=Healthcare, 6=Media/PR, 7=None
Q1_TERMINATE_CODES = {1, 2, 3, 4, 5, 6}

AGE_QUOTA_MAP = {
    2: "band1_25_34",
    3: "band2_35_44",
    4: "band3_45_55",
}

GENDER_QUOTA_MAP = {1: "female", 2: "male"}

# Q8 category incidence codes â†’ category keys
Q8_CATEGORY_MAP = {
    1: ["pain_fever", "cold_cough"],   # Fever, cold, cough or flu
    2: ["pain_fever"],                 # Body pain, headache or joint pain
    3: ["digestive"],                  # Acidity, indigestion, gas or bloating
    4: ["skin_antifungal"],            # Skin rash, fungal infection or itching
    5: ["vitamins"],                   # Fatigue / vitamin deficiency
    6: ["digestive"],                  # Diarrhoea or stomach upset
    7: ["vitamins"],                   # General wellness / immunity supplement
    8: ["ayurvedic"],                  # Ayurvedic / herbal product
    9: [],                             # None of the above
}

MAX_MODULE_C_BLOCKS = 3

# Module C question IDs are encoded as Q{25-35}_{cat_key}
_MC_PATTERN = re.compile(r"^Q(2[5-9]|3[0-5])_([a-z_]+)$")


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _extract_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For for reverse-proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_straight_line(answer) -> bool:
    """
    Detect straight-lining on a grid question.
    Returns True when every non-null item in the answer has the same value.
    Accepts dict {row_key: score} or list of scores.
    Requires >= 3 rated items to avoid false-positives on very short grids.
    """
    if isinstance(answer, dict):
        values = [v for v in answer.values() if v is not None]
    elif isinstance(answer, list):
        values = [v for v in answer if v is not None]
    else:
        return False
    if len(values) < 3:
        return False
    return len(set(str(v) for v in values)) == 1


def _coerce_int(answer) -> int:
    if isinstance(answer, int):
        return answer
    if isinstance(answer, list) and answer:
        return int(answer[0])
    return int(answer)


def _check_max_select(qid: str, answer, max_n: int):
    """Raise 422 if a multi-answer question exceeds its maxSelect limit."""
    if isinstance(answer, list) and len(answer) > max_n:
        raise HTTPException(
            status_code=422,
            detail=f"{qid}: maximum {max_n} selection(s) allowed, got {len(answer)}",
        )


def _get_active_categories(q8_answer) -> list[str]:
    """
    Return deduplicated active categories from Q8, capped at MAX_MODULE_C_BLOCKS.

    Ordering follows the QRE instruction: "prioritise by reported frequency".
    Each Q8 code that maps to a category counts as one frequency hit for that
    category.  Categories with more hits are served first (i.e. more Q8 symptoms
    that are relevant to that category = higher priority).  Ties are broken by
    the hardcoded CATEGORY_PRIORITY list to ensure deterministic output.
    """
    codes = q8_answer if isinstance(q8_answer, list) else [q8_answer]
    hit_count: dict[str, int] = {}
    for code in codes:
        for cat in Q8_CATEGORY_MAP.get(int(code), []):
            hit_count[cat] = hit_count.get(cat, 0) + 1

    # Sort: primary key = hit count descending; tie-break = CATEGORY_PRIORITY index
    priority_index = {cat: i for i, cat in enumerate(CATEGORY_PRIORITY)}
    sorted_cats = sorted(
        hit_count.keys(),
        key=lambda c: (-hit_count[c], priority_index.get(c, 999)),
    )
    return sorted_cats[:MAX_MODULE_C_BLOCKS]


def _next_mc_or_demo(respondent: dict, finished_cat: str) -> str:
    """After finishing a category block return next Q25_{cat} or Q36."""
    active = respondent.get("active_categories", [])
    try:
        idx = active.index(finished_cat)
    except ValueError:
        return "Q36"
    if idx + 1 < len(active):
        return f"Q25_{active[idx + 1]}"
    return "Q36"


def _first_mc_question(respondent: dict) -> str:
    active = respondent.get("active_categories", [])
    return f"Q25_{active[0]}" if active else "Q36"


async def _terminate(db, rid: str, reason: str) -> RoutingDecision:
    """Mark respondent terminated, release quota claims, resolve redirect URL.

    Quality terminations (reason starts with 'quality_') also set ip_locked=True
    to prevent re-entry from the same IP.  Screening terminations (wrong city,
    age out-of-quota, etc.) do NOT lock the IP.
    """
    respondent = await db.respondents.find_one(
        {"_id": rid}, {"quota_claims": 1, "study_id": 1, "vendor_rid": 1}
    )
    if respondent:
        for qk in respondent.get("quota_claims", []):
            await release_quota(db, qk)

    # Lock IP for quality failures only, not for routine screenouts.
    lock_ip = reason.startswith("quality_")

    await db.respondents.update_one(
        {"_id": rid},
        {"$set": {
            "status": "terminated",
            "termination_reason": reason,
            "terminated_at": datetime.now(timezone.utc),
            "quota_claims": [],
            "ip_locked": lock_ip,
        }},
    )

    redirect_url = None
    if respondent:
        study_id = respondent.get("study_id")
        vendor_rid = respondent.get("vendor_rid", "")
        if study_id and study_id != "default":
            study = await db.studies.find_one({"_id": study_id}, {"redirects": 1})
            if study:
                url_key = "overquota_url" if "quota_full" in reason else "terminate_url"
                raw_url = study.get("redirects", {}).get(url_key, "")
                if raw_url:
                    redirect_url = (
                        raw_url
                        .replace("[RID]", vendor_rid)
                        .replace("[rid]", vendor_rid)
                        .replace("{RID}", vendor_rid)
                        .replace("{rid}", vendor_rid)
                    )

    return RoutingDecision(action="terminate", reason=reason, redirect_url=redirect_url)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartSurveyResponse)
async def start_survey(request: Request, study_id: str = "default", rid: str = ""):
    """Create a new respondent session, enforcing one session per IP address."""
    db = _db()
    ip = _extract_ip(request)
    now = datetime.now(timezone.utc)

    # --- IP deduplication -------------------------------------------------
    # Skip check when IP is unknown (misconfigured proxy); otherwise enforce
    # one completed/locked entry per IP, and surface in-progress sessions.
    if ip != "unknown":
        existing = await db.respondents.find_one(
            {"ip_address": ip},
            {"_id": 1, "status": 1, "ip_locked": 1},
        )
        if existing:
            if existing.get("ip_locked") or existing.get("status") == "completed":
                raise HTTPException(
                    status_code=403,
                    detail="This survey has already been completed from your connection.",
                )
            if existing.get("status") == "in_progress":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A session from your connection is already in progress. "
                        f"Resume respondent_id={existing['_id']}"
                    ),
                )
    # ----------------------------------------------------------------------

    wave_id = None
    if study_id != "default":
        study = await db.studies.find_one({"_id": study_id}, {"active_wave_id": 1, "status": 1})
        if not study:
            raise HTTPException(status_code=404, detail="Study not found")
        if study.get("status") not in ("live", "draft"):
            raise HTTPException(status_code=400, detail="Study is not accepting responses")
        wave_id = study.get("active_wave_id")

    respondent_id = str(uuid.uuid4())[:12]
    await db.respondents.insert_one({
        "_id": respondent_id,
        "study_id": study_id,
        "wave_id": wave_id,
        "vendor_rid": rid,
        "ip_address": ip,
        "ip_locked": False,
        "status": "in_progress",
        "responses": {},
        "quota_claims": [],
        "active_categories": [],
        "straight_line_flags": 0,
        "started_at": now,
        "updated_at": now,
        "current_question_id": "Q1",
        "termination_reason": None,
    })

    return StartSurveyResponse(respondent_id=respondent_id, first_question_id="Q1")


@router.post("/answer", response_model=RoutingDecision)
async def submit_answer(payload: AnswerPayload):
    """Save one answer and return routing decision."""
    db = _db()
    rid = payload.respondent_id
    qid = payload.question_id
    answer = payload.answer

    respondent = await db.respondents.find_one({"_id": rid, "status": "in_progress"})
    if not respondent:
        raise HTTPException(
            status_code=404,
            detail="Respondent not found or already completed/terminated",
        )

    # Persist the answer
    await db.respondents.update_one(
        {"_id": rid},
        {"$set": {
            f"responses.{qid}": answer,
            "current_question_id": qid,
            "updated_at": datetime.now(timezone.utc),
        }},
    )

    responses = {**respondent.get("responses", {}), qid: answer}

    # ==========================================================================
    # SECTION S â€” SCREENER (Q1-Q7)
    # ==========================================================================

    # Q1 â€” Industry screener
    if qid == "Q1":
        codes = answer if isinstance(answer, list) else [answer]
        if any(int(c) in Q1_TERMINATE_CODES for c in codes):
            return await _terminate(db, rid, "Q1_industry_disqualified")
        return RoutingDecision(action="next", next_question_id="Q2")

    # Q2 â€” City qualification + hard quota (n=200 per city)
    if qid == "Q2":
        code = _coerce_int(answer)
        if code not in CITY_CODE_MAP:
            return await _terminate(db, rid, "Q2_not_target_city")
        city_key = CITY_CODE_MAP[code]
        claimed = await try_claim_quota(db, city_key)
        if not claimed:
            return await _terminate(db, rid, f"Q2_city_quota_full_{city_key}")
        await db.respondents.update_one(
            {"_id": rid},
            {"$push": {"quota_claims": city_key}, "$set": {"city": city_key}},
        )
        return RoutingDecision(action="next", next_question_id="Q3")

    # Q3 â€” Age qualification + quota
    if qid == "Q3":
        code = _coerce_int(answer)
        if code in (1, 5):
            return await _terminate(db, rid, "Q3_age_disqualified")
        quota_key = AGE_QUOTA_MAP.get(code)
        if quota_key:
            claimed = await try_claim_quota(db, quota_key)
            if not claimed:
                return await _terminate(db, rid, f"Q3_age_quota_full_{quota_key}")
            await db.respondents.update_one(
                {"_id": rid}, {"$push": {"quota_claims": quota_key}}
            )
        return RoutingDecision(action="next", next_question_id="Q4")

    # Q4 — Gender — soft quota 50F/50M, never terminate
    if qid == "Q4":
        code = _coerce_int(answer)
        quota_key = GENDER_QUOTA_MAP.get(code)
        if quota_key:
            claimed = await try_claim_quota(db, quota_key)
            if claimed:
                await db.respondents.update_one(
                    {"_id": rid}, {"$push": {"quota_claims": quota_key}}
                )
        return RoutingDecision(action="next", next_question_id="Q5")

    # Q5 â€” Decision maker gate
    if qid == "Q5":
        code = _coerce_int(answer)
        if code == 3:
            return await _terminate(db, rid, "Q5_not_decision_maker")
        return RoutingDecision(action="next", next_question_id="Q6")

    # Q6 â€” Household durables / NCCS proxy; terminate if no electricity or fan
    if qid == "Q6":
        codes = [int(c) for c in (answer if isinstance(answer, list) else [answer])]
        if 1 not in codes or 2 not in codes:
            return await _terminate(db, rid, "Q6_below_minimum_durables")
        return RoutingDecision(action="next", next_question_id="Q7")

    # Q7 â€” Education + NCCS classification and quota
    if qid == "Q7":
        code = _coerce_int(answer)
        if code in (5, 6):
            return await _terminate(db, rid, "Q7_education_disqualified")
        q6_raw = responses.get("Q6", [])
        q6_codes = [int(c) for c in (q6_raw if isinstance(q6_raw, list) else [q6_raw])]
        nccs = classify_nccs(q6_codes, code)
        if nccs["band"] in ("below_minimum", "nccs_terminate"):
            return await _terminate(db, rid, f"Q7_nccs_disqualified_{nccs['band']}")
        quota_key = nccs["band"]
        claimed = await try_claim_quota(db, quota_key)
        if not claimed:
            return await _terminate(db, rid, f"Q7_nccs_quota_full_{quota_key}")
        await db.respondents.update_one(
            {"_id": rid},
            {
                "$push": {"quota_claims": quota_key},
                "$set": {"nccs_grade": nccs["grade"], "nccs_band": quota_key},
            },
        )
        return RoutingDecision(action="next", next_question_id="Q8")

    # ==========================================================================
    # MODULE A â€” THE DISCOVERY JOURNEY (Q8-Q16)
    # ==========================================================================

    # Q8 — Category incidence; determines Module C blocks
    if qid == "Q8":
        active_cats = _get_active_categories(answer)
        # Code 9 = "None of the above" (exclusive) → no eligible OTC category → terminate
        if not active_cats:
            return await _terminate(db, rid, "Q8_no_eligible_category")
        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {"active_categories": active_cats}},
        )
        return RoutingDecision(
            action="next",
            next_question_id="Q9",
            active_categories=active_cats,
        )

    # Q9â€“Q11 â€” Sequential, no skip logic
    if qid in ("Q9", "Q10", "Q11"):
        nxt = {"Q9": "Q10", "Q10": "Q11", "Q11": "Q12"}[qid]
        return RoutingDecision(action="next", next_question_id=nxt)

    # Q12 - Discovery influence frequency grid (straight-liner check)
    if qid == "Q12":
        if _is_straight_line(answer):
            updated = await db.respondents.find_one_and_update(
                {"_id": rid},
                {"$inc": {"straight_line_flags": 1}},
                return_document=True,
                projection={"straight_line_flags": 1},
            )
            if updated and updated.get("straight_line_flags", 0) >= STRAIGHT_LINE_FLAGS_TO_TERMINATE:
                return await _terminate(db, rid, "quality_straight_liner")
        return RoutingDecision(action="next", next_question_id="Q41")

    # Q41 — App usage by purpose grid (NEW v2.0); always sequential
    if qid == "Q41":
        return RoutingDecision(action="next", next_question_id="Q13")

    # Q13â€“Q14 â€” Sequential
    if qid in ("Q13", "Q14"):
        nxt = {"Q13": "Q14", "Q14": "Q15"}[qid]
        return RoutingDecision(action="next", next_question_id=nxt)

    # Q15 — Discovery-to-purchase gap; always routes to Q43 first
    if qid == "Q15":
        return RoutingDecision(action="next", next_question_id="Q43")

    # Q43 — Purchase channel by situation type grid (NEW v2.0)
    # Routing: Q16 only if Q15=4 (explicitly discovered online but bought at chemist).
    #          Q15=3 ("local chemist") carries no online-discovery signal → does NOT go to Q16.
    #          Else Q44 if Q14=1/2/3 (online buyer); else Q17.
    if qid == "Q43":
        q15 = _coerce_int(responses.get("Q15", 0))
        if q15 == 4:
            return RoutingDecision(action="next", next_question_id="Q16")
        q14 = _coerce_int(responses.get("Q14", 0))
        if q14 in (1, 2, 3):
            return RoutingDecision(action="next", next_question_id="Q44")
        return RoutingDecision(action="skip_to", skip_to_question_id="Q17")

    # Q16 — Conditional: why-chemist-despite-online-discovery
    # After Q16: Q44 if Q14=1/2/3 (has bought online); else skip to Q17
    if qid == "Q16":
        q14 = _coerce_int(responses.get("Q14", 0))
        if q14 in (1, 2, 3):
            return RoutingDecision(action="next", next_question_id="Q44")
        return RoutingDecision(action="skip_to", skip_to_question_id="Q17")

    # Q44 — Top 2 online purchase motivations (NEW v2.0, MA max 2)
    # Conditional: only reached when Q14 codes 1-3 (has bought online at least once)
    if qid == "Q44":
        _check_max_select(qid, answer, 2)
        return RoutingDecision(action="next", next_question_id="Q17")

    # ==========================================================================
    # MODULE B â€” TRUST BY SOURCE (Q17-Q24)
    # ==========================================================================

    # Q17 - Trust hierarchy grid (straight-liner check; terminate if both grids flagged)
    if qid == "Q17":
        if _is_straight_line(answer):
            updated = await db.respondents.find_one_and_update(
                {"_id": rid},
                {"$inc": {"straight_line_flags": 1}},
                return_document=True,
                projection={"straight_line_flags": 1},
            )
            if updated and updated.get("straight_line_flags", 0) >= STRAIGHT_LINE_FLAGS_TO_TERMINATE:
                return await _terminate(db, rid, "quality_straight_liner")
        return RoutingDecision(action="next", next_question_id="Q42")

    # Q42 — Language of health content preference (NEW v2.0, SA); always sequential
    if qid == "Q42":
        return RoutingDecision(action="next", next_question_id="Q18")

    # Q18 — Top 3 trust signals for unfamiliar health brand (MA max 3)
    if qid == "Q18":
        _check_max_select(qid, answer, 3)
        return RoutingDecision(action="next", next_question_id="Q19")

    # Q19â€"Q23 â€" Sequential
    if qid in ("Q19", "Q20", "Q21", "Q22", "Q23"):
        nxt = {
            "Q19": "Q20", "Q20": "Q21",
            "Q21": "Q22", "Q22": "Q23", "Q23": "Q24",
        }[qid]
        return RoutingDecision(action="next", next_question_id=nxt)

    # Q24 â€” Spend trend; route to Module C or Section D
    if qid == "Q24":
        fresh = await db.respondents.find_one({"_id": rid}, {"active_categories": 1})
        first_q = _first_mc_question(fresh or respondent)
        return RoutingDecision(action="next", next_question_id=first_q)

    # ==========================================================================
    # MODULE C â€” COMPETITIVE LANDSCAPE (Q25-Q35 per category; max 3 blocks)
    # Question IDs encoded as Q{25-35}_{cat_key}
    # ==========================================================================

    mc_match = _MC_PATTERN.match(qid)
    if mc_match:
        q_num = int(mc_match.group(1))
        cat_key = mc_match.group(2)

        # Q25 â€” Usage frequency; skip entire block if code 6 (not used)
        if q_num == 25:
            code = _coerce_int(answer)
            if code == 6:
                next_q = _next_mc_or_demo(respondent, cat_key)
                return RoutingDecision(action="skip_to", skip_to_question_id=next_q)
            return RoutingDecision(action="next", next_question_id=f"Q26_{cat_key}")
        # Q31 — Brand choice reasons (MA max 3)
        if q_num == 31:
            _check_max_select(qid, answer, 3)
            return RoutingDecision(action="next", next_question_id=f"Q32_{cat_key}")
        # Q26â€“Q34 â€” Sequential within block
        if 26 <= q_num <= 34:
            return RoutingDecision(action="next", next_question_id=f"Q{q_num + 1}_{cat_key}")

        # Q35 â€” Switching intent; end of category block
        if q_num == 35:
            next_q = _next_mc_or_demo(respondent, cat_key)
            return RoutingDecision(action="next", next_question_id=next_q)

    # ==========================================================================
    # SECTION D â€” DEMOGRAPHICS (Q36-Q40)
    # ==========================================================================

    if qid in ("Q36", "Q37", "Q38", "Q39"):
        nxt = {"Q36": "Q37", "Q37": "Q38", "Q38": "Q39", "Q39": "Q40"}[qid]
        return RoutingDecision(action="next", next_question_id=nxt)

    # Q40 - Last question; speeder check, then mark complete and redirect
    if qid == "Q40":
        now = datetime.now(timezone.utc)

        # --- Speeder check ------------------------------------------------
        started_at = respondent.get("started_at")
        if started_at:
            # Normalize started_at: MongoDB stores naive UTC datetimes
            if started_at.tzinfo is None:
                from datetime import timezone as _tz
                started_at = started_at.replace(tzinfo=_tz.utc)
            elapsed = (now - started_at).total_seconds()
            if elapsed < MIN_COMPLETE_SECONDS:
                return await _terminate(
                    db, rid,
                    f"quality_speeder_{int(elapsed)}s_of_{MIN_COMPLETE_SECONDS}s_required",
                )
        # ------------------------------------------------------------------

        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {"status": "completed", "completed_at": now, "ip_locked": True}},
        )
        redirect_url = None
        study_id = respondent.get("study_id")
        vendor_rid = respondent.get("vendor_rid", "")
        if study_id and study_id != "default":
            study = await db.studies.find_one({"_id": study_id}, {"redirects": 1})
            if study:
                raw_url = study.get("redirects", {}).get("complete_url", "")
                if raw_url:
                    redirect_url = (
                        raw_url
                        .replace("[RID]", vendor_rid)
                        .replace("[rid]", vendor_rid)
                        .replace("{RID}", vendor_rid)
                        .replace("{rid}", vendor_rid)
                    )
        return RoutingDecision(action="complete", redirect_url=redirect_url)

    # Fallback — unknown question_id; should never be reached in a correctly sequenced survey
    raise HTTPException(status_code=400, detail=f"Unknown question id: {qid}")


@router.get("/resume/{respondent_id}", response_model=ResumeSurveyResponse)
async def resume_survey(respondent_id: str):
    """Resume an interrupted survey session."""
    doc = await _db().respondents.find_one({"_id": respondent_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Respondent not found")
    return ResumeSurveyResponse(
        respondent_id=respondent_id,
        responses=doc.get("responses", {}),
        current_question_id=doc.get("current_question_id"),
        active_categories=doc.get("active_categories", []),
        status=doc.get("status", "in_progress"),
    )

