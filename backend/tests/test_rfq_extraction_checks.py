"""Code checks that replace the model's self-reported confidence on RFQ extraction."""
from rfq.extraction_checks import check, countries_named

MAIL = """RFQ_Premium SUV Study
LOI: 15 minutes
IR: 25%
Market: India
Total 1600"""

TWO = """Please quote: India n=800 and Indonesia n=500, LOI 15 minutes, IR around 40%."""


def line(**kw):
    base = {"country": "IN", "n": 1600, "loi_minutes": 15, "ir_percent": 25}
    base.update(kw)
    return base


def test_good_extraction_passes():
    r = check({"line_items": [line()]}, MAIL)
    assert r["pass"], r["problems"]


def test_invented_number_fails_grounding():
    r = check({"line_items": [line(loi_minutes=150)]}, MAIL)
    assert not r["pass"] and any("LOI 150" in p for p in r["problems"])


def test_out_of_range_fails():
    r = check({"line_items": [line(ir_percent=250)]}, MAIL)
    assert any("IR 250" in p and "range" in p for p in r["problems"])


def test_dropped_market_fails_coverage():
    """The 1.5B model returned only India for this mail."""
    r = check({"line_items": [line(n=800, loi_minutes=15, ir_percent=40)]}, TWO)
    assert not r["pass"] and any("coverage" in p and "ID" in p for p in r["problems"])
    ok = check({"line_items": [line(n=800, ir_percent=40), line(country="ID", n=500, ir_percent=40)]}, TWO)
    assert ok["pass"], ok["problems"]


def test_country_not_in_mail_fails():
    r = check({"line_items": [line(country="US")]}, MAIL)
    assert any("US not named" in p for p in r["problems"])


def test_missing_required_fields_fail():
    assert not check({"line_items": [line(n=None)]}, MAIL)["pass"]
    assert not check({"line_items": []}, MAIL)["pass"]


def test_ir_may_be_absent():
    assert check({"line_items": [line(ir_percent=None)]}, MAIL)["pass"]


def test_country_detection_by_name_and_code():
    assert countries_named("Geo : US, DE, JP, UK, IN, FR, KR, BR") >= {"US", "DE", "JP", "GB", "IN", "FR", "KR", "BR"}
    assert "IT" not in countries_named("please quote it today")   # 'it' is a word, not Italy
