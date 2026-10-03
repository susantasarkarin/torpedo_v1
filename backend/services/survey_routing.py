"""
Survey qualification & routing engine (project / adhoc traffic).

  Traffic -> landing page (qualification questions; PII for Paid Ads)
          -> qualification check per project
          -> country check (Cloudflare IP country decides)
          -> eligible live projects in priority order
          -> survey attempt 1 .. ROUTING_MAX_ATTEMPTS (default 3)

Kept separate from SFW scoring (services/respondent_quality.py):
  qualification -> which surveys can this person enter?
  SFW-B         -> is this person behaving suspiciously?
  router        -> which eligible survey next?

Re-routing rules (after the client's redirect):
  COMPLETE                 stop
  TERMINATED / OVERQUOTA   next eligible survey, until attempts run out
  SECURITY_TERMINATED      stop (client fraud/quality terminate: /surveyterminate?...&type=security)
  SFW_BLOCKED              never routed

Project fields (email_automation.projects), all optional; absent = today's behaviour:
  qualification: {enabled, ageMin, ageMax, genders[], employment[], occupation[],
                  bank: [{id, qualifying[]}],          questions from the shared question bank
                  custom: [{id, text, options[], qualifying[]}]}   (legacy inline questions)
  routingEnabled: bool     may receive routed respondents
  routingPriority: int     lower = offered first

Question bank (email_automation.qualification_questions): reusable study questions
  {_id: "q_<id>", text, options[], active, createdAt, createdBy}. Create once, use in any
  project. Archived questions stay evaluable for projects that already use them.

Entry tracking (url_parameters.entryType): pid_link (panel / vendor link to one project),
  router_link (no pid), rerouted_prescreen, rerouted_country, rerouted_after_terminated /
  rerouted_after_overquota.

Switches (backend/.env):
  SURVEY_ROUTING_ENABLED   router links + re-routing after terminate / quota (default off)
  COUNTRY_ROUTING_ENABLED  IP country must match the project's country (default off)
  ROUTING_MAX_ATTEMPTS     surveys one respondent may be offered (default 3)
"""
import os
import re
import time
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from bson import ObjectId

# Fixed, reusable qualification questions. Age and gender come from the date of
# birth / gender the landing page already asks; these are the extra ones.
QUESTION_LIBRARY: List[Dict[str, Any]] = [
    {
        "id": "employment",
        "text": "Which best describes your current employment status?",
        "options": [
            {"value": "employed_full_time", "label": "Employed full-time"},
            {"value": "employed_part_time", "label": "Employed part-time"},
            {"value": "self_employed", "label": "Self-employed"},
            {"value": "unemployed", "label": "Not currently employed"},
            {"value": "student", "label": "Student"},
            {"value": "homemaker", "label": "Homemaker"},
            {"value": "retired", "label": "Retired"},
        ],
    },
    {
        "id": "occupation",
        "text": "Which industry do you mainly work in?",
        "options": [
            {"value": "healthcare", "label": "Healthcare"},
            {"value": "hospitality", "label": "Hospitality / food service"},
            {"value": "retail", "label": "Retail"},
            {"value": "security", "label": "Security"},
            {"value": "transport_logistics", "label": "Transport / logistics"},
            {"value": "manufacturing", "label": "Manufacturing"},
            {"value": "emergency_services", "label": "Emergency services"},
            {"value": "education", "label": "Education"},
            {"value": "it_technology", "label": "IT / technology"},
            {"value": "finance", "label": "Banking / finance"},
            {"value": "government", "label": "Government / public sector"},
            {"value": "construction", "label": "Construction"},
            {"value": "agriculture", "label": "Agriculture"},
            {"value": "other", "label": "Other"},
            {"value": "not_working", "label": "I don't work"},
        ],
    },
]
_LIBRARY = {q["id"]: q for q in QUESTION_LIBRARY}
_CUSTOM_ID = re.compile(r"^q_[A-Za-z0-9_]{3,40}$")

PII_CONSENT_VERSION = "2026-10-03b"
# Two separate purposes, two separate ticks (DPDP: consent must be specific and freely given).
VERIFY_CONSENT_TEXT = (
    "I agree that SurveyFieldwork may use my name, email and phone number to verify my "
    "participation in this survey and to contact me about it."
)
PANEL_CONSENT_TEXT = (
    "Optional: I'd like to join the SurveyFieldwork panel and be invited to future paid surveys. "
    "I can unsubscribe or ask for my data to be deleted at any time."
)
PII_CONSENT_TEXT = VERIFY_CONSENT_TEXT  # kept for callers of the old single-consent name


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def routing_enabled() -> bool:
    return _truthy(os.getenv("SURVEY_ROUTING_ENABLED"))


def country_routing_enabled() -> bool:
    return _truthy(os.getenv("COUNTRY_ROUTING_ENABLED"))


def max_attempts() -> int:
    try:
        return max(1, int(os.getenv("ROUTING_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


def privacy_policy_url() -> str:
    return os.getenv("SFW_PRIVACY_POLICY_URL", "https://surveyfieldwork.com/privacy-policy")


def norm_country(value: Any) -> str:
    value = str(value or "").strip().upper()
    return "UK" if value == "GB" else value


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip()) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------

_BANK_CACHE: Dict[str, Any] = {"until": 0.0, "bank": {}}


def new_question_id() -> str:
    return f"q_{ObjectId()}"


def clean_bank_question(raw: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = raw if isinstance(raw, dict) else {}
    text = str(raw.get("text") or "").strip()
    options = []
    for o in raw.get("options") or []:
        o = str(o).strip()[:120]
        if o and o not in options:
            options.append(o)
    if not text:
        return None, "Question text is required"
    if len(options) < 2:
        return None, "Give at least two answer options"
    return {"text": text[:300], "options": options[:20]}, ""


async def load_bank(projects_db, force: bool = False) -> Dict[str, Dict[str, Any]]:
    """All bank questions (incl. archived) by id, cached 60 s."""
    if not force and _BANK_CACHE["until"] > time.time():
        return _BANK_CACHE["bank"]
    docs = await projects_db["qualification_questions"].find({}).to_list(length=1000)
    bank = {str(d["_id"]): {"id": str(d["_id"]), "text": d.get("text", ""), "options": d.get("options") or [],
                            "active": d.get("active", True)} for d in docs}
    _BANK_CACHE.update(until=time.time() + 60, bank=bank)
    return bank


def invalidate_bank() -> None:
    _BANK_CACHE["until"] = 0.0


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------

def project_qualification(project: Optional[Dict[str, Any]], bank: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalised qualification config; defensive because projects are free-form documents.
    Bank references are resolved to {id, text, options, qualifying} like inline questions.
    """
    raw = (project or {}).get("qualification") or {}
    if not isinstance(raw, dict):
        raw = {}
    custom = []
    for ref in raw.get("bank") or []:
        if not isinstance(ref, dict):
            continue
        question = (bank or {}).get(str(ref.get("id") or ""))
        if not question:
            continue  # unknown id: ignored rather than failing everyone
        qualifying = [o for o in _str_list(ref.get("qualifying")) if o in question["options"]]
        if qualifying:
            custom.append({"id": question["id"], "text": question["text"],
                           "options": list(question["options"]), "qualifying": qualifying})
    for q in raw.get("custom") or []:
        if not isinstance(q, dict):
            continue
        qid, text = str(q.get("id") or ""), str(q.get("text") or "").strip()
        options = _str_list(q.get("options"))
        qualifying = [o for o in _str_list(q.get("qualifying")) if o in options]
        if _CUSTOM_ID.match(qid) and text and options and qualifying:
            custom.append({"id": qid, "text": text[:300], "options": options[:20], "qualifying": qualifying})
    return {
        "enabled": bool(raw.get("enabled")),
        "ageMin": _int_or_none(raw.get("ageMin")),
        "ageMax": _int_or_none(raw.get("ageMax")),
        "genders": [g for g in _str_list(raw.get("genders")) if g in ("m", "f", "o")],
        "employment": [v for v in _str_list(raw.get("employment"))
                       if v in {o["value"] for o in _LIBRARY["employment"]["options"]}],
        "occupation": [v for v in _str_list(raw.get("occupation"))
                       if v in {o["value"] for o in _LIBRARY["occupation"]["options"]}],
        "custom": custom,
    }


def questions_for(projects: List[Dict[str, Any]], bank: Optional[Dict[str, Any]] = None,
                  limit: int = 8) -> List[Dict[str, Any]]:
    """Landing-page questions the given projects' enabled criteria need (deduplicated)."""
    out, seen = [], set()
    for project in projects:
        qual = project_qualification(project, bank)
        if not qual["enabled"]:
            continue
        for lib_id in ("employment", "occupation"):
            if qual[lib_id] and lib_id not in seen:
                seen.add(lib_id)
                out.append({"id": lib_id, "text": _LIBRARY[lib_id]["text"], "options": _LIBRARY[lib_id]["options"]})
        for q in qual["custom"]:
            if q["id"] not in seen:
                seen.add(q["id"])
                out.append({"id": q["id"], "text": q["text"],
                            "options": [{"value": o, "label": o} for o in q["options"]]})
    return out[:limit]


def age_on(profile: Dict[str, Any], today: Optional[date] = None) -> Optional[int]:
    try:
        born = date(int(profile.get("birthday_year")), int(profile.get("birthday_month")),
                    int(profile.get("birthday_day")))
    except (TypeError, ValueError):
        return None
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def evaluate(project: Dict[str, Any], answers: Dict[str, Any], profile: Dict[str, Any],
             bank: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[str]]:
    """(qualifies, reasons it failed). A project without enabled criteria always qualifies."""
    qual = project_qualification(project, bank)
    if not qual["enabled"]:
        return True, []
    answers = answers or {}
    reasons = []
    if qual["ageMin"] is not None or qual["ageMax"] is not None:
        age = age_on(profile or {})
        if age is None:
            reasons.append("age_missing")
        elif (qual["ageMin"] is not None and age < qual["ageMin"]) or (qual["ageMax"] is not None and age > qual["ageMax"]):
            reasons.append("age")
    if qual["genders"]:
        gender = str((profile or {}).get("gender") or "").lower()[:1]
        if gender not in qual["genders"]:
            reasons.append("gender")
    for lib_id in ("employment", "occupation"):
        if qual[lib_id]:
            answer = str(answers.get(lib_id) or "")
            if not answer:
                reasons.append(f"{lib_id}_missing")
            elif answer not in qual[lib_id]:
                reasons.append(lib_id)
    for q in qual["custom"]:
        answer = str(answers.get(q["id"]) or "")
        if not answer:
            reasons.append(f"{q['id']}_missing")
        elif answer not in q["qualifying"]:
            reasons.append(q["id"])
    return not reasons, reasons


def clean_answers(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:20]:
        key = str(key)
        if key in _LIBRARY or _CUSTOM_ID.match(key):
            out[key] = str(value or "").strip()[:200]
    return out


# ---------------------------------------------------------------------------
# Paid Ads PII
# ---------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
_PHONE = re.compile(r"^\+?[0-9 ()-]{7,20}$")


def is_paid_ads(vendor: Optional[Dict[str, Any]], traffic_source: Optional[str]) -> bool:
    from services.ad_tracking import is_ad_platform
    if vendor and str(vendor.get("vendorType") or "").strip().lower() == "paid ads":
        return True
    return is_ad_platform(traffic_source)


def clean_pii(raw: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    (pii fields to store, error). Name, email, phone and the verification consent are
    required; joining the panel is a separate, optional consent. Only panel joiners get
    `email` (which the daily panelist-lead promotion turns into a panel invite);
    everyone's address is kept as `contactEmail` for verification.
    """
    raw = raw if isinstance(raw, dict) else {}
    first = str(raw.get("firstName") or "").strip()[:80]
    last = str(raw.get("lastName") or "").strip()[:80]
    email = str(raw.get("email") or "").strip().lower()[:254]
    phone = str(raw.get("phone") or "").strip()[:20]
    if not first or not last:
        return None, "Please enter your first and last name."
    if not _EMAIL.match(email):
        return None, "Please enter a valid email address."
    if not _PHONE.match(phone):
        return None, "Please enter a valid phone number."
    if raw.get("verifyConsent") is not True and raw.get("consent") is not True:
        return None, "Please agree to the use of your details for verification to continue."
    now = datetime.utcnow()
    joins_panel = raw.get("panelConsent") is True
    fields = {
        "firstName": first, "lastName": last, "contactEmail": email, "phone": phone,
        "verifyConsent": {"given": True, "at": now, "version": PII_CONSENT_VERSION,
                          "text": VERIFY_CONSENT_TEXT, "policyUrl": privacy_policy_url()},
        "panelConsent": {"given": joins_panel, "at": now, "version": PII_CONSENT_VERSION,
                         "text": PANEL_CONSENT_TEXT, "policyUrl": privacy_policy_url()},
    }
    if joins_panel:
        fields["email"] = email  # picked up by the daily panelist-lead promotion (double opt-in invite)
    return fields, ""


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_FULL_CACHE: Dict[str, Tuple[float, bool]] = {}


async def is_full(url_col, project: Dict[str, Any]) -> bool:
    """Project has reached totalCompletesRequired (cached 60 s)."""
    target = _int_or_none(project.get("totalCompletesRequired"))
    survey_no = str(project.get("surveyNo") or "")
    if not target or not survey_no:
        return False
    cached = _FULL_CACHE.get(survey_no)
    if cached and cached[0] > time.time():
        return cached[1]
    completes = await url_col.count_documents(
        {"params.pid": survey_no, "params.api": "false", "status": "COMPLETE"}, limit=target)
    full = completes >= target
    _FULL_CACHE[survey_no] = (time.time() + 60, full)
    return full


async def routable_projects(projects_col, country: str) -> List[Dict[str, Any]]:
    """Live, routing-enabled projects with a live link for this country, in priority order."""
    query: Dict[str, Any] = {"is_deleted": {"$ne": True}, "routingEnabled": True}
    docs = await projects_col.find(query).to_list(length=500)
    out = []
    for p in docs:
        if str(p.get("projectStatus") or "").strip().lower() != "live":
            continue
        if not (p.get("liveLink") or p.get("clientLink")):
            continue
        if country and norm_country(p.get("countryCode")) and norm_country(p.get("countryCode")) != country:
            continue
        out.append(p)
    out.sort(key=lambda p: (_int_or_none(p.get("routingPriority")) or 1000, str(p.get("createdAt") or "")))
    return out


async def _already_in(url_col, record: Dict[str, Any], survey_no: str) -> bool:
    """Has this person (our cookie / _fbp / vendor rid) entered this survey before?"""
    from services.respondent_quality import _strong_key_clauses
    clauses = _strong_key_clauses(record)
    if not clauses:
        return False
    return bool(await url_col.find_one(
        {"assignedSurveyId": survey_no, "_id": {"$ne": record.get("_id")}, "$or": clauses}, {"_id": 1}))


async def eligible_projects(
    url_col, projects_col, record: Dict[str, Any], country: str, exclude: List[str],
) -> List[Tuple[Dict[str, Any], List[str]]]:
    """Eligible routable projects for this respondent, in priority order."""
    answers = record.get("qualificationAnswers") or {}
    profile = record.get("profilingData") or {}
    bank = await load_bank(projects_col.database)
    out = []
    for project in await routable_projects(projects_col, country):
        survey_no = str(project.get("surveyNo") or "")
        if not survey_no or survey_no in exclude:
            continue
        ok, _ = evaluate(project, answers, profile, bank)
        if not ok or await is_full(url_col, project) or await _already_in(url_col, record, survey_no):
            continue
        out.append(project)
    return out


# ---------------------------------------------------------------------------
# Sessions and attempts
# ---------------------------------------------------------------------------

_COPY_FIELDS = (
    "vendorId", "respondentId", "countryCode", "geoIpCountry", "cfIpCountry", "cfIpTor", "clientIp",
    "ipSource", "userAgent", "deviceFingerprint", "panelId", "profilingData", "qualificationAnswers",
    "traffic_source", "adTracking", "sfwVisitorId", "sfwSignals", "sfwScore", "sfwBand", "sfwFlags",
    "sfwQ", "sfwH", "firstName", "lastName", "phone", "contactEmail", "verifyConsent", "panelConsent",
    "paidAds", "routingSessionId",
)


async def start_session(db, record: Dict[str, Any], country: str) -> ObjectId:
    session_id = ObjectId()
    await db["routing_sessions"].insert_one({
        "_id": session_id, "createdAt": datetime.utcnow(), "country": country,
        "vendorId": record.get("vendorId"), "respondentId": record.get("respondentId"),
        "entryPid": (record.get("params") or {}).get("pid"),
        "attempts": [], "tried": [], "final": None,
    })
    return session_id


async def record_attempt(db, session_id, rid: str, survey_no: str, reason: str) -> None:
    await db["routing_sessions"].update_one({"_id": session_id}, {
        "$push": {"attempts": {"rid": rid, "surveyNo": survey_no, "reason": reason,
                               "at": datetime.utcnow(), "outcome": None}},
        "$addToSet": {"tried": survey_no},
    })


async def close_attempt(db, session_id, rid: str, outcome: str, final: bool) -> None:
    update: Dict[str, Any] = {"$set": {"attempts.$[a].outcome": outcome, "attempts.$[a].closedAt": datetime.utcnow()}}
    if final:
        update["$set"]["final"] = {"outcome": outcome, "rid": rid, "at": datetime.utcnow()}
    await db["routing_sessions"].update_one({"_id": session_id}, update, array_filters=[{"a.rid": rid}])


BuildLink = Callable[[Dict[str, Any], str], Awaitable[str]]


async def create_attempt(url_col, base: Dict[str, Any], project: Dict[str, Any], build_link: BuildLink,
                         attempt_no: int, routed_from: str, entry_type: str = "rerouted") -> Tuple[str, str]:
    """New traffic record (new RID) for the next survey, copying the respondent's identity."""
    survey_no = str(project["surveyNo"])
    doc = {k: base[k] for k in _COPY_FIELDS if k in base}
    params = dict(base.get("params") or {})
    params.update({"pid": survey_no, "api": "false"})
    now = datetime.utcnow()
    doc.update({
        "_id": ObjectId(), "params": params, "status": "INCOMPLETE", "createdAt": now, "updatedAt": now,
        "timestamp": now.isoformat(), "surveySource": "PROJECT", "assignedSurveyId": survey_no,
        "projectId": str(project.get("_id")), "routingAttempt": attempt_no, "routedFrom": routed_from,
        "entryType": entry_type, "url": base.get("url"),
    })
    rid = str(doc["_id"])
    doc["redirectUrl"] = await build_link(project, rid)
    await url_col.insert_one(doc)
    return rid, doc["redirectUrl"]


async def next_attempt(url_col, projects_col, record: Dict[str, Any], outcome: str,
                       build_link: BuildLink) -> Optional[str]:
    """
    After a client terminate / quota-full: the next eligible survey's entry link,
    or None when routing is off, attempts are used up, or nothing else fits.
    """
    session_id = record.get("routingSessionId")
    db = url_col.database
    if not session_id:
        return None
    rid = str(record["_id"])
    reroutable = outcome in ("TERMINATED", "OVERQUOTA") and routing_enabled() and record.get("sfwBand") != "block"
    session = await db["routing_sessions"].find_one({"_id": session_id}) if reroutable else None
    attempts = len((session or {}).get("attempts") or [])
    if not session or attempts >= max_attempts():
        await close_attempt(db, session_id, rid, outcome, final=True)
        return None
    await close_attempt(db, session_id, rid, outcome, final=False)
    country = session.get("country") or ""
    candidates = await eligible_projects(url_col, projects_col, record, country, list(session.get("tried") or []))
    if not candidates:
        await close_attempt(db, session_id, rid, outcome, final=True)
        return None
    project = candidates[0]
    new_rid, link = await create_attempt(url_col, record, project, build_link, attempts + 1,
                                         str(record.get("assignedSurveyId")), f"rerouted_after_{outcome.lower()}")
    await record_attempt(db, session_id, new_rid, str(project["surveyNo"]), f"after_{outcome.lower()}")
    return link
