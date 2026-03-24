# NCCS classification for India OTC Discovery Intelligence Study (Tier 2) v2.0
#
# Inputs:
#   q6_codes  — list[int]: household durables selected (Q6)
#               1=Electricity connection  2=Ceiling fan(s)  3=Refrigerator
#               4=Motorcycle/scooter      5=Colour television  6=Car/four-wheeler
#               7=Air conditioner         8=Washing machine
#   q7_code   — int: education of chief earner (Q7)
#               1=Graduate/PG Professional  2=Graduate/PG General
#               3=Diploma / some college    4=SSC/HSC (Class 10 or 12)
#               5=School below class 10     → terminate
#               6=No formal education       → terminate
#
# Classification rules (from QRE v2.0, Section S):
#   Terminate if electricity (1) OR ceiling fan (2) absent  → band = "below_minimum"
#   Terminate if education code 5 or 6                      → band = "nccs_terminate"
#   Terminate if 0 additional durables beyond elec+fan      → band = "below_minimum"
#
#   NCCS A: Electricity + Fan + 3 or more additional durables
#   NCCS B: Electricity + Fan + 1-2 additional durables
#   (Classification is purely durables-based; education only gates termination)
#
# Quota: 50% NCCS A / 50% NCCS B


def classify_nccs(q6_codes: list[int], q7_code: int) -> dict:
    """
    Returns {
        "grade": "A" | "B" | "below",
        "band":  "nccs_a" | "nccs_b" | "below_minimum" | "nccs_terminate"
    }
    """
    has_electricity = 1 in q6_codes
    has_fan = 2 in q6_codes

    if not has_electricity or not has_fan:
        return {"grade": "below", "band": "below_minimum"}

    if q7_code in (5, 6):
        return {"grade": "below", "band": "nccs_terminate"}

    additional = sum(1 for c in q6_codes if c in {3, 4, 5, 6, 7, 8})

    if additional == 0:
        return {"grade": "below", "band": "below_minimum"}

    # Durables-only split (v2.0): ≥3 additional → A; 1-2 → B
    if additional >= 3:
        return {"grade": "A", "band": "nccs_a"}
    return {"grade": "B", "band": "nccs_b"}
