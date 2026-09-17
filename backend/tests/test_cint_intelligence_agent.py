"""
CINT INTELLIGENCE AGENT TESTS

Covers score_buyer_performance() -- validated directly against real
aggregated numbers from a live query against cint_research.cint_surveys
(2026-09-17), not synthetic-only cases. Pure function, no I/O, no live
Mongo needed.
"""
from agents.cint_intelligence_agent import score_buyer_performance


# ============================================================
# Validated against real observed buyers (live aggregation, 2026-09-17)
# ============================================================

def test_real_strong_buyer_lucid_marketplace():
    """surveys=3093, avg_conversion=6.65, deactivated=1180 ->
    deactivation_rate=0.381 (not high) + high conversion -> strong."""
    result = score_buyer_performance(
        surveys=3093, avg_conversion=6.649407030051126, deactivated=1180)
    assert result["tier"] == "strong"
    assert result["deactivation_rate"] == 0.382


def test_real_underperforming_buyer_sago():
    """surveys=16925, avg_conversion=0.037 (not high), deactivated=13577 ->
    deactivation_rate=0.802 (high) -> underperforming."""
    result = score_buyer_performance(
        surveys=16925, avg_conversion=0.03749301294855754, deactivated=13577)
    assert result["tier"] == "underperforming"
    assert result["deactivation_rate"] == 0.802


def test_real_mixed_buyer_savanta():
    """surveys=6802, avg_conversion=1.67 (high), deactivated=4326 ->
    deactivation_rate=0.636 (also high) -- genuine conversion track record
    AND high churn, correctly not called confidently good or bad."""
    result = score_buyer_performance(
        surveys=6802, avg_conversion=1.6679179231891001, deactivated=4326)
    assert result["tier"] == "mixed"


def test_real_underperforming_buyer_opinionspark():
    """The weakest real conversion observed (0.0037) with high deactivation."""
    result = score_buyer_performance(
        surveys=8479, avg_conversion=0.0036614562201103835, deactivated=4641)
    assert result["tier"] == "underperforming"


# ============================================================
# Edge cases and threshold behavior
# ============================================================

def test_no_surveys_is_no_data():
    result = score_buyer_performance(surveys=0, avg_conversion=0.0, deactivated=0)
    assert result["tier"] == "no_data"
    assert result["deactivation_rate"] is None


def test_average_buyer_neither_signal_crosses_threshold():
    result = score_buyer_performance(surveys=1000, avg_conversion=0.5, deactivated=200)
    assert result["tier"] == "average"


def test_conversion_threshold_boundary_is_inclusive():
    result = score_buyer_performance(surveys=100, avg_conversion=1.0, deactivated=0)
    assert result["tier"] == "strong"


def test_deactivation_threshold_boundary_is_inclusive():
    result = score_buyer_performance(surveys=100, avg_conversion=0.0, deactivated=50)
    assert result["tier"] == "underperforming"


def test_high_conversion_alone_is_strong_even_with_zero_deactivation():
    result = score_buyer_performance(surveys=50, avg_conversion=10.0, deactivated=0)
    assert result["tier"] == "strong"
    assert result["deactivation_rate"] == 0.0


def test_result_never_invents_a_single_numeric_score():
    """The function must expose the two real underlying numbers, not just
    a tier -- no composite weighted score is computed anywhere."""
    result = score_buyer_performance(surveys=100, avg_conversion=2.5, deactivated=10)
    assert set(result.keys()) == {"tier", "deactivation_rate", "avg_conversion"}
