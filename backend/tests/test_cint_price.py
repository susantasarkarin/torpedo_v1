"""Cint offerwall price: RPI {"value", "currency_code"} (2026-10-22), and the filter that uses it."""
import routers.traffic as traffic


def _survey(n, rpi, ir=60):
    return {"SurveyNumber": n, "BidIncidence": ir, "Conversion": 0, "RPI": {"value": str(rpi), "currency_code": "USD"}}


def test_price_from_rpi_dict_and_older_fields():
    assert traffic._cint_price({"RPI": {"value": "0.84875000", "currency_code": "USD"}}) == 0.84875
    assert traffic._cint_price({"CPI": 1.2}) == 1.2
    assert traffic._cint_price({"payout": "0.9"}) == 0.9
    assert traffic._cint_price({"RPI": {"value": None}}) == 0.0
    assert traffic._cint_price({}) == 0.0


def test_relaxed_filter_now_passes_priced_surveys(monkeypatch):
    for var in ("MIN_CINT_FALLBACK_IR", "MIN_CINT_FALLBACK_CONV", "MIN_CINT_FALLBACK_CPI"):
        monkeypatch.delenv(var, raising=False)
    surveys = [_survey("1", 0.14), _survey("2", 0.85), _survey("3", 0.01)]
    out = traffic._apply_cint_quality_filter(surveys, respondent_age=32, relaxed=True)
    assert [s["SurveyNumber"] for s in out] == ["1", "2"]          # $0.05 floor; $0.01 still out


def test_normal_filter_keeps_its_floors(monkeypatch):
    for var in ("MIN_CINT_IR", "MIN_CINT_CONVERSION", "MIN_CINT_CPI"):
        monkeypatch.delenv(var, raising=False)
    surveys = [_survey("1", 0.14), _survey("2", 0.85), _survey("4", 2.0, ir=5)]
    out = traffic._apply_cint_quality_filter(surveys, respondent_age=None)
    assert [s["SurveyNumber"] for s in out] == ["2"]               # IR >= 15 and >= $0.75


def test_panel_member_floor_covers_their_reward():
    floor = traffic._panel_member_price_floor("IN")
    ten_min = {"LengthOfInterview": 10}
    assert round(floor(ten_min), 3) == round(8 / 96.73 * 1.2, 3)          # Rs 8 reward x 1.2
    assert floor({}) == floor({"LengthOfInterview": 30})                   # unknown length priced as long
    us = traffic._panel_member_price_floor("US")
    assert us({"LengthOfInterview": 12}) == 0.60 * 1.2
    cheap = {"LengthOfInterview": 10, "RPI": {"value": "0.14"}}
    assert traffic._cint_price(cheap) >= traffic._panel_member_price_floor("IN")(cheap)   # India: Rs 8 = $0.083 x 1.2
    assert traffic._cint_price(cheap) < us(cheap)                                         # US: pays $0.40, earns $0.14
    longer = {"LengthOfInterview": 15, "RPI": {"value": "0.14"}}
    assert traffic._cint_price(longer) < traffic._panel_member_price_floor("IN")(longer)  # Rs 12 x 1.2 = $0.149
