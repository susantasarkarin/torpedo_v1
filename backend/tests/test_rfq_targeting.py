"""RFQ email -> screening criteria (layouts as in the client's real RFQs), and NCCS being India-only."""
from services import respondent_profile as rp
from services import rfq_targeting as rt
from services import survey_routing as sr

CIRCUIT = """Hi Team,
Please quote asap for the following specs:
Target Group:
*       Males/Females (80:20)
*       Aged 18-60 years old (18-25 - 25%, 26-35 - 40%, 36-45 - 25%, 46-60 - 10%)
*       NCCS A
*       Pre Campaign  - 700 Electronics Intenders
LOI - 10 Min
Sample Plan:
Market
Mumbai
100
Delhi NCR
100
Bangalore
100
Total
900
Thank You!!
Best Regards,
Someone
DISCLAIMER: Pune Chennai confidential
"""

ABHA = """Target Group:
  *   Women only
  *   LOI:15 min
  *   IR: 40%
  *   Market: India
  *   NCCS A/B
  *   Age 15-40
  *   Who watch YouTube at least once a week.
Sample Plan:
Cities
Delhi
90
Gurugram
110
Bengaluru
90
Thank You!!
"""

MBA = """Target Group:
* Currently employed and has a graduate degree
* Age: 23 and above
* Mothers of kids aged 5-12
Sample Plan: Kochi 50, Gurgaon 50, Bangalore 40, Bengaluru 10
Regards
"""


def test_circuit_layout():
    r = rt.extract(CIRCUIT)
    q = r["qualification"]
    assert (q["ageMin"], q["ageMax"]) == (18, 60)
    assert "genders" not in q                       # 80:20 is a quota split, not a screen
    assert q["nccs"] == ["A1", "A2", "A3"]
    assert q["cities"] == "Mumbai, Delhi, Gurugram, Noida, Ghaziabad, Faridabad, Bengaluru"   # NCR expanded; signature ignored
    assert r["loi"] == 10
    assert any("Electronics Intenders" in n for n in r["notes"])


def test_abha_layout():
    r = rt.extract(ABHA)
    q = r["qualification"]
    assert q["genders"] == ["f"] and (q["ageMin"], q["ageMax"]) == (15, 40)
    assert q["nccs"] == ["A1", "A2", "A3", "B1", "B2"]
    assert q["cities"] == "Delhi, Gurugram, Bengaluru"
    assert r["ir"] == 40 and r["loi"] == 15
    assert r["notes"] == ["Who watch YouTube at least once a week."]


def test_and_above_children_and_city_spellings():
    q = rt.extract(MBA)["qualification"]
    assert q["ageMin"] == 23 and "ageMax" not in q
    assert q["genders"] == ["f"]
    assert (q["childrenMin"], q["childAgeMin"], q["childAgeMax"]) == (1, 5, 12)
    assert q["cities"] == "Kochi, Gurugram, Bengaluru"


def test_no_target_block():
    assert rt.extract("Hi, please share your redirects. Thanks")["qualification"] == {}


def test_rfq_subject():
    assert rt.rfq_subject("RE: RFQ_Abha_Brand Uplift Study_HRG_SFW - Dubur amala") == "RFQ_Abha_Brand Uplift Study_HRG_SFW"


def test_nccs_is_india_only():
    raw = {"enabled": True, "nccs": ["A1"]}
    assert rp.criteria(raw, "IN")["nccs"] == ["A1"]
    assert rp.criteria(raw, "UK")["nccs"] == []
    uk = {"surveyNo": "9", "countryCode": "UK", "qualification": raw}
    assert sr.evaluate(uk, {}, {}) == (True, [])                      # not screened, not asked
    assert sr.questions_for([uk], {}, country="UK") == []
    india = {"surveyNo": "8", "countryCode": "IN", "qualification": raw}
    assert sr.evaluate(india, {}, {}) == (False, ["nccs_missing"])
