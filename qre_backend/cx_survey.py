"""
CX survey definition + routing engine — IDFC FIRST Bank Customer Experience &
Sales Process Evaluation (Quantitative QRE, Rev. 2).

This module is fully self-contained and data-driven. It does NOT touch the
existing (health-syndicate) survey flow in routes/survey.py; the survey routes
dispatch to this engine only when a study's `type == "cx_survey"`.

Design
------
* QUESTION_BANK   ordered list of question definitions (sections S–I), used both
                  for routing and for the /config payload a respondent UI renders.
* CX_QUOTAS       Mumbai & Delhi NCR bank-customer quota frame.
* Routing model   a single ordered walk: after an answer we (a) check whether the
                  answer terminates, then (b) advance to the next question whose
                  `ask_if` predicate AND section gate are satisfied; if none
                  remain the survey completes. Section skips and conditional
                  blocks fall out of the askability predicates — there is no
                  separate skip bookkeeping.

All question IDs use the QRE's native codes (S1, A4, B3, …, I3).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Answer helpers
# ---------------------------------------------------------------------------

def _as_codes(answer) -> list[int]:
    """Coerce a single/multi answer into a list of int codes (best-effort)."""
    if answer is None:
        return []
    if isinstance(answer, dict):
        out = []
        for v in answer.values():
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(answer, list):
        out = []
        for v in answer:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return [int(answer)]
    except (TypeError, ValueError):
        return []


def _one(answer):
    codes = _as_codes(answer)
    return codes[0] if codes else None


def _grid_codes(answer) -> dict:
    """Return a {row_key: int_code} mapping for a grid answer (tolerant)."""
    if isinstance(answer, dict):
        out = {}
        for k, v in answer.items():
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = v
        return out
    return {}


# ---------------------------------------------------------------------------
# Scales (shared answer-option sets)
# ---------------------------------------------------------------------------

AGREE5 = ["Strongly disagree", "Disagree", "Neither", "Agree", "Strongly agree"]
SAT5 = ["Very dissatisfied", "Dissatisfied", "Neither", "Satisfied", "Very satisfied"]
EASY5 = ["Very difficult", "Difficult", "Neither", "Easy", "Very easy"]
FREQ5 = ["Weekly+", "Monthly", "Quarterly", "Rarely", "Never"]
SCALE_0_10 = list(range(0, 11))

# B1 channel rows (used for Section C / D gating). Order = display order.
B1_ROWS = ["branch", "app", "internet", "atm", "phone", "rm"]


# ---------------------------------------------------------------------------
# ask_if / section-gate predicates
#   Each takes the accumulated `responses` dict ({qid: answer}) and returns bool.
# ---------------------------------------------------------------------------

def _b1_channel_not_never(responses, row_key) -> bool:
    """True when B1 grid marks `row_key` as anything other than 'Never' (code 5).
    Missing B1 is treated as askable (don't hide sections on absent data)."""
    b1 = responses.get("B1")
    if b1 is None:
        return True
    grid = _grid_codes(b1)
    if row_key in grid:
        return grid[row_key] != 5
    return True


def _has_loan(responses) -> bool:
    """S9 routes to Section E unless it is exactly 'None of these' (code 10)."""
    codes = _as_codes(responses.get("S9"))
    return bool(codes) and codes != [10] and 10 not in codes


def _f_personal_channel(responses) -> bool:
    """F3–F7 gate: a personal channel (branch staff / RM / phone) at F2."""
    if _one(responses.get("F1")) != 1:
        return False
    return any(c in (1, 2, 3) for c in _as_codes(responses.get("F2")))


# Per-question ask_if predicates. Absent ⇒ always askable (subject to section gate).
ASK_IF = {
    "B4": lambda r: _one(r.get("B3")) == 1,
    "B5": lambda r: _one(r.get("B3")) == 1,
    "B6": lambda r: _one(r.get("B3")) == 2,
    "B7": lambda r: _one(r.get("B3")) == 1,
    "B8": lambda r: _one(r.get("B7")) == 1,
    "C4": lambda r: _one(r.get("C3")) == 1,
    "E10": lambda r: 8 in _as_codes(r.get("S9")),
    "F2": lambda r: _one(r.get("F1")) == 1,
    "F3": _f_personal_channel,
    "F4": _f_personal_channel,
    "F5": _f_personal_channel,
    "F6": _f_personal_channel,
    "F7": lambda r: _one(r.get("F6")) == 1,
    "G2": lambda r: _one(r.get("G1")) == 2,
    "G3": lambda r: _one(r.get("G1")) == 1,
    "G4": lambda r: _one(r.get("G1")) == 1,
    "H2": lambda r: _one(r.get("H1")) in (1, 2),
    # H4 only if the best-CX bank named at H3 is not the respondent's primary bank.
    "H4": lambda r: bool(r.get("H3")) and str(r.get("H3")) != str(r.get("S4")),
}

# Whole-section gates (apply to every qid in the section).
SECTION_GATE = {
    "C": lambda r: _b1_channel_not_never(r, "branch"),
    "D": lambda r: _b1_channel_not_never(r, "app") or _b1_channel_not_never(r, "internet"),
    "E": _has_loan,
}


# ---------------------------------------------------------------------------
# Terminations (screener + quality). Returns a reason string or None.
# ---------------------------------------------------------------------------

def terminate_reason(qid, answer) -> str | None:
    if qid == "S1" and any(c in (1, 2, 3, 4, 5) for c in _as_codes(answer)):
        return "S1_industry_disqualified"
    if qid == "S2" and _one(answer) == 1:
        return "S2_recent_research_participation"
    if qid == "S6" and _one(answer) in (3, 4):
        return "S6_inactive_customer"
    if qid == "S7" and _one(answer) == 3:
        return "S7_not_decision_maker"
    return None


# ---------------------------------------------------------------------------
# Question bank (ordered). `id` uses native QRE codes.
# `type`: single | multi | grid_single | open | record
# ---------------------------------------------------------------------------

def _opts(*pairs):
    return [{"code": c, "label": l} for c, l in pairs]


# Bank list shown at S3 (banks held), S4 (primary bank) and H3 (best-CX bank).
_BANK_NAMES = [
    "Bank of Baroda", "Bank of India", "Bank of Maharashtra", "Canara Bank",
    "Central Bank of India", "Indian Bank", "Indian Overseas Bank", "Punjab National Bank",
    "Punjab & Sind Bank", "State Bank of India", "UCO Bank", "Union Bank of India",
    "Axis Bank Ltd.", "Bandhan Bank", "Catholic Syrian Bank Ltd.", "City Union Bank Ltd.",
    "Dhanlaxmi Bank Ltd.", "Development Credit Bank Ltd.", "Federal Bank Ltd.", "HDFC Bank Ltd.",
    "ICICI Bank Ltd.", "IDBI Bank Ltd.", "IDFC First Bank", "Indusind Bank Ltd.",
    "Karnataka Bank Ltd.", "Karur Vysya Bank Ltd.", "Kotak Mahindra Bank Ltd.",
    "Tamilnad Mercantile Bank Ltd.", "The Jammu & Kashmir Bank Ltd.", "The Nainital Bank Ltd.",
    "RBL Bank", "The South Indian Bank Ltd.", "Yes Bank Ltd.", "BNP Paribas", "Citi Bank",
    "DBS Bank Ltd.", "Deutsche Bank", "HSBC", "Standard Chartered Bank", "National Westminster Bank",
]
BANKS = [{"code": i + 1, "label": name} for i, name in enumerate(_BANK_NAMES)]
BANKS.append({"code": len(_BANK_NAMES) + 1, "label": "Other (specify)", "specify": True})


QUESTION_BANK = [
    # ---------------- Section S — Screener ----------------
    {"id": "S1", "section": "S", "type": "multi", "text": "Do you or any member of your close family work in any of the following?",
     "options": _opts((1, "Banking or financial services"), (2, "Insurance"), (3, "Market research"),
                      (4, "Advertising / media / PR"), (5, "Journalism"), (6, "None of these"))},
    {"id": "S2", "section": "S", "type": "single", "text": "Have you participated in any market research survey or discussion in the past 6 months?",
     "options": _opts((1, "Yes"), (2, "No"))},
    {"id": "S3", "section": "S", "type": "multi", "text": "Which banks do you currently hold an account or product with?",
     "instruction": "RECORD ALL. SHOW LIST + OTHER (SPECIFY).", "options": BANKS},
    {"id": "S4", "section": "S", "type": "single", "text": "And which of these would you consider your MAIN or PRIMARY bank — the one you use most?",
     "instruction": "All following questions refer to this bank.", "options": BANKS},
    {"id": "S5", "section": "S", "type": "single", "text": "How long have you been a customer of [PRIMARY BANK]?",
     "options": _opts((1, "Less than 1 year"), (2, "1 – 3 years"), (3, "4 – 7 years"), (4, "8 – 15 years"), (5, "More than 15 years"))},
    {"id": "S6", "section": "S", "type": "single", "text": "When did you last interact with [PRIMARY BANK] in any way — branch, app, ATM, phone, or staff contact?",
     "options": _opts((1, "Within the past month"), (2, "1 – 3 months ago"), (3, "More than 3 months ago"), (4, "Can't recall"))},
    {"id": "S7", "section": "S", "type": "single", "text": "When it comes to decisions about banking and financial products in your household, are you…?",
     "options": _opts((1, "The main decision-maker"), (2, "A joint decision-maker"), (3, "Not involved in these decisions"))},
    {"id": "S8", "section": "S", "type": "multi", "text": "Which of these products do you currently hold with [PRIMARY BANK]?",
     "instruction": "ROTATE. MUST HOLD AT LEAST ONE.",
     "options": _opts((1, "Savings account"), (2, "Current account"), (3, "Fixed / recurring deposit"), (4, "Credit card"),
                      (5, "Home loan"), (6, "Personal / auto / other loan"), (7, "Insurance (life / health / general)"),
                      (8, "Mutual funds / investments / demat"), (9, "Other (specify)"))},
    {"id": "S9", "section": "S", "type": "multi", "text": "And in the LAST 24 MONTHS, have you taken any of the following — even if you no longer hold it, or hold it with a different bank?",
     "instruction": "ROTATE. NONE = EXCLUSIVE. Determines routing to Section E. Carry single most recent/highest-value as [LOAN PRODUCT].",
     "options": _opts((1, "Home loan"), (2, "Personal loan"), (3, "Vehicle loan"), (4, "Loan against property (LAP)"),
                      (5, "Business loan"), (6, "Education loan"), (7, "Gold loan"), (8, "New credit card"),
                      (9, "Consumer durable loan / overdraft / cash credit"), (10, "None of these"))},
    {"id": "S10", "section": "S", "type": "single", "text": "Which gender do you identify as?",
     "instruction": "RECORD GENDER. Check gender quota.",
     "options": _opts((1, "Female"), (2, "Male"), (3, "Other / prefer not to say"))},
    {"id": "S11", "section": "S", "type": "single", "text": "Which age group do you fall into?",
     "instruction": "ASK AGE. Check age quota.",
     "options": _opts((1, "18 – 24"), (2, "25 – 34"), (3, "35 – 44"), (4, "45 – 54"), (5, "55 +"))},

    # ---------------- Section A — Relationship, Satisfaction & Trust ----------------
    {"id": "A1", "section": "A", "type": "single", "text": "Overall, how satisfied are you with [PRIMARY BANK]?",
     "scale": SCALE_0_10, "instruction": "0 = Extremely dissatisfied, 10 = Extremely satisfied."},
    {"id": "A2", "section": "A", "type": "single", "text": "How likely are you to recommend [PRIMARY BANK] to friends or family?",
     "scale": SCALE_0_10, "instruction": "NPS. 0 = Not at all likely, 10 = Extremely likely."},
    {"id": "A3", "section": "A", "type": "open", "text": "What is the main reason for your score?", "instruction": "MANDATORY. RECORD VERBATIM."},
    {"id": "A4", "section": "A", "type": "grid_single", "text": "How much do you agree or disagree with each statement about [PRIMARY BANK]?",
     "scale": AGREE5, "instruction": "ROTATE.",
     "rows": [
         {"key": "money_safe", "label": "My money is safe with this bank"},
         {"key": "serves_my_interest", "label": "This bank's product recommendations serve MY interests, not just sales targets"},
         {"key": "upfront_charges", "label": "The bank is upfront about all charges and fees"},
         {"key": "terms_clear", "label": "Product terms and conditions are explained clearly before I sign"},
         {"key": "values_longterm", "label": "The bank values long-term customers like me"},
         {"key": "trust_advice", "label": "I trust the advice given by this bank's staff"},
         {"key": "branch_atm_findable", "label": "This bank's branches and ATMs are conveniently located and easy to find"},
         {"key": "relationship_continuity", "label": "I can always reach the same person or team for help, rather than starting over with someone new"},
     ]},

    # ---------------- Section B — Channel, Preference & RM ----------------
    {"id": "B1", "section": "B", "type": "grid_single", "text": "How often do you use each of the following to deal with [PRIMARY BANK]?",
     "scale": FREQ5,
     "rows": [
         {"key": "branch", "label": "Branch visit"},
         {"key": "app", "label": "Mobile banking app"},
         {"key": "internet", "label": "Internet banking (browser)"},
         {"key": "atm", "label": "ATM"},
         {"key": "phone", "label": "Phone banking / call centre"},
         {"key": "rm", "label": "Relationship manager / bank staff contact"},
     ]},
    {"id": "B2", "section": "B", "type": "grid_single", "text": "For each task, which channel would you PREFER to use?",
     "columns": ["Branch / person", "App / online", "Phone", "No preference"],
     "rows": [
         {"key": "open_fd", "label": "Opening a fixed deposit"},
         {"key": "apply_loan", "label": "Applying for a loan"},
         {"key": "resolve_complaint", "label": "Resolving a problem / complaint"},
         {"key": "buy_insurance", "label": "Buying insurance or investments"},
         {"key": "transfers", "label": "Everyday transfers & payments"},
     ]},
    {"id": "B3", "section": "B", "type": "single", "text": "Do you have a relationship manager (RM) or a specific named person at [PRIMARY BANK] you deal with?",
     "options": _opts((1, "Yes"), (2, "No"))},
    {"id": "B4", "section": "B", "type": "single", "text": "In the past 6 months, when your RM has contacted you, what was it MOSTLY about?",
     "options": _opts((1, "Mostly servicing my existing needs / requests"), (2, "Mostly offering me new products"),
                      (3, "An even mix of both"), (4, "RM has not contacted me in this period"))},
    {"id": "B5", "section": "B", "type": "single", "text": "How would you rate your RM's responsiveness and availability when YOU need them?",
     "options": _opts((1, "Very poor"), (2, "Poor"), (3, "Average"), (4, "Good"), (5, "Very good"))},
    {"id": "B6", "section": "B", "type": "single", "text": "Would you value having a dedicated relationship manager at [PRIMARY BANK]?",
     "options": _opts((1, "Yes, definitely"), (2, "Maybe, if offered"), (3, "No, not needed"))},
    {"id": "B7", "section": "B", "type": "single", "text": "In the past 12 months, has the person/RM you usually deal with at [PRIMARY BANK] changed or left?",
     "options": _opts((1, "Yes"), (2, "No"), (3, "Not sure"))},
    {"id": "B8", "section": "B", "type": "single", "text": "How was that transition handled?",
     "options": _opts((1, "Smoothly — the new person already knew my situation"), (2, "Okay, but I had to re-explain my situation from scratch"),
                      (3, "Poorly — I lost touch with the bank for a while"), (4, "Other (specify)"))},

    # ---------------- Section C — Branch Experience (gated on B1 branch != Never) ----------------
    {"id": "C1", "section": "C", "type": "single", "text": "How long did you wait to be served on your most recent branch visit?",
     "options": _opts((1, "No wait / under 5 minutes"), (2, "5 – 15 minutes"), (3, "16 – 30 minutes"), (4, "More than 30 minutes"))},
    {"id": "C2", "section": "C", "type": "grid_single", "text": "Thinking of your branch experiences in the past 3 months, how satisfied are you with each of the following?",
     "scale": SAT5, "instruction": "ROTATE.",
     "rows": [
         {"key": "courtesy", "label": "Courtesy of staff"},
         {"key": "knowledge", "label": "Staff knowledge & competence"},
         {"key": "speed", "label": "Speed of service"},
         {"key": "queue", "label": "Queue / waiting management"},
         {"key": "one_visit", "label": "Getting the task done in one visit"},
         {"key": "ambience", "label": "Branch ambience & comfort"},
     ]},
    {"id": "C3", "section": "C", "type": "single", "text": "In the past 6 months, have you ever left a branch WITHOUT completing what you came for?",
     "options": _opts((1, "Yes"), (2, "No"))},
    {"id": "C4", "section": "C", "type": "single", "text": "What was the main reason?",
     "options": _opts((1, "Queue / wait too long"), (2, "Required documents not accepted / more demanded"),
                      (3, "Staff unavailable or unhelpful"), (4, "System / server down"),
                      (5, "Sent to another branch or channel"), (6, "Other (specify)"))},
    {"id": "C5", "section": "C", "type": "single", "text": "In the past 6 months, how often have you had to make MULTIPLE visits or contacts to the bank for the SAME issue?",
     "instruction": "ASK ALL (not conditional on branch use).",
     "options": _opts((1, "Never — always resolved in one visit/contact"), (2, "Rarely"), (3, "Sometimes"), (4, "Often"))},
    {"id": "C6", "section": "C", "type": "single", "text": "And how often have you had to REPEAT information you'd already given, to a different person at the bank?",
     "options": _opts((1, "Never"), (2, "Rarely"), (3, "Sometimes"), (4, "Often"))},
    {"id": "C7", "section": "C", "type": "grid_single", "text": "On your most recent branch visit, did staff…?",
     "columns": ["Yes", "No"],
     "rows": [
         {"key": "greet", "label": "Greet you promptly when you arrived"},
         {"key": "focused", "label": "Stay focused on you, without using their phone for personal reasons"},
         {"key": "private_area", "label": "Have access to a private area for any sensitive discussion (e.g. loan, large transaction, complaint)"},
     ]},
    {"id": "C8", "section": "C", "type": "single", "text": "Was a Branch Manager visible or reachable during your visit, if you needed one?",
     "options": _opts((1, "Yes, visible and reachable"), (2, "No, not visible"), (3, "Didn't need to see the BM"), (4, "Don't know / can't recall"))},

    # ---------------- Section D — Digital Banking (gated on B1 app/internet != Never) ----------------
    {"id": "D1", "section": "D", "type": "multi", "text": "Which of these have you done digitally (app or internet banking) in the past 3 months?",
     "instruction": "ROTATE.",
     "options": _opts((1, "Money transfers / payments"), (2, "Bill payments / recharges"), (3, "Opened FD / RD"),
                      (4, "Card management (block, limits, PIN)"), (5, "Downloaded statements / certificates"),
                      (6, "Applied for loan / credit card"), (7, "Bought insurance / investments"), (8, "Raised a service request or complaint"))},
    {"id": "D2", "section": "D", "type": "multi", "text": "In the past 3 months, which problems have you faced with the bank's digital channels?",
     "instruction": "ROTATE. NONE = EXCLUSIVE.",
     "options": _opts((1, "Login / OTP problems"), (2, "App crashes or freezes"), (3, "Failed or stuck transactions"),
                      (4, "Hard to find features / confusing menus"), (5, "Slow performance"), (6, "Feature I needed wasn't available"),
                      (7, "Language / clarity issues"), (8, "None of these"))},
    {"id": "D3", "section": "D", "type": "single", "text": "Overall, how satisfied are you with [PRIMARY BANK]'s digital banking?",
     "scale": SCALE_0_10, "instruction": "0 = Extremely dissatisfied, 10 = Extremely satisfied."},
    {"id": "D4", "section": "D", "type": "grid_single", "text": "For each of the following, would you feel comfortable doing it ENTIRELY through the app/online banking, or would you prefer to do it at a branch?",
     "columns": ["App entirely", "Prefer branch", "Either way"],
     "rows": [
         {"key": "balance", "label": "Checking your balance"},
         {"key": "small_transfer", "label": "Transferring a small amount (under ₹5,000)"},
         {"key": "large_transfer", "label": "Transferring a large amount (above ₹50,000)"},
         {"key": "apply_loan", "label": "Applying for a loan"},
         {"key": "report_fraud", "label": "Reporting suspected fraud on your account"},
     ]},

    # ---------------- Section E — Product & Loan Journey (gated on S9 != None) ----------------
    {"id": "E1", "section": "E", "type": "multi", "text": "Thinking about your [LOAN PRODUCT] taken in the last 24 months — why did you choose [PRIMARY BANK] for this, rather than another lender?",
     "instruction": "ROTATE.",
     "options": _opts((1, "Existing relationship / convenience"), (2, "Better interest rate / charges than alternatives"),
                      (3, "Faster approval / disbursement"), (4, "Recommended by bank staff / RM"),
                      (5, "Recommended by a third party (dealer, agent, friend)"), (6, "No real choice — only option available to me"),
                      (7, "Other (specify)"))},
    {"id": "E2", "section": "E", "type": "single", "text": "How easy or difficult was the APPLICATION process to understand, from start to finish?", "scale": EASY5},
    {"id": "E3", "section": "E", "type": "single", "text": "Were you asked to submit the same documents more than once during this process?",
     "options": _opts((1, "Yes, multiple times"), (2, "Yes, once extra"), (3, "No, only once"), (4, "Can't recall"))},
    {"id": "E4", "section": "E", "type": "single", "text": "Was the timeline you were given for approval/disbursement met?",
     "options": _opts((1, "Yes, on time or earlier"), (2, "Slightly delayed"), (3, "Significantly delayed"), (4, "No timeline was given to me"))},
    {"id": "E5", "section": "E", "type": "grid_single", "text": "Were each of the following clearly explained to you BEFORE you signed for this [LOAN PRODUCT]?",
     "columns": ["Yes", "No", "Can't recall"],
     "rows": [
         {"key": "charges", "label": "All applicable charges and fees (processing, etc.)"},
         {"key": "rate_structure", "label": "Interest rate structure / revision conditions"},
         {"key": "prepay", "label": "Prepayment or foreclosure charges"},
         {"key": "addon", "label": "Any insurance or add-on product bundled with this loan/product"},
     ]},
    {"id": "E6", "section": "E", "type": "single", "text": "Was any insurance or other add-on product bundled with this [LOAN PRODUCT]?",
     "options": _opts((1, "Yes, and it felt mandatory to get approval"), (2, "Yes, but it was clearly optional"),
                      (3, "No add-on was bundled"), (4, "Can't recall"))},
    {"id": "E7", "section": "E", "type": "single", "text": "After the [LOAN PRODUCT] was disbursed / activated, how easy has it been to get SUPPORT when you needed it?",
     "options": _opts((1, "Very difficult"), (2, "Difficult"), (3, "Neither"), (4, "Easy"), (5, "Very easy"), (6, "Haven't needed support so far"))},
    {"id": "E8", "section": "E", "type": "multi", "text": "Have you faced any of the following issues with this [LOAN PRODUCT] AFTER taking it?",
     "instruction": "ROTATE. NONE = EXCLUSIVE.",
     "options": _opts((1, "Unexpected charges / deductions"), (2, "Difficulty getting statements / closure documents"),
                      (3, "Errors in account / credit bureau reporting"), (4, "Repeated calls/offers to upgrade or take a top-up"),
                      (5, "Poor communication about rate or EMI changes"), (6, "None of these"))},
    {"id": "E9", "section": "E", "type": "single", "text": "Knowing what you know now, would you take this product — or use [PRIMARY BANK] for this — again?",
     "options": _opts((1, "Yes, definitely"), (2, "Probably yes"), (3, "Probably not"), (4, "Definitely not"))},
    {"id": "E10", "section": "E", "type": "grid_single", "text": "Thinking about your new credit card specifically — have you experienced any of the following?",
     "columns": ["Yes", "No"],
     "rows": [
         {"key": "fee_unclear", "label": "Annual fee / charges were NOT clearly explained when I took the card"},
         {"key": "dispute", "label": "I have had a billing dispute or fraud issue with this card"},
         {"key": "pressured_upgrade", "label": "I have been pressured to upgrade this card or take an add-on card"},
     ]},
    {"id": "E11", "section": "E", "type": "single", "text": "While your [LOAN PRODUCT] application was being processed, did the bank proactively update you on status, or did you have to follow up yourself?",
     "options": _opts((1, "Bank proactively updated me"), (2, "I had to follow up myself"), (3, "A mix of both"), (4, "Not applicable — no delays"))},
    {"id": "E12", "section": "E", "type": "single", "text": "Now that your [LOAN PRODUCT] is active, who do you primarily contact if you need help with it?",
     "options": _opts((1, "The same person who sold it to me"), (2, "A different servicing team or RM"), (3, "The branch generally"),
                      (4, "Call centre / app self-service"), (5, "I'm not sure who to contact"))},

    # ---------------- Section F — Sales & Cross-sell (core) ----------------
    {"id": "F1", "section": "F", "type": "single", "text": "In the past 6 months, has [PRIMARY BANK] suggested or offered you any additional product — for example a credit card, insurance, loan, or investment?",
     "options": _opts((1, "Yes"), (2, "No"), (3, "Can't recall"))},
    {"id": "F2", "section": "F", "type": "multi", "text": "Through which channels were products suggested to you?",
     "options": _opts((1, "Branch staff during a visit"), (2, "Relationship manager"), (3, "Phone call from the bank"),
                      (4, "SMS / email / WhatsApp"), (5, "App notification / banner"), (6, "Other (specify)"))},
    {"id": "F3", "section": "F", "type": "single", "text": "Thinking of the MOST RECENT recommendation made by a bank employee: did the employee ask about your needs or situation BEFORE suggesting the product?",
     "options": _opts((1, "Yes, asked in detail"), (2, "Asked briefly"), (3, "No, went straight to the product"), (4, "Can't recall"))},
    {"id": "F4", "section": "F", "type": "grid_single", "text": "Were each of the following clearly explained to you?",
     "columns": ["Yes", "No", "Can't recall"],
     "rows": [
         {"key": "charges", "label": "Charges, fees and premiums"},
         {"key": "lockin", "label": "Lock-in period / exit conditions"},
         {"key": "risk", "label": "Risks or returns not being guaranteed"},
         {"key": "suited", "label": "Why this product suited YOUR needs"},
     ]},
    {"id": "F5", "section": "F", "type": "single", "text": "Overall, how did that recommendation feel?",
     "options": _opts((1, "Very helpful"), (2, "Somewhat helpful"), (3, "Neither"), (4, "Somewhat pushy"), (5, "Very pushy"))},
    {"id": "F6", "section": "F", "type": "single", "text": "Did you purchase a product based on a bank employee's recommendation in the past 12 months?",
     "options": _opts((1, "Yes"), (2, "No"))},
    {"id": "F7", "section": "F", "type": "single", "text": "Looking back, how do you feel about that purchase?",
     "options": _opts((1, "Good decision — product suits my needs"), (2, "Mixed feelings"), (3, "Regret it — didn't suit my needs"), (4, "Too early to say"))},
    {"id": "F8", "section": "F", "type": "grid_single", "text": "Have you EVER experienced any of the following with [PRIMARY BANK]?",
     "columns": ["Yes", "No"], "instruction": "ASK ALL. SENSITIVE — READ NEUTRALLY.",
     "rows": [
         {"key": "pressured", "label": "Felt pressured to buy a product you didn't want"},
         {"key": "required", "label": "Told a product (e.g., insurance) was REQUIRED to get a loan, locker or other service"},
         {"key": "without_consent", "label": "Found a product or service added to your account without your clear consent"},
         {"key": "hidden_charges", "label": "Discovered charges or deductions you were never told about"},
         {"key": "unexplained_forms", "label": "Asked to sign forms that were not explained to you"},
     ]},
    {"id": "F9", "section": "F", "type": "single", "text": "How relevant to your actual needs are the product offers you receive from [PRIMARY BANK]?",
     "options": _opts((1, "Almost always relevant"), (2, "Sometimes relevant"), (3, "Rarely relevant"), (4, "Never relevant / generic offers"), (5, "Don't receive offers"))},
    {"id": "F10", "section": "F", "type": "single", "text": "In a typical month, roughly how many times does [PRIMARY BANK] proactively contact you (call, SMS, WhatsApp, app notification) to offer a product?",
     "options": _opts((1, "None"), (2, "1–2 times"), (3, "3–5 times"), (4, "More than 5 times"), (5, "Too many to count"))},
    {"id": "F11", "section": "F", "type": "single", "text": "And how many such contacts per month would feel acceptable to you?",
     "options": _opts((1, "None"), (2, "1–2 times"), (3, "3–5 times"), (4, "More than 5"), (5, "No strong preference"))},
    {"id": "F12", "section": "F", "type": "single", "text": "For a large transaction on your account (for example, above ₹50,000), would you want the bank to proactively reach out to confirm or check in with you?",
     "instruction": "IF CODE 1 OR 2, ASK OPEN-END FOLLOW-UP for amount.",
     "options": _opts((1, "Yes, definitely"), (2, "Yes, but only for very large amounts"), (3, "No, not necessary"))},

    # ---------------- Section G — Complaints & Service Recovery ----------------
    {"id": "G1", "section": "G", "type": "single", "text": "In the past 12 months, have you raised any complaint or problem with [PRIMARY BANK]?",
     "options": _opts((1, "Yes"), (2, "No — had a problem but didn't complain"), (3, "No — had no problems"))},
    {"id": "G2", "section": "G", "type": "open", "text": "Why didn't you complain?"},
    {"id": "G3", "section": "G", "type": "single", "text": "How satisfied were you with how your complaint was handled?",
     "options": _opts((1, "Very satisfied"), (2, "Somewhat satisfied"), (3, "Neither"), (4, "Somewhat dissatisfied"), (5, "Very dissatisfied"), (6, "Still unresolved"))},
    {"id": "G4", "section": "G", "type": "single", "text": "How much effort did YOU personally have to put in to get it addressed?",
     "options": _opts((1, "Very little — resolved easily"), (2, "Some effort"), (3, "A lot of effort — repeated follow-ups"))},

    # ---------------- Section H — Loyalty & Competition ----------------
    {"id": "H1", "section": "H", "type": "single", "text": "In the past 12 months, have you seriously considered switching your primary bank?",
     "options": _opts((1, "Yes, actively looked at alternatives"), (2, "Thought about it but took no action"), (3, "No"))},
    {"id": "H2", "section": "H", "type": "multi", "text": "What has stopped you from switching so far?", "instruction": "ROTATE.",
     "options": _opts((1, "Too much hassle / paperwork"), (2, "Salary account is here"), (3, "Linked services (loans, auto-pay, investments)"),
                      (4, "Long relationship / familiarity"), (5, "No clearly better alternative"), (6, "Other (specify)"))},
    {"id": "H3", "section": "H", "type": "single", "text": "Which ONE bank — whether you use it or not — do you believe offers the best overall customer experience?",
     "instruction": "SHOW LIST + OTHER. Record primary bank if same.", "options": BANKS},
    {"id": "H4", "section": "H", "type": "grid_single", "text": "Compared to [BANK NAMED AT H3], would you say [PRIMARY BANK] is BETTER, ABOUT THE SAME, or WORSE on each of the following?",
     "columns": ["Better", "About the same", "Worse", "Can't say"],
     "rows": [
         {"key": "proactive_checkin", "label": "Proactively checking in with you after you've bought something"},
         {"key": "doorstep", "label": "Offering doorstep / at-home service when needed"},
         {"key": "branch_atm", "label": "Having branches and ATMs that are easy to find"},
     ]},

    # ---------------- Section I — Classification ----------------
    {"id": "I1", "section": "I", "type": "single", "text": "Which best describes your occupation?",
     "options": _opts((1, "Salaried – private sector"), (2, "Salaried – government / public sector"), (3, "Self-employed / business owner"),
                      (4, "Professional (doctor, lawyer, CA, etc.)"), (5, "Homemaker"), (6, "Student"), (7, "Retired"), (8, "Other (specify)"))},
    {"id": "I2", "section": "I", "type": "single", "text": "Which range best describes your total monthly household income?",
     "instruction": "SHOW LOCALISED INCOME BANDS. REFUSED = CODE 9.",
     "options": _opts((1, "Up to ₹25,000"), (2, "₹25,001 – ₹50,000"), (3, "₹50,001 – ₹75,000"),
                      (4, "₹75,001 – ₹1,00,000"), (5, "₹1,00,001 – ₹2,00,000"), (6, "₹2,00,001 – ₹5,00,000"),
                      (7, "Above ₹5,00,000"), (9, "Prefer not to say"))},
    {"id": "I3", "section": "I", "type": "single", "text": "Which city do you live in?",
     "instruction": "RECORD CITY / CENTRE.",
     "options": _opts((1, "Mumbai"), (2, "Delhi / NCR"), (3, "Bengaluru"), (4, "Chennai"), (5, "Kolkata"),
                      (6, "Hyderabad"), (7, "Pune"), (8, "Ahmedabad")) + [{"code": 9, "label": "Other (please specify)", "specify": True}]},
]

# Fast lookups
_ORDER = [q["id"] for q in QUESTION_BANK]
_BY_ID = {q["id"]: q for q in QUESTION_BANK}
FIRST_QUESTION_ID = _ORDER[0]

# Mark the "None of these" option exclusive on the NONE=EXCLUSIVE multis so the
# respondent UI clears other selections when it is chosen (and vice versa).
for _qid, _code in [("S9", 10), ("D2", 8), ("E8", 6)]:
    for _o in _BY_ID[_qid]["options"]:
        if _o["code"] == _code:
            _o["exclusive"] = True


# ---------------------------------------------------------------------------
# Askability + routing
# ---------------------------------------------------------------------------

def _is_askable(qid, responses) -> bool:
    q = _BY_ID[qid]
    gate = SECTION_GATE.get(q["section"])
    if gate and not gate(responses):
        return False
    pred = ASK_IF.get(qid)
    if pred and not pred(responses):
        return False
    return True


def next_question(qid, responses) -> str | None:
    """Return the next askable question id after `qid`, or None when the survey
    is complete. `responses` must already include the answer to `qid`."""
    try:
        start = _ORDER.index(qid)
    except ValueError:
        return None
    for nxt in _ORDER[start + 1:]:
        if _is_askable(nxt, responses):
            return nxt
    return None


def first_question(responses=None) -> str:
    """First askable question (S1 is always askable, but keep this general)."""
    responses = responses or {}
    for qid in _ORDER:
        if _is_askable(qid, responses):
            return qid
    return FIRST_QUESTION_ID


# ---------------------------------------------------------------------------
# Quota frame — Mumbai & Delhi NCR bank-customer sample
# ---------------------------------------------------------------------------

CX_QUOTAS = {
    "total_sample": 400,
    "cells": {
        # Centres (2)
        "mumbai": 200,
        "delhi_ncr": 200,
        # Age bands (S10 codes 2–5; 18–24 light)
        "age_18_24": 40,
        "age_25_34": 120,
        "age_35_44": 120,
        "age_45_54": 80,
        "age_55_plus": 40,
        # Gender
        "female": 200,
        "male": 200,
    },
}

# S11 age code → quota key
AGE_QUOTA_MAP = {1: "age_18_24", 2: "age_25_34", 3: "age_35_44", 4: "age_45_54", 5: "age_55_plus"}
# S10 gender code → quota key (code 3 "Other / prefer not to say" is not quota'd)
GENDER_QUOTA_MAP = {1: "female", 2: "male"}
# I3 city code → centre quota key (only the two in-scope centres are quota'd)
CENTRE_QUOTA_MAP = {1: "mumbai", 2: "delhi_ncr"}


def config_payload():
    """Question bank + quota frame for a respondent UI / external programmer."""
    return {
        "survey_type": "cx_survey",
        "title": "IDFC FIRST Bank — Customer Experience & Sales Process Evaluation",
        "first_question_id": FIRST_QUESTION_ID,
        "questions": QUESTION_BANK,
        "quotas": CX_QUOTAS,
    }
