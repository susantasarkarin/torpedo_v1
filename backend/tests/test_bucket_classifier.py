"""
BUCKET CLASSIFIER TESTS
=======================

Covers the cheap exclusion filter, the strict JSON contract (including every
way a model response can violate it), and the confidence gate.

No network calls: the Bedrock transport seam is patched.

Run with: pytest backend/tests/test_bucket_classifier.py -v
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import bedrock_client
from leads.bucket_classifier import (
    build_prompt,
    check_exclusion,
    classify_lead,
    validate_result,
)
from leads.outreach_config import (
    BUCKETS,
    REJECT_BUCKET,
    REVIEW_BUCKET,
    VALID_BUCKETS,
    bucket_for_basket,
    bucket_for_icp,
)


QUALIFIED = {
    "_id": "abc123",
    "name": "Asha Rao",
    "title": "Head of BIM",
    "company": "Larsen & Toubro",
    "company_industry": "Construction",
    "country": "India",
    "seniority_level": "Head",
}


# ============================================
# EXCLUSION FILTER
# ============================================

@pytest.mark.parametrize("title", [
    "Student", "MBA Student", "Marketing Intern", "Summer Intern",
    "Graduate Trainee", "Fresher", "Apprentice",
    "Seeking opportunities in marketing", "Open to work",
    "Professor of Marketing", "Assistant Professor", "Research Scholar",
    "Technical Recruiter", "Talent Acquisition Manager", "HR Manager",
    "Head of Human Resources", "Staffing Consultant",
    "Business Development Executive", "Sales Executive",
    "Account Executive", "SDR", "Inside Sales Manager",
    "Retired Architect", "Former CTO", "Freelancer",
])
def test_excluded_titles_are_rejected(title):
    reason = check_exclusion({"title": title})
    assert reason is not None, f"{title!r} should have been excluded"


@pytest.mark.parametrize("title", [
    "BIM Manager", "Head of BIM", "CAD Manager", "Digital Delivery Manager",
    "Director of Consumer Insights", "VP Market Research", "CMO",
    "Head of Insights", "Chief Marketing Officer", "Technical Director",
])
def test_qualified_titles_pass(title):
    assert check_exclusion({"title": title, "company_industry": "Construction"}) is None


# --- Regression: real titles from leads_raw that were wrongly excluded ---
# These are LinkedIn headlines, not clean job titles. Substring matching and a
# naive generic-term rule dropped 26% of the database, including CMOs and VPs.

@pytest.mark.parametrize("headline", [
    "VP and Chief Marketing Officer, Schneider Electric India",   # 'officer'
    "Assistant Vice President at Marsh India | AIII",             # 'assistant'
    "Vice President Student Council @ International",             # 'student'
    "International MBA || IE Business School || Product",         # 'intern' inside 'International'
    "Vice President Product Engineering and India",               # 'engineer'
    "Associate Principal (Partner) at ZS | Data Analytics",       # 'associate'
    "Research Partner & Principal Consultant | Market",           # 'consultant'
    "Chief Economist I MD NEO Economists Professor",              # 'professor', but an MD
])
def test_senior_headlines_are_not_excluded(headline):
    reason = check_exclusion({"title": headline})
    assert reason is None, f"{headline!r} wrongly excluded: {reason}"


def test_past_tense_only_disqualifies_when_leading():
    """'Former CTO' has left; 'Analyst | Former Amazon' just names an employer."""
    assert check_exclusion({"title": "Former CTO"}) is not None
    assert check_exclusion({"title": "Retired Architect"}) is not None
    assert check_exclusion({"title": "Head of Insights | Former Nielsen"}) is None


def test_hr_is_excluded_at_every_seniority():
    """HR leadership is senior but never buys our services."""
    for title in ("Head of Human Resources", "VP Talent Acquisition",
                  "Chief Human Resources Officer", "Director of Recruitment"):
        assert check_exclusion({"title": title}) is not None, title


def test_word_boundary_prevents_substring_matches():
    """'intern' must not match 'International', 'sdr' must not match inside words."""
    assert check_exclusion({"title": "International Marketing Director"}) is None
    assert check_exclusion({"title": "Head of International Insights"}) is None


def test_junior_versions_of_those_titles_still_excluded():
    """The seniority override must not blanket-allow genuinely junior people."""
    assert check_exclusion({"title": "Technical Recruiter"}) is not None
    assert check_exclusion({"title": "Student at the University of Miami"}) is not None
    assert check_exclusion({"title": "Marketing Intern"}) is not None
    assert check_exclusion({"title": "Electrical Engineer"}) is not None


def test_long_headline_not_judged_by_generic_term():
    """Headlines beyond the clean-title length are left for the model."""
    long_headline = ("Market Research Specialist | Consumer Insights | "
                     "Brand Strategy | Speaker | Ex-Nielsen")
    assert check_exclusion({"title": long_headline}) is None


def test_hard_exclusions_apply_even_to_senior_titles():
    """Vendor-side sales is disqualifying regardless of seniority."""
    assert check_exclusion({"title": "VP of Business Development Executive"}) is not None


def test_missing_title_is_rejected():
    assert check_exclusion({}) == "no job title"
    assert check_exclusion({"title": "   "}) == "no job title"


def test_exclusion_is_case_insensitive():
    assert check_exclusion({"title": "INTERN"}) is not None
    assert check_exclusion({"title": "Talent Acquisition"}) is not None


def test_generic_title_rejected_without_support():
    """A bare 'Consultant' has no buying authority signal."""
    assert check_exclusion({"title": "Consultant"}) is not None


def test_generic_title_allowed_with_industry_support():
    assert check_exclusion({"title": "Consultant",
                            "company_industry": "Market Research"}) is None


def test_generic_title_allowed_with_seniority_support():
    assert check_exclusion({"title": "Analyst", "seniority_level": "Director"}) is None


def test_exclusion_runs_before_any_model_call():
    """A rejected lead must never cost a Bedrock call."""
    with patch.object(bedrock_client, "converse") as mock_invoke:
        result = classify_lead({"_id": "x", "title": "Marketing Intern"})
    mock_invoke.assert_not_called()
    assert result["bucket"] == REJECT_BUCKET
    assert result["method"] == "exclusion_filter"


# ============================================
# JSON CONTRACT
# ============================================

def test_valid_result_accepted():
    bucket, conf, reason = validate_result(
        {"bucket": "BIM", "confidence": 0.92, "reason": "BIM Manager at AEC firm"})
    assert (bucket, conf) == ("BIM", 0.92)
    assert "BIM Manager" in reason


def test_reject_is_a_valid_bucket():
    bucket, _, _ = validate_result(
        {"bucket": "REJECT", "confidence": 0.99, "reason": "student"})
    assert bucket == REJECT_BUCKET


def test_bucket_is_normalized():
    bucket, _, _ = validate_result(
        {"bucket": "  bim  ", "confidence": 0.9, "reason": "x"})
    assert bucket == "BIM"


@pytest.mark.parametrize("payload", [
    None,                                                    # nothing parsed
    "a string",                                              # not an object
    {},                                                      # empty
    {"confidence": 0.9, "reason": "x"},                      # no bucket
    {"bucket": None, "confidence": 0.9},                     # null bucket
    {"bucket": "MARKETING", "confidence": 0.9},              # unknown bucket
    {"bucket": "BIM"},                                       # no confidence
    {"bucket": "BIM", "confidence": "high"},                 # non-numeric
    {"bucket": "BIM", "confidence": None},                   # null confidence
    {"bucket": "BIM", "confidence": 1.5},                    # out of range
    {"bucket": "BIM", "confidence": -0.2},                   # negative
])
def test_contract_violations_route_to_review(payload):
    bucket, conf, reason = validate_result(payload)
    assert bucket == REVIEW_BUCKET, f"{payload!r} should route to review"
    assert conf == 0.0
    assert reason


def test_missing_reason_gets_placeholder():
    _, _, reason = validate_result({"bucket": "BIM", "confidence": 0.9})
    assert reason == "no reason given"


# ============================================
# CONFIDENCE GATE
# ============================================

def test_high_confidence_assigns_bucket_without_escalating():
    """A confident cheap-model answer must not pay for the smart model."""
    payload = '{"bucket": "BIM", "confidence": 0.95, "reason": "clear match"}'
    with patch.object(bedrock_client, "converse", return_value=payload) as mock:
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == "BIM"
    assert result["method"] == "cheap"
    assert mock.call_count == 1
    assert mock.call_args.kwargs.get("role") == "cheap" or \
        mock.call_args.args[0] == "cheap"


def test_low_confidence_escalates_to_smart_model():
    """Below threshold on cheap -> one retry on smart, which resolves it."""
    cheap = '{"bucket": "BIM", "confidence": 0.55, "reason": "thin"}'
    smart = '{"bucket": "BIM", "confidence": 0.88, "reason": "confirmed"}'
    with patch.object(bedrock_client, "converse", side_effect=[cheap, smart]) as mock:
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert mock.call_count == 2
    assert result["bucket"] == "BIM"
    assert result["method"] == "smart_escalation"
    assert result["confidence"] == 0.88


def test_escalation_can_change_the_bucket():
    cheap = '{"bucket": "BIM", "confidence": 0.4, "reason": "unsure"}'
    smart = '{"bucket": "SFW", "confidence": 0.91, "reason": "research buyer"}'
    with patch.object(bedrock_client, "converse", side_effect=[cheap, smart]):
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == "SFW"


def test_escalation_can_reject():
    cheap = '{"bucket": "BIM", "confidence": 0.3, "reason": "unsure"}'
    smart = '{"bucket": "REJECT", "confidence": 0.95, "reason": "vendor sales"}'
    with patch.object(bedrock_client, "converse", side_effect=[cheap, smart]):
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == REJECT_BUCKET


def test_reject_on_cheap_pass_does_not_escalate():
    """A confident rejection is final — no need to spend the smart model."""
    payload = '{"bucket": "REJECT", "confidence": 0.9, "reason": "student"}'
    with patch.object(bedrock_client, "converse", return_value=payload) as mock:
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == REJECT_BUCKET
    assert mock.call_count == 1


def test_escalation_failure_routes_to_review():
    cheap = '{"bucket": "BIM", "confidence": 0.5, "reason": "thin"}'
    with patch.object(bedrock_client, "converse",
                      side_effect=[cheap, RuntimeError("throttled out")]):
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == REVIEW_BUCKET
    assert result["method"] == "escalation_error"


def test_low_confidence_on_both_passes_routes_to_review():
    """Still below threshold after escalation -> review folder, not a bucket."""
    payload = '{"bucket": "BIM", "confidence": 0.55, "reason": "thin"}'
    with patch.object(bedrock_client, "converse", return_value=payload) as mock:
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert mock.call_count == 2
    assert result["bucket"] == REVIEW_BUCKET
    assert result["method"] == "low_confidence_after_escalation"
    assert result["proposed_bucket"] == "BIM"


def test_threshold_boundary_is_inclusive():
    payload = '{"bucket": "BIM", "confidence": 0.7, "reason": "exact"}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == "BIM"


def test_threshold_is_configurable():
    payload = '{"bucket": "BIM", "confidence": 0.55, "reason": "thin"}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        result = classify_lead(QUALIFIED, threshold=0.5)
    assert result["bucket"] == "BIM"


def test_low_confidence_reject_is_not_downgraded():
    """REJECT is not gated â€” a rejection stands regardless of confidence."""
    payload = '{"bucket": "REJECT", "confidence": 0.3, "reason": "unclear"}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        result = classify_lead(QUALIFIED, threshold=0.7)
    assert result["bucket"] == REJECT_BUCKET


def test_model_failure_routes_to_review():
    with patch.object(bedrock_client, "converse", side_effect=RuntimeError("503")):
        result = classify_lead(QUALIFIED)
    assert result["bucket"] == REVIEW_BUCKET
    assert result["method"] == "error"


def test_malformed_output_routes_to_review():
    with patch.object(bedrock_client, "converse", return_value="I'm not sure"):
        result = classify_lead(QUALIFIED)
    assert result["bucket"] == REVIEW_BUCKET


# ============================================
# PROMPT / CONFIG
# ============================================

def test_prompt_contains_all_buckets_and_lead_fields():
    prompt = build_prompt(QUALIFIED)
    for bucket in VALID_BUCKETS:
        assert bucket in prompt
    assert "Head of BIM" in prompt
    assert "Larsen & Toubro" in prompt


def test_prompt_truncates_long_snippets():
    prompt = build_prompt({**QUALIFIED, "snippet": "x" * 2000})
    assert "..." in prompt
    assert len(prompt) < 4000


def test_prompt_handles_missing_fields():
    prompt = build_prompt({"_id": "x", "title": "BIM Manager"})
    assert "unknown" in prompt


def test_buckets_map_onto_existing_basket_vocabulary():
    """Buckets must align with canonical_ingestion's A/B/C baskets."""
    assert bucket_for_basket("A") == "SFW"
    assert bucket_for_basket("B") == "COGENTIX_RESEARCH"
    assert bucket_for_basket("C") == "BIM"
    assert bucket_for_basket("Z") is None


def test_buckets_map_onto_existing_icps():
    assert bucket_for_icp("survey_fieldwork") == "SFW"
    assert bucket_for_icp("cogentix") == "COGENTIX_RESEARCH"
    assert bucket_for_icp("bimwave") == "BIM"


def test_every_bucket_has_a_definition():
    for key, cfg in BUCKETS.items():
        assert cfg["description"].strip()
        assert cfg["ideal_buyer"].strip()
        assert "TODO" not in cfg["description"]
        assert "TODO" not in cfg["ideal_buyer"]

