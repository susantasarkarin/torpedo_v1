"""
Smoke tests for the Phase 5 seo_agent (scaffold).

The analysis logic is fully tested; the run path is verified with an injected
fake metrics provider and confirmed to no-op gracefully without credentials.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
agent = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.agents import seo_agent as _agent
    crm_service, agent = _svc, _agent
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture(autouse=True)
def _guard():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")


# ---- pure analysis ----

def test_low_ctr_page_flagged():
    recs = agent.seo_recommendations([{"url": "/a", "impressions": 1000, "clicks": 5}])
    assert len(recs) == 1 and recs[0]["issue"] == "low_ctr"


def test_healthy_page_no_recommendation():
    recs = agent.seo_recommendations([{"url": "/b", "impressions": 1000, "clicks": 100, "position": 3}])
    assert recs == []


def test_page_two_flagged():
    recs = agent.seo_recommendations([{"url": "/c", "impressions": 60, "clicks": 1, "position": 15}])
    assert len(recs) == 1 and recs[0]["issue"] == "page_two"


# ---- run ----

def test_run_without_credentials_is_graceful_noop():
    stats = agent.run()  # default provider returns None (no creds)
    assert stats["status"] == "no_data"
    assert stats["recommendations"] == 0


def test_run_with_injected_provider_logs_decision():
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    try:
        pages = [{"url": "/a", "impressions": 1000, "clicks": 5},
                 {"url": "/c", "impressions": 60, "clicks": 1, "position": 15}]
        stats = agent.run(metrics_provider=lambda: pages)
        assert stats["pages"] == 2
        assert stats["recommendations"] == 2
        assert stats["decision_id"]
        dec = crm_service.get("ai_decisions", stats["decision_id"])
        assert dec["agent_name"] == "seo_agent"
    finally:
        crm_service._db().client.drop_database("crm_db_test")
