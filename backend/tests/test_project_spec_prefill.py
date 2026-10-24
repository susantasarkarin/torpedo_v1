"""A won RFQ's brief prefills the Operations project's own fields."""

from app.services.won_handoff import _number, _project_spec_fields


def test_numbers_are_read_from_brief_text():
    assert _number("1,000 completes") == 1000
    assert _number("15 mins") == 15
    assert _number("30%") == 30
    assert _number(12) == 12
    assert _number("TBD") is None


def test_spec_fields_from_rfq():
    rfq = {"sample_size": "1,000", "loi": "15 min", "ir": "30%", "country": "India",
           "methodology": "Online", "target_audience": "Gen Z gamers"}
    out = _project_spec_fields(rfq, 5000.0, {"industry": "Market Research"})
    assert out == {"totalCompletesRequired": 1000, "loi": 15.0, "clientIR": 30.0, "cpi": 5.0,
                   "country": "India", "methodology": "Online", "targetAudience": "Gen Z gamers",
                   "industry": "Market Research"}


def test_quoted_cpi_wins_and_blanks_are_left_out():
    out = _project_spec_fields({"cpi": 4.25, "sample_size": "500"}, 9999.0, {})
    assert out == {"totalCompletesRequired": 500, "cpi": 4.25}
