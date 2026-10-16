"""Landing-page security check: retry before ending a visit (2026-10-17).

Of 647 security terms since the check went live, 231 were "bad_token" (a
stale or unloaded question) and 410 wrong answers. A real person now gets a
fresh question for a stale token and one more question after a wrong answer;
bots (trap, too fast, no check at all) still end at once.
"""
import time

from services import bot_check as bc


def _answer(token_info, correct=True, aged=5.0, trap=""):
    q = next(q for q in bc.QUESTIONS if q["text"] == token_info["text"])
    return {"token": token_info["token"], "answer": q["answer"] if correct else q["others"][0], "trap": trap}


def _aged(monkeypatch, seconds):
    real = time.time()
    monkeypatch.setattr(bc.time, "time", lambda: real + seconds)


def test_right_answer_passes(monkeypatch):
    q = bc.issue()
    _aged(monkeypatch, 5)
    assert bc.decide(_answer(q))[0] == "pass"


def test_first_wrong_answer_gets_one_more_question_second_ends(monkeypatch):
    q = bc.issue()
    _aged(monkeypatch, 5)
    action, reason, attempt = bc.decide(_answer(q, correct=False))
    assert (action, reason, attempt) == ("retry", "wrong_answer", 1)
    monkeypatch.undo()
    q2 = bc.issue(attempt=attempt)
    assert q2["attempt"] == 1
    _aged(monkeypatch, 5)
    assert bc.decide(_answer(q2, correct=False))[:2] == ("term", "wrong_answer")
    assert bc.decide(_answer(q2))[0] == "pass"


def test_attempt_count_cannot_be_reset_by_the_browser(monkeypatch):
    q2 = bc.issue(attempt=1)
    forged = q2["token"].replace(".1.", ".0.", 1)
    _aged(monkeypatch, 5)
    # a tampered token fails its signature: treated as stale -> a fresh question,
    # never a free pass and never a reset of the attempt to 0 with a passing answer
    action, reason, _ = bc.decide({"token": forged, "answer": "x", "trap": ""})
    assert (action, reason) == ("retry", "bad_token")


def test_stale_or_missing_token_gets_a_fresh_question(monkeypatch):
    assert bc.decide({"token": "", "answer": "Monday", "trap": ""})[:2] == ("retry", "bad_token")
    q = bc.issue()
    _aged(monkeypatch, bc.MAX_AGE_SECONDS + 10)
    assert bc.decide(_answer(q))[:2] == ("retry", "expired")


def test_bots_still_end_at_once(monkeypatch):
    q = bc.issue()
    _aged(monkeypatch, 5)
    assert bc.decide(_answer(q, trap="http://spam"))[:2] == ("term", "trap")
    assert bc.decide(None)[:2] == ("term", "missing")
    monkeypatch.undo()
    q = bc.issue()
    _aged(monkeypatch, 0.5)
    assert bc.decide(_answer(q))[:2] == ("term", "too_fast")


def test_tokens_issued_before_the_change_still_work(monkeypatch):
    payload = f"week.{time.time():.3f}"
    legacy = {"token": f"{payload}.{bc._sign(payload)}", "answer": "Monday", "trap": ""}
    _aged(monkeypatch, 5)
    assert bc.decide(legacy)[0] == "pass"
    legacy["answer"] = "Summer"
    assert bc.decide(legacy)[:3] == ("retry", "wrong_answer", 1)
