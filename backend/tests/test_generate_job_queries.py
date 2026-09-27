"""
generate_job_queries() -- Qwen-generated queries for a WebSearch job, ICP-aware
====================================================================================

Covers leads/router.py's generate_job_queries(), added 2026-09-27: a WebSearch
job tagged with an ICP (icp_id, previously used only to tag imported leads)
now asks leads/icp_query_ai.generate_icp_queries() -- the same Qwen-via-
bedrock_client path leads/scheduler.py's LeadScheduler already uses in
production -- for its initial query list, instead of the template's blind
cartesian product. Falls back to the unchanged template on any failure.
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def router(monkeypatch):
    """Import leads.router with Mongo stubbed out (it builds many handles at import)."""
    fake_db = types.ModuleType("database")
    fake_db.get_client = lambda: MagicMock()
    monkeypatch.setitem(sys.modules, "database", fake_db)
    sys.modules.pop("leads.router", None)
    from leads import router as mod
    yield mod
    sys.modules.pop("leads.router", None)


def test_no_icp_id_goes_straight_to_the_template(router):
    config = {"designations": ["CEO"], "countries": ["India"], "seniorities": [],
             "custom_query": "", "industries": []}
    with patch.object(router, "generate_query_combinations", return_value=["template query"]) as tmpl:
        result = router.generate_job_queries(None, config)
    assert result == ["template query"]
    tmpl.assert_called_once()


def test_icp_id_that_does_not_resolve_falls_back_to_the_template(router):
    config = {"designations": [], "countries": [], "seniorities": [], "custom_query": "", "industries": []}
    fake_icp_config = MagicMock(get_icp_by_slug=MagicMock(return_value=None))
    with patch.dict(sys.modules, {"leads.icp_config": fake_icp_config}), \
         patch.object(router, "generate_query_combinations", return_value=["template query"]) as tmpl:
        result = router.generate_job_queries("unknown-slug", config)
    assert result == ["template query"]
    tmpl.assert_called_once()


def test_resolved_icp_uses_qwen_queries_when_available(router):
    config = {"designations": [], "countries": [], "seniorities": [], "custom_query": "", "industries": []}
    icp = {"slug": "bimwave", "name": "BIMwave", "designations": ["BIM Manager"],
          "countries": ["India"], "seniority_levels": ["Manager"], "industries": ["AEC"]}
    fake_icp_config = MagicMock(get_icp_by_slug=MagicMock(return_value=icp))
    fake_icp_query_ai = MagicMock(generate_icp_queries=MagicMock(return_value=["ai query 1", "ai query 2"]))
    with patch.dict(sys.modules, {"leads.icp_config": fake_icp_config,
                                  "leads.icp_query_ai": fake_icp_query_ai}), \
         patch.object(router, "generate_query_combinations") as tmpl:
        result = router.generate_job_queries("bimwave", config)
    assert result == ["ai query 1", "ai query 2"]
    tmpl.assert_not_called()
    fake_icp_query_ai.generate_icp_queries.assert_called_once()
    passed_icp = fake_icp_query_ai.generate_icp_queries.call_args.args[0]
    assert passed_icp["designations"] == ["BIM Manager"]   # ICP's own defaults preserved


def test_job_specific_filters_override_the_icps_own_defaults(router):
    """A job narrowed to one country/designation must not be silently widened
    back out to the ICP's own broader defaults."""
    config = {"designations": ["CAD Manager"], "countries": ["UK"], "seniorities": [],
             "custom_query": "", "industries": []}
    icp = {"slug": "bimwave", "designations": ["BIM Manager", "BIM Coordinator"],
          "countries": ["India", "UAE"], "seniority_levels": [], "industries": []}
    fake_icp_config = MagicMock(get_icp_by_slug=MagicMock(return_value=icp))
    fake_icp_query_ai = MagicMock(generate_icp_queries=MagicMock(return_value=["q"]))
    with patch.dict(sys.modules, {"leads.icp_config": fake_icp_config,
                                  "leads.icp_query_ai": fake_icp_query_ai}):
        router.generate_job_queries("bimwave", config)
    passed_icp = fake_icp_query_ai.generate_icp_queries.call_args.args[0]
    assert passed_icp["designations"] == ["CAD Manager"]
    assert passed_icp["countries"] == ["UK"]


def test_qwen_returning_nothing_falls_back_to_the_template(router):
    config = {"designations": [], "countries": [], "seniorities": [], "custom_query": "", "industries": []}
    icp = {"slug": "bimwave"}
    fake_icp_config = MagicMock(get_icp_by_slug=MagicMock(return_value=icp))
    fake_icp_query_ai = MagicMock(generate_icp_queries=MagicMock(return_value=[]))
    with patch.dict(sys.modules, {"leads.icp_config": fake_icp_config,
                                  "leads.icp_query_ai": fake_icp_query_ai}), \
         patch.object(router, "generate_query_combinations", return_value=["template query"]) as tmpl:
        result = router.generate_job_queries("bimwave", config)
    assert result == ["template query"]
    tmpl.assert_called_once()


def test_qwen_raising_never_crashes_the_job_and_falls_back(router):
    config = {"designations": [], "countries": [], "seniorities": [], "custom_query": "", "industries": []}
    icp = {"slug": "bimwave"}
    fake_icp_config = MagicMock(get_icp_by_slug=MagicMock(return_value=icp))
    fake_icp_query_ai = MagicMock(generate_icp_queries=MagicMock(side_effect=RuntimeError("model unavailable")))
    with patch.dict(sys.modules, {"leads.icp_config": fake_icp_config,
                                  "leads.icp_query_ai": fake_icp_query_ai}), \
         patch.object(router, "generate_query_combinations", return_value=["template query"]) as tmpl:
        result = router.generate_job_queries("bimwave", config)
    assert result == ["template query"]
    tmpl.assert_called_once()
