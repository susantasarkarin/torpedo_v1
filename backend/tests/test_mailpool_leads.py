"""
Tests for sales/mailpool_leads.py (mail pool -> client / vendor leads).
"""
from datetime import datetime, timedelta

from app.services import mail_categorizer as mc
from sales import mailpool_leads as ml


def _ctx(**kw):
    base = dict(client_domains={"hansaresearch.com"}, vendor_domains={"purespectrum.com"},
                client_emails=set(), vendor_emails=set(), outreach_threads=set(),
                relationships={"cint.com": "both"}, both_defaults={"cint.com": "vendor"},
                thread_opener={"t-cint-rfq": "them"})
    base.update(kw)
    return mc.Context(**base)


def _party(cat, sender=None, to=None, thread=None, openers=None):
    doc = {"ai_tier1_category": cat, "gmail_thread_id": thread,
           "direction": "outbound" if to else "inbound", "from_email": sender, "to_emails": to or []}
    return ml.party_for(doc, _ctx(), openers or {})


# ---- summary ----------------------------------------------------------------

def test_summary_skips_greeting_quote_and_signature():
    body = ("Hi Susanta,\n\nPlease share the costing for 500 completes in Brazil. "
            "We need it by Friday.\n\nRegards,\nKeya\n\nOn Mon, 1 Sep 2025 Susanta wrote:\n> old text")
    s = ml.extract_summary("RFQ_Brazil", body)
    assert s.startswith("Please share the costing for 500 completes in Brazil.")
    assert "Regards" not in s and "old text" not in s


def test_summary_falls_back_to_subject():
    assert ml.extract_summary("Invoice attached", "") == "Invoice attached"


# ---- counterparty ------------------------------------------------------------

def test_counterparty_is_the_external_side():
    assert ml.counterparty({"direction": "inbound", "from_email": "Keya@HansaResearch.com"}) == "keya@hansaresearch.com"
    assert ml.counterparty({"direction": "outbound",
                            "to_emails": ["indira@surveyfieldwork.com", "rohit@cint.com"]}) == "rohit@cint.com"
    assert ml.counterparty({"direction": "inbound", "from_email": "susanta@cogentixresearch.com"}) == ""


# ---- client / vendor / promotional -----------------------------------------

def test_known_parties():
    assert _party("rfq", "keya@hansaresearch.com") == "client"
    assert _party("others", "ops@purespectrum.com") == "vendor"
    assert _party("invoice", "billing@purespectrum.com") == "vendor"


def test_both_party_follows_the_thread():
    assert _party("rfq", "gurujot@cint.com", thread="t-cint-rfq") == "client"
    assert _party("others", "sheik@cint.com", thread="t-other") == "vendor"


def test_noise_categories():
    assert _party("promotional", "news@yourstory.com") == "promotional"
    assert _party("spam", "x@scam.biz") == "promotional"
    assert _party("automated", "noreply@github.com") == "automated"
    assert _party("outreach", to=["buyer@acme.com"]) == "outreach"


def test_unknown_rfq_is_judged_by_who_opened_the_thread():
    assert _party("rfq", to=["quotes@newvendor.com"], thread="t1", openers={"t1": "us"}) == "vendor"
    assert _party("rfq", "buyer@newclient.com", thread="t2", openers={"t2": "them"}) == "client"
    assert _party("rfq", "buyer@newclient.com") == "client"  # inbound RFQ with no thread history


def _party_body(cat, sender, subject, body):
    doc = {"ai_tier1_category": cat, "direction": "inbound", "from_email": sender,
           "subject": subject, "body": body, "gmail_thread_id": None}
    return ml.party_for(doc, _ctx(), {})


def test_an_unknown_company_sending_us_an_estimate_is_a_vendor():
    assert _party_body("proposal", "niddhi@nuagecx.com", "Re: Scope of Work & Estimate Enclosed- Survey Fieldwork",
                       "Just following up on the estimate shared.") == "vendor"
    assert _party_body("new_inquiry", "vamsi@dhruvsoft.com", "Re: Follow-up",
                       "I wanted to follow up on the proposal for Zoho Products Implementation that I shared earlier.") == "vendor"


def test_replies_to_our_supplier_sourcing_mailer_are_vendors():
    assert _party_body("proposal", "tejash@strateworks.co.in",
                       "Re: Looking for Partners in Zoho ERP implementation", "status of the proposal?") == "vendor"


def test_a_client_asking_for_our_quote_is_still_a_client():
    assert _party_body("proposal", "buyer@newclient.com", "Re: Brazil study",
                       "Can you send your quote for 500 completes?") == "client"


def test_prospect_reply_is_client_side():
    assert _party("outreach_reply", "cmo@prospect.com") == "client"
    assert _party("new_inquiry", "someone@startup.io") == "client"


def test_system_addresses_never_become_leads(monkeypatch):
    monkeypatch.setattr(mc, "_production_patterns",
                        lambda: (mc.re.compile("mailer-daemon"), mc.re.compile("x"), None))
    assert not ml._is_person_address("noreply@hansaresearch.com")
    assert not ml._is_person_address("mailer-daemon@google.com")
    assert ml._is_person_address("keya.kundu@hansaresearch.com")


# ---- lead records ----------------------------------------------------------------

class _Col:
    name = "leads_enriched"

    def __init__(self, docs=()):
        self.docs = list(docs)
        self.ops = []

    def find(self, *a, **k):
        return list(self.docs)

    def bulk_write(self, ops, ordered=False):
        self.ops.extend(ops)


def _row(email, **kw):
    now = datetime.utcnow()
    r = {"_id": email, "messages_in": 3, "messages_out": 2, "first_contact_at": now - timedelta(days=90),
         "last_contact_at": now, "last_subject": "RFQ_Bev", "last_summary": "Needs a quote.",
         "last_direction": "inbound", "categories": ["rfq"], "name": "Keya Kundu"}
    r.update(kw)
    return r


def test_new_client_contact_lands_on_the_leads_page():
    col = _Col()
    stats = ml.upsert_client_leads({"email_automation": {"leads_enriched": col}}, [_row("keya@hansaresearch.com")],
                                   datetime.utcnow())
    assert stats == {"created": 1, "updated": 0}
    doc = col.ops[0]._doc
    assert doc["source"] == "gmail"  # a source the Sales > Leads page shows
    assert doc["company_name"] == "Hansaresearch" and doc["mail_pool"]["relationship"] == "client"


def test_existing_lead_keeps_its_fields_and_a_summary_someone_wrote():
    col = _Col([{"_id": 7, "email": "Keya@hansaresearch.com"}])
    ml.upsert_client_leads({"email_automation": {"leads_enriched": col}}, [_row("keya@hansaresearch.com")],
                           datetime.utcnow())
    first, second = col.ops
    assert set(first._doc["$set"]) == {"mail_pool", "updated_at"}
    # the summary write is guarded: only an empty or mail-pool-written summary is replaced
    assert "$or" in second._filter


def test_vendor_contact_lands_on_vendor_leads():
    col = _Col()
    ml.upsert_vendor_leads({"email_automation": {"vendor_leads": col}}, [_row("sheik@cint.com")], datetime.utcnow())
    doc = col.ops[0]._doc
    assert doc["source"] == "mail_pool" and doc["status"] == "new" and doc["company"] == "Cint"
