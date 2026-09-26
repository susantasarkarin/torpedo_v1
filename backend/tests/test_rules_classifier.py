"""
DETERMINISTIC RULES CLASSIFIER
================================

Covers leads/rules_classifier.py. Every case here is either a real title from
the 26 Aug-1 Sep validation dataset or a direct regression for one of the
false-positive patterns found and fixed on 2026-09-26 (bare "insights", bare
"market researcher", vendor company names, wrong-industry title matches,
sales/lead-gen combined titles, non-market research roles).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads.outreach_config import REJECT_BUCKET, REVIEW_BUCKET
from leads.rules_classifier import classify


def _lead(title, company="", industry=""):
    return {"title": title, "company": company, "company_industry": industry}


# --------------------------------------------------------------- exclusions

def test_deterministic_exclusion_runs_first():
    v = classify(_lead("Marketing Intern"))
    assert v.bucket == REJECT_BUCKET
    assert v.method == "exclusion_filter"


def test_empty_title_is_the_existing_hard_exclusion_not_a_new_review_path():
    """check_exclusion (unchanged, proven code) already treats a missing title
    as a hard REJECT ('no job title'); it runs before rules_classifier's own
    title check ever gets a chance to fire."""
    v = classify(_lead(""))
    assert v.bucket == REJECT_BUCKET
    assert v.method == "exclusion_filter"


# ------------------------------------------------------------ company signals

@pytest.mark.parametrize("company,title", [
    ("Ipsos", "Global COO"),
    ("Kantar", "Research Director"),
    ("NielsenIQ", "Consumer Insights Professional"),
    ("Forrester", "VP & Research Director"),
    ("", "Research Director at Forrester"),
])
def test_vendor_company_is_never_decided(company, title):
    v = classify(_lead(title, company=company))
    assert v.bucket == REVIEW_BUCKET
    assert "vendor" in v.reason


def test_academic_institution_is_never_decided():
    v = classify(_lead("Director of Research", company="Some University"))
    assert v.bucket == REVIEW_BUCKET
    assert "academic" in v.reason


# ------------------------------------------------------------------------ BIM

@pytest.mark.parametrize("title", ["BIM Manager", "Head of BIM", "Digital Delivery Manager"])
def test_bim_titles_decide_bim(title):
    assert classify(_lead(title)).bucket == "BIM"


@pytest.mark.parametrize("title", ["VDC Coordinator", "Revit Specialist"])
def test_bim_titles_need_industry_support_same_as_the_existing_exclusion_filter(title):
    """check_exclusion (unchanged) treats a short, clean title with no
    industry/seniority as an unsupported generic title -- "coordinator" and
    "specialist" alone don't carry buying authority without more context, the
    same rule that already applies to every other bucket."""
    assert classify(_lead(title)).bucket == REJECT_BUCKET
    assert classify(_lead(title, industry="Construction")).bucket == "BIM"


# ------------------------------------------------------------- COGENTIX_RESEARCH

def test_consumer_insights_with_no_industry_or_company_goes_to_review():
    """The bucket's title patterns alone are not specific enough -- proven
    2026-09-20 (33% correct / 28% wrong on title-only signal)."""
    v = classify(_lead("Consumer Insights Manager"))
    assert v.bucket == REVIEW_BUCKET
    assert "no industry/company signal" in v.reason


def test_consumer_insights_with_fmcg_industry_decides_cogentix():
    v = classify(_lead("Consumer Insights Manager", industry="Consumer Goods"))
    assert v.bucket == "COGENTIX_RESEARCH"


def test_consumer_insights_at_a_known_fmcg_major_decides_cogentix_even_with_no_industry():
    v = classify(_lead("Consumer Insights Manager", company="Mondelez International"))
    assert v.bucket == "COGENTIX_RESEARCH"


def test_a_topic_that_matches_no_bucket_pattern_at_all_goes_to_review():
    """'Chocolate Insights Manager' doesn't literally say consumer/customer/
    shopper/brand insights, so no COGENTIX pattern fires -- and there is no
    bare-insights fallback (removed, see the module's own docstring on why).
    A recognised FMCG employer alone isn't enough without a title match."""
    v = classify(_lead("Chocolate Insights Manager", company="Mondelez International"))
    assert v.bucket == REVIEW_BUCKET


def test_cmo_at_a_non_fmcg_company_with_stated_industry_goes_to_review():
    v = classify(_lead("Chief Marketing Officer", company="Oracle", industry="Software"))
    assert v.bucket == REVIEW_BUCKET
    assert "does not agree" in v.reason


# ------------------------------------------------------------------------ SFW

def test_bare_market_researcher_is_not_decided():
    """A bare 'Market Researcher' (no manager/director/lead) does the research
    for a living -- overwhelmingly REJECT in the ground truth, not a buyer."""
    assert classify(_lead("Market Researcher")).bucket == REVIEW_BUCKET


def test_market_research_manager_is_decided_sfw():
    assert classify(_lead("Market Research Manager")).bucket == "SFW"


def test_head_of_market_research_is_decided_sfw():
    assert classify(_lead("Head of Market Research")).bucket == "SFW"


def test_bare_research_director_with_no_market_qualifier_is_not_decided():
    """Measured 2026-09-26: 'Director of Research' alone hit a petroleum
    company, a financial regulator and a fraud-detection vendor -- 'research'
    without 'market' is not specific enough."""
    for title in ("Director of Research", "Research Manager", "Research Director"):
        assert classify(_lead(title)).bucket == REVIEW_BUCKET, title


def test_bare_insights_is_never_decided():
    """Removed after measurement: fired on hundreds of unrelated REJECT roles
    (shipping, HR, government) and stole COGENTIX_RESEARCH leads whose title
    never said 'consumer/customer/shopper/brand insights' outright."""
    for title in ("Global Insights Manager", "Data & Insights Manager", "Shipper Insights Manager"):
        assert classify(_lead(title)).bucket == REVIEW_BUCKET, title


def test_ux_or_product_research_is_not_market_research():
    assert classify(_lead("UX Research Manager")).bucket == REVIEW_BUCKET
    assert classify(_lead("Product Research Lead")).bucket == REVIEW_BUCKET


def test_market_research_combined_with_sales_or_leadgen_is_not_decided():
    """A vendor-side / lead-gen role, not a buyer."""
    for title in ("Market Research and Lead Generation", "Market Research and Business Development"):
        assert classify(_lead(title)).bucket == REVIEW_BUCKET, title


def test_panel_manager_is_decided_sfw():
    assert classify(_lead("Panel Management Manager")).bucket == "SFW"


def test_sfw_at_wrong_industry_goes_to_review():
    v = classify(_lead("Head of Market Research", company="", industry="Software Development"))
    assert v.bucket == REVIEW_BUCKET


# ---------------------------------------------------------------- never raises

@pytest.mark.parametrize("lead", [
    {}, {"title": None}, {"title": 123}, {"title": "a" * 5000},
])
def test_never_raises_on_malformed_input(lead):
    v = classify(lead)
    assert v.bucket in (REJECT_BUCKET, REVIEW_BUCKET, "BIM", "SFW", "COGENTIX_RESEARCH")
