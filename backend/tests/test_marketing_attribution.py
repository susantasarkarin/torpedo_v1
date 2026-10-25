"""Identity + attribution (MARKETING_PLAN 3.8)."""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from marketing import attribution as A, touchpoints as T
from tests._fakemongo import FakeDB

D0 = datetime(2026, 10, 1)


def tp(kind="visit", days=0, **kw):
    return {"kind": kind, "at": D0 + timedelta(days=days), **kw}


@pytest.mark.parametrize("t,ch", [
    (tp(click_ids={"gclid": "x"}), "paid_search"),
    (tp(utm={"utm_medium": "cpc", "utm_source": "google"}), "paid_search"),
    (tp(click_ids={"li_fat_id": "x"}), "paid_social"),
    (tp(utm={"utm_medium": "paid_social", "utm_source": "facebook"}), "paid_social"),
    (tp(click_ids={"fbclid": "x"}, referrer="https://l.facebook.com/"), "social"),     # fbclid alone is not paid
    (tp(utm={"utm_source": "linkedin", "utm_medium": "social"}), "social"),
    (tp(utm={"utm_source": "quora"}), "social"),
    (tp(utm={"utm_medium": "email"}), "email"),
    (tp(mail_token=True), "email"),
    (tp(referrer="https://www.google.com/"), "organic_search"),
    (tp(referrer="https://esomar.org/directory"), "referral"),
    (tp(), "direct"),
    (tp("mail_out"), "email"),
    (tp("chat"), "whatsapp"),
])
def test_channel_rules(t, ch):
    assert A.channel(t) == ch


def test_models_weights():
    path = [{"channel": c} for c in ("organic_search", "email", "email", "direct")]
    assert A.credits(path, "first_touch") == [1, 0, 0, 0]
    assert A.credits(path, "last_touch") == [0, 0, 0, 1]
    assert A.credits(path, "last_non_direct") == [0, 0, 1, 0]
    assert A.credits(path, "position_based") == [0.4, 0.1, 0.1, 0.4]
    assert A.credits(path[:2], "position_based") == [0.5, 0.5]
    assert A.credits([{"channel": "direct"}], "last_non_direct") == [1]
    for m in A.MODELS:
        assert abs(sum(A.credits(path, m)) - 1) < 1e-9
    assert A.credits([], "first_touch") == []


def test_attribute_counts_only_touches_before_conversion_and_splits_value():
    tps = [tp(days=0, referrer="https://google.com"), tp("mail_out", days=3), tp(days=5), tp(days=20, click_ids={"gclid": "g"})]
    r = A.attribute(tps, {"id": "o:won", "event": "won", "at": D0 + timedelta(days=10), "value_inr": 100000})
    assert r["touches"] == 3 and r["path"] == ["organic_search", "email", "direct"] and r["days_to_convert"] == 10
    assert r["models"]["last_non_direct"] == {"email": {"credit": 1.0, "value_inr": 100000.0}}
    pb = r["models"]["position_based"]
    assert pb["organic_search"]["value_inr"] == 40000 and pb["email"]["value_inr"] == 20000 and pb["direct"]["value_inr"] == 40000


def _world():
    d = {n: FakeDB() for n in ("crm_db", "email_automation", "torpedo_gmail", "finance_db")}
    gd = lambda n: d[n]
    cid, pid = ObjectId(), ObjectId()
    lead = {"_id": ObjectId(), "email": "asha@builder.in", "contact_id": str(cid), "bu": "BIM",
            "web_submissions": [{"at": D0 + timedelta(days=4), "page": "https://bimwavesolutions.com/contact",
                                 "utm": {}, "click_ids": {}, "visitor_id": "v1", "heard_from": "Google"}]}
    d["crm_db"]["leads"].insert_one(lead)
    ea = d["email_automation"]
    ea["web_visitors"].insert_one({"visitor_id": "v1", "lead_id": str(lead["_id"]),
                                   "first_touch": {"utm_source": "google", "utm_medium": "cpc", "gclid": "G1",
                                                   "ts": (D0 - timedelta(days=2)).isoformat() + "Z"}})
    ea["web_visitors"].insert_one({"visitor_id": "stranger", "form_email": "other@x.com"})
    ea["web_sessions"].insert_one({"session_id": "s1", "visitor_id": "v1", "started_at": D0 + timedelta(days=4),
                                   "utm": {}, "click_ids": {}, "referrer": "", "bu": "BIM"})
    ea["web_sessions"].insert_one({"session_id": "s9", "visitor_id": "stranger", "started_at": D0})
    d["torpedo_gmail"]["email_metadata"].insert_one({"mail_counterparty": "asha@builder.in", "direction": "outbound",
                                                     "timestamp": D0 + timedelta(days=5), "subject": "Re: enquiry"})
    d["crm_db"]["opportunities"].insert_one({"contact_id": cid, "created_at": D0 + timedelta(days=6), "status": "won",
                                             "won_at": D0 + timedelta(days=9), "amount": 430, "currency": "USD",
                                             "project_id": str(pid)})
    d["finance_db"]["invoices"].insert_one({"ops_project_id": str(pid), "subtotal": 250000, "currency_code": "INR",
                                            "status": "sent"})
    return d, gd, lead


def test_build_links_only_deterministic_touchpoints():
    d, gd, lead = _world()
    tps = T.build(gd, lead)
    kinds = sorted(t["kind"] for t in tps)
    assert kinds == ["form", "mail_out", "visit", "visit"]                        # stranger's session not included
    first = min(tps, key=lambda t: t["at"])
    assert first["channel"] == "paid_search" and first["ref"] == "first:v1"
    assert len({t["tp_key"] for t in tps}) == 4 and all(t["lead_id"] == str(lead["_id"]) for t in tps)


def test_conversions_use_invoiced_inr_over_won_amount():
    d, gd, lead = _world()
    c = {x["event"]: x for x in T.conversions(gd, lead)}
    assert c["rfq"]["value_inr"] == 0
    assert c["won"]["value_inr"] == 250000 and c["won"]["value_basis"] == "invoiced" and not c["won"]["fx_missing"]


def test_foreign_won_amount_without_rate_is_not_guessed():
    out = T.revenue_inr(FakeDB(), {"amount": 430, "currency": "USD"})
    assert out["value_inr"] == 0 and out["fx_missing"] and out["value"] == 430


def test_run_dry_reports_and_writes_nothing():
    d, gd, lead = _world()
    rep = T.run(gd, apply=False)
    assert rep["leads"] == 1 and rep["touchpoints"] == 4 and rep["conversions"] == {"rfq": 1, "won": 1}
    assert rep["won_value_inr"] == 250000
    assert rep["channel_last_non_direct"]["won:email"] == 1.0          # the reply mail was the last non-direct touch
    assert d["email_automation"]["touchpoints"].count_documents({}) == 0
    assert d["email_automation"]["attribution_results"].count_documents({}) == 0
