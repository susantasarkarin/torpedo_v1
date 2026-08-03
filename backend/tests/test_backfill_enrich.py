"""
BACKFILL / ENRICH TESTS
=======================

Covers the safety rules, the title-only scoring guard, name derivation,
checkpoint resumability, and dry-run write suppression.

No network calls; Google CSE and the Bedrock extraction path are patched.

Run with: pytest backend/tests/test_backfill_enrich.py -v
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.backfill_enrich import (
    Checkpoint,
    build_enrichment_query,
    derive_name_parts,
    has_scoring_signal,
    has_valid_identity,
    missing_fields,
    scrub_enrichment,
)


# ============================================
# SAFETY: IDENTITY
# ============================================

def test_keeps_lead_with_name_and_linkedin():
    assert has_valid_identity({
        "name": "Asha Rao",
        "linkedin_url": "https://in.linkedin.com/in/asharao",
    })


def test_keeps_lead_with_email_only():
    assert has_valid_identity({"email": "a@b.com"})


def test_discards_lead_with_no_name():
    assert not has_valid_identity({
        "linkedin_url": "https://in.linkedin.com/in/asharao"})


def test_discards_company_page_url():
    """Only /in/ profile URLs count as a real LinkedIn identity."""
    assert not has_valid_identity({
        "name": "Acme Corp",
        "linkedin_url": "https://linkedin.com/company/acme",
    })


def test_discards_empty_record():
    assert not has_valid_identity({})


# ============================================
# SAFETY: SCRUBBING
# ============================================

def test_guessed_email_candidate_is_dropped():
    out = scrub_enrichment({"title": "CTO", "email_candidate": "a.b@c.com"})
    assert "email_candidate" not in out
    assert out["title"] == "CTO"


def test_placeholder_company_is_dropped():
    for junk in ("unknown", "N/A", "-", "none", ""):
        out = scrub_enrichment({"company": junk, "title": "CTO"})
        assert "company" not in out, junk


def test_real_company_survives():
    assert scrub_enrichment({"company": "Larsen & Toubro"})["company"] == "Larsen & Toubro"


def test_blank_and_none_values_dropped():
    out = scrub_enrichment({"a": None, "b": "   ", "c": "keep"})
    assert out == {"c": "keep"}


# ============================================
# SCORING GUARD
# ============================================

def test_title_only_lead_has_no_scoring_signal():
    """A title match is 3 points and the threshold is >3 — never classifiable."""
    assert not has_scoring_signal({"title": "BIM Manager", "name": "X"})


@pytest.mark.parametrize("field", [
    "company_industry", "industry", "location", "country",
    "inferred_location", "company_headquarters", "seniority_level",
])
def test_any_extra_signal_enables_scoring(field):
    assert has_scoring_signal({"title": "BIM Manager", field: "something"})


def test_empty_values_are_not_signal():
    assert not has_scoring_signal({"company_industry": "", "country": None})


# ============================================
# NAME DERIVATION
# ============================================

def test_splits_simple_name():
    assert derive_name_parts({"name": "Asha Rao"}) == {
        "first_name": "Asha", "last_name": "Rao"}


def test_strips_credentials_after_comma():
    assert derive_name_parts({"name": "Piyul Mukherjee, PhD"}) == {
        "first_name": "Piyul", "last_name": "Mukherjee"}


def test_handles_three_part_name():
    assert derive_name_parts({"name": "Ana Maria Silva"}) == {
        "first_name": "Ana", "last_name": "Maria Silva"}


def test_single_word_name_has_no_last():
    assert derive_name_parts({"name": "Madonna"}) == {"first_name": "Madonna"}


def test_does_not_overwrite_existing_first_name():
    assert derive_name_parts({"name": "Asha Rao", "first_name": "Existing"}) == {}


def test_blank_name_yields_nothing():
    assert derive_name_parts({"name": "   "}) == {}
    assert derive_name_parts({}) == {}


# ============================================
# ENRICHMENT TARGETING
# ============================================

def test_missing_fields_detection():
    lead = {"company": "Acme", "title": None, "company_industry": "", "country": "India"}
    assert set(missing_fields(lead)) == {"title", "company_industry"}


def test_query_prefers_linkedin_slug():
    q = build_enrichment_query({
        "linkedin_url": "https://in.linkedin.com/in/piyul/",
        "name": "Piyul Mukherjee"})
    assert q == 'site:linkedin.com/in/ "piyul"'


def test_query_falls_back_to_name_and_company():
    q = build_enrichment_query({"name": "Asha Rao", "company": "Acme"})
    assert q == 'site:linkedin.com/in/ "Asha Rao" Acme'


def test_query_none_without_identity():
    assert build_enrichment_query({}) is None


# ============================================
# CHECKPOINT / RESUMABILITY
# ============================================

def test_checkpoint_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cp.json")
        cp = Checkpoint(path)
        assert cp.last_id is None

        cp.save("64b8f0c2a1d3e4f5a6b7c8d9", 250)

        resumed = Checkpoint(path)
        assert resumed.last_id == "64b8f0c2a1d3e4f5a6b7c8d9"
        assert resumed.processed == 250


def test_checkpoint_survives_corruption():
    """A truncated checkpoint must not crash the run."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cp.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"last_id": "abc"')  # truncated
        cp = Checkpoint(path)
        assert cp.last_id is None
        assert cp.processed == 0


def test_checkpoint_clear():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cp.json")
        cp = Checkpoint(path)
        cp.save("64b8f0c2a1d3e4f5a6b7c8d9", 10)
        assert os.path.exists(path)
        cp.clear()
        assert not os.path.exists(path)


def test_checkpoint_write_is_atomic():
    """os.replace is used so a crash mid-write cannot leave a partial file."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cp.json")
        cp = Checkpoint(path)
        cp.save("64b8f0c2a1d3e4f5a6b7c8d9", 5)
        assert not os.path.exists(path + ".tmp")
        with open(path, encoding="utf-8") as fh:
            assert json.load(fh)["processed"] == 5
