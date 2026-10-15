"""
Title rules that decide a bucket without a model call (2026-10-14).

Only "bim" and "survey" -- the signals the model agreed with on >= 95% of its
definite verdicts. Everything else, multi-bucket titles and seller titles,
still go to the model; exclusions still run first.
"""
from unittest.mock import patch

import pytest

from leads import bucket_classifier as bc


@pytest.fixture(autouse=True)
def _model_on(monkeypatch):
    """Rules come before the model either way; these tests run with the model on."""
    monkeypatch.setattr(bc, "MODEL_CLASSIFICATION_ENABLED", True)


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


class _Enriched:
    def __init__(self, doc):
        self.doc, self.q = doc, None

    def find_one(self, q, proj=None):
        self.q = q
        return self.doc


def test_snippet_comes_from_the_enriched_record():
    """leads_raw has no snippet; the prompt said 'none' for every lead (2026-10-14)."""
    from bson import ObjectId
    oid = ObjectId()
    col = _Enriched({"snippet": "Director- Marketing at Oracle. Delhi, India.", "location": "Delhi"})
    out = bc.with_profile_context({"_id": "r1", "title": "Director- Marketing", "enriched_lead_id": str(oid)}, col)
    assert out["snippet"].startswith("Director- Marketing at Oracle")
    assert out["location"] == "Delhi" and col.q == {"_id": oid}
    assert "Oracle" in bc.build_prompt(out)


def test_existing_snippet_and_unlinked_leads_are_left_alone():
    col = _Enriched({"snippet": "other"})
    lead = {"_id": "r1", "title": "x", "snippet": "own words", "enriched_lead_id": "507f1f77bcf86cd799439011"}
    assert bc.with_profile_context(lead, col)["snippet"] == "own words" and col.q is None
    assert bc.with_profile_context({"_id": "r2", "title": "x"}, col) == {"_id": "r2", "title": "x"}


def test_a_bad_enriched_id_never_breaks_classification():
    lead = {"_id": "r1", "title": "x", "enriched_lead_id": "not-an-id"}
    assert bc.with_profile_context(lead, _Enriched(None)) == lead


def test_with_the_model_off_ambiguous_leads_go_to_review_without_a_call(monkeypatch):
    """Off by default (2026-10-15): 0 usable verdicts from the 1.5B in 2,851 tries."""
    monkeypatch.setattr(bc, "MODEL_CLASSIFICATION_ENABLED", False)
    with _no_model():
        r = bc.classify_lead(_lead("Research Director"))
        assert r["bucket"] == bc.REVIEW_BUCKET and r["method"] == "model_disabled"
        assert r["proposed_bucket"] == "SFW"
        assert bc.classify_lead(_lead("Head of BIM"))["method"] == "rules"        # rules still decide
        assert bc.classify_lead(_lead("Student"))["method"] == "exclusion_filter"  # exclusions still first


def test_model_off_is_the_default():
    import importlib, os
    os.environ.pop("BUCKET_CLASSIFIER_USE_MODEL", None)
    assert importlib.reload(bc).MODEL_CLASSIFICATION_ENABLED is False
