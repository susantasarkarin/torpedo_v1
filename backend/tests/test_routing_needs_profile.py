"""The landing page asks DOB + gender only where a project screens on them (2026-10-17).

It had stopped asking everyone, so an age/gender rule could never be met
(every entry failed as "age_missing")."""
from services import survey_routing as sr


def test_age_or_gender_rules_need_the_profile():
    assert sr.needs_profile([{"qualification": {"enabled": True, "genders": ["f"]}}])
    assert sr.needs_profile([{"qualification": {"enabled": True, "ageMin": 25}}])
    assert sr.needs_profile([{}, {"qualification": {"enabled": True, "ageMax": 45}}])


def test_other_projects_do_not():
    assert not sr.needs_profile([])
    assert not sr.needs_profile([{}])
    assert not sr.needs_profile([{"qualification": {"enabled": False, "genders": ["f"]}}])
    assert not sr.needs_profile([{"qualification": {"enabled": True, "employment": ["full_time"]}}])


def test_rules_screen_on_the_submitted_profile():
    women = {"qualification": {"enabled": True, "genders": ["f"]}}
    assert sr.evaluate(women, {}, {"gender": "f"})[0]
    assert sr.evaluate(women, {}, {"gender": "m"}) == (False, ["gender"])
    over25 = {"qualification": {"enabled": True, "ageMin": 25}}
    assert sr.evaluate(over25, {}, {"birthday_year": 1990, "birthday_month": 1, "birthday_day": 1})[0]
    assert sr.evaluate(over25, {}, {"birthday_year": 2005, "birthday_month": 1, "birthday_day": 1}) == (False, ["age"])
