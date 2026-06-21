"""
Unit tests for scorer.py — deterministic, no API calls, no DB writes.
Uses an in-memory profiles_seen (mocked out).
"""

import sys
import types
from unittest.mock import patch

import pytest

# Stub the state module before importing scorer so we don't hit SQLite
_state_stub = types.ModuleType("backend.lead_gen_mcp.state")
_state_stub.is_profile_seen = lambda url: False
_state_stub.mark_profile_seen = lambda url, icp_id, query: True
sys.modules.setdefault("backend.lead_gen_mcp.state", _state_stub)

from backend.lead_gen_mcp.scorer import score_result, score_and_dedup, extract_title_synonyms
from backend.lead_gen_mcp.tests.fixtures import (
    SURVEY_ICP,
    SERP_HIT,
    SERP_LOW_SCORE,
    SERP_EXCLUDED,
)


def test_score_high_match():
    score = score_result(SERP_HIT, SURVEY_ICP)
    assert score >= 0.65, f"Expected high score for clear ICP match, got {score}"


def test_score_low_match():
    score = score_result(SERP_LOW_SCORE, SURVEY_ICP)
    assert score < 0.30, f"Expected low score for SWE profile, got {score}"


def test_exclusion_rule_applied():
    with patch("backend.lead_gen_mcp.scorer.st") as mock_st:
        mock_st.is_profile_seen.return_value = False
        mock_st.mark_profile_seen.return_value = True
        output = score_and_dedup([SERP_EXCLUDED], SURVEY_ICP)
    assert len(output.rejected_low_score) == 1
    assert SERP_EXCLUDED in output.rejected_low_score


def test_dedup_pipeline_level():
    with patch("backend.lead_gen_mcp.scorer.st") as mock_st:
        mock_st.is_profile_seen.return_value = True  # simulate seen
        mock_st.mark_profile_seen.return_value = False
        output = score_and_dedup([SERP_HIT], SURVEY_ICP)
    assert len(output.rejected_dupes) == 1
    assert len(output.accepted) == 0


def test_within_batch_dedup():
    with patch("backend.lead_gen_mcp.scorer.st") as mock_st:
        mock_st.is_profile_seen.return_value = False
        mock_st.mark_profile_seen.return_value = True
        duplicate_hit = SERP_HIT.model_copy()
        output = score_and_dedup([SERP_HIT, duplicate_hit], SURVEY_ICP)
    assert len(output.accepted) == 1
    assert len(output.rejected_dupes) == 1


def test_low_score_rejected():
    with patch("backend.lead_gen_mcp.scorer.st") as mock_st:
        mock_st.is_profile_seen.return_value = False
        mock_st.mark_profile_seen.return_value = True
        output = score_and_dedup([SERP_LOW_SCORE], SURVEY_ICP)
    assert len(output.rejected_low_score) == 1
    assert len(output.accepted) == 0


def test_synonym_extraction():
    novel = extract_title_synonyms([SERP_HIT], SURVEY_ICP)
    # SERP_HIT title "Head of Insights" IS in target_titles, so should not appear
    assert "head of insights" not in [t.lower() for t in novel]

    from backend.lead_gen_mcp.schemas import SERPResult
    cro = SERPResult(
        name="X",
        title="Chief Revenue Officer",
        company="Y",
        profile_url="https://linkedin.com/in/cro-x",
        snippet="CRO",
        source_query="q",
    )
    novel2 = extract_title_synonyms([cro], SURVEY_ICP)
    assert "chief revenue officer" in [t.lower() for t in novel2]
