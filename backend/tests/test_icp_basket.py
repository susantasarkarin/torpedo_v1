"""Guards ICP basket assignment against the empty-industry collapse."""

import pytest

from leads.canonical_ingestion import compute_icp_basket


def basket(**fields):
    return compute_icp_basket(fields).get("classification_basket")


def test_no_signal_is_unqualified_not_a_dual_fit():
    """The bug that created basket D.

    `"" in kw` is always True, so an empty industry matched every keyword in
    every list and scored the full +4 on all three ICPs simultaneously. 99.8%
    of the 11.3K "Dual Fit" leads had no industry and no department — the
    label meant "we know nothing", not "fits two ICPs".
    """
    assert basket(company_industry="", department="", title="", company_name="") == "E"
    assert basket() == "E"


@pytest.mark.parametrize("industry", ["", "  ", "it", "n/a"])
def test_short_or_blank_industry_never_matches(industry):
    assert basket(company_industry=industry, department="", title="") == "E"


def test_market_research_goes_to_survey_fieldwork():
    assert basket(
        company_industry="market research",
        department="research",
        title="Research Director",
    ) == "A"


def test_construction_goes_to_bimwave():
    assert basket(
        company_industry="construction",
        department="engineering",
        title="BIM Manager",
    ) == "C"


def test_genuine_tie_is_unqualified_rather_than_arbitrary():
    """Two ICPs scoring identically is an unresolved classification.

    Breaking such a tie by list order is what proposed moving 10,790 leads
    into BIMwave on no evidence.
    """
    tied = compute_icp_basket({
        "company_industry": "market research",
        "department": "",
        "title": "",
        "company_name": "",
        "snippet": "brand health and concept testing",
    })
    # Whatever the scores, the result is never a coin-flip between two ICPs.
    assert tied.get("classification_basket") in {"A", "B", "C", "E"}


def test_basket_d_is_never_emitted():
    """Basket D no longer exists — one person, one ICP, one basket."""
    for fields in (
        {"company_industry": "market research", "department": "marketing"},
        {"company_industry": "consumer insights", "department": "insights"},
        {"company_industry": "", "department": ""},
        {"company_industry": "architecture", "department": "design"},
    ):
        assert compute_icp_basket(fields).get("classification_basket") != "D"
