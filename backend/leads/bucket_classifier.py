"""
BUCKET CLASSIFIER
=================
Assigns every qualified lead to exactly one outreach bucket — SFW,
COGENTIX_RESEARCH or BIM — or rejects it.

Pipeline per lead:

    1. Cheap exclusion filter (no model call)   -> REJECT
    2. Bedrock classification, strict JSON      -> bucket + confidence + reason
    3. Confidence gate                          -> below threshold goes to REVIEW
    4. Persist bucket/confidence/reason, and map onto the existing
       `classification_basket` (A/B/C) so the outreach auto-enrollment
       machinery in canonical_ingestion keeps working unchanged.

The exclusion filter runs first specifically so obviously-unqualified leads
(students, recruiters, job seekers) never cost a model call.

Model contract — the response must be exactly:

    {"bucket": "SFW"|"COGENTIX_RESEARCH"|"BIM"|"REJECT",
     "confidence": 0.0-1.0,
     "reason": "..."}

Anything else is treated as a parse failure and routed to REVIEW rather than
guessed at.

Usage:
    python -m leads.bucket_classifier --dry-run --limit 50
"""

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

from bson import ObjectId
from pymongo import MongoClient


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


try:
    from .outreach_config import (
        BUCKETS,
        CLASSIFIER_MAX_TOKENS,
        CLASSIFIER_ROLE_ESCALATION,
        CLASSIFIER_ROLE_FIRST_PASS,
        CLASSIFIER_TEMPERATURE,
        CLASSIFY_DAILY_CAP,
        CONFIDENCE_THRESHOLD,
        EXCLUDED_TITLE_TERMS,
        GENERIC_TITLE_TERMS,
        MAX_CLEAN_TITLE_WORDS,
        POSITIONAL_EXCLUSION_TERMS,
        REJECT_BUCKET,
        REVIEW_BUCKET,
        SENIOR_TITLE_MARKERS,
        SOFT_EXCLUSION_TERMS,
        VALID_BUCKETS,
        config_summary,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from leads.outreach_config import (
        BUCKETS,
        CLASSIFIER_MAX_TOKENS,
        CLASSIFIER_ROLE_ESCALATION,
        CLASSIFIER_ROLE_FIRST_PASS,
        CLASSIFIER_TEMPERATURE,
        CLASSIFY_DAILY_CAP,
        CONFIDENCE_THRESHOLD,
        EXCLUDED_TITLE_TERMS,
        GENERIC_TITLE_TERMS,
        MAX_CLEAN_TITLE_WORDS,
        POSITIONAL_EXCLUSION_TERMS,
        REJECT_BUCKET,
        REVIEW_BUCKET,
        SENIOR_TITLE_MARKERS,
        SOFT_EXCLUSION_TERMS,
        VALID_BUCKETS,
        config_summary,
    )

logger = logging.getLogger("bucket_classifier")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
_client = _get_pooled_client()
_db = _client["email_automation"]
leads_raw = _db["leads_raw"]


# ============================================================
# CHEAP EXCLUSION FILTER
# ============================================================

def _contains_term(text: str, term: str) -> bool:
    """
    Word-boundary match. Plain substring matching is unsafe here: 'intern'
    matches 'International', 'sdr' matches inside acronyms, and so on.
    """
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def has_senior_marker(title: str) -> bool:
    """
    True when the title carries an unambiguous seniority signal. Such a lead is
    never excluded for a generic term — 'Chief Marketing Officer' contains
    'officer', 'Assistant Vice President' contains 'assistant'.
    """
    return any(_contains_term(title, m) for m in SENIOR_TITLE_MARKERS)


def check_exclusion(lead: Dict[str, Any]) -> Optional[str]:
    """
    Cheap pre-AI filter. Returns a rejection reason, or None if the lead should
    proceed to classification.

    Note these titles are usually LinkedIn *headlines* ("Sr. Analyst @ Acme |
    Ex-Nielsen | Speaker"), not clean job titles, so matching is deliberately
    conservative: word boundaries only, and seniority always wins.
    """
    title = (lead.get("title") or "").lower().strip()
    if not title:
        return "no job title"

    senior = has_senior_marker(title)

    for term in EXCLUDED_TITLE_TERMS:
        if not _contains_term(title, term):
            continue

        # Past-tense markers disqualify only when they lead the title.
        if term in POSITIONAL_EXCLUSION_TERMS:
            if title.startswith(term):
                return f"excluded title term: {term} (leading)"
            continue

        # A senior person whose headline merely mentions a soft term (e.g.
        # "MD ... Professor", "VP Student Council") is not disqualified.
        if senior and term in SOFT_EXCLUSION_TERMS:
            continue

        return f"excluded title term: {term}"

    # Generic titles: only disqualifying for a short, clean title with no
    # seniority marker and no supporting industry/seniority field. Long
    # headlines are left for the model to judge.
    if not senior:
        has_support = bool(
            lead.get("company_industry") or lead.get("industry")
            or lead.get("seniority_level")
        )
        is_clean_title = len(title.split()) <= MAX_CLEAN_TITLE_WORDS
        if not has_support and is_clean_title:
            for term in GENERIC_TITLE_TERMS:
                if _contains_term(title, term):
                    return f"generic title with no supporting signal: {term}"

    return None


# ============================================================
# PROMPT
# ============================================================

def _bucket_briefing() -> str:
    lines = []
    for key, cfg in BUCKETS.items():
        lines.append(
            f'- "{key}" ({cfg["label"]})\n'
            f'    What we sell: {cfg["description"]}\n'
            f'    Ideal buyer:  {cfg["ideal_buyer"]}'
        )
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are a B2B lead qualification analyst. You assign each lead to exactly "
    "one service line, or reject it. You are conservative: when the evidence is "
    "thin you lower your confidence rather than guessing. You return only valid "
    "JSON."
)

USER_PROMPT = """Assign this lead to exactly one bucket, or reject it.

BUCKETS
{briefing}

LEAD
  Name:      {name}
  Title:     {title}
  Company:   {company}
  Industry:  {industry}
  Country:   {country}
  Seniority: {seniority}
  Profile snippet: {snippet}

REJECT the lead ("bucket": "REJECT") if the person is any of the following,
regardless of other signals:
  - a student, intern, fresher, trainee or apprentice
  - a job seeker (profile says "seeking opportunities", "open to work", etc.)
  - an academic: professor, lecturer, researcher at a university
  - HR, recruiting, talent acquisition or staffing
  - sales or business development AT A VENDOR selling services (they sell to
    us, they do not buy from us)
  - retired, former, or no longer at the company
  - holding a generic title with no buying authority and no other signal
    supporting a fit

Set "confidence" honestly:
  - 0.9-1.0  title and industry both clearly match one bucket
  - 0.7-0.9  strong signal from one field, consistent with the bucket
  - 0.4-0.7  plausible but thin evidence; missing industry or seniority
  - 0.0-0.4  guessing

Return JSON in exactly this shape and nothing else:
{{"bucket": "SFW" | "COGENTIX_RESEARCH" | "BIM" | "REJECT",
  "confidence": 0.0,
  "reason": "one short sentence"}}"""


def build_prompt(lead: Dict[str, Any]) -> str:
    def _f(*keys: str) -> str:
        for k in keys:
            v = lead.get(k)
            if v:
                return str(v).strip()
        return "unknown"

    snippet = (lead.get("snippet") or "").strip()
    if len(snippet) > 400:
        snippet = snippet[:400] + "..."

    return USER_PROMPT.format(
        briefing=_bucket_briefing(),
        name=_f("name", "first_name"),
        title=_f("title", "job_title"),
        company=_f("company", "company_name"),
        industry=_f("company_industry", "industry"),
        country=_f("country", "location", "company_headquarters"),
        seniority=_f("seniority_level"),
        snippet=snippet or "none",
    )


# ============================================================
# RESULT VALIDATION
# ============================================================

def validate_result(data: Optional[Dict[str, Any]]) -> Tuple[str, float, str]:
    """
    Coerce a model response into (bucket, confidence, reason).

    Any contract violation — missing keys, unknown bucket, non-numeric or
    out-of-range confidence — routes to REVIEW rather than being guessed at.
    """
    if not isinstance(data, dict):
        return REVIEW_BUCKET, 0.0, "model response was not a JSON object"

    bucket = data.get("bucket")
    if not isinstance(bucket, str):
        return REVIEW_BUCKET, 0.0, "missing 'bucket' field"
    bucket = bucket.strip().upper()

    if bucket not in VALID_BUCKETS and bucket != REJECT_BUCKET:
        return REVIEW_BUCKET, 0.0, f"unknown bucket {bucket!r}"

    raw_conf = data.get("confidence")
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError):
        return REVIEW_BUCKET, 0.0, "confidence was not a number"

    if not (0.0 <= confidence <= 1.0):
        return REVIEW_BUCKET, 0.0, f"confidence {confidence} out of range"

    reason = str(data.get("reason") or "").strip() or "no reason given"
    return bucket, confidence, reason


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_lead(lead: Dict[str, Any],
                  threshold: float = CONFIDENCE_THRESHOLD) -> Dict[str, Any]:
    """
    Classify one lead. Always returns a dict with bucket/confidence/reason/
    method — never raises.
    """
    lead_id = str(lead.get("_id", "?"))

    # --- Step 1: cheap exclusion -------------------------------------
    excluded = check_exclusion(lead)
    if excluded:
        logger.info("lead=%s bucket=REJECT method=exclusion reason=%s",
                    lead_id, excluded)
        return {"bucket": REJECT_BUCKET, "confidence": 1.0,
                "reason": excluded, "method": "exclusion_filter"}

    # --- Step 2: first pass on the cheap model -------------------------
    prompt = build_prompt(lead)
    bucket, confidence, reason, error = _classify_with(
        CLASSIFIER_ROLE_FIRST_PASS, prompt, lead_id)
    if error:
        return {"bucket": REVIEW_BUCKET, "confidence": 0.0,
                "reason": error, "method": "error"}

    if bucket in VALID_BUCKETS and confidence >= threshold:
        logger.info("lead=%s bucket=%s confidence=%.2f method=cheap",
                    lead_id, bucket, confidence)
        return {"bucket": bucket, "confidence": confidence,
                "reason": reason, "method": "cheap"}

    if bucket == REJECT_BUCKET:
        logger.info("lead=%s bucket=REJECT confidence=%.2f method=cheap",
                    lead_id, confidence)
        return {"bucket": bucket, "confidence": confidence,
                "reason": reason, "method": "cheap"}

    # --- Step 3: escalate borderline leads to the smart model ----------
    # Unless both roles resolve to the same model, which they do under the
    # Qwen-only policy. Re-asking one model the same prompt at temperature 0
    # returns the same answer, so the escalation would burn a second call and
    # land on exactly this REVIEW outcome anyway. Skip straight to it.
    if _roles_share_a_model():
        logger.info(
            "lead=%s bucket=REVIEW (proposed=%s confidence=%.2f threshold=%.2f) "
            "— escalation skipped, cheap and smart resolve to the same model",
            lead_id, bucket, confidence, threshold)
        return {"bucket": REVIEW_BUCKET, "confidence": confidence,
                "reason": f"low confidence, no stronger model to escalate to: {reason}",
                "method": "low_confidence_no_escalation",
                "proposed_bucket": bucket}

    logger.info("lead=%s cheap pass inconclusive (bucket=%s confidence=%.2f) "
                "— escalating to smart model", lead_id, bucket, confidence)

    smart_bucket, smart_confidence, smart_reason, smart_error = _classify_with(
        CLASSIFIER_ROLE_ESCALATION, prompt, lead_id)

    if smart_error:
        return {"bucket": REVIEW_BUCKET, "confidence": confidence,
                "reason": f"escalation failed: {smart_error}",
                "method": "escalation_error", "proposed_bucket": bucket}

    if smart_bucket in VALID_BUCKETS and smart_confidence >= threshold:
        logger.info("lead=%s bucket=%s confidence=%.2f method=smart_escalation",
                    lead_id, smart_bucket, smart_confidence)
        return {"bucket": smart_bucket, "confidence": smart_confidence,
                "reason": smart_reason, "method": "smart_escalation"}

    if smart_bucket == REJECT_BUCKET:
        logger.info("lead=%s bucket=REJECT confidence=%.2f method=smart_escalation",
                    lead_id, smart_confidence)
        return {"bucket": smart_bucket, "confidence": smart_confidence,
                "reason": smart_reason, "method": "smart_escalation"}

    # --- Step 4: still inconclusive -> review --------------------------
    logger.info("lead=%s bucket=REVIEW after escalation "
                "(proposed=%s confidence=%.2f threshold=%.2f)",
                lead_id, smart_bucket, smart_confidence, threshold)
    return {"bucket": REVIEW_BUCKET, "confidence": smart_confidence,
            "reason": f"low confidence after escalation: {smart_reason}",
            "method": "low_confidence_after_escalation",
            "proposed_bucket": smart_bucket}


def _roles_share_a_model() -> bool:
    """True when the escalation role resolves to the same model as the first
    pass, making escalation a no-op. Resolved at call time, not import time, so
    pointing the roles at different models via env re-enables escalation without
    a code change."""
    from leads.bedrock_client import model_for_role
    try:
        return model_for_role(CLASSIFIER_ROLE_FIRST_PASS) == model_for_role(
            CLASSIFIER_ROLE_ESCALATION)
    except Exception:
        return False


def _classify_with(role: str, prompt: str, lead_id: str
                   ) -> Tuple[str, float, str, Optional[str]]:
    """
    One classification pass. Returns (bucket, confidence, reason, error).
    `error` is None on success.
    """
    from leads.bedrock_client import converse_json_object

    try:
        data = converse_json_object(
            role=role,
            system=SYSTEM_PROMPT,
            user=prompt,
            max_tokens=CLASSIFIER_MAX_TOKENS,
            temperature=CLASSIFIER_TEMPERATURE,
        )
    except Exception as e:
        logger.warning("lead=%s %s classification call failed: %s",
                       lead_id, role, e)
        return REVIEW_BUCKET, 0.0, "", f"model call failed: {e}"

    bucket, confidence, reason = validate_result(data)
    return bucket, confidence, reason, None


# ============================================================
# PERSISTENCE
# ============================================================

def persist(lead: Dict[str, Any], result: Dict[str, Any],
            dry_run: bool = False) -> bool:
    """
    Write the bucket decision onto the lead record. Also sets the existing
    `classification_basket` so downstream auto-enrollment keeps working.
    Returns True if a write happened.
    """
    lead_id = lead.get("_id")
    bucket = result["bucket"]

    updates: Dict[str, Any] = {
        "outreach_bucket": bucket,
        "outreach_bucket_confidence": round(float(result["confidence"]), 3),
        "outreach_bucket_reason": result["reason"][:500],
        "outreach_bucket_method": result["method"],
        "outreach_bucket_at": datetime.utcnow(),
        # Role, not model ID — the concrete model is bedrock_client's business.
        "outreach_bucket_role": (CLASSIFIER_ROLE_ESCALATION
                                 if "escalation" in result["method"]
                                 else CLASSIFIER_ROLE_FIRST_PASS),
    }
    if result.get("proposed_bucket"):
        updates["outreach_bucket_proposed"] = result["proposed_bucket"]

    # Map onto the existing basket vocabulary (A/B/C) used by
    # canonical_ingestion._auto_enroll_in_outreach.
    cfg = BUCKETS.get(bucket)
    if cfg:
        updates["classification_basket"] = cfg["basket"]
        updates["classification_basket_name"] = cfg["label"]

    if dry_run:
        logger.info("lead=%s WOULD PERSIST bucket=%s confidence=%.2f",
                    str(lead_id), bucket, result["confidence"])
        return False

    leads_raw.update_one({"_id": lead_id}, {"$set": updates})

    # Mirror onto leads_enriched as well.
    #
    # This classifier wrote ONLY to leads_raw, but every downstream consumer —
    # ICP segmentation, basket assignment, campaign enrollment — reads
    # leads_enriched. Measured 2026-09-02: 17,457 raw docs carried an
    # outreach_bucket and ZERO enriched docs did, so the derivation chain
    #
    #     outreach_bucket -> icp_segment -> classification_basket
    #
    # broke at its first link: icp_segment stayed "unknown" for 87% of leads,
    # compute_icp_basket fell through to its keyword fallback, and 17,836 of
    # 22,117 leads parked in basket E (Nurture / Unqualified). The AI had
    # already decided; its answer just never reached the collection that
    # needed it.
    #
    # Only the three service-line buckets carry an ICP segment — REJECT has no
    # ICP and REVIEW has no *decided* one, so neither is mirrored.
    enriched_id = lead.get("enriched_lead_id")
    if cfg and cfg.get("icp_slug") and enriched_id:
        mirror = {
            "outreach_bucket": bucket,
            "icp_segment": cfg["icp_slug"],
            "classification_basket": cfg["basket"],
            "classification_basket_name": cfg["label"],
        }
        try:
            leads_enriched = leads_raw.database["leads_enriched"]
            leads_enriched.update_one({"_id": ObjectId(enriched_id)},
                                      {"$set": mirror})
        except Exception:
            # Never fail the classification because the mirror failed — the
            # backfill (scripts/backfill_bucket_to_enriched.py) re-converges.
            logger.warning("lead=%s enriched mirror failed", str(lead_id),
                           exc_info=True)
    return True


# ============================================================
# BATCH RUN
# ============================================================

def run(dry_run: bool = False, limit: Optional[int] = None,
        threshold: float = CONFIDENCE_THRESHOLD,
        reclassify: bool = False) -> Dict[str, int]:

    logger.info("classifier config: %s", config_summary())

    query: Dict[str, Any] = {}
    if not reclassify:
        query["outreach_bucket"] = {"$exists": False}

    cap = min(limit or CLASSIFY_DAILY_CAP, CLASSIFY_DAILY_CAP)
    # Newest first: an unsorted/oldest-first cursor means freshly generated
    # leads queue behind the entire historical backlog and never get
    # classified while it's being worked through. Newest-first guarantees new
    # leads clear within one run; the backlog still drains in the remaining
    # per-run capacity.
    cursor = leads_raw.find(query).sort("created_at", -1).limit(cap)

    stats = {b: 0 for b in VALID_BUCKETS}
    stats.update({REJECT_BUCKET: 0, REVIEW_BUCKET: 0,
                  "scanned": 0, "written": 0, "excluded_pre_ai": 0})

    for lead in cursor:
        stats["scanned"] += 1
        result = classify_lead(lead, threshold=threshold)
        stats[result["bucket"]] = stats.get(result["bucket"], 0) + 1
        if result["method"] == "exclusion_filter":
            stats["excluded_pre_ai"] += 1
        if persist(lead, result, dry_run=dry_run):
            stats["written"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify leads into outreach buckets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=CONFIDENCE_THRESHOLD)
    parser.add_argument("--reclassify", action="store_true",
                        help="re-classify leads that already have a bucket")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.dry_run:
        logger.info("DRY RUN — no writes will be made")

    stats = run(dry_run=args.dry_run, limit=args.limit,
                threshold=args.threshold, reclassify=args.reclassify)

    logger.info("=== classification complete ===")
    for key in sorted(stats):
        logger.info("  %-18s %d", key, stats[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
