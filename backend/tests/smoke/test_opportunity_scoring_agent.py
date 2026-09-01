"""
Smoke tests for the Phase 5 opportunity_scoring_agent.

Covers the pure scorer (no DB) and the end-to-end run that writes scores back to
open opportunities and logs a summary decision (throwaway crm_db).
"""

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
agent = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from agents import opportunity_scoring_agent as _agent
    crm_service, agent = _svc, _agent
except Exception as e:  # pragma: no cover
    _import_error = e


@pytest.fixture(autouse=True)
def _guard():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")


# ---- pure scorer ----

def test_high_value_recent_linked_scores_high():
    now = datetime(2026, 1, 1)
    r = agent.score_opportunity(
        {"amount": 50000, "stage": "negotiation", "status": "open", "account_id": "a", "contact_id": "c"},
        last_activity=now, now=now,
    )
    assert r["score"] == 100  # capped
    assert r["next_best_action"] == "push_to_close"


def test_stale_opportunity_recommends_follow_up():
    now = datetime(2026, 1, 1)
    r = agent.score_opportunity(
        {"amount": 0, "stage": "new", "status": "open"},
        last_activity=now - timedelta(days=40), now=now,
    )
    assert r["next_best_action"] == "follow_up"
    assert r["factors"]["days_idle"] == 40
    assert r["score"] == 5  # stage points only


def test_stage_drives_next_best_action():
    now = datetime(2026, 1, 1)
    r = agent.score_opportunity(
        {"amount": 2000, "stage": "qualified", "status": "open", "account_id": "a"},
        last_activity=now - timedelta(days=3), now=now,
    )
    assert r["next_best_action"] == "send_proposal"
    assert r["score"] == 2 + 20 + 15 + 5  # amount + stage + recency + linkage


# ---- end-to-end run ----

@pytest.fixture()
def env():
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    now = datetime.utcnow()
    col = crm_service._col("opportunities")
    col.insert_one({"title": "Big", "amount": 50000, "stage": "negotiation", "status": "open",
                    "account_id": "a", "contact_id": "c", "updated_at": now})
    col.insert_one({"title": "Stale", "amount": 0, "stage": "new", "status": "open",
                    "updated_at": now - timedelta(days=40)})
    col.insert_one({"title": "Won", "amount": 9999, "stage": "won", "status": "won", "updated_at": now})
    yield
    crm_service._db().client.drop_database("crm_db_test")


def test_run_scores_open_opps_and_logs_decision(env):
    stats = agent.run()
    assert stats["scanned"] == 2  # only open ones
    assert stats["scored"] == 2
    assert stats["decision_id"]

    big = crm_service._col("opportunities").find_one({"title": "Big"})
    stale = crm_service._col("opportunities").find_one({"title": "Stale"})
    assert big["score"] > stale["score"]
    assert big["next_best_action"] == "push_to_close"
    assert stale["next_best_action"] == "follow_up"

    # Top ranking in the logged decision is sorted by score desc.
    dec = crm_service.get("ai_decisions", stats["decision_id"])
    top = dec["input_summary"]["top"]
    assert top[0]["title"] == "Big"


def test_dry_run_writes_no_scores(env):
    stats = agent.run(dry_run=True)
    assert stats["scanned"] == 2
    assert crm_service._col("opportunities").find_one({"title": "Big"}).get("score") is None
    assert crm_service._col("ai_decisions").count_documents({}) == 0
