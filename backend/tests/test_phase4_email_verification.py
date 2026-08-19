"""
PHASE 4 — constructed-email gate and the bounce circuit breaker

outreach_qualification has always claimed it requires an email that is "not an
AI guess". It did not deliver that: the enricher constructs addresses from
cached domain patterns, labels them constructed/Predicted, and they passed
every gate. That is why bounce_recovery.py exists.
"""

import os
import sys
from datetime import datetime, timedelta

import pytest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import outreach_qualification as oq  # noqa: E402
from leads import bounce_circuit_breaker as bcb  # noqa: E402


NOW = datetime.utcnow()


# ===========================================================================
# The constructed-email gate
# ===========================================================================

@pytest.mark.parametrize("status", [
    "constructed", "Predicted", "PREDICTED", "guessed", "pattern", "inferred",
])
def test_constructed_addresses_fail_the_gate(status):
    """
    Case-insensitive: leads_enriched stores title case ("Predicted"), the MCP
    enricher stores lowercase ("constructed"). 3,522 rows carry "Predicted" in
    the sample examined — matching on exact case would have missed all of them.
    """
    assert oq.check_email_verification({"email_status": status}) == "constructed_unverified"


@pytest.mark.parametrize("status", ["verified", "valid", "deliverable"])
def test_verified_addresses_pass(status):
    assert oq.check_email_verification({"email_status": status}) is None


def test_unknown_provenance_is_treated_as_unverified():
    """
    Failing open would readmit every constructed address that simply lacks a
    label — which is most of them. 1,780 rows carry "Unknown" and 1,558 carry
    nothing at all.
    """
    assert oq.check_email_verification({"email_status": "Unknown"}) == "email_verification_unknown"
    assert oq.check_email_verification({}) == "email_verification_unknown"


def test_the_gate_is_strict_by_default():
    assert oq.REQUIRE_VERIFIED_EMAIL is True, (
        "the flag must default strict; a lax default reopens the hole silently")


def test_the_gate_can_be_disabled_deliberately(monkeypatch):
    monkeypatch.setattr(oq, "REQUIRE_VERIFIED_EMAIL", False)
    assert oq.check_email_verification({"email_status": "Predicted"}) is None


def test_constructed_reason_is_distinct_from_no_email():
    """
    Distinct reasons so the funnel separates "no usable address" from "an
    address we invented and never confirmed". They call for different fixes.
    """
    assert oq.check_email_verification({"email_status": "constructed"}) != "no_email"
    assert "constructed" in oq.check_email_verification({"email_status": "constructed"})


def test_smtp_probe_result_is_not_an_accepted_verification_status():
    """
    The SMTP probe must never be recorded as verification. It false-positives
    on catch-all domains and on Workspace/M365 accept-then-bounce setups —
    precisely the enterprise targets that matter. A 'no' is informative; a
    'yes' is not.
    """
    for smtp_ish in ("smtp_ok", "smtp_accepted", "rcpt_ok", "probe_ok"):
        assert smtp_ish not in oq.VERIFIED_EMAIL_STATUSES
        assert oq.check_email_verification({"email_status": smtp_ish}) == \
            "email_verification_unknown"


# ===========================================================================
# Bounce circuit breaker
# ===========================================================================

@pytest.fixture
def db():
    try:
        c = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
                        serverSelectionTimeoutMS=1500)
        c.server_info()
    except ServerSelectionTimeoutError:
        pytest.skip("no mongo reachable")
    name = "torpedo_test_breaker"
    c.drop_database(name)
    yield c[name]
    c.drop_database(name)


def _seed_sends(db, entity, total, bounced):
    docs = []
    for i in range(total):
        docs.append({"entity": entity, "sent_at": NOW - timedelta(days=1),
                     "status": "bounced" if i < bounced else "delivered"})
    db.sends.insert_many(docs)


def test_healthy_rate_does_not_trip(db):
    _seed_sends(db, "SFW", 1000, 5)          # 0.5%
    state = bcb.measure(db, "SFW")
    assert state.status == "ok"
    assert not state.should_pause


def test_rate_at_threshold_trips(db):
    _seed_sends(db, "SFW", 1000, 20)         # exactly 2%
    state = bcb.measure(db, "SFW")
    assert state.status == "tripped"
    assert state.should_pause


def test_small_sample_is_not_a_rate(db):
    """One bounce in three sends is 33% and means nothing."""
    _seed_sends(db, "SFW", 3, 1)
    state = bcb.measure(db, "SFW")
    assert state.status == "insufficient_data"
    assert not state.should_pause


def test_unreadable_data_fails_closed():
    """
    An unreadable bounce rate is the same epistemic state as a bad one — you
    do not know it is safe to send. Must pause, not assume healthy.
    """
    class Exploding:
        def __getitem__(self, _):
            raise RuntimeError("bounce store unavailable")

    state = bcb.measure(Exploding(), "SFW")
    assert state.status == "unreadable"
    assert state.should_pause, "an unreadable rate must fail closed"


def test_entities_are_measured_independently(db):
    _seed_sends(db, "SFW", 1000, 200)        # 20%
    _seed_sends(db, "BIM", 1000, 2)          # 0.2%
    assert bcb.measure(db, "SFW").should_pause
    assert not bcb.measure(db, "BIM").should_pause


def test_shared_sending_domain_is_flagged(monkeypatch):
    """
    While all three brands share one identity, a per-entity breaker cannot
    isolate the damage — one entity's bounces burn the other two.
    """
    monkeypatch.setenv("OUTREACH_SENDER_EMAIL", "hello@onedomain.com")
    rep = bcb.BreakerReport()
    rep.entities = [bcb.EntityBounceState(e, sending_domain="onedomain.com")
                    for e in bcb.ENTITIES]
    domains = {e.sending_domain for e in rep.entities}
    assert len(domains) == 1, "fixture sanity"
    assert bcb._sending_domain("hello@onedomain.com") == "onedomain.com"


def test_report_is_json_serializable():
    import json
    rep = bcb.BreakerReport(checked_at=NOW.isoformat())
    rep.entities = [bcb.EntityBounceState("SFW", sends=100, hard_bounces=50,
                                          rate=0.5, status="tripped")]
    payload = json.loads(json.dumps(rep.to_dict(), default=str))
    assert payload["healthy"] is False
    assert payload["entities"][0]["should_pause"] is True
