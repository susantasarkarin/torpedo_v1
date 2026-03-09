"""
Survey API routes — handles start, answer submission, resume and completion.
All quota checks use atomic MongoDB operations for safe concurrent access.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from models import (
    AnswerPayload, StartSurveyResponse, RoutingDecision, ResumeSurveyResponse,
)
from services.quota_service import try_claim_quota, release_quota
from services.nccs import classify_nccs

router = APIRouter(prefix="/api/survey", tags=["survey"])

# ---- helpers ----

def _db():
    from main import db
    return db


# Mapping: Q2 age code → quota key
AGE_QUOTA_MAP = {
    2: "band1_25_34", 3: "band1_25_34",
    4: "band2_35_44", 5: "band2_35_44",
    6: "band3_45_55", 7: "band3_45_55",
}

GENDER_QUOTA_MAP = {1: "male", 2: "female"}

# Q6 city codes → quota keys (10 cities; code 11 = Other → terminate)
CITY_QUOTA_MAP = {
    1: "mumbai",    2: "delhi_ncr",  3: "bangalore",
    4: "kolkata",   5: "chennai",   6: "hyderabad",
    7: "pune",      8: "ahmedabad", 9: "jaipur",
    10: "lucknow",
}

# Q1 terminate codes (industry disqualifiers)
Q1_TERMINATE_CODES = {1, 2, 3, 4, 5, 6}

# Symptom → module mapping (Q9 codes → module numbers)
SYMPTOM_MODULE_MAP = {
    1:  [1],   # Fever → Pain & Fever Relief
    2:  [3],   # Cold/cough → Cold, Cough & Flu
    3:  [5],   # Acidity → Antacids & Digestive
    4:  [9],   # Skin rash → Antifungal & Skin
    5:  [6],   # Allergy → Allergy & Antihistamine
    6:  [4],   # Diarrhoea → Anti-Diarrheal & ORS
    7:  [10],  # Eye → Eye & Ear Care
    8:  [10],  # Ear → Eye & Ear Care
    9:  [1],   # Pain → Pain & Fever Relief
    10: [2],   # Fatigue/vitamins → Vitamins & Supplements
    11: [2],   # Sleep → Vitamins & Supplements
    12: [19],  # Mental stress → Mental Health & Wellness
    13: [11],  # Dental → Oral Care
    14: [10],  # Vision → Eye & Ear Care
    15: [],    # Chronic condition — no single OTC module
}

# Rotation group assignment (used at Q10); group → 4 module numbers
from config import ROTATION_GROUPS as _ROTATION_GROUPS
_GROUP_KEYS = list(_ROTATION_GROUPS.keys())          # ['group_a' … 'group_g']

# Module number → first question ID  (25 modules × 21 questions, starting Q31)
MODULE_START_Q = {i + 1: 31 + i * 21 for i in range(25)}

MODULES_PER_RESPONDENT = 4  # each respondent sees 4 modules
QUESTIONS_PER_MODULE   = 21 # questions in each category module
AD_TEST_START          = 556
DEMO_START             = 561
LAST_QUESTION_ID       = f"Q{DEMO_START + 5}"


# ---- endpoints ----

@router.post("/start", response_model=StartSurveyResponse)
async def start_survey(study_id: str = "default", rid: str = ""):
    """Create a new respondent session, scoped to a study."""
    db = _db()
    respondent_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc)

    # Resolve active wave for this study
    wave_id = None
    if study_id != "default":
        study = await db.studies.find_one({"_id": study_id}, {"active_wave_id": 1, "status": 1})
        if not study:
            raise HTTPException(status_code=404, detail="Study not found")
        if study.get("status") not in ("live", "draft"):
            raise HTTPException(status_code=400, detail="Study is not accepting responses")
        wave_id = study.get("active_wave_id")

    await db.respondents.insert_one({
        "_id": respondent_id,
        "study_id": study_id,
        "wave_id": wave_id,
        "vendor_rid": rid,
        "status": "in_progress",
        "responses": {},
        "quota_claims": [],  # track what was claimed for rollback
        "assigned_modules": [],
        "eligible_modules": [],
        "started_at": now,
        "updated_at": now,
        "current_question_id": "Q1",
        "termination_reason": None,
    })

    return StartSurveyResponse(
        respondent_id=respondent_id,
        first_question_id="Q1",
    )


@router.post("/answer", response_model=RoutingDecision)
async def submit_answer(payload: AnswerPayload):
    """
    Save one answer and return routing decision.
    Handles all screener termination, quota checks, and skip logic.
    """
    db = _db()
    rid = payload.respondent_id
    qid = payload.question_id
    answer = payload.answer

    # Verify respondent exists and is in_progress
    respondent = await db.respondents.find_one({"_id": rid, "status": "in_progress"})
    if not respondent:
        raise HTTPException(status_code=404, detail="Respondent not found or already completed/terminated")

    # Save the answer
    await db.respondents.update_one(
        {"_id": rid},
        {
            "$set": {
                f"responses.{qid}": answer,
                "current_question_id": qid,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    # ---- ROUTING LOGIC ----
    responses = respondent.get("responses", {})
    responses[qid] = answer  # include current answer

    # -- Q1: Industry screener --
    if qid == "Q1":
        codes = answer if isinstance(answer, list) else [answer]
        if any(c in Q1_TERMINATE_CODES for c in codes):
            return await _terminate(db, rid, "Q1_industry_disqualified")
        return RoutingDecision(action="next", next_question_id="Q2")

    # -- Q2: Age screener + quota --
    if qid == "Q2":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code in (1, 8):
            return await _terminate(db, rid, "Q2_age_disqualified")
        quota_key = AGE_QUOTA_MAP.get(code)
        if quota_key:
            claimed = await try_claim_quota(db, quota_key)
            if not claimed:
                return await _terminate(db, rid, f"Q2_age_quota_full_{quota_key}")
            await db.respondents.update_one(
                {"_id": rid}, {"$push": {"quota_claims": quota_key}}
            )
        return RoutingDecision(action="next", next_question_id="Q3")

    # -- Q3: Gender — soft quota --
    if qid == "Q3":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        quota_key = GENDER_QUOTA_MAP.get(code)
        if quota_key:
            claimed = await try_claim_quota(db, quota_key)
            if not claimed:
                # Soft quota: allow but flag
                await db.respondents.update_one(
                    {"_id": rid}, {"$set": {"gender_over_quota": True}}
                )
            else:
                await db.respondents.update_one(
                    {"_id": rid}, {"$push": {"quota_claims": quota_key}}
                )
        return RoutingDecision(action="next", next_question_id="Q4")

    # -- Q4: City tier — terminate if Tier 2 / Tier 3 (only Metro + Tier 1) --
    if qid == "Q4":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code in (3, 4):
            return await _terminate(db, rid, "Q4_tier2_or_lower_disqualified")
        return RoutingDecision(action="next", next_question_id="Q5")

    # -- Q5: Health purchase role — terminate if non-decision-maker --
    if qid == "Q5":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code == 3:
            return await _terminate(db, rid, "Q5_non_decision_maker")
        return RoutingDecision(action="next", next_question_id="Q6")

    # -- Q6: City dropdown — quota check; terminate if 'Other City' --
    if qid == "Q6":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code == 11:
            return await _terminate(db, rid, "Q6_other_city")
        quota_key = CITY_QUOTA_MAP.get(code)
        if quota_key:
            claimed = await try_claim_quota(db, quota_key)
            if not claimed:
                return await _terminate(db, rid, f"Q6_city_quota_full_{quota_key}")
            await db.respondents.update_one(
                {"_id": rid}, {"$push": {"quota_claims": quota_key}}
            )
        return RoutingDecision(action="next", next_question_id="Q7")

    # -- Q7: Household SEC durables —minimum qualifiers --
    if qid == "Q7":
        codes = answer if isinstance(answer, list) else [answer]
        if 1 not in codes or 2 not in codes:   # must have electricity AND ceiling fan
            return await _terminate(db, rid, "Q7_no_electricity_or_fan")
        return RoutingDecision(action="next", next_question_id="Q8")

    # -- Q8: Education + NCCS quota (uses Q7 durables) --
    if qid == "Q8":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code in (5, 6):
            return await _terminate(db, rid, "Q8_education_disqualified")
        q7_answer = responses.get("Q7", [])
        q7_codes = q7_answer if isinstance(q7_answer, list) else [q7_answer]
        nccs = classify_nccs(q7_codes, code)
        quota_key = nccs["band"]
        if quota_key == "nccs_below":
            return await _terminate(db, rid, "Q8_nccs_below_B")
        claimed = await try_claim_quota(db, quota_key)
        if not claimed:
            return await _terminate(db, rid, f"Q8_nccs_quota_full_{quota_key}")
        await db.respondents.update_one(
            {"_id": rid},
            {
                "$push": {"quota_claims": quota_key},
                "$set": {"nccs_grade": nccs["grade"], "nccs_band": quota_key},
            },
        )
        return RoutingDecision(action="next", next_question_id="Q9")

    # -- Q9: Symptom incidence → note symptom-relevant modules --
    if qid == "Q9":
        codes = answer if isinstance(answer, list) else [answer]
        symptom_eligible = set()
        for c in codes:
            for m in SYMPTOM_MODULE_MAP.get(c, []):
                symptom_eligible.add(m)
        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {"symptom_eligible_modules": list(symptom_eligible)}},
        )
        return RoutingDecision(action="next", next_question_id="Q10")

    # -- Q10: Lifestyle → assign rotation group (4 modules per respondent) --
    if qid == "Q10":
        # Balance rotation groups using an atomic counter
        counter_doc = await db.module_counters.find_one_and_update(
            {"_id": "rotation"},
            {"$inc": {"counter": 1}},
            upsert=True,
            return_document=True,
        )
        rotation_idx = counter_doc.get("counter", 0)
        group_key = _GROUP_KEYS[rotation_idx % len(_GROUP_KEYS)]
        assigned = list(_ROTATION_GROUPS[group_key])

        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {
                "rotation_group": group_key,
                "assigned_modules": assigned,
                "eligible_modules": assigned,
            }},
        )
        return RoutingDecision(
            action="next",
            next_question_id="Q11",
            eligible_modules=assigned,
            assigned_modules=assigned,
        )

    # -- Q24: Brand switching filter — skip switch-reasons (Q25) if 'No' --
    if qid == "Q24":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code == 2:
            return RoutingDecision(action="skip_to", skip_to_question_id="Q26")
        return RoutingDecision(action="next", next_question_id="Q25")

    # -- Q28: Unmet needs filter — skip open-end (Q29) if 'No' → go to Q30 --
    if qid == "Q28":
        code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
        if code == 3:
            return RoutingDecision(action="skip_to", skip_to_question_id="Q30")
        return RoutingDecision(action="next", next_question_id="Q29")

    # -- Q29: Open-end unmet need → category importance grid --
    if qid == "Q29":
        return RoutingDecision(action="next", next_question_id="Q30")

    # -- Q30: Category importance grid → first assigned module --
    if qid == "Q30":
        next_q = _get_first_module_question(respondent)
        return RoutingDecision(action="next", next_question_id=next_q)

    # -- Category module routing (Q31–Q555) --
    module_num = _get_module_from_question(qid)
    if module_num is not None:
        q_offset = _get_question_offset_in_module(qid, module_num)

        # CM1 (offset 0): If 'No' (code 2), skip to next module
        if q_offset == 0:
            code = answer if isinstance(answer, int) else answer[0] if isinstance(answer, list) else int(answer)
            if code == 2:
                next_q = _get_next_module_or_section(respondent, module_num)
                return RoutingDecision(action="skip_to", skip_to_question_id=next_q)

        # Last question in module (offset 20): go to next module or ad-test
        if q_offset == QUESTIONS_PER_MODULE - 1:
            next_q = _get_next_module_or_section(respondent, module_num)
            return RoutingDecision(action="next", next_question_id=next_q)

    # -- Q560: Last ad-test question → demographics --
    if qid == f"Q{AD_TEST_START + 4}":
        return RoutingDecision(action="next", next_question_id=f"Q{DEMO_START}")

    # -- Q566: Last demographics question → complete --
    if qid == f"Q{DEMO_START + 5}":
        await db.respondents.update_one(
            {"_id": rid},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc),
            }},
        )
        # Resolve complete redirect URL
        redirect_url = None
        study_id = respondent.get("study_id")
        vendor_rid = respondent.get("vendor_rid", "")
        if study_id and study_id != "default":
            study = await db.studies.find_one({"_id": study_id}, {"redirects": 1})
            if study:
                raw_url = study.get("redirects", {}).get("complete_url", "")
                if raw_url:
                    redirect_url = raw_url.replace("[RID]", vendor_rid).replace("[rid]", vendor_rid)
        return RoutingDecision(action="complete", redirect_url=redirect_url)

    # -- Default: advance to next sequential question --
    return RoutingDecision(action="next", next_question_id=_next_q_id(qid))


@router.get("/resume/{respondent_id}", response_model=ResumeSurveyResponse)
async def resume_survey(respondent_id: str):
    """Resume an interrupted survey."""
    doc = await _db().respondents.find_one({"_id": respondent_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Respondent not found")

    return ResumeSurveyResponse(
        respondent_id=respondent_id,
        responses=doc.get("responses", {}),
        current_question_id=doc.get("current_question_id"),
        assigned_modules=doc.get("assigned_modules"),
        status=doc.get("status", "in_progress"),
    )


# ---- internal helpers ----

async def _terminate(db, rid: str, reason: str) -> RoutingDecision:
    """Mark respondent as terminated and release claimed quotas."""
    respondent = await db.respondents.find_one({"_id": rid})
    if respondent:
        for qk in respondent.get("quota_claims", []):
            await release_quota(db, qk)

    await db.respondents.update_one(
        {"_id": rid},
        {"$set": {
            "status": "terminated",
            "termination_reason": reason,
            "terminated_at": datetime.now(timezone.utc),
            "quota_claims": [],
        }},
    )

    # Resolve redirect URL
    redirect_url = None
    if respondent:
        study_id = respondent.get("study_id")
        vendor_rid = respondent.get("vendor_rid", "")
        if study_id and study_id != "default":
            study = await db.studies.find_one({"_id": study_id}, {"redirects": 1})
            if study:
                redirects = study.get("redirects", {})
                url_key = "overquota_url" if "quota_full" in reason else "terminate_url"
                raw_url = redirects.get(url_key, "")
                if raw_url:
                    redirect_url = raw_url.replace("[RID]", vendor_rid).replace("[rid]", vendor_rid)

    return RoutingDecision(action="terminate", reason=reason, redirect_url=redirect_url)


def _next_q_id(qid: str) -> str:
    """Simple sequential: Q1 → Q2, Q10 → Q11, etc."""
    num = int(qid.replace("Q", ""))
    return f"Q{num + 1}"


def _get_module_from_question(qid: str) -> int | None:
    """Return module number (1-25) if the question belongs to a category module."""
    num = int(qid.replace("Q", ""))
    for mod, start in MODULE_START_Q.items():
        if start <= num < start + QUESTIONS_PER_MODULE:
            return mod
    return None


def _get_question_offset_in_module(qid: str, module_num: int) -> int:
    """Return 0-based offset within a module (0=CM1, 7=CM8)."""
    num = int(qid.replace("Q", ""))
    return num - MODULE_START_Q[module_num]


def _get_first_module_question(respondent: dict) -> str:
    """Return the Q ID of the first assigned module's CM1 question."""
    assigned = respondent.get("assigned_modules", [])
    if assigned:
        return f"Q{MODULE_START_Q[assigned[0]]}"
    return f"Q{AD_TEST_START}"  # Fallback to ad test if no modules assigned


def _get_next_module_or_section(respondent: dict, current_module: int) -> str:
    """After finishing a module, find the next assigned module or move to ad test section."""
    assigned = respondent.get("assigned_modules", [])
    try:
        idx = assigned.index(current_module)
        if idx + 1 < len(assigned):
            next_mod = assigned[idx + 1]
            return f"Q{MODULE_START_Q[next_mod]}"
    except ValueError:
        pass
    # No more modules — go to ad test
    return f"Q{AD_TEST_START}"
