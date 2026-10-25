"""AI Database segregation: rules decide first; a model label must quote its evidence."""
from leads import party_type

CTX = {"client_domains": {"hansaresearch.com"}, "vendor_domains": {"samplehub.io"}, "service_domains": {"apollo.io"},
       "client_emails": set(), "vendor_emails": {"rep@repvendor.com"}}


def rec(**kw):
    base = {"email": "anita.rao@acme.com", "company_name": "Acme Foods", "company_domain": "acme.com",
            "company_industry": "Food & Beverages", "title": "Insights Manager", "outreach_bucket": None}
    return {**base, **kw}


def test_rules_order():
    assert party_type.rules(rec(company_domain="hansaresearch.com"), CTX)["label"] == "client"
    assert party_type.rules(rec(company_domain="samplehub.io"), CTX)["label"] == "vendor"
    assert party_type.rules(rec(email="rep@repvendor.com"), CTX)["label"] == "vendor"
    assert party_type.rules(rec(company_domain="apollo.io"), CTX)["label"] == "vendor"
    assert party_type.rules(rec(company_name="Dynata India", company_domain="dynata.com"), CTX)["label"] == "vendor"
    assert party_type.rules(rec(email="marketing@acme.com"), CTX)["label"] == "role_mailbox"
    assert party_type.rules(rec(outreach_bucket="REJECT"), CTX)["label"] == "not_relevant"
    assert party_type.rules(rec(outreach_bucket="COGENTIX_RESEARCH"), CTX)["label"] == "potential_client"
    assert party_type.rules(rec(), CTX) is None


def test_model_label_needs_quoted_evidence_and_sell_side_words_for_vendor():
    text = party_type.record_text(rec(company_industry="Online panel and sample provider"))
    assert party_type.model_check({"label": "vendor", "evidence": "Online panel and sample provider"}, text) == []
    assert party_type.model_check({"label": "vendor", "evidence": "Food & Beverages"}, party_type.record_text(rec()))
    assert party_type.model_check({"label": "potential_client", "evidence": "they love surveys"}, text)
    assert party_type.model_check({"label": "unclear", "evidence": ""}, text) == []
    assert party_type.model_check({"label": "role_mailbox", "evidence": "x"}, text)      # only the rules may say this


def test_classify_uses_model_only_when_rules_are_silent():
    calls = []

    def model(**kw):
        calls.append(kw)
        assert kw["enqueue_on_fail"] is False and kw["task"] == "contact_classification"
        return {"status": "ok", "data": {"label": "potential_client", "evidence": "Insights Manager"}, "problems": [], "tier": "qwen"}
    assert party_type.classify(rec(outreach_bucket="SFW"), CTX, model)["tier"] == "rules" and not calls
    out = party_type.classify(rec(), CTX, model)
    assert out["label"] == "potential_client" and out["tier"] == "qwen" and len(calls) == 1
    deferred = party_type.classify(rec(), CTX, lambda **k: {"status": "deferred"})
    assert deferred["label"] is None
    failed = party_type.classify(rec(), CTX, lambda **k: {"status": "failed", "data": None, "problems": ["x"]})
    assert failed["label"] == "unclear"
