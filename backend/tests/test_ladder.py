"""Escalation ladder: Qwen -> Haiku -> Sonnet -> person, accepted only by schema + code checks."""
import json

import pytest

from platform_core import config_store, ladder, review_queue
from tests._fakemongo import FakeDB

SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": ["integer", "null"]}, "note": {"type": "string"}}}


@pytest.fixture
def env(monkeypatch):
    gov, ea = FakeDB(), FakeDB()
    monkeypatch.setattr(review_queue, "_col", lambda db=None: ea["review_queue_items"])
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    ladder._UNAVAILABLE.clear()
    return {"gov": gov, "ea": ea}


def _qwen(status="ok", data=None, problems=None):
    calls = []

    def run(**kw):
        calls.append(kw)
        assert kw["enqueue_review"] is False
        return {"status": status, "data": data, "problems": problems or [], "job_id": "q1"}
    run.calls = calls
    return run


def _cloud(answers):
    seen = []

    def t(**kw):
        seen.append(kw)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return json.dumps(a), 1000, 40
    t.seen = seen
    return t


def check_n(data, clean):
    return [] if data.get("n") and str(data["n"]) in clean else [f"N {data.get('n')} not in the mail"]


def test_qwen_answer_that_passes_checks_stops_the_ladder(env):
    q, cl = _qwen(data={"n": 500}), _cloud([])
    r = ladder.run(task="reply_classification", system="s", body="Need N=500", schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=cl, tiers=["qwen", "haiku", "sonnet"])
    assert r["status"] == "ok" and r["tier"] == "qwen" and not cl.seen


def test_failed_check_escalates_to_haiku_then_sonnet(env):
    q = _qwen(status="review", data={"n": 999}, problems=["N 999 not in the mail"])
    cl = _cloud([{"n": 600, "note": "x"}, {"n": 500, "note": "x"}])
    r = ladder.run(task="reply_classification", system="s", body="Sample N=500 India", schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=cl, tiers=["qwen", "haiku", "sonnet"])
    assert [a["tier"] for a in r["attempts"]] == ["qwen", "haiku", "sonnet"]
    assert cl.seen[0]["model"] == "claude-haiku-5-5" and cl.seen[1]["model"] == "claude-sonnet-5-5"
    assert cl.seen[0]["thinking"] == {"type": "disabled"} and cl.seen[1]["thinking"] == {"type": "between_tools"}
    assert r["data"]["n"] == 500 and r["tier"] == "sonnet"
    assert env["gov"]["ladder_spend"].find_one({})["usd"] > 0


def test_everything_fails_goes_to_one_review_item_with_best_attempt(env):
    q = _qwen(status="review", data={"n": 1}, problems=["N 1 not in the mail"])
    cl = _cloud([{"n": 2, "note": ""}])
    r = ladder.run(task="sender_type", system="s", body="nothing", schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=cl, ref={"collection": "x", "id": "1"})
    assert r["status"] == "review" and r["review_item"]
    assert env["ea"]["review_queue_items"].count_documents({}) == 1


def test_pii_masked_before_cloud_and_restored_after(env):
    q = _qwen(status="failed", data=None)
    cl = _cloud([{"n": 5, "note": "write to <EMAIL_1> or <PHONE_1>"}])
    body = "N=5. Contact raj.kumar@client.com or +91 98300 12345 for details"
    r = ladder.run(task="mail_summary", system="s", body=body, schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=cl, tiers=["qwen", "haiku"])
    sent = cl.seen[0]["user"]
    assert "raj.kumar@client.com" not in sent and "98300" not in sent and "<EMAIL_1>" in sent
    assert r["data"]["note"] == "write to raj.kumar@client.com or +91 98300 12345"


def test_no_credit_switches_cloud_off_and_budget_cap_skips_it(env):
    class BadRequestError(Exception):
        pass
    q = _qwen(status="review", data={"n": 1}, problems=["bad"])
    cl = _cloud([BadRequestError("Your credit balance is too low to access the Anthropic API.")])
    r = ladder.run(task="reply_classification", system="s", body="N=500", schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=cl, tiers=["qwen", "haiku", "sonnet"])
    assert r["attempts"][1]["status"] == "failed" and ladder._UNAVAILABLE.get("haiku")
    assert r["status"] == "review"
    ladder._UNAVAILABLE.clear()
    env["gov"]["ladder_spend"].insert_one({"_id": ladder._month(), "usd": 99.0})
    cl2 = _cloud([])
    r2 = ladder.run(task="reply_classification", system="s", body="N=500", schema=SCHEMA, code_check=check_n,
                    db=env["gov"], qwen_run=q, cloud_transport=cl2, tiers=["qwen", "haiku"])
    assert not cl2.seen and "budget" in r2["attempts"][1]["problems"][0]


def test_night_only_qwen_work_is_deferred_not_bought(env):
    q = _qwen(status="deferred")
    cl = _cloud([])
    r = ladder.run(task="lead_bucketing", system="s", body="x", schema=SCHEMA, db=env["gov"], qwen_run=q, cloud_transport=cl,
                   tiers=["qwen", "haiku"])
    assert r["status"] == "deferred" and not cl.seen


def test_always_review_task_still_goes_to_a_person_when_accepted(env):
    q = _qwen(data={"n": 500})
    r = ladder.run(task="rfq_extraction", system="s", body="N=500", schema=SCHEMA, code_check=check_n,
                   db=env["gov"], qwen_run=q, cloud_transport=_cloud([]), ref={"collection": "o", "id": "1"},
                   tiers=["qwen", "haiku", "sonnet"])
    assert r["status"] == "review" and r["tier"] == "qwen" and r["data"] == {"n": 500}


def test_strict_schema_closes_objects_and_makes_optional_nullable():
    s = ladder.strict_schema({"type": "object", "required": ["a"], "properties": {
        "a": {"type": "string", "maxLength": 5}, "b": {"type": "integer"},
        "items": {"type": "array", "items": {"type": "object", "properties": {"c": {"type": "number"}}}}}})
    assert s["additionalProperties"] is False and set(s["required"]) == {"a", "b", "items"}
    assert s["properties"]["b"]["type"] == ["integer", "null"] and "maxLength" not in s["properties"]["a"]
    inner = s["properties"]["items"]["items"]
    assert inner["additionalProperties"] is False and inner["required"] == ["c"]


def test_escalate_json_for_direct_callers_uses_their_own_check(env):
    good = {"body": "Hi Raj, checking in on the study."}
    chk = lambda d: [] if isinstance(d, dict) and d.get("body", "").startswith("Hi Raj") else ["bad greeting"]
    data, tier, tries = ladder.escalate_json(task="reengagement_draft", system="s", user="u", schema=None, check=chk,
                                             local=lambda: {"body": "Dear sir"}, db=env["gov"], cloud_transport=_cloud([good]))
    assert data == good and tier == "haiku" and [t["tier"] for t in tries] == ["qwen", "haiku"]
    data2, tier2, _ = ladder.escalate_json(task="reengagement_draft", system="s", user="u", schema=None, check=chk,
                                           local=lambda: good, db=env["gov"], cloud_transport=_cloud([]))
    assert tier2 == "qwen" and data2 == good
    boom = lambda: (_ for _ in ()).throw(RuntimeError("slot busy"))
    data3, tier3, tries3 = ladder.escalate_json(task="reengagement_draft", system="s", user="u", schema=None, check=chk,
                                                local=boom, db=env["gov"], cloud_transport=_cloud([{"body": "nope"}, {"body": "nope"}]))
    assert data3 is None and tier3 is None and "slot busy" in tries3[0]["problems"][0]
