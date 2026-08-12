"""
SUPPRESSION DRIFT CHECK TESTS

The check has to be trustworthy the moment VM access lands, because it is the
interim guard on the only live legal exposure in this remediation.
"""

import os
import sys

import pytest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import suppression_drift as sd  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    try:
        c = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
                        serverSelectionTimeoutMS=1500)
        c.server_info()
    except ServerSelectionTimeoutError:
        pytest.skip("no mongo reachable")

    unsub_db, sender_db = "torpedo_test_drift_unsub", "torpedo_test_drift_sender"
    c.drop_database(unsub_db)
    c.drop_database(sender_db)
    monkeypatch.setattr(sd, "UNSUB_STORE", (unsub_db, "suppression_list"))
    monkeypatch.setattr(sd, "SENDER_STORE", (sender_db, "outreach_bounce_suppression"))
    yield c
    c.drop_database(unsub_db)
    c.drop_database(sender_db)


def _seed(client, unsub=(), sender=()):
    for e in unsub:
        client[sd.UNSUB_STORE[0]][sd.UNSUB_STORE[1]].insert_one({"email": e})
    for e in sender:
        client[sd.SENDER_STORE[0]][sd.SENDER_STORE[1]].insert_one({"email": e})


def test_identical_stores_are_healthy(client):
    _seed(client, unsub=["a@x.com", "b@x.com"], sender=["a@x.com", "b@x.com"])
    r = sd.check_drift(client)
    assert r.healthy
    assert r.total_drift == 0


def test_unsubscribe_invisible_to_sender_is_detected(client):
    """The dangerous direction: this person opted out and can still be mailed."""
    _seed(client, unsub=["optedout@x.com"], sender=[])
    r = sd.check_drift(client)
    assert not r.healthy
    assert r.missing_from_sender == ["optedout@x.com"]


def test_drift_in_the_other_direction_is_also_detected(client):
    """
    A one-directional check would call this healthy. It is not a sending risk,
    but it is still divergence between two stores that must agree, and the
    whole point of this check is catching that class of problem.
    """
    _seed(client, unsub=[], sender=["bounced@x.com"])
    r = sd.check_drift(client)
    assert not r.healthy
    assert r.missing_from_unsub == ["bounced@x.com"]
    assert r.missing_from_sender == []


def test_both_directions_at_once(client):
    _seed(client, unsub=["only-unsub@x.com", "both@x.com"],
          sender=["only-sender@x.com", "both@x.com"])
    r = sd.check_drift(client)
    assert r.missing_from_sender == ["only-unsub@x.com"]
    assert r.missing_from_unsub == ["only-sender@x.com"]
    assert r.total_drift == 2


def test_comparison_is_case_and_whitespace_insensitive(client):
    """Case difference is not drift; treating it as such would cry wolf."""
    _seed(client, unsub=["  Opted.Out@X.com "], sender=["opted.out@x.com"])
    assert sd.check_drift(client).healthy


def test_check_never_writes(client):
    _seed(client, unsub=["a@x.com"], sender=[])
    before = (client[sd.UNSUB_STORE[0]][sd.UNSUB_STORE[1]].count_documents({}),
              client[sd.SENDER_STORE[0]][sd.SENDER_STORE[1]].count_documents({}))
    sd.check_drift(client)
    after = (client[sd.UNSUB_STORE[0]][sd.UNSUB_STORE[1]].count_documents({}),
             client[sd.SENDER_STORE[0]][sd.SENDER_STORE[1]].count_documents({}))
    assert before == after, "the drift check must be read-only"


def test_report_is_json_serializable_for_alerting(client):
    _seed(client, unsub=["a@x.com"], sender=[])
    import json
    payload = json.loads(json.dumps(sd.check_drift(client).to_dict()))
    assert payload["healthy"] is False
    assert payload["missing_from_sender_count"] == 1
