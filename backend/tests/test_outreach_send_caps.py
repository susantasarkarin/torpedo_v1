"""
OUTREACH SEND CAP + AI PERSONALISATION TESTS
============================================

Guards the fix for a live incident: all three Gmail accounts sent 1,983-2,004
emails in 24h against Google's 2,000/day hard cap, with a 30% bounce rate.
Root causes were (a) the cap was set AT the hard ceiling and (b) the check was
count-then-send, which is not atomic, so concurrent workers overshot it.

Also covers the AI personalisation guardrails: generated copy that is a
refusal, a placeholder, too short, or addressed to the wrong person must be
rejected in favour of the campaign template rather than mailed out.

Run with: pytest backend/tests/test_outreach_send_caps.py -v
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(monkeypatch, **env):
    """Import the router module fresh with the given environment."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for var in ("OUTREACH_DAILY_LIMIT_PER_MAILBOX",):
        if var not in env:
            monkeypatch.delenv(var, raising=False)
    import routers.cold_outreach_router as mod
    return importlib.reload(mod)


# ============================================
# CAP CONFIGURATION
# ============================================

def test_default_is_far_below_gmail_hard_cap(monkeypatch):
    mod = _load(monkeypatch)
    assert mod._GMAIL_HARD_CAP == 2000
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX == 500
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX < mod._GMAIL_HARD_CAP


def test_limit_is_configurable(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="300")
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX == 300


def test_limit_clamped_below_hard_cap(monkeypatch):
    """Configuring 2000 (or more) must be clamped - never send at the ceiling."""
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="5000")
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX == 1800
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX < mod._GMAIL_HARD_CAP


def test_garbage_limit_falls_back_to_default(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="not-a-number")
    assert mod._DAILY_SEND_LIMIT_PER_MAILBOX == 500


def test_per_mailbox_override(monkeypatch):
    mod = _load(monkeypatch,
                OUTREACH_DAILY_LIMIT_PER_MAILBOX="500",
                OUTREACH_DAILY_LIMIT__indira_at_surveyfieldwork_com="120")
    assert mod._daily_limit_for("indira@surveyfieldwork.com") == 120
    assert mod._daily_limit_for("meera@cogentixresearch.com") == 500


def test_per_mailbox_override_also_clamped(monkeypatch):
    mod = _load(monkeypatch,
                OUTREACH_DAILY_LIMIT__x_at_y_com="9999")
    assert mod._daily_limit_for("x@y.com") == 1800


# ============================================
# ATOMIC RESERVATION
# ============================================

class _FakeQuota:
    """Minimal stand-in for the outreach_daily_quota collection."""

    def __init__(self):
        self.docs = {}

    def count_documents(self, q, limit=None):
        return 1 if q["_id"] in self.docs else 0

    def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise Exception("duplicate key")
        self.docs[doc["_id"]] = dict(doc)

    def find_one_and_update(self, q, update, return_document=None):
        doc = self.docs.get(q["_id"])
        if doc is None:
            return None
        doc["count"] += update["$inc"]["count"]
        doc.update(update.get("$set", {}))
        return dict(doc)

    def update_one(self, q, update):
        doc = self.docs.get(q["_id"])
        if doc is None:
            return
        if "count" in q and isinstance(q["count"], dict):
            if not doc["count"] > q["count"]["$gt"]:
                return
        doc["count"] += update["$inc"]["count"]


class _FakeSends:
    def __init__(self, seed=0):
        self.seed = seed

    def count_documents(self, q):
        return self.seed


class _FakeDB:
    def __init__(self, seed=0, provider="gmail"):
        self._quota = _FakeQuota()
        self._sends = _FakeSends(seed)
        self._provider = provider

    def __getitem__(self, name):
        if name == "outreach_daily_quota":
            return self._quota
        if name == "outreach_sends_v2":
            return self._sends
        if name == "outreach_mailboxes":
            provider = self._provider
            return type("C", (), {
                "find_one": staticmethod(lambda q: {"provider": provider})})()
        raise KeyError(name)


def test_reservation_allows_up_to_limit(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="5")
    db = _FakeDB(seed=0)
    granted = sum(1 for _ in range(10)
                  if mod._reserve_daily_send_slot(db, "a@b.com"))
    assert granted == 5


def test_reservation_cannot_overshoot(monkeypatch):
    """The incident: concurrent workers pushed one account to 2,004/2,000."""
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="100")
    db = _FakeDB(seed=0)
    for _ in range(500):
        mod._reserve_daily_send_slot(db, "a@b.com")
    counter = db["outreach_daily_quota"].docs[mod._quota_id("a@b.com")]
    assert counter["count"] == 100, "counter overshot the cap"


def test_counter_seeded_from_existing_sends(monkeypatch):
    """A mid-day restart must not hand out a fresh allowance."""
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="500")
    db = _FakeDB(seed=498)  # already sent 498 today
    assert mod._reserve_daily_send_slot(db, "a@b.com") is True   # 499
    assert mod._reserve_daily_send_slot(db, "a@b.com") is True   # 500
    assert mod._reserve_daily_send_slot(db, "a@b.com") is False  # over


def test_release_returns_the_slot(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="2")
    db = _FakeDB(seed=0)
    assert mod._reserve_daily_send_slot(db, "a@b.com")
    assert mod._reserve_daily_send_slot(db, "a@b.com")
    assert not mod._reserve_daily_send_slot(db, "a@b.com")
    mod._release_daily_send_slot(db, "a@b.com")
    assert mod._reserve_daily_send_slot(db, "a@b.com"), "slot not reusable"


def test_release_never_goes_negative(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="5")
    db = _FakeDB(seed=0)
    mod._reserve_daily_send_slot(db, "a@b.com")
    for _ in range(5):
        mod._release_daily_send_slot(db, "a@b.com")
    counter = db["outreach_daily_quota"].docs[mod._quota_id("a@b.com")]
    assert counter["count"] >= 0


def test_ses_mailboxes_are_exempt(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="1")
    db = _FakeDB(seed=0, provider="ses")
    assert all(mod._reserve_daily_send_slot(db, "a@b.com") for _ in range(50))


def test_three_accounts_have_independent_quotas(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_DAILY_LIMIT_PER_MAILBOX="3")
    db = _FakeDB(seed=0)
    for account in ("susanta@bimwavesolutions.com",
                    "indira@surveyfieldwork.com",
                    "meera@cogentixresearch.com"):
        granted = sum(1 for _ in range(10)
                      if mod._reserve_daily_send_slot(db, account))
        assert granted == 3, f"{account} got {granted}"


# ============================================
# AI PERSONALISATION GUARDRAILS
# ============================================

LEAD = {
    "name": "Asha Rao", "first_name": "Asha", "title": "Head of BIM",
    "company_name": "Larsen & Toubro", "company_industry": "Construction",
}
GOOD_BODY = ("Hi Asha, running BIM delivery across a construction portfolio "
             "usually means coordination models pile up faster than anyone can "
             "review them, and the ISO 19650 paperwork lands on one desk. "
             "We take that modelling and coordination load off in-house teams "
             "so your engineers stay on design. Worth a quick chat about how "
             "your delivery pipeline is set up right now?")


def _gen(monkeypatch, payload):
    mod = _load(monkeypatch)
    from unittest.mock import patch
    from leads import bedrock_client
    with patch.object(bedrock_client, "converse", return_value=payload):
        return mod._generate_personalised_email(
            lead=LEAD, campaign_ctx={"value_proposition": "BIM outsourcing"},
            business_label="BIMwave", sender_name="Susanta", step_number=1)


def test_good_output_accepted(monkeypatch):
    import json
    subject, body_html = _gen(monkeypatch, json.dumps(
        {"subject": "BIM delivery load", "body": GOOD_BODY}))
    assert subject == "BIM delivery load"
    assert "<p>" in body_html and "Asha" in body_html


@pytest.mark.parametrize("payload", [
    '{"subject": "Hi", "body": "I cannot help with that request."}',
    '{"subject": "Hi", "body": "As an AI language model I must decline."}',
    '{"subject": "Hi", "body": "Hi [First Name], we do TODO things for you."}',
    '{"subject": "Hi", "body": "Hi {{first_name}}, lorem ipsum dolor sit amet."}',
])
def test_refusals_and_placeholders_rejected(monkeypatch, payload):
    assert _gen(monkeypatch, payload) == ("", "")


def test_wrong_recipient_name_rejected(monkeypatch):
    import json
    payload = json.dumps({"subject": "Hi", "body": GOOD_BODY.replace("Asha", "Priya")})
    assert _gen(monkeypatch, payload) == ("", "")


def test_too_short_body_rejected(monkeypatch):
    import json
    payload = json.dumps({"subject": "Hi", "body": "Hi Asha, quick question. Call?"})
    assert _gen(monkeypatch, payload) == ("", "")


def test_unparseable_output_falls_back(monkeypatch):
    assert _gen(monkeypatch, "not json at all") == ("", "")


def test_missing_fields_fall_back(monkeypatch):
    assert _gen(monkeypatch, '{"subject": "Only a subject"}') == ("", "")


def test_identity_swap_rejected(monkeypatch):
    # Reproduces the actual failure found 2026-09-16 testing a small local
    # model on this path: sender described as holding the RECIPIENT's own
    # title and company. Every other guardrail (name present, length,
    # no placeholder text) passes on this payload -- only the identity-swap
    # check should catch it.
    import json
    payload = json.dumps({
        "subject": "Hi Asha",
        "body": ("Hi Asha, I'm Susanta, the Head of BIM at Larsen & Toubro. "
                  "I'm impressed by your expertise and your commitment to "
                  "excellence in construction. We're always looking to expand "
                  "our team and bring in like-minded individuals. Let's talk "
                  "about how we can work together to achieve our goals soon."),
    })
    assert _gen(monkeypatch, payload) == ("", "")


def test_identity_correctly_attributed_accepted(monkeypatch):
    # Sanity check the swap detector isn't just rejecting any co-occurrence:
    # the sender's own name and company appearing together is fine.
    import json
    payload = json.dumps({"subject": "BIM delivery load", "body": GOOD_BODY})
    subject, body_html = _gen(monkeypatch, payload)
    assert subject == "BIM delivery load"
    assert "Asha" in body_html


def test_ai_generation_timeout_falls_back(monkeypatch):
    import time
    from unittest.mock import patch

    mod = _load(monkeypatch, OUTREACH_AI_TIMEOUT_SECONDS="0.2")
    from leads import bedrock_client

    def _slow_converse(*args, **kwargs):
        time.sleep(2)
        return '{"subject": "Hi Asha", "body": "' + GOOD_BODY + '"}'

    with patch.object(bedrock_client, "converse", side_effect=_slow_converse):
        result = mod._generate_personalised_email(
            lead=LEAD, campaign_ctx={"value_proposition": "BIM outsourcing"},
            business_label="BIMwave", sender_name="Susanta", step_number=1)
    assert result == ("", "")


def test_ai_can_be_disabled(monkeypatch):
    mod = _load(monkeypatch, OUTREACH_AI_PERSONALISATION="false")
    assert mod._AI_PERSONALISATION_ENABLED is False


def test_ai_enabled_by_default(monkeypatch):
    monkeypatch.delenv("OUTREACH_AI_PERSONALISATION", raising=False)
    mod = _load(monkeypatch)
    assert mod._AI_PERSONALISATION_ENABLED is True


# ============================================
# GLOBAL KILL SWITCH (outreach_kill_switch doc)
# ============================================
#
# This is the production kill switch born from the August incident -- a DB
# flag (not an env var) so pausing takes effect on the next send attempt with
# no deploy/restart, and it's checked independently of any campaign's own
# is_active flag. Nothing exercised _process_one_outreach_lead or this check
# directly before now; only the separate SENDING_ENABLED env-var kill switch
# in messaging/facade.py had coverage.

class _FakeCollection:
    """Records every find_one/update_one call so tests can assert not just
    the return value but whether a LATER check (campaign lookup) ever ran --
    that's what actually proves the kill switch short-circuited, since both
    the kill-switch branch and the campaign-inactive branch set the same
    workflow_status="paused" and would otherwise be indistinguishable."""

    def __init__(self, find_one_result=None):
        self._find_one_result = find_one_result
        self.find_one_calls = 0
        self.update_one_calls = []

    def find_one(self, query, *a, **kw):
        self.find_one_calls += 1
        return self._find_one_result

    def update_one(self, query, update):
        self.update_one_calls.append((query, update))


class _FakeKillSwitchDB:
    def __init__(self, kill_doc):
        self.outreach_kill_switch = _FakeCollection(find_one_result=kill_doc)
        # No campaign matches -> if the kill switch didn't block, the function
        # returns False here instead, for a documented, different reason.
        self.outreach_campaigns_v2 = _FakeCollection(find_one_result=None)
        self.outreach_leads_v2 = _FakeCollection()

    def __getitem__(self, name):
        return getattr(self, name)


_LEAD_RECORD = {"_id": "lead-1", "campaign_id": "camp-1", "current_step": 0}


@pytest.mark.parametrize("kill_doc", [
    None,                                  # missing doc -- fail-safe paused
    {"_id": "global", "paused": True},     # explicitly paused
])
def test_kill_switch_blocks_send_and_short_circuits(monkeypatch, kill_doc):
    mod = _load(monkeypatch)
    db = _FakeKillSwitchDB(kill_doc)
    result = mod._process_one_outreach_lead(db, _LEAD_RECORD)
    assert result is False
    assert db.outreach_kill_switch.find_one_calls == 1
    # The real proof: campaign lookup must never be reached.
    assert db.outreach_campaigns_v2.find_one_calls == 0
    # A pause HOLDS the lead: it is stamped with why it wasn't sent but its
    # workflow_status is left alone, so it is still selectable after resume. It
    # used to be written "paused" -- a status nothing selects and nothing
    # restored (see test_outreach_resume.py).
    stamp = db.outreach_leads_v2.update_one_calls[0][1]["$set"]
    assert "workflow_status" not in stamp
    assert "kill switch" in stamp["last_send_error"]


def test_kill_switch_resumed_allows_processing_to_continue(monkeypatch):
    mod = _load(monkeypatch)
    db = _FakeKillSwitchDB({"_id": "global", "paused": False})
    result = mod._process_one_outreach_lead(db, _LEAD_RECORD)
    # Still False overall (no matching campaign in this fake), but for a
    # DIFFERENT reason -- proving the kill switch let execution continue.
    assert result is False
    assert db.outreach_campaigns_v2.find_one_calls == 1
