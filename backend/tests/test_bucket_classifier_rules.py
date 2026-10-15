"""
Title rules that decide a bucket without a model call (2026-10-14).

Only "bim" and "survey" -- the signals the model agreed with on >= 95% of its
definite verdicts. Everything else, multi-bucket titles and seller titles,
still go to the model; exclusions still run first.
"""
from unittest.mock import patch

import pytest

from leads import bucket_classifier as bc


def _lead(title, **kw):
    return {"_id": "x1", "name": "A B", "title": title, "company": "Acme", **kw}


def _no_model():
    return patch.object(bc, "_classify_with", side_effect=AssertionError("model must not be called"))


@pytest.mark.parametrize("title,bucket", [
    ("Head of BIM", "BIM"),
    ("BIM Manager / Product Owner (integrations)", "BIM"),
    ("BIM Lead, Larsen & Toubro", "BIM"),
    ("Survey Methodologist", "SFW"),
    ("Head of Surveys", "SFW"),
])
def test_clear_titles_skip_the_model(title, bucket):
    with _no_model():
        r = bc.classify_lead(_lead(title))
    assert r["bucket"] == bucket and r["method"] == "rules"
    assert r["confidence"] >= bc.CONFIDENCE_THRESHOLD


@pytest.mark.parametrize("title", [
    "Research Director",            # 91% agreement: below the bar
    "Chief Marketing Officer",
    "Market Research Manager",
    "Consumer Insights Lead",
    "Design Manager",               # no signal at all
])
def test_ambiguous_titles_still_use_the_model(title):
    with patch.object(bc, "_classify_with", return_value=("REVIEW", 0.0, "unsure", None)) as m:
        r = bc.classify_lead(_lead(title))
    assert m.called and r["method"] != "rules"


@pytest.mark.parametrize("title", [
    "BIM Sales Manager",
    "Business Development - BIM Services",
    "Survey Panel Partnerships Lead",
    "Key Account Manager, BIM",
])
def test_sellers_are_left_to_the_model(title):
    with patch.object(bc, "_classify_with", return_value=("REJECT", 0.9, "vendor", None)) as m:
        r = bc.classify_lead(_lead(title))
    assert r["method"] != "rules"
    # check_exclusion may already reject some of these (sales titles); either
    # way the rule did not accept them.
    assert r["bucket"] != "BIM" or m.called


def test_a_title_with_two_bucket_signals_goes_to_the_model():
    title = "BIM & Survey Data Collection Lead"   # BIM and SFW signals
    with patch.object(bc, "_classify_with", return_value=("REVIEW", 0.0, "", None)) as m:
        r = bc.classify_lead(_lead(title))
    assert m.called and r["method"] != "rules"


def test_exclusions_still_win_over_rules():
    with _no_model():
        r = bc.classify_lead(_lead("BIM Intern"))
    assert r["bucket"] == bc.REJECT_BUCKET and r["method"] == "exclusion_filter"


def test_run_counts_skipped_model_calls(monkeypatch):
    leads = [_lead("Head of BIM", _id="1"), _lead("Student", _id="2"), _lead("Design Manager", _id="3")]

    class _Cur(list):
        def sort(self, *a, **k): return self
        def limit(self, n): return self

    monkeypatch.setattr(bc, "leads_raw", type("C", (), {"find": lambda self, q: _Cur(leads)})())
    monkeypatch.setattr(bc, "persist", lambda lead, result, dry_run=False: True)
    with patch.object(bc, "_classify_with", return_value=("REVIEW", 0.0, "unsure", None)):
        stats = bc.run(dry_run=True, limit=10)
    assert stats["rules_decided"] == 1
    assert stats["excluded_pre_ai"] == 1
    assert stats["model_calls_skipped"] == 2
