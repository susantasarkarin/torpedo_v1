"""
Smoke tests for the Phase 5 lead_research_agent.

Uses an injected fake enricher (no Apollo/network) to verify: candidate
selection (leads missing fields), approval-gated enrichment, graceful no-data
skip, idempotency via cooldown, and dry-run safety. Isolated to a throwaway
crm_db.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
ai_engine = None
agent = None
_import_error = None
try:
    from backend.app.services import crm_service as _svc
    from backend.app.services import ai_engine as _ai
    from backend.agents import lead_research_agent as _agent
    crm_service, ai_engine, agent = _svc, _ai, _agent
except Exception as e:  # pragma: no cover
    _import_error = e


def fake_enricher(lead):
    if lead.get("email") == "rich@a.com":
        return {"title": "CEO", "phone": "+1-555-0100"}
    return None  # no data for everyone else


@pytest.fixture()
def env():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    # a: enrichable + data; b: enrichable + no data; c: already complete (not a candidate)
    crm_service.create("leads", {"email": "rich@a.com", "firstName": "A"})
    crm_service.create("leads", {"email": "poor@b.com", "firstName": "B"})
    crm_service.create("leads", {"email": "done@c.com", "title": "Eng", "phone": "+1", "company": "C"})
    yield
    crm_service._db().client.drop_database("crm_db_test")


def test_dry_run_writes_nothing(env):
    stats = agent.run(dry_run=True, enricher=fake_enricher)
    assert stats["candidates"] == 2  # a and b; c is complete
    assert crm_service._col("ai_decisions").count_documents({}) == 0


def test_approve_enriches_and_gates(env):
    stats = agent.run(autonomy_mode="approve", enricher=fake_enricher)
    assert stats["candidates"] == 2
    assert stats["enriched"] == 1      # only "a" had data
    assert stats["queued"] == 1
    assert stats["no_data"] == 1       # "b" returned nothing

    # Not applied yet — approval-gated.
    a = crm_service.find_account_by_name  # noqa (ensure module loaded)
    lead_a = crm_service._col("leads").find_one({"email": "rich@a.com"})
    assert not lead_a.get("title")

    pending = ai_engine.list_queue(status="pending")
    assert len(pending) == 1
    assert pending[0]["action_type"] == "update_record"

    # Approve -> the lead gets the enriched fields.
    ai_engine.approve_action(pending[0]["_id"], user="researcher")
    lead_a = crm_service._col("leads").find_one({"email": "rich@a.com"})
    assert lead_a["title"] == "CEO"
    assert lead_a["phone"] == "+1-555-0100"


def test_no_data_logs_observe_decision(env):
    agent.run(autonomy_mode="approve", enricher=fake_enricher)
    # "b" produced an observe decision marking no_data (so cooldown applies).
    dec = crm_service._col("ai_decisions").find_one(
        {"agent_name": "lead_research_agent", "input_summary.lead_id": {"$exists": True},
         "input_summary.result": "no_data"}
    )
    assert dec is not None


def test_idempotent_rerun(env):
    first = agent.run(autonomy_mode="approve", enricher=fake_enricher)
    assert first["enriched"] == 1
    second = agent.run(autonomy_mode="approve", enricher=fake_enricher)
    assert second["enriched"] == 0
    assert second["skipped_recent"] >= 2  # both a and b were decided on last run
