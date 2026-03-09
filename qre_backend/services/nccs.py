# NCCS (New Consumer Classification System) — India
# Grid: rows = number of consumer durables owned (from Q6), cols = education of chief earner (from Q7)
# Returns NCCS grade: "A1","A2","A3","B1","B2","C1","C2","D1","D2","E1","E2"
# For this survey we only need the top-level band: A or B (terminate rest)

# Durable scoring from Q6 — each item is worth 1 point
# Items: Electricity(1), Ceiling Fan(2), LPG(3), Two-Wheeler(4), Colour TV(5),
#         Refrigerator(6), Washing Machine(7), PC/Laptop(8), Car(9), AC(10), Agri land(11)

# Standard NCCS mapping (simplified for survey-level classification)
# Education codes from Q7:
#   1 = Grad/PG Professional   → edu_score 7
#   2 = Grad/PG General        → edu_score 6
#   3 = Some College/Diploma   → edu_score 5
#   4 = SSC/HSC                → edu_score 4
#   5 = School 5-9 yrs         → edu_score 3   (terminated)
#   6 = Literate ≤4 yrs        → edu_score 2   (terminated)

_EDU_SCORE = {1: 7, 2: 6, 3: 5, 4: 4, 5: 3, 6: 2}

# NCCS grid (edu_score, durables_count) → NCCS grade
_NCCS_GRID = {
    (7, 9): "A1", (7, 8): "A1", (7, 7): "A2", (7, 6): "A2",
    (7, 5): "A3", (7, 4): "A3", (7, 3): "B1", (7, 2): "B1",
    (7, 1): "B2", (7, 0): "C1",
    (6, 9): "A1", (6, 8): "A2", (6, 7): "A2", (6, 6): "A3",
    (6, 5): "A3", (6, 4): "B1", (6, 3): "B1", (6, 2): "B2",
    (6, 1): "C1", (6, 0): "C1",
    (5, 9): "A2", (5, 8): "A3", (5, 7): "A3", (5, 6): "B1",
    (5, 5): "B1", (5, 4): "B2", (5, 3): "B2", (5, 2): "C1",
    (5, 1): "C1", (5, 0): "C2",
    (4, 9): "A3", (4, 8): "B1", (4, 7): "B1", (4, 6): "B2",
    (4, 5): "B2", (4, 4): "C1", (4, 3): "C1", (4, 2): "C2",
    (4, 1): "D1", (4, 0): "D2",
    (3, 9): "B1", (3, 8): "B2", (3, 7): "C1", (3, 6): "C1",
    (3, 5): "C2", (3, 4): "D1", (3, 3): "D1", (3, 2): "D2",
    (3, 1): "E1", (3, 0): "E2",
    (2, 9): "B2", (2, 8): "C1", (2, 7): "C2", (2, 6): "D1",
    (2, 5): "D1", (2, 4): "D2", (2, 3): "E1", (2, 2): "E1",
    (2, 1): "E2", (2, 0): "E2",
}


def classify_nccs(q6_codes: list[int], q7_code: int) -> dict:
    """
    Given Q6 selected codes and Q7 education code,
    return NCCS grade and band (A or B).
    """
    durables_count = len(q6_codes) if q6_codes else 0
    durables_count = min(durables_count, 9)  # cap at 9 for grid lookup
    edu_score = _EDU_SCORE.get(q7_code, 2)

    grade = _NCCS_GRID.get((edu_score, durables_count), "E2")

    # Band mapping for quota
    if grade.startswith("A"):
        band = "nccs_a"
    elif grade.startswith("B"):
        band = "nccs_b"
    else:
        band = "nccs_below"  # C/D/E — would be terminated

    return {"grade": grade, "band": band}
