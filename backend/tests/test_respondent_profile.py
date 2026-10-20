"""Targeting profile: NCCS grid, panel mapping, criteria, landing questions, routing integration."""
from datetime import date

from services import respondent_profile as rp
from services import survey_routing as sr

TODAY = date(2026, 10, 20)


def test_nccs_grid_corners():
    assert rp.nccs_grade(1, 0) == "E3"
    assert rp.nccs_grade(7, 9) == "A1"
    assert rp.nccs_grade(7, 11) == "A1"          # 9+ items
    assert rp.nccs_grade(4, 4) == "C1"
    assert rp.nccs_grade(6, 6) == "A3"
    assert rp.nccs_grade(0, 3) is None and rp.nccs_grade("x", 3) is None


def test_from_panel_answers():
    answers = {"CORE_04": "IN", "CORE_05": "Maharashtra", "CORE_06": "Mumbai", "CORE_07": "400001", "CORE_13": 2,
               "CORE_14": [{"birthYear": 2014, "gender": 2}, {"birthYear": 2020, "gender": 1}],
               "CORE_19": 6, "CORE_20": [1, 2, 3, 4, 5, 6, 8, 11]}
    out = rp.from_panel_answers(answers, today=TODAY)
    assert out == {"state": "Maharashtra", "city": "Mumbai", "zip_code": "400001", "children_ages": [12, 6], "nccs": "A2"}
    assert rp.from_panel_answers({"CORE_13": 0}, today=TODAY) == {"children_ages": []}
    assert rp.from_panel_answers({"CORE_19": 6, "CORE_20": [1, 2], "CORE_04": "GB"}, today=TODAY) == {}  # NCCS: India only
    assert "children_ages" not in rp.from_panel_answers({}, today=TODAY)                                 # never answered


def test_city_aliases_and_criteria():
    crit = rp.criteria({"cities": "Mumbai, Bengaluru", "zipPrefixes": ["400", "56"], "nccs": ["a1", "A2", "Z9"]})
    assert crit["nccs"] == ["A1", "A2"]
    assert rp.reasons(crit, {"city": "Bombay", "zip_code": "400 001", "nccs": "A2"}) == []
    assert rp.reasons(crit, {"city": "Bangalore", "zip_code": "560001", "nccs": "A1"}) == []
    assert rp.reasons(crit, {"city": "Pune", "zip_code": "411001", "nccs": "B1"}) == ["city", "zip", "nccs"]
    assert rp.reasons(crit, {}) == ["city_missing", "zip_missing", "nccs_missing"]


def test_children_criteria():
    crit = rp.criteria({"childrenMin": 1, "childAgeMin": 5, "childAgeMax": 12})
    assert rp.reasons(crit, {"children_ages": [3, 8]}) == []
    assert rp.reasons(crit, {"children_ages": [2, 15]}) == ["child_age"]
    assert rp.reasons(crit, {"children_ages": []}) == ["children", "child_age"]
    assert rp.reasons(crit, {}) == ["children_missing"]
    assert rp.reasons(rp.criteria({"childrenMax": 0}), {"children_ages": []}) == []


def test_questions_only_for_unknown_fields():
    crits = [rp.criteria({"cities": ["Mumbai", "Delhi"], "nccs": ["A1"]}), rp.criteria({"cities": ["Bombay", "Pune"], "childAgeMin": 4})]
    qs = rp.questions(crits, {}, "IN")
    ids = [q["id"] for q in qs]
    assert ids == ["p_city", "p_nccs_edu", "p_nccs_items", "p_children"]
    city = qs[0]
    assert [o["value"] for o in city["options"]] == ["Delhi", "Mumbai", "Pune", rp.OTHER]   # Bombay = Mumbai
    known = {"city": "Mumbai", "children_ages": [], "nccs": "A1"}
    assert rp.questions(crits, known, "IN") == []


def test_clean_and_landing_answers():
    raw = {"p_city": " Mumbai ", "p_zip": "400-001", "p_children": [8, "3", 40, "x"], "p_nccs_edu": "6",
           "p_nccs_items": [1, 2, 2, 3, 4, 5, 6, 12], "junk": 1}
    clean = rp.clean_answers(raw)
    assert clean == {"p_city": "Mumbai", "p_zip": "400001", "p_children": [8, 3], "p_nccs_edu": "6",
                     "p_nccs_items": [1, 2, 3, 4, 5, 6]}
    assert rp.from_landing_answers(clean) == {"city": "Mumbai", "zip_code": "400001", "children_ages": [8, 3], "nccs": "A3"}


def test_merge_keeps_panel_values_first():
    out = rp.merge({"gender": "f", "zip_code": ""}, {"city": "Mumbai", "children_ages": []},
                   {"city": "Pune", "zip_code": "411001", "children_ages": [5]})
    assert out == {"gender": "f", "zip_code": "411001", "city": "Mumbai", "children_ages": []}


def test_routing_evaluate_and_questions():
    project = {"surveyNo": "1", "qualification": {"enabled": True, "genders": ["f"], "cities": ["Mumbai"],
                                                   "childrenMin": 1, "nccs": ["A1", "A2", "A3"]}}
    profile = {"gender": "f", "city": "mumbai", "children_ages": [6], "nccs": "A2"}
    assert sr.evaluate(project, {}, profile) == (True, [])
    ok, reasons = sr.evaluate(project, {}, {**profile, "nccs": "C1"})
    assert not ok and reasons == ["nccs"]
    ids = [q["id"] for q in sr.questions_for([project], {}, country="IN")]
    assert ids == ["p_city", "p_children", "p_nccs_edu", "p_nccs_items"]
    assert sr.questions_for([project], {}, known={"city": "Mumbai", "children_ages": [6], "nccs": "A1"}) == []
    answers = sr.clean_answers({"p_city": "Mumbai", "employment": "student", "p_children": [4]})
    assert answers == {"employment": "student", "p_city": "Mumbai", "p_children": [4]}
