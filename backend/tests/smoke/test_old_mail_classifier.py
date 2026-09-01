"""
Smoke tests for the Phase 5 old_mail_classifier agent.

Seeds throwaway email_crm_extractions, runs the agent through the AI decision
engine, and verifies: contact/account matching + dedupe, approval-gated
attachment (nothing attaches until approved), autopilot auto-attach, provenance,
and idempotent re-runs. Throwaway DBs are dropped at the end.
"""

import pytest

pytestmark = pytest.mark.smoke

crm_service = None
ai_engine = None
agent = None
get_database = None
_import_error = None
try:
    from app.services import crm_service as _svc
    from app.services import ai_engine as _ai
    from agents import old_mail_classifier as _agent
    from database import get_database as _get_db
    crm_service, ai_engine, agent, get_database = _svc, _ai, _agent, _get_db
except Exception as e:  # pragma: no cover
    _import_error = e

SRC_DB = "crm_src_test"
EXTR_COL = "email_crm_extractions"


def _seed():
    col = get_database(SRC_DB)[EXTR_COL]
    col.delete_many({})
    col.insert_many(
        [
            {
                "email_id": "m1",
                "email_type": "client_rfq",
                "subject": "RFQ for CATI study",
                "contact": {"name": "Jane Doe", "email": "jane@acme.com", "company_name": "Acme"},
                "account": {"company_name": "Acme", "country": "India"},
                "rfq": {"is_rfq": True, "rfq_summary": "1000 CATI interviews"},
            },
            {
                "email_id": "m2",
                "email_type": "client_general",
                "subject": "Re: timelines",
                "contact": {"name": "John Roe", "email": "john@acme.com", "company_name": "Acme"},
                "account": {"company_name": "Acme", "country": "India"},
            },
            {
                "email_id": "m3",
                "email_type": "promotional",
                "subject": "Newsletter",
                "contact": {},  # no email, no company -> skipped
                "account": {},
            },
        ]
    )


@pytest.fixture()
def env():
    if agent is None:
        pytest.skip(f"imports unavailable: {_import_error}")
    crm_service.CRM_DB_NAME = "crm_db_test"
    try:
        crm_service._db().command("ping")
    except Exception as e:
        pytest.skip(f"MongoDB not reachable: {e}")
    _seed()
    yield
    crm_service._db().client.drop_database("crm_db_test")
    crm_service._db().client.drop_database(SRC_DB)


def test_dry_run_writes_nothing(env):
    stats = agent.run(dry_run=True, extractions_db=SRC_DB, extractions_collection=EXTR_COL)
    assert stats["scanned"] == 3
    assert crm_service._col("contacts").count_documents({}) == 0
    assert crm_service._col("ai_decisions").count_documents({}) == 0


def test_approve_mode_gates_attachment(env):
    stats = agent.run(autonomy_mode="approve", extractions_db=SRC_DB, extractions_collection=EXTR_COL)
    # m1 + m2 processed; m3 skipped (no contact/account).
    assert stats["processed"] == 2
    assert stats["queued"] == 2
    # Two Acme leads share one deduped account; two distinct contacts.
    assert crm_service._col("accounts").count_documents({}) == 1
    assert crm_service._col("contacts").count_documents({}) == 2
    # Nothing attached yet — activities only appear after approval.
    assert crm_service._col("activities").count_documents({}) == 0

    pending = ai_engine.list_queue(status="pending")
    assert len(pending) == 2

    # Approve one -> the email activity is attached to the contact.
    ai_engine.approve_action(pending[0]["_id"], user="reviewer")
    assert crm_service._col("activities").count_documents({}) == 1
    act = crm_service._col("activities").find_one({})
    assert act["type"] == "email"
    assert act["metadata"]["source"] == EXTR_COL
    assert act["contact_id"]


def test_autopilot_attaches_immediately(env):
    stats = agent.run(autonomy_mode="autopilot", extractions_db=SRC_DB, extractions_collection=EXTR_COL)
    assert stats["processed"] == 2
    assert stats["executed"] == 2
    assert stats["queued"] == 0
    # Low-risk attachment executed without human approval.
    assert crm_service._col("activities").count_documents({}) == 2


def test_idempotent_rerun(env):
    first = agent.run(autonomy_mode="autopilot", extractions_db=SRC_DB, extractions_collection=EXTR_COL)
    assert first["processed"] == 2

    second = agent.run(autonomy_mode="autopilot", extractions_db=SRC_DB, extractions_collection=EXTR_COL)
    assert second["processed"] == 0
    assert second["skipped_seen"] == 3  # m1, m2 already seen; m3 still unattachable
    assert crm_service._col("activities").count_documents({}) == 2
