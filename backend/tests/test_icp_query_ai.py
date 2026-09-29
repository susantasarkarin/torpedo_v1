"""
ICP query generation via the local SLM, the template fallback, and per-ICP
daily budget enforcement. The model seam (query_variants_ai._ask) is patched.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import query_variants_ai as qv
from leads.icp_config import DEFAULT_ICPS
from leads.icp_query_ai import generate_icp_queries, remaining_daily_budget

BIM = next(i for i in DEFAULT_ICPS if i["slug"] == "bimwave")


def test_uses_slm_output_when_on_topic():
    with patch.object(qv, "_ask", return_value=['"BIM Manager" Pune', "Revit coordinator Mumbai"]):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out == ['"BIM Manager" Pune', "Revit coordinator Mumbai"]


def test_deduplicates_and_caps_at_count():
    raw = ["BIM Manager India", "bim manager  india", "BIM coordinator Pune", "Head of BIM Delhi"]
    with patch.object(qv, "_ask", return_value=raw):
        out = generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert out == ["BIM Manager India", "BIM coordinator Pune"]


def test_overlong_and_off_topic_queries_dropped():
    raw = ["BIM " + "x" * 400, "crypto trader Dubai", "BIM Manager Chennai"]
    with patch.object(qv, "_ask", return_value=raw):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={}) == ["BIM Manager Chennai"]


def test_already_used_searches_are_not_returned():
    with patch.object(qv, "_ask", return_value=["BIM Manager India", "BIM Lead Kolkata"]):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={}, used=["bim manager india"])
    assert out == ["BIM Lead Kolkata"]


def test_falls_back_to_template_when_model_unavailable():
    with patch.object(qv, "_ask", return_value=None):
        out = generate_icp_queries(BIM, count=5, leads_per_icp={})
    assert out, "template fallback produced nothing"
    for query in out:
        assert any(d.lower() in query.lower() for d in BIM["designations"])


def test_falls_back_on_nothing_usable_or_error():
    with patch.object(qv, "_ask", return_value=[]):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={})
    with patch.object(qv, "_ask", side_effect=RuntimeError("boom")):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={})


def test_fallback_can_be_disabled():
    with patch.object(qv, "_ask", return_value=None):
        assert generate_icp_queries(BIM, count=5, leads_per_icp={}, allow_fallback=False) == []


def test_path_is_logged(caplog):
    with patch.object(qv, "_ask", return_value=["BIM Manager Pune"]):
        with caplog.at_level("INFO", logger="leads.icp_query_ai"):
            generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert "path=slm" in caplog.text
    caplog.clear()
    with patch.object(qv, "_ask", return_value=None):
        with caplog.at_level("INFO", logger="leads.icp_query_ai"):
            generate_icp_queries(BIM, count=2, leads_per_icp={})
    assert "path=template" in caplog.text


def test_exhausted_budget_makes_no_ai_call():
    used = {BIM["slug"]: BIM["daily_budget"]}
    with patch.object(qv, "_ask") as mock:
        assert generate_icp_queries(BIM, count=5, leads_per_icp=used) == []
    mock.assert_not_called()


def test_request_clamped_to_remaining_budget():
    used = {BIM["slug"]: BIM["daily_budget"] - 2}
    raw = ["BIM Manager Pune", "BIM Lead Delhi", "BIM Engineer Noida", "CAD Manager Mumbai"]
    with patch.object(qv, "_ask", return_value=raw):
        assert len(generate_icp_queries(BIM, count=10, leads_per_icp=used)) == 2


def test_remaining_budget_arithmetic():
    assert remaining_daily_budget(BIM, {BIM["slug"]: 0}) == BIM["daily_budget"]
    assert remaining_daily_budget(BIM, {BIM["slug"]: 9999}) == 0
    assert remaining_daily_budget(BIM, {}) == BIM["daily_budget"]


def test_ai_disabled_flag_skips_the_model(monkeypatch):
    monkeypatch.setenv("DISABLE_AI_CALLS", "true")
    with patch.object(qv, "_ask") as mock:
        out = generate_icp_queries(BIM, count=3, leads_per_icp={})
    mock.assert_not_called()
    assert out, "should still fall back to the template builder"


def test_variations_of_a_tapped_out_query():
    q = '"BIM Manager" India'
    with patch.object(qv, "_ask", return_value=[q, '"BIM Manager" Hyderabad', "Revit MEP lead Pune", "sales"]):
        assert qv.variations(q, BIM, already=[]) == ['"BIM Manager" Hyderabad', "Revit MEP lead Pune"]
    with patch.object(qv, "_ask", return_value=None):
        assert qv.variations(q, BIM) is None


def test_keyword_soup_and_punctuation_repeats_dropped():
    raw = ["Head of BIM BIM Lead BIM Engineer CAD Manager Project Architect India", "BIM Manager, India",
           "BIM Coordinator India"]
    assert qv.clean(raw, BIM, ['"BIM Manager" India'], 5) == ["BIM Coordinator India"]
