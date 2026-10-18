""""Open in Chrome" split test for vendor-app in-app browsers (2026-10-18)."""
from services import inapp_browser as ib

WV = "Mozilla/5.0 (Linux; Android 14; CPH2381 Build/UKQ1.230924.001; wv) AppleWebKit/537.36 Chrome/155.0 Mobile Safari/537.36"
CHROME = "Mozilla/5.0 (Linux; Android 14; CPH2381) AppleWebKit/537.36 Chrome/155.0 Mobile Safari/537.36"


def test_only_research_desk_in_app_visitors_are_in_the_test(monkeypatch):
    monkeypatch.delenv("IN_APP_OFFER_VENDORS", raising=False)
    assert ib.arm_for("5068", "r1", WV) in ("offer", "control")
    assert ib.arm_for("5068", "r1", CHROME) is None          # normal browser: untouched
    assert ib.arm_for("4738", "r1", WV) is None              # Cint in-app traffic was fine
    assert ib.arm_for("", "r1", WV) is None


def test_arm_is_stable_and_split_roughly_in_half(monkeypatch):
    monkeypatch.delenv("IN_APP_OFFER_VENDORS", raising=False)
    monkeypatch.delenv("IN_APP_OFFER_PERCENT", raising=False)
    assert ib.arm_for("5068", "same-rid", WV) == ib.arm_for("5068", "same-rid", WV)
    offers = sum(ib.arm_for("5068", f"rid-{i}", WV) == "offer" for i in range(2000))
    assert 850 < offers < 1150


def test_switches(monkeypatch):
    monkeypatch.setenv("IN_APP_OFFER_PERCENT", "100")
    assert ib.arm_for("5068", "x", WV) == "offer"
    monkeypatch.setenv("IN_APP_OFFER_PERCENT", "0")
    assert ib.arm_for("5068", "x", WV) == "control"
    monkeypatch.setenv("IN_APP_OFFER_VENDORS", "")
    assert ib.arm_for("5068", "x", WV) is None              # off for everyone
    monkeypatch.setenv("IN_APP_OFFER_VENDORS", "4738,5068")
    monkeypatch.setenv("IN_APP_OFFER_PERCENT", "100")
    assert ib.arm_for("4738", "x", WV) == "offer"


def test_events_are_validated():
    ok = ib.clean_event({"event": "open_clicked", "arm": "offer", "vid": "5068", "rid": "r1", "pid": "74536"})
    assert ok["event"] == "open_clicked" and ok["vendorId"] == "5068" and ok["projectNo"] == "74536"
    assert ib.clean_event({"event": "hack", "arm": "offer"}) is None
    assert ib.clean_event({"event": "landing", "arm": "both"}) is None
    assert ib.clean_event("nope") is None
