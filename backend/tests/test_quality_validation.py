"""Respondent score vs client rejections: lift per flag/band, vendor rejection rate."""
from quality import validation


def _rows():
    rows = []
    for i in range(100):                       # 10% baseline rejection
        rows.append({"sfwFlags": [], "sfwBand": "good", "vendorId": "A", "clientRejected": i < 10})
    for i in range(40):                        # speeders rejected 50% of the time
        rows.append({"sfwFlags": ["speeder"], "sfwBand": "block", "vendorId": "B", "clientRejected": i < 20})
    for i in range(40):                        # a flag that predicts nothing
        rows.append({"sfwFlags": ["new_device"], "sfwBand": "review", "vendorId": "A", "clientRejected": i < 3})
    return rows


def test_lift_marks_only_predictive_flags_as_enforce_candidates():
    rep = validation.summarize(_rows())
    assert rep["completes"] == 180 and rep["rejected"] == 33
    assert rep["by_flag"]["speeder"]["enforce_candidate"] is True and rep["by_flag"]["speeder"]["lift"] > 2
    assert rep["by_flag"]["new_device"]["enforce_candidate"] is False
    assert list(rep["by_flag"])[0] == "speeder"                     # sorted by lift


def test_band_and_vendor_rates():
    rep = validation.summarize(_rows())
    assert rep["by_band"]["block"]["rejection_rate"] == 0.5
    assert rep["by_vendor"]["B"]["rejected"] == 20 and rep["by_vendor"]["A"]["completes"] == 140


def test_small_support_is_never_a_candidate_and_empty_is_safe():
    few = [{"sfwFlags": ["vpn"], "clientRejected": True}] * 5 + [{"sfwFlags": [], "clientRejected": False}] * 50
    assert validation.summarize(few)["by_flag"]["vpn"]["enforce_candidate"] is False
    empty = validation.summarize([])
    assert empty["baseline_rejection_rate"] is None and empty["by_flag"] == {}
