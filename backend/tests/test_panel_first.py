"""
Panel members try our own projects before CPX / Cint (2026-10-21); project
qualifications with several age ranges and SurveyFieldwork Panel questions.
"""
from datetime import date

import routers.traffic as traffic
from services import panel_questions as pq
from services import survey_routing as r
from tests.test_survey_routing import _project, env  # noqa: F401  (pytest fixture)

LANDING = "https://torpedo.example/takesurvey?api=true&vid=2656&cc=US&rid=pr-1&panel=SFW1"
MEMBER = {"birthday_day": 1, "birthday_month": 1, "birthday_year": date.today().year - 30, "gender": "f",
          "zip_code": "", "targeting": {}, "panelAnswers": {"CORE_24": 1, "CORE_29": [1, 3]}}


class FakeCpx:
    def __init__(self):
        self.calls = 0

    async def async_fetch_and_allocate_for_respondent(self, **kw):
        self.calls += 1
        return {"success": True, "entry_link": "https://cpx.example/s/1", "survey_id": "c-1", "loi": 9}


def _member_env(env, monkeypatch, projects_list):
    client, url_col, projects, db = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    projects.docs += projects_list
    async def member(_pid):
        return MEMBER
    monkeypatch.setattr(traffic.panel_profile, "fetch", member)
    cpx = FakeCpx()
    monkeypatch.setattr(traffic, "cpx_service", cpx)
    return client, url_col, db, cpx


def _panel_store(client, url=LANDING, after=None):
    params = {"api": "true", "vid": "2656", "cc": "US", "rid": "pr-1", "panel": "SFW1"}
    if after:
        params["after"] = after
    body = {"params": params, "clientIp": "1.2.3.4", "sfwVisitorId": "visitor-p1", "url": url}
    return client.post("/api/store", json=body, headers={"CF-IPCountry": "US"}).json()


def test_age_ranges_and_panel_questions_evaluate():
    qual = {"enabled": True, "ageRanges": [{"min": 18, "max": 24}, {"min": 35, "max": 44}],
            "panelQuestions": [{"id": "CORE_24", "qualifying": [1, 2]}, {"id": "CORE_29", "qualifying": ["3"]}]}
    p = _project("1", qualification=qual)
    year = date.today().year
    prof = {"birthday_year": year - 40, "birthday_month": 1, "birthday_day": 1, "panelAnswers": {"CORE_24": 2, "CORE_29": [3, 4]}}
    assert r.evaluate(p, {}, prof) == (True, [])
    assert r.evaluate(p, {}, {**prof, "birthday_year": year - 30}) == (False, ["age"])        # between the ranges
    assert r.evaluate(p, {}, {**prof, "panelAnswers": {"CORE_24": 5}}) == (False, ["CORE_24", "CORE_29_missing"])
    # someone outside the panel answers on the landing page (pq_<id>, same codes)
    landing = r.clean_answers({"pq_CORE_24": "1", "pq_CORE_29": ["3"], "pq_bad id": "1", "pq_CORE_99": "x"})
    assert landing == {"pq_CORE_24": "1", "pq_CORE_29": ["3"]}
    assert r.evaluate(p, landing, {"birthday_year": year - 20, "birthday_month": 1, "birthday_day": 1}) == (True, [])


def test_panel_question_landing_wording_and_codes():
    catalog = {"CORE_24": {"id": "CORE_24", "type": "single", "countries": {
        "IN": {"text": "Employment?", "options": [{"code": 1, "label": "Full-time"}, {"code": 11, "label": "Daily wage"}]},
        "US": {"text": "Employment (US)?", "options": [{"code": 1, "label": "Full-time (35+ h)"}]}}}}
    crit = [pq.criteria([{"id": "CORE_24", "qualifying": [1]}])]
    q = pq.questions(crit, {}, "IN", catalog)[0]
    assert q == {"id": "pq_CORE_24", "type": "select", "text": "Employment?",
                 "options": [{"value": "1", "label": "Full-time"}, {"value": "11", "label": "Daily wage"}]}
    assert pq.questions(crit, {}, "US", catalog)[0]["text"] == "Employment (US)?"
    assert pq.questions(crit, {"CORE_24": 3}, "IN", catalog) == []          # a member's profile already answers it


def test_member_answers_keep_codes_only():
    assert pq.member_answers({"CORE_24": 1, "CORE_29": [1, 3], "CONTACT_01": 9876, "CORE_06": "Mumbai",
                              "CORE_14": [{"birthYear": 2014}], "x": 1}) == {"CORE_24": 1, "CORE_29": [1, 3]}


def test_panel_member_goes_to_our_matching_project_first(env, monkeypatch):
    fits = _project("201", routing=True, loi="12", qualification={"enabled": True, "panelQuestions": [{"id": "CORE_24", "qualifying": [1]}]})
    client, url_col, db, cpx = _member_env(env, monkeypatch, [fits])
    out = _panel_store(client)
    assert out["allocation_success"] and out["source"] == "PROJECT" and cpx.calls == 0
    rec = url_col.docs[0]
    assert (rec["assignedSurveyId"], rec["entryType"], rec["routedFrom"], rec["panelFirst"], rec["surveyLoi"]) == \
        ("201", "panel_project", "panel", True, 12.0)
    assert rec["params"]["pid"] == "201" and rec["params"]["api"] == "false"
    assert rec["profilingData"]["panelAnswers"] == MEMBER["panelAnswers"]


def test_panel_member_with_no_fitting_project_goes_to_cpx(env, monkeypatch):
    other = _project("202", routing=True, qualification={"enabled": True, "panelQuestions": [{"id": "CORE_24", "qualifying": [4]}]})
    client, url_col, db, cpx = _member_env(env, monkeypatch, [other])
    out = _panel_store(client)
    assert out["allocation_success"] and out["source"] == "CPX" and cpx.calls == 1
    assert url_col.docs[0]["status"] == "INCOMPLETE"          # not marked NOT_ROUTED


def test_terminated_by_our_project_then_cpx(env, monkeypatch):
    fits = _project("203", routing=True)
    client, url_col, db, cpx = _member_env(env, monkeypatch, [fits])
    rid = _panel_store(client)["id"]
    resp = client.get("/surveyterminate", params={"rid": rid}, follow_redirects=False)
    loc = resp.headers["location"]
    assert loc.startswith("https://torpedo.example/takesurvey?") and "after=projects" in loc and "rid=pr-1" in loc
    # the landing page posts again with after=projects: our projects are skipped
    out = _panel_store(client, after="projects")
    assert out["source"] == "CPX" and cpx.calls == 1


def test_security_terminate_never_goes_on_to_cpx(env, monkeypatch):
    client, url_col, db, cpx = _member_env(env, monkeypatch, [_project("204", routing=True)])
    rid = _panel_store(client)["id"]
    resp = client.get("/surveysecurity", params={"rid": rid}, follow_redirects=False)
    assert "after=projects" not in resp.headers.get("location", "")


def test_switch_off_keeps_cpx_first(env, monkeypatch):
    monkeypatch.setenv("PANEL_PROJECTS_FIRST", "false")
    client, url_col, db, cpx = _member_env(env, monkeypatch, [_project("205", routing=True)])
    assert _panel_store(client)["source"] == "CPX"


def test_non_members_unchanged(env, monkeypatch):
    client, url_col, projects, db = env
    monkeypatch.setenv("SURVEY_ROUTING_ENABLED", "true")
    projects.docs.append(_project("206", routing=True))
    cpx = FakeCpx()
    monkeypatch.setattr(traffic, "cpx_service", cpx)
    body = {"params": {"api": "true", "vid": "5068", "cc": "US", "rid": "v-9"}, "clientIp": "1.2.3.4", "sfwVisitorId": "v9"}
    out = client.post("/api/store", json=body, headers={"CF-IPCountry": "US"}).json()
    assert out["source"] == "CPX"
