"""
ICP QUERY GENERATION VIA BEDROCK (Task 2)
=========================================

Covers the Bedrock path, the automatic fallback to the bug-fixed template
builder, and per-ICP daily budget enforcement.

The Bedrock seam (`bedrock_client.converse`) is patched; no AWS calls.

Run with: pytest backend/tests/test_icp_query_ai.py -v
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import bedrock_client
from leads.icp_config import DEFAULT_ICPS
from leads.icp_query_ai import generate_icp_queries, remaining_daily_budget

BIM = next(i for i in DEFAULT_ICPS if i["slug"] == "bimwave")


# ============================================
# BEDROCK PATH
# ============================================

def test_uses_bedrock_output_when_valid():
    payload = '{"queries": ["site:linkedin.com/in/ \\"BIM Manager\\" India"]}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out == ['site:linkedin.com/in/ "BIM Manager" India']


def test_uses_cheap_role():
    """Query generation is a cheap-model task."""
    payload = '{"queries": ["a"]}'
    with patch.object(bedrock_client, "converse", return_value=payload) as mock:
        generate_icp_queries(BIM, count=2, leads_per_icp={})
    role = mock.call_args.kwargs.get("role") or mock.call_args.args[0]
    assert role == "cheap"


def test_handles_fenced_json():
    payload = '```json\n{"queries": ["fenced query"]}\n```'
    with patch.object(bedrock_client, "converse", return_value=payload):
        assert generate_icp_queries(BIM, count=3, leads_per_icp={}) == ["fenced query"]


def test_deduplicates_and_caps_at_count():
    payload = '{"queries": ["dup", "DUP", " dup ", "unique", "third"]}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        out = generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert out == ["dup", "unique"]


def test_overlong_queries_dropped():
    payload = '{"queries": ["%s", "ok"]}' % ("x" * 400)
    with patch.object(bedrock_client, "converse", return_value=payload):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={}) == ["ok"]


# ============================================
# FALLBACK
# ============================================

def test_falls_back_to_template_on_bedrock_failure():
    with patch.object(bedrock_client, "converse", side_effect=RuntimeError("503")):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out, "template fallback produced nothing"
    # Fallback still honours the Task 1 ICP-scoping fix.
    for query in out:
        assert "crypto" not in query.lower()
        assert any(d.lower() in query.lower() for d in BIM["designations"])


def test_falls_back_on_unparseable_output():
    """converse_json retries once, then the fallback takes over."""
    with patch.object(bedrock_client, "converse", return_value="I cannot help"):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out


def test_falls_back_on_empty_query_list():
    with patch.object(bedrock_client, "converse", return_value='{"queries": []}'):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={})


def test_fallback_can_be_disabled():
    with patch.object(bedrock_client, "converse", side_effect=RuntimeError("503")):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={},
                                   allow_fallback=False)
    assert out == []


def test_path_is_logged(caplog):
    payload = '{"queries": ["a"]}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        with caplog.at_level("INFO", logger="leads.icp_query_ai"):
            generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert "path=bedrock" in caplog.text

    caplog.clear()
    with patch.object(bedrock_client, "converse", side_effect=RuntimeError("x")):
        with caplog.at_level("INFO", logger="leads.icp_query_ai"):
            generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert "path=template" in caplog.text


# ============================================
# DAILY BUDGET
# ============================================

def test_exhausted_budget_makes_no_ai_call():
    used = {BIM["slug"]: BIM["daily_budget"]}
    with patch.object(bedrock_client, "converse") as mock:
        out = generate_icp_queries(BIM, count=5, leads_per_icp=used)
    assert out == []
    mock.assert_not_called()


def test_request_clamped_to_remaining_budget():
    used = {BIM["slug"]: BIM["daily_budget"] - 2}
    payload = '{"queries": ["a", "b", "c", "d", "e"]}'
    with patch.object(bedrock_client, "converse", return_value=payload):
        assert len(generate_icp_queries(BIM, count=10, leads_per_icp=used)) == 2


def test_remaining_budget_arithmetic():
    assert remaining_daily_budget(BIM, {BIM["slug"]: 0}) == BIM["daily_budget"]
    assert remaining_daily_budget(BIM, {BIM["slug"]: 9999}) == 0
    assert remaining_daily_budget(BIM, {}) == BIM["daily_budget"]


def test_ai_disabled_flag_skips_bedrock(monkeypatch):
    monkeypatch.setenv("DISABLE_AI_CALLS", "true")
    with patch.object(bedrock_client, "converse") as mock:
        out = generate_icp_queries(BIM, count=3, leads_per_icp={})
    mock.assert_not_called()
    assert out, "should still fall back to the template builder"
