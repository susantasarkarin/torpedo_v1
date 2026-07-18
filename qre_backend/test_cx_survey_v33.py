"""Routing tests for cx_survey_v33 (Rev 3 / v3.3, PII after S3) —
run: python test_cx_survey_v33.py"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import cx_survey as base_engine
import cx_survey_v33 as cx


def walk(answers: dict):
    """Drive the v3.3 engine using {qid: answer}. Returns (visited, ending)."""
    responses = {}
    qid = cx.first_question()
    visited = []
    guard = 0
    while qid is not None:
        guard += 1
        assert guard < 200, "routing loop guard tripped"
        visited.append(qid)
        ans = answers.get(qid)
        if ans is None:
            ans = _default_answer(qid)
        responses[qid] = ans
        reason = cx.terminate_reason(qid, ans)
        if reason:
            return visited, f"terminate:{reason}"
        qid = cx.next_question(qid, responses)
    return visited, "complete"


def _default_answer(qid):
    q = cx._BY_ID[qid]
    t = q["type"]
    if t == "open" or t == "record":
        return "n/a"
    if t == "grid_single":
        return {r["key"]: 1 for r in q.get("rows", [])}
    if t == "multi":
        opts = q.get("options") or [{"code": 1}]
        return [opts[0]["code"]]
    return q.get("options", [{"code": 1}])[0]["code"] if q.get("options") else 1


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        check.failed += 1
check.failed = 0


base = {
    "S1": [6], "S2": 2, "S6": 1, "S7": 1,
    "S11": 2,                         # valid age (default option is Under 18 → would terminate)
    "S9": [10],
    "B1": {"branch": 1, "app": 1, "internet": 5, "atm": 1, "phone": 1, "rm": 1},
    "B3": 1, "B7": 2, "C3": 2,
    "F1": 1, "F2": [1, 2], "F6": 1, "F12": 1,
    "G1": 1, "H1": 1,
    "H3": "HDFC Bank", "S4": "IDFC FIRST Bank",
}

# 1. Base isolation — the Rev-2/3 engine must NOT contain the PII module
check("base cx_survey has no P-questions (isolation)",
      not any(q["id"].startswith("P") for q in base_engine.QUESTION_BANK))
check("v3.3 bank = base bank + exactly P0-P3",
      [q["id"] for q in cx.QUESTION_BANK if not q["id"].startswith("P")]
      == [q["id"] for q in base_engine.QUESTION_BANK]
      and [q["id"] for q in cx.QUESTION_BANK if q["id"].startswith("P")]
      == ["P0", "P1", "P2", "P3"])

# 2. No IDFC at S3 → PII module skipped entirely, survey completes
v, e = walk(base)   # default S3 = [1] (Bank of Baroda)
check("P0-P3 skipped when S3 has no IDFC account",
      e == "complete" and not any(x.startswith("P") for x in v))

# 3. Valid PII path — asked between S3 and S4, completes
IDFC = cx.IDFC_BANK_CODE
pii_ok = {**base, "S3": [1, IDFC], "P0": 1, "P1": "Ravi Kumar",
          "P2": "98765 43210", "P3": "Don't know"}
v, e = walk(pii_ok)
check("P0-P3 asked when S3 includes IDFC, valid PII path completes",
      e == "complete" and all(x in v for x in ["P0", "P1", "P2", "P3"]))
check("P0-P3 sit between S3 and S4",
      v.index("S3") < v.index("P0") < v.index("P3") < v.index("S4"))

# 4. Terminations
v, e = walk({**pii_ok, "P0": 2})
check("P0 refusal terminates", e == "terminate:P0_pii_consent_refused" and v[-1] == "P0")

v, e = walk({**pii_ok, "P1": "   "})
check("P1 blank/refused terminates", e == "terminate:P1_name_refused")

v, e = walk({**pii_ok, "P2": "12345"})
check("P2 invalid mobile terminates", e == "terminate:P2_mobile_refused_or_invalid")

v, e = walk({**pii_ok, "P2": "+91-98765-43210"})
check("P2 with country code fails 10-digit validation", e == "terminate:P2_mobile_refused_or_invalid")

# 5. Base screener terminations still work through the v3.3 wrapper
v, e = walk({**pii_ok, "S1": [1]})
check("S1 termination inherited from base engine", e == "terminate:S1_industry_disqualified")

# 6. Config payload identifies the new version
cfg = cx.config_payload()
check("config_payload has survey_type cx_survey_v33 and P0 present",
      cfg["survey_type"] == "cx_survey_v33"
      and any(q["id"] == "P0" for q in cfg["questions"]))

print()
print("ALL PASS" if check.failed == 0 else f"{check.failed} FAILURE(S)")
raise SystemExit(1 if check.failed else 0)
