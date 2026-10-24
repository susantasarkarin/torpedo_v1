"""CRM plan 3.2.2-3.2.3: one company -> one BU; accounts keep theirs; model only for new companies."""
from tests._fakemongo import FakeDB
from leads import bucket_classifier as bc


def test_company_domain_from_website_or_work_email_not_webmail():
    assert bc.company_domain({"company_website": "https://www.Kantar.co.uk/about"}) == "kantar.co.uk"
    assert bc.company_domain({"email": "raj@ipsos.com"}) == "ipsos.com"
    assert bc.company_domain({"email": "raj@gmail.com"}) is None


def test_existing_account_keeps_its_bu():
    db = FakeDB()
    db["accounts"].insert_one({"domain": "acme.com", "status": None, "bu": "BIM", "name": "Acme"})
    out = bc.company_bucket({"email": "a@acme.com"}, accounts=db["accounts"], raw=db["leads_raw"])
    assert out["bucket"] == "BIM" and out["method"] == "account_bu"


def test_second_lead_at_a_company_reuses_the_model_bucket_without_a_call():
    db = FakeDB()
    db["leads_raw"].insert_one({"company_domain": "acme.com", "outreach_bucket": "SFW",
                                "outreach_bucket_method": "cheap", "outreach_bucket_confidence": 0.9})
    out = bc.company_bucket({"_id": "new", "company_domain": "acme.com"}, threshold=0.7,
                            accounts=db["accounts"], raw=db["leads_raw"])
    assert out["bucket"] == "SFW" and out["method"] == "company_reuse"


def test_low_confidence_or_review_is_not_reused():
    db = FakeDB()
    db["leads_raw"].insert_one({"company_domain": "acme.com", "outreach_bucket": "SFW",
                                "outreach_bucket_method": "cheap", "outreach_bucket_confidence": 0.4})
    db["leads_raw"].insert_one({"company_domain": "acme.com", "outreach_bucket": "REVIEW",
                                "outreach_bucket_method": "cheap", "outreach_bucket_confidence": 0.95})
    assert bc.company_bucket({"company_domain": "acme.com"}, threshold=0.7,
                             accounts=db["accounts"], raw=db["leads_raw"]) is None


def test_bu_descriptions_come_from_config(monkeypatch):
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s: {"descriptions": {"BIM": {"what_we_sell": "Scan-to-BIM only"}}})
    assert "Scan-to-BIM only" in bc._bucket_briefing()
