"""
CX survey v3.3 — IDFC FIRST Bank Customer Experience & Sales Process
Evaluation (Quantitative QRE, Revision 3 / v3.3 — "PII after S3, Terminate").

This is a NEW VERSION of the questionnaire, kept as its own engine so the
original Rev-2/3 study (`type == "cx_survey"`, cx_survey.py) keeps running
untouched. Studies dispatch here when `type == "cx_survey_v33"`.

Delta vs. cx_survey.py — the P0–P3 PII match-back module, asked directly
after S3 and only when S3 includes IDFC FIRST Bank:
  P0  consent script (read verbatim)      — refusal TERMINATES
  P1  full name (open, verbatim)          — refusal/blank TERMINATES
  P2  mobile number (10-digit, validated) — refusal/invalid TERMINATES
  P3  customer ID / account number (open) — optional, never terminates

Everything else (question bank S–I, gating, quota frame, helpers) is reused
from cx_survey so the two revisions cannot drift apart accidentally.
"""
from __future__ import annotations

import copy
import re

import cx_survey as base

# Re-export the helpers/frames the routes use, so this module is a drop-in
# engine with the same surface as cx_survey.
_one = base._one
_as_codes = base._as_codes
CX_QUOTAS = base.CX_QUOTAS
CENTRE_QUOTA_MAP = base.CENTRE_QUOTA_MAP
IDFC_BANK_CODE = base.IDFC_BANK_CODE
cross_quota_key = base.cross_quota_key

SURVEY_TYPE = "cx_survey_v33"


# ---------------------------------------------------------------------------
# v3.3 question bank = base bank with P0–P3 inserted after S3 (before S4),
# matching the QRE's placement. Deep-copied so the base bank is never mutated.
# ---------------------------------------------------------------------------

_PII_QUESTIONS = [
    {"id": "P0", "section": "P", "type": "single",
     "text": "IDFC FIRST Bank, who this study is being conducted for, has asked us to also record your name, mobile number, and customer ID or account number, so they can match your feedback to their own service records. This is used only for internal service-improvement purposes, not for marketing or sales. Are you comfortable sharing these details?",
     "instruction": "READ VERBATIM — DO NOT PARAPHRASE. ASK ONLY IF S3 INCLUDES IDFC FIRST BANK.",
     "options": [{"code": 1, "label": "Yes, willing to share"},
                 {"code": 2, "label": "No, prefer not to share"}]},
    {"id": "P1", "section": "P", "type": "open", "pii": True,
     "text": "May I take your full name, please?",
     "instruction": "RECORD VERBATIM. ASK ONLY IF P0 = 1. IF REFUSED, TERMINATE."},
    {"id": "P2", "section": "P", "type": "open", "pii": True, "validation": "mobile_in_10",
     "text": "And your mobile number?",
     "instruction": "NUMERIC, 10 DIGITS. VALIDATE FORMAT. ASK ONLY IF P0 = 1. IF REFUSED OR INVALID, TERMINATE."},
    {"id": "P3", "section": "P", "type": "open", "pii": True, "optional": True,
     "text": "And could I take your IDFC FIRST Bank customer ID or account number, if you have it to hand?",
     "instruction": "RECORD VERBATIM. ASK ONLY IF P0 = 1. IF NOT KNOWN OR NOT TO HAND, CODE 'DON'T KNOW' — DO NOT PROBE OR ASK THE RESPONDENT TO LOOK IT UP; DOES NOT TERMINATE."},
]

QUESTION_BANK = copy.deepcopy(base.QUESTION_BANK)
_s3_idx = next(i for i, q in enumerate(QUESTION_BANK) if q["id"] == "S3")
QUESTION_BANK[_s3_idx + 1:_s3_idx + 1] = copy.deepcopy(_PII_QUESTIONS)

_ORDER = [q["id"] for q in QUESTION_BANK]
_BY_ID = {q["id"]: q for q in QUESTION_BANK}
FIRST_QUESTION_ID = _ORDER[0]


# ---------------------------------------------------------------------------
# Ask-logic: base predicates + the PII module's own.
# ---------------------------------------------------------------------------

ASK_IF = {
    **base.ASK_IF,
    # P0 only when the respondent holds an IDFC FIRST Bank account at S3
    # (whether or not it turns out to be primary at S4).
    "P0": lambda r: IDFC_BANK_CODE in _as_codes(r.get("S3")),
    "P1": lambda r: _one(r.get("P0")) == 1,
    "P2": lambda r: _one(r.get("P0")) == 1,
    "P3": lambda r: _one(r.get("P0")) == 1,
}

SECTION_GATE = base.SECTION_GATE  # section P has no gate → always passes


def terminate_reason(qid, answer) -> str | None:
    # ---- v3.3 PII module (P0–P3) ----
    # P0: not comfortable sharing match-back details → terminate.
    if qid == "P0" and _one(answer) != 1:
        return "P0_pii_consent_refused"
    # P1: name is a hard requirement — refusal / blank terminates.
    if qid == "P1" and not str(answer or "").strip():
        return "P1_name_refused"
    # P2: mobile number, 10 digits after stripping separators — refused or
    # invalid terminates (per QRE: VALIDATE FORMAT).
    if qid == "P2" and not re.fullmatch(r"\d{10}", re.sub(r"[\s\-+()]", "", str(answer or ""))):
        return "P2_mobile_refused_or_invalid"
    # P3 never terminates ('Don't know' is an accepted answer).
    if qid == "P3":
        return None
    return base.terminate_reason(qid, answer)


# ---------------------------------------------------------------------------
# Askability + routing (same walk as the base engine, over the v3.3 order)
# ---------------------------------------------------------------------------

def _is_askable(qid, responses) -> bool:
    q = _BY_ID[qid]
    gate = SECTION_GATE.get(q["section"])
    if gate and not gate(responses):
        return False
    pred = ASK_IF.get(qid)
    if pred and not pred(responses):
        return False
    return True


def next_question(qid, responses) -> str | None:
    """Return the next askable question id after `qid`, or None when the
    survey is complete. `responses` must already include the answer to `qid`."""
    try:
        start = _ORDER.index(qid)
    except ValueError:
        return None
    for nxt in _ORDER[start + 1:]:
        if _is_askable(nxt, responses):
            return nxt
    return None


def first_question(responses=None) -> str:
    responses = responses or {}
    for qid in _ORDER:
        if _is_askable(qid, responses):
            return qid
    return FIRST_QUESTION_ID


def config_payload():
    """Question bank + quota frame for a respondent UI / external programmer."""
    return {
        "survey_type": SURVEY_TYPE,
        "title": "IDFC FIRST Bank — Quantitative QRE (Revision 3 / v3.3, PII after S3)",
        "first_question_id": FIRST_QUESTION_ID,
        "questions": QUESTION_BANK,
        "quotas": CX_QUOTAS,
    }
