"""
Bot check on the survey landing page (/takesurvey).

A simple question any person answers instantly ("Which of these is a fruit?"),
issued by the server with a signed token, plus two silent checks:
  - a hidden "trap" field people never see (bots fill every input), and
  - a minimum time between showing the question and answering it.
The answer key never goes to the browser; /api/store verifies the token.
"""
import hashlib
import hmac
import os
import random
import time
from typing import Optional, Tuple

MIN_SECONDS = 2.0          # faster than this is not a person reading the page
MAX_AGE_SECONDS = 45 * 60  # a question is valid for 45 minutes

QUESTIONS = [
    {"id": "fruit", "text": "Which of these is a fruit?", "answer": "Apple", "others": ["Chair", "Car", "Shoe"]},
    {"id": "bark", "text": "Which of these animals barks?", "answer": "Dog", "others": ["Fish", "Cat", "Bird"]},
    {"id": "sky", "text": "What colour is a clear daytime sky?", "answer": "Blue", "others": ["Green", "Purple", "Brown"]},
    {"id": "week", "text": "Which of these is a day of the week?", "answer": "Monday", "others": ["January", "Summer", "Morning"]},
    {"id": "legs", "text": "How many legs does a cat have?", "answer": "Four", "others": ["Two", "Six", "Eight"]},
    {"id": "bigger", "text": "Which number is the biggest?", "answer": "100", "others": ["10", "5", "1"]},
    {"id": "cold", "text": "Which of these is cold?", "answer": "Ice", "others": ["Fire", "Sun", "Oven"]},
    {"id": "drink", "text": "Which of these can you drink?", "answer": "Water", "others": ["Stone", "Paper", "Sand"]},
    {"id": "fly", "text": "Which of these can fly?", "answer": "Bird", "others": ["Fish", "Horse", "Tree"]},
    {"id": "grass", "text": "What colour is fresh grass?", "answer": "Green", "others": ["Red", "Black", "Orange"]},
]
_BY_ID = {q["id"]: q for q in QUESTIONS}


def _secret() -> bytes:
    key = os.getenv("BOT_CHECK_SECRET") or os.getenv("SFW_INTERNAL_KEY") or os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET") or ""
    return key.encode() or b"torpedo-bot-check"


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:24]


# One more question after a wrong answer (owner, 2026-10-17): a mis-tap should
# not lose a real person. A second wrong answer ends the visit.
MAX_RETRIES = 1


def issue(attempt: int = 0) -> dict:
    """A fresh question for the landing page: text, shuffled options and a
    signed token. The attempt number is inside the signature, so the browser
    cannot reset it."""
    q = random.choice(QUESTIONS)
    options = [q["answer"], *q["others"]]
    random.shuffle(options)
    payload = f"{q['id']}.{time.time():.3f}.{int(attempt)}"
    return {"token": f"{payload}.{_sign(payload)}", "text": q["text"], "options": options,
            "attempt": int(attempt)}


def _parse(token: str) -> Optional[Tuple[str, float, int]]:
    """(question id, issued at, attempt) from a genuine token, else None.
    Tokens issued before 2026-10-17 have no attempt part (= attempt 0)."""
    parts = token.split(".")
    if len(parts) == 4:
        qid, ts_whole, ts_frac, sig = parts
        attempt_s, payload = "0", f"{qid}.{ts_whole}.{ts_frac}"
    elif len(parts) == 5:
        qid, ts_whole, ts_frac, attempt_s, sig = parts
        payload = f"{qid}.{ts_whole}.{ts_frac}.{attempt_s}"
    else:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        return qid, float(f"{ts_whole}.{ts_frac}"), int(attempt_s)
    except ValueError:
        return None


def verify(check: Optional[dict]) -> Tuple[bool, str]:
    """(passed, reason) for the bot-check part of an /api/store request."""
    if not isinstance(check, dict):
        return False, "missing"
    if str(check.get("trap") or "").strip():
        return False, "trap"
    parsed = _parse(str(check.get("token") or ""))
    if not parsed:
        return False, "bad_token"
    qid, issued_at, _attempt = parsed
    age = time.time() - issued_at
    if age < MIN_SECONDS:
        return False, "too_fast"
    if age > MAX_AGE_SECONDS:
        return False, "expired"
    q = _BY_ID.get(qid)
    if not q or str(check.get("answer") or "").strip() != q["answer"]:
        return False, "wrong_answer"
    return True, "ok"


def decide(check: Optional[dict]) -> Tuple[str, str, int]:
    """("pass" | "retry" | "term", reason, attempt for the next question).

    Retry instead of ending the visit when the failure says nothing about the
    person (2026-10-17: 231 of 647 security terms were "bad_token" -- a stale
    or unloaded question, not a wrong answer):
      - bad / expired token: a fresh question, attempt count unchanged;
      - first wrong answer: one more question.
    Still final at once: the hidden trap filled, answered faster than a person
    reads, no check sent at all, or a second wrong answer."""
    ok, reason = verify(check)
    if ok:
        return "pass", reason, 0
    if reason in ("missing", "trap", "too_fast"):
        return "term", reason, 0
    parsed = _parse(str((check or {}).get("token") or ""))
    attempt = parsed[2] if parsed else 0
    if reason in ("bad_token", "expired"):
        return "retry", reason, attempt
    if reason == "wrong_answer" and attempt < MAX_RETRIES:
        return "retry", reason, attempt + 1
    return "term", reason, attempt
