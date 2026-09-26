"""
Tests for leads/linkedin_snippet_parser.py, grounded in real stashed Google
search results (extraction_backlog, 2026-09-21..26) rather than invented
examples -- the whole point of this module is to stop mis-parsing real,
messy LinkedIn snippets the way the old regex-only fallback did.
"""
from leads.linkedin_snippet_parser import (
    extract_company_from_free_text,
    extract_structured_snippet_fields,
    has_no_real_signal,
    resolve_company_and_location,
    resolve_company_with_confidence,
)


# ---- the real bug this module exists to fix -------------------------------

def test_truncated_title_at_dots_never_becomes_a_company():
    # Real case: "Kathy Spiegelman - VP/Chief Planning, Real Estate, and
    # Facilities at ..." -- Google's own truncation, not a company name.
    assert extract_company_from_free_text(
        "Kathy Spiegelman - VP/Chief Planning, Real Estate, and Facilities at ...",
        "") == ""


def test_a_sentence_fragment_is_not_mistaken_for_a_company():
    # Real production incident: a snippet sentence became "company_name",
    # then fed a domain guess and an undeliverable email.
    snippet = ("I spot tech trends before they hit mainstream, so IT managers "
              "can prepare and build knowledge | Lifelong learner, servant "
              "leader, mentor | Sparring partner...")
    assert extract_company_from_free_text("", snippet) == ""


# ---- structured 'Experience: X · Location: Y' fields -----------------------

def test_experience_label_is_the_most_reliable_signal():
    snippet = ("Experience: Stevens Global Logistics · Education: Harvard "
              "Business School · Location: Yorba Linda · 500+ connections "
              "on LinkedIn. View Allen Morrison's profile ...")
    fields = extract_structured_snippet_fields(snippet)
    assert fields["company_name"] == "Stevens Global Logistics"
    assert fields["location"] == "Yorba Linda"


def test_experience_wins_over_a_looser_title_match():
    title = "James Sivyer, CFA - Senior Vice President, Private Markets - LinkedIn"
    snippet = ("Senior Vice President, Private Markets at Gallagher · "
              "Experience: Gallagher · Education: Birkbeck, University of "
              "London · Location: London Area,...")
    company, location = resolve_company_and_location(title, snippet)
    assert company == "Gallagher"
    assert location == "London Area"


def test_location_never_captures_the_word_linkedin():
    fields = extract_structured_snippet_fields(
        "Experience: Crimson Education · Education: Harvard · Location: LinkedIn")
    assert "location" not in fields


# ---- title-based fallback when there's no structured snippet --------------

def test_clean_title_at_clause_is_used_when_no_experience_label():
    company, _ = resolve_company_and_location(
        "Andrew Armstrong - Chief Operating Officer at Scout Cold Logistics", "")
    assert company == "Scout Cold Logistics"


def test_of_pattern_is_recognized_not_just_at():
    company, _ = resolve_company_and_location(
        "Stacy Lynn Bourgeois - Chief Marketing Officer of Neighborly", "")
    assert company == "Neighborly"


def test_oversized_match_is_rejected_as_a_sentence_not_a_name():
    # A run-on clause with 9+ words is a sentence fragment, not a company.
    company, _ = resolve_company_and_location(
        "Someone - Head of Growth at a very long winding sentence about many things", "")
    assert company == ""


# ---- profiles with no usable signal at all ---------------------------------

def test_recognizes_pure_linkedin_chrome_with_no_profile_content():
    assert has_no_real_signal(
        "... you agree to LinkedIn's User Agreement, Privacy Policy, and "
        "Cookie Policy. Join to view profile · Report this profile; Close menu.")


def test_a_real_bio_is_not_flagged_as_no_signal():
    assert not has_no_real_signal(
        "Senior Vice President, Private Markets at Gallagher · Experience: Gallagher")


def test_empty_snippet_is_not_flagged_as_no_signal():
    # Absence of a snippet is a different, already-handled case (empty
    # company/location); has_no_real_signal is specifically about chrome.
    assert not has_no_real_signal("")
    assert not has_no_real_signal(None)


# ---- resolve_company_and_location never raises on odd input ---------------

def test_resolve_handles_missing_title_and_snippet():
    assert resolve_company_and_location(None, None) == ("", "")


def test_resolve_prefers_experience_even_when_title_has_a_clean_at_clause():
    # If the two disagree, LinkedIn's own structured field is more trustworthy
    # than a search-result title, which Google may have rewritten/truncated.
    title = "Someone - Title at Wrong Co - LinkedIn"
    snippet = "Experience: Right Co · Location: Somewhere"
    company, _ = resolve_company_and_location(title, snippet)
    assert company == "Right Co"


# ---- confidence gating: a caller building a domain/email guess must know
# whether company_name came from LinkedIn's own field or a free-text guess --
# guessing a domain from a guessed company name is the exact incident this
# module exists to prevent. ----------------------------------------------

def test_experience_label_is_high_confidence():
    company, location, high_confidence = resolve_company_with_confidence(
        "James Sivyer - Senior VP - LinkedIn",
        "Experience: Gallagher · Location: London")
    assert (company, high_confidence) == ("Gallagher", True)
    assert location == "London"


def test_title_only_guess_is_low_confidence():
    company, _, high_confidence = resolve_company_with_confidence(
        "Andrew Armstrong - Chief Operating Officer at Scout Cold Logistics", "")
    assert company == "Scout Cold Logistics"
    assert high_confidence is False


def test_no_company_found_is_low_confidence_not_an_error():
    company, _, high_confidence = resolve_company_with_confidence("Just A Name", "")
    assert company == "" and high_confidence is False


def test_placeholder_experience_value_is_not_treated_as_a_company():
    # Real cases: some people literally put "TBC" / "Self-employed" /
    # "Currently Unemployed" in their own LinkedIn Experience field. It's
    # still LinkedIn's own structured field (high_confidence would otherwise
    # be True), but it is not a company and must never seed a domain guess
    # (tbc.com, selfemployed.com are exactly the wrong-domain incident this
    # module exists to prevent).
    for placeholder in ("TBC", "Self-employed", "Currently Unemployed", "N/A"):
        snippet = f"Experience: {placeholder} · Location: London"
        company, _, high_confidence = resolve_company_with_confidence("Someone", snippet)
        assert company == "", placeholder
        assert high_confidence is False, placeholder
