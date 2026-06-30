"""Routing tests for cx_survey — run: python test_cx_survey.py"""
import cx_survey as cx


def walk(answers: dict):
    """Drive the engine using a dict of {qid: answer}. Returns (visited, ending).
    `ending` is 'complete' or a 'terminate:<reason>' string."""
    responses = {}
    qid = cx.first_question()
    visited = []
    guard = 0
    while qid is not None:
        guard += 1
        assert guard < 200, "routing loop guard tripped"
        visited.append(qid)
        ans = answers.get(qid)
        # default an answer if not supplied so the walk can proceed
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
        rows = q.get("rows", [])
        return {r["key"]: 1 for r in rows}
    if t == "multi":
        opts = q.get("options") or [{"code": 1}]
        return [opts[0]["code"]]
    return q.get("options", [{"code": 1}])[0]["code"] if q.get("options") else 1


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        check.failed += 1
check.failed = 0


# 1. Screener terminations
v, e = walk({"S1": [1]})
check("S1 banking-family terminates", e == "terminate:S1_industry_disqualified" and v == ["S1"])

v, e = walk({"S1": [6], "S2": 1})
check("S2 recent-research terminates", e == "terminate:S2_recent_research_participation")

v, e = walk({"S1": [6], "S2": 2, "S6": 3})
check("S6 inactive terminates", e == "terminate:S6_inactive_customer")

v, e = walk({"S1": [6], "S2": 2, "S6": 1, "S7": 3})
check("S7 non-decision-maker terminates", e == "terminate:S7_not_decision_maker")

# 2. Full path, no loan, RM=yes, branch+app used → all sections except E
base = {
    "S1": [6], "S2": 2, "S6": 1, "S7": 1,
    "S9": [10],                       # no loan → skip Section E
    "B1": {"branch": 1, "app": 1, "internet": 5, "atm": 1, "phone": 1, "rm": 1},
    "B3": 1,                          # has RM → B4,B5,B7 ; B6 skipped
    "B7": 2,                          # RM didn't change → B8 skipped
    "C3": 2,                          # didn't leave → C4 skipped
    "F1": 1, "F2": [1, 2],            # personal channel → F3-F7
    "F6": 1,                          # purchased → F7 asked
    "F12": 1,
    "G1": 1,                          # complained → G3,G4 ; G2 skipped
    "H1": 1,                          # considered switching → H2 asked
    "H3": "HDFC Bank", "S4": "IDFC FIRST Bank",  # different → H4 asked
}
v, e = walk(base)
check("no-loan path completes", e == "complete")
check("Section E skipped when S9=None", not any(x.startswith("E") for x in v))
check("B4/B5/B7 asked, B6/B8 skipped", all(x in v for x in ["B4", "B5", "B7"]) and "B6" not in v and "B8" not in v)
check("C section present (branch used), C4 skipped", "C1" in v and "C4" not in v)
check("D section present (app used)", "D1" in v)
check("F3-F7 asked (personal channel + purchased)", all(x in v for x in ["F3", "F4", "F5", "F6", "F7"]))
check("G3/G4 asked, G2 skipped", "G3" in v and "G4" in v and "G2" not in v)
check("H2 + H4 asked", "H2" in v and "H4" in v)
check("ends on I3", v[-1] == "I3")

# 3. No RM → B6 asked, B4/B5/B7/B8 skipped
v, e = walk({**base, "B3": 2})
check("B3=No → B6 asked; B4/B5/B7/B8 skipped",
      "B6" in v and not any(x in v for x in ["B4", "B5", "B7", "B8"]))

# 4. Branch never + app never → Sections C and D skipped
v, e = walk({**base, "B1": {"branch": 5, "app": 5, "internet": 5, "atm": 1, "phone": 1, "rm": 1}})
check("C and D skipped when branch+app+internet=Never",
      not any(x.startswith("C") for x in v) and not any(x.startswith("D") for x in v))

# 5. Loan path with new credit card → Section E incl. E10
loan = {**base, "S9": [8, 1]}  # includes new credit card (8)
v, e = walk(loan)
check("Section E present when S9 has loan", "E1" in v and "E12" in v)
check("E10 asked when S9 includes new credit card (8)", "E10" in v)

# 6. Loan path WITHOUT credit card → E10 skipped
v, e = walk({**base, "S9": [1]})
check("E10 skipped when no new credit card", "E1" in v and "E10" not in v)

# 7. F1=No → F2..F7 skipped but F8/F9/F10 asked
v, e = walk({**base, "F1": 2})
check("F1=No → F2-F7 skipped, F8 still asked",
      not any(x in v for x in ["F2", "F3", "F4", "F5", "F6", "F7"]) and "F8" in v and "F9" in v)

# 8. G1=No problems → Section G done after G1; H reached
v, e = walk({**base, "G1": 3})
check("G1=3 → G2/G3/G4 skipped", not any(x in v for x in ["G2", "G3", "G4"]) and "H1" in v)

# 9. G1=problem-but-didn't-complain → G2 asked, G3/G4 skipped
v, e = walk({**base, "G1": 2})
check("G1=2 → G2 asked, G3/G4 skipped", "G2" in v and "G3" not in v and "G4" not in v)

# 10. H1=No → H2 skipped; H3 same as primary → H4 skipped
v, e = walk({**base, "H1": 3, "H3": "IDFC FIRST Bank", "S4": "IDFC FIRST Bank"})
check("H1=No → H2 skipped", "H2" not in v)
check("H3==primary → H4 skipped", "H4" not in v)

print()
print("ALL PASS" if check.failed == 0 else f"{check.failed} FAILURE(S)")
raise SystemExit(1 if check.failed else 0)
