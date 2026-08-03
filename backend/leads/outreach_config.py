"""
OUTREACH CONFIGURATION
======================
Single source of truth for bucket definitions, thresholds, model IDs and send
caps. Nothing downstream hardcodes these values.

Every setting can be overridden by environment variable, so staging and
production differ by config rather than by code.

BUCKET DEFINITIONS — PROVENANCE
-------------------------------
These were NOT invented. Each bucket maps 1:1 onto an ICP already defined in
`icp_config.DEFAULT_ICPS`, and onto the basket vocabulary already used by
`canonical_ingestion.compute_icp_basket` and `_auto_enroll_in_outreach`:

    bucket              ICP slug           basket   campaign 'business'
    SFW                 survey_fieldwork   A        sfw
    COGENTIX_RESEARCH   cogentix           B        cogentix
    BIM                 bimwave            C        bimwave

`description` and `ideal_buyer` below are derived from each ICP's own
`description` + `designations`. Confirm the wording matches how you actually
pitch each service line — the classifier's accuracy depends on it.
"""

import os
from typing import Any, Dict, List, Optional


def _env_str(name: str, default: str) -> str:
    return os.getenv(name) or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


# ============================================================
# BUCKETS
# ============================================================

REVIEW_BUCKET = "REVIEW"
REJECT_BUCKET = "REJECT"

# Sentinel for pitch copy that has not been written yet. The email validator
# treats any generated body containing placeholder text as invalid, so leaving
# these in place makes --send refuse rather than mail out filler.
PITCH_PLACEHOLDER = "[TODO: service pitch not yet supplied]"

BUCKETS: Dict[str, Dict[str, Any]] = {
    "SFW": {
        "label": "Survey Fieldwork",
        "icp_slug": "survey_fieldwork",
        "basket": "A",
        "business": "sfw",
        "storage_dir": "outreach/SFW",
        "description": (
            "Market research and survey panel provider — programmed surveys, "
            "panel sample and fieldwork execution for global mid-market "
            "researchers."
        ),
        "ideal_buyer": (
            "Research and insights buyers who commission or run primary "
            "fieldwork: Head of Insights, Research Director, VP Market "
            "Research, Panel Manager, Primary Research Manager — at research "
            "agencies and at brands with in-house research teams."
        ),
        # REPLACE ME. What you actually offer, why it beats the incumbent, and
        # any proof point worth stating. Until this is real, --send refuses.
        "pitch": PITCH_PLACEHOLDER,
    },
    "COGENTIX_RESEARCH": {
        "label": "Cogentix Research",
        "icp_slug": "cogentix",
        "basket": "B",
        "business": "cogentix",
        "storage_dir": "outreach/cogentix_research",
        "description": (
            "AI-native consumer intelligence platform — brand tracking, "
            "concept testing and consumer insight for global mid-market brands."
        ),
        "ideal_buyer": (
            "Brand and marketing decision-makers who own consumer "
            "understanding: CMO, VP Marketing, Marketing Director, Head of "
            "Brand, Director of Consumer Insights — at FMCG, retail, consumer "
            "goods and consumer electronics companies."
        ),
        # REPLACE ME — see note on the SFW bucket above.
        "pitch": PITCH_PLACEHOLDER,
    },
    "BIM": {
        "label": "BIMwave",
        "icp_slug": "bimwave",
        "basket": "C",
        "business": "bimwave",
        "storage_dir": "outreach/BIM",
        "description": (
            "BIM outsourcing for AEC firms — modelling, coordination and "
            "ISO 19650 compliant digital delivery."
        ),
        "ideal_buyer": (
            "BIM, CAD and construction-technology decision makers: BIM "
            "Manager, BIM Coordinator, Head of BIM, CAD Manager, Digital "
            "Delivery Manager, Design Manager, Technical Director — at "
            "architecture, engineering, construction and infrastructure firms."
        ),
        # REPLACE ME — see note on the SFW bucket above.
        "pitch": PITCH_PLACEHOLDER,
    },
}


def buckets_missing_pitch() -> List[str]:
    """Buckets whose pitch copy is still a placeholder. Blocks --send."""
    return [k for k, c in BUCKETS.items()
            if PITCH_PLACEHOLDER in (c.get("pitch") or "")]

VALID_BUCKETS = tuple(BUCKETS.keys())
ALL_CLASSIFIER_OUTPUTS = VALID_BUCKETS + (REJECT_BUCKET,)


def bucket_for_basket(basket: str) -> Optional[str]:
    """Reverse lookup: basket code (A/B/C) -> bucket key."""
    for key, cfg in BUCKETS.items():
        if cfg["basket"] == basket:
            return key
    return None


def bucket_for_icp(slug: str) -> Optional[str]:
    """Reverse lookup: ICP slug -> bucket key."""
    for key, cfg in BUCKETS.items():
        if cfg["icp_slug"] == slug:
            return key
    return None


# ============================================================
# CLASSIFICATION
# ============================================================

# Below this, a lead is escalated to the smart model; if it is still below
# after escalation, it goes to the review folder instead of a bucket.
CONFIDENCE_THRESHOLD = _env_float("BUCKET_CONFIDENCE_THRESHOLD", 0.7)

# Roles, never model IDs — only bedrock_client.py may name a model.
CLASSIFIER_ROLE_FIRST_PASS = "cheap"
CLASSIFIER_ROLE_ESCALATION = "smart"

CLASSIFIER_MAX_TOKENS = _env_int("BUCKET_CLASSIFIER_MAX_TOKENS", 512)
# Low temperature: classification should be stable, not creative.
CLASSIFIER_TEMPERATURE = _env_float("BUCKET_CLASSIFIER_TEMPERATURE", 0.0)

# Max leads classified per run, to bound spend.
CLASSIFY_DAILY_CAP = _env_int("BUCKET_CLASSIFY_DAILY_CAP", 500)


# ============================================================
# EXCLUSIONS (cheap filter, applied before any model call)
# ============================================================
# Substring matched case-insensitively against the job title. Kept explicit
# and readable — this list is the cheapest quality lever in the pipeline.

EXCLUDED_TITLE_TERMS: List[str] = [
    # Students / early career — no budget
    "student", "intern", "internship", "trainee", "fresher", "apprentice",
    "graduate trainee", "management trainee", "articleship",

    # Job seekers
    "seeking opportunities", "seeking new opportunities", "open to work",
    "looking for opportunities", "actively seeking", "job seeker",
    "aspiring", "ex-", "unemployed",

    # Academia
    "professor", "lecturer", "phd scholar", "research scholar",
    "postdoctoral", "post-doctoral", "teaching assistant", "dean",
    "assistant professor", "associate professor", "academic",

    # HR / recruiting — not our buyer
    "recruiter", "recruitment", "talent acquisition", "hr executive",
    "hr manager", "hr generalist", "human resources", "staffing",
    "headhunter", "talent partner", "people operations",

    # Vendor-side sales/BD — they sell to us, not buy
    "business development executive", "business development manager",
    "sales executive", "sales representative", "account executive",
    "inside sales", "sales development representative", "sdr", "bdr",
    "telecaller", "telesales", "lead generation specialist",

    # Retired / inactive
    "retired", "former", "ex employee", "emeritus",

    # Freelance/consultant with no org buying authority
    "freelancer", "self employed", "self-employed", "independent consultant",
]

# Titles too generic to imply buying authority on their own. Only excluded for
# a SHORT title with no seniority marker and no supporting industry/seniority
# field — see bucket_classifier.check_exclusion.
GENERIC_TITLE_TERMS: List[str] = [
    "consultant", "analyst", "associate", "executive", "officer",
    "coordinator", "assistant", "specialist", "administrator",
    "engineer", "developer", "designer",
]

# Unambiguous seniority signals. A title carrying any of these is never
# excluded for a generic term, and is exempt from the soft exclusions below.
# Rationale: "Chief Marketing Officer" contains "officer", "Assistant Vice
# President" contains "assistant", "VP Student Council" contains "student".
SENIOR_TITLE_MARKERS: List[str] = [
    "vp", "svp", "evp", "avp", "vice president", "president",
    "chief", "ceo", "cto", "cfo", "coo", "cmo", "cro", "cio", "chro", "cpo",
    "c-suite", "c-level", "head", "director", "md", "managing director",
    "partner", "principal", "owner", "founder", "co-founder", "proprietor",
]

# Terms that disqualify only when the person is NOT senior. A "VP Student
# Council" is still a VP; a "Student" is not.
#
# HR / recruiting is deliberately NOT here: a Head of Human Resources or VP
# Talent Acquisition is senior but still never buys market research or BIM,
# so those stay hard exclusions at every level.
SOFT_EXCLUSION_TERMS = {
    "professor", "academic", "student", "aspiring", "freelancer",
    "independent consultant", "self employed", "self-employed",
    "former", "ex-", "retired",
}

# Past-tense markers only disqualify when they LEAD the title. "Former CTO"
# means they have left; "Market Research Analyst | Former Amazon" describes a
# previous employer and says nothing about their current standing.
POSITIONAL_EXCLUSION_TERMS = {"former", "ex-", "retired", "ex"}

# Titles longer than this are LinkedIn headlines, not job titles, and are not
# judged by the generic-term rule.
MAX_CLEAN_TITLE_WORDS = 6


# ============================================================
# STORAGE
# ============================================================

OUTREACH_ROOT = _env_str("OUTREACH_ROOT", "outreach")
REVIEW_DIR = os.path.join(OUTREACH_ROOT, "review")
PREVIEW_DIR = os.path.join(OUTREACH_ROOT, "preview")


def storage_dir_for(bucket: str) -> str:
    """Filesystem location for a bucket's artifacts."""
    cfg = BUCKETS.get(bucket)
    if not cfg:
        return REVIEW_DIR
    return cfg["storage_dir"]


# ============================================================
# COLD OUTREACH QUALIFICATION (Task 5)
# ============================================================

# Generic mailbox prefixes that are never a person.
GENERIC_EMAIL_PREFIXES = {
    "info", "sales", "support", "admin", "contact", "hello", "help",
    "enquiry", "enquiries", "inquiry", "office", "team", "mail", "no-reply",
    "noreply", "donotreply", "marketing", "careers", "jobs", "hr",
    "webmaster", "postmaster", "abuse", "billing", "accounts",
}

# Minimum ICP score (title 3 / industry 2 / country 2 / seniority 1) to be
# eligible for cold outreach. Matches icp_config's ">3" rule.
MIN_ICP_SCORE = _env_int("OUTREACH_MIN_ICP_SCORE", 4)

# Only fully-developed person records get cold-emailed.
REQUIRED_LEAD_BRACKET = _env_str("OUTREACH_REQUIRED_BRACKET", "contact")


# ============================================================
# SENDING (Task 6)
# ============================================================

SEND_DAILY_CAP = _env_int("OUTREACH_SEND_DAILY_CAP", 200)
SEND_HOURLY_CAP = _env_int("OUTREACH_SEND_HOURLY_CAP", 25)
SEND_MIN_SPACING_SECONDS = _env_int("OUTREACH_SEND_MIN_SPACING", 45)
SEND_MAX_SPACING_SECONDS = _env_int("OUTREACH_SEND_MAX_SPACING", 180)

SEND_TRANSPORT = _env_str("OUTREACH_TRANSPORT", "ses")  # 'ses' | 'smtp'

# CAN-SPAM / GDPR: a physical postal address is legally required in every
# commercial email. Deliberately has no default — sending must fail loudly
# rather than ship a non-compliant footer.
SENDER_POSTAL_ADDRESS = os.getenv("OUTREACH_SENDER_POSTAL_ADDRESS", "")
SENDER_NAME = _env_str("OUTREACH_SENDER_NAME", "")
SENDER_EMAIL = _env_str("OUTREACH_SENDER_EMAIL", "")
UNSUBSCRIBE_BASE_URL = _env_str("OUTREACH_UNSUBSCRIBE_URL", "")


def config_summary() -> Dict[str, Any]:
    """Effective configuration, for logging at startup."""
    return {
        "buckets": list(VALID_BUCKETS),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "classifier_roles": [CLASSIFIER_ROLE_FIRST_PASS, CLASSIFIER_ROLE_ESCALATION],
        "classify_daily_cap": CLASSIFY_DAILY_CAP,
        "min_icp_score": MIN_ICP_SCORE,
        "required_bracket": REQUIRED_LEAD_BRACKET,
        "send_daily_cap": SEND_DAILY_CAP,
        "send_hourly_cap": SEND_HOURLY_CAP,
        "transport": SEND_TRANSPORT,
        "excluded_terms": len(EXCLUDED_TITLE_TERMS),
    }
