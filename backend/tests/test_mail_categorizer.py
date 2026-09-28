"""
Tests for app/services/mail_categorizer.py (Mail Pool segregation).
Cases are taken from the 2026-09-28 dry run over the real 366k-message pool.
"""
from app.services import mail_categorizer as mc


def _ctx(**kw):
    base = dict(client_domains={"ipsos.com", "idfcfirst.bank.in", "hansaresearch.com"},
                vendor_domains={"cint.com", "ipsos.com"},
                client_emails=set(), vendor_emails=set(),
                outreach_threads={"thread-outreach-1"},
                bulk_subjects={"survey fieldwork - one stop solution for all your research needs",
                               "surveyfieldwork - one stop solution for all your research needs",
                               "i have a proposal!"})
    base.update(kw)
    return mc.Context(**base)


def _in(subject, sender, body="", thread=None):
    return mc.categorize_inbound({"subject": subject, "from_email": sender, "body": body,
                                  "gmail_thread_id": thread, "direction": "inbound"}, _ctx())


def _out(subject, to, thread=None):
    return mc.categorize_outbound({"subject": subject, "to_emails": to,
                                   "gmail_thread_id": thread, "direction": "outbound"}, _ctx())


# ---- system mail ---------------------------------------------------------------

def test_bounce_is_system_mail():
    r = _in("Delivery Status Notification (Failure)", "mailer-daemon@googlemail.com")
    assert (r["category"], r["system_subtype"]) == ("automated", "bounce")


def test_out_of_office_is_system_mail():
    r = _in("Automatic reply: Accepted: Project Briefing", "rupal@kalpataru.com")
    assert r["system_subtype"] == "out_of_office"


def test_calendar_acceptance_is_system_mail():
    assert _in("Accepted: Cogentix x Kalpataru", "rupal@kalpataru.com")["system_subtype"] == "calendar_response"


# ---- outreach --------------------------------------------------------------------

def test_reply_in_an_outreach_thread():
    assert _in("Re: anything", "buyer@acme.com", thread="thread-outreach-1")["category"] == "outreach_reply"


def test_reply_to_an_older_bulk_campaign_is_an_outreach_reply():
    r = _in("RE: SurveyFieldwork - One stop solution for all your research needs", "hroman@decisionanalyst.com")
    assert r["category"] == "outreach_reply"


def test_personalised_bulk_subject_is_recognised():
    assert mc.normalize_subject("Re: [SFW-BCC] Hi Rob, I have a Proposal!") == "i have a proposal!"
    assert _in("Re: Hi Valentin I have a Proposal!", "s@daisycon.com")["category"] == "outreach_reply"


def test_copy_of_our_own_bulk_mail_is_outreach_not_proposal():
    assert _in("Hi Rob I have a Proposal!", "indira@cogentixresearch.com")["category"] == "outreach"


# ---- our own domain ----------------------------------------------------------------

def test_internal_rfq_thread_is_rfq():
    assert _in("Re: RFQ_Cox Hispanics_USA", "susanta@surveyfieldwork.com")["category"] == "rfq"


def test_other_own_domain_mail_is_internal():
    assert _in("Re: Lake Constance region", "susanta@surveyfieldwork.com")["category"] == "internal"


# ---- business signals ---------------------------------------------------------------

def test_rfq_with_underscores_is_an_rfq():
    assert _in("RE: Urgent_RFQ _Bev_ Study", "imam@myriad-research.com")["category"] == "rfq"
    assert _in("RFQ_Tourism", "ashi@theinsightsshop.com")["category"] == "rfq"


def test_newsletter_mentioning_pricing_is_promotional_not_proposal():
    r = _in("MDR on UPI: the small fee", "newsletters@yourstory.com", body="new pricing for UPI")
    assert r["category"] == "promotional"


def test_sign_off_is_an_active_deal():
    assert _in("Re: WOOP x Cogentix | Client Sign-Off Kit", "shweta@woop.world")["category"] == "active_deal"


def test_bank_that_is_also_a_client_is_a_client():
    r = _in("Discussion on Mystery Audits", "himanshu@idfcfirst.bank.in")
    assert r["category"] == "client"


def test_plain_bank_mail_is_banking():
    assert _in("AXIS BANK : Statement for April 2025", "statements@axisbank.com")["category"] == "banking"


def test_a_domain_with_vendor_evidence_is_not_silently_a_client():
    # build_context removes plain buyers (strong RFQ senders) from the vendor
    # set before this point; whatever is still in both is a vendor.
    assert _in("Overview page counts", "samplingplatforms@ipsos.com")["category"] == "vendor"
    assert _in("Cint - API not working", "sheik@cint.com")["category"] == "vendor"


def test_a_vendor_quote_is_vendor_mail_not_a_sales_rfq():
    assert _in("RE: RFQ - US Gen Pop n=500", "rohit.tiwari@cint.com")["category"] == "vendor"
    assert _in("Revised pricing for the Brazil study", "sheik@cint.com")["category"] == "vendor"
    # a vendor's bill is still an invoice
    assert _in("Invoice INV-2231 from Cint", "billing@cint.com")["category"] == "invoice"


def test_relationship_set_by_a_person_beats_evidence():
    ctx = _ctx(client_domains={"cint.com", "hansaresearch.com"}, vendor_domains={"hansaresearch.com"},
               relationships={"cint.com": "vendor", "hansaresearch.com": "client"})
    assert ctx.party("rohit.tiwari@cint.com") == "vendor"
    assert ctx.party("keya.kundu@hansaresearch.com") == "client"


def _both_ctx():
    return _ctx(relationships={"cint.com": "both"}, both_defaults={"cint.com": "vendor"},
                thread_opener={"t-they-asked": "them", "t-we-asked": "us"})


def test_both_party_is_a_client_in_threads_they_opened():
    r = mc.categorize_inbound({"subject": "RFQ - India GP feasibility", "from_email": "rohit@cint.com",
                               "gmail_thread_id": "t-they-asked", "direction": "inbound"}, _both_ctx())
    assert r["category"] == "rfq"


def test_both_party_is_a_vendor_in_threads_we_opened():
    r = mc.categorize_inbound({"subject": "RE: RFQ - US GP n=500", "from_email": "rohit@cint.com",
                               "gmail_thread_id": "t-we-asked", "direction": "inbound"}, _both_ctx())
    assert r["category"] == "vendor"
    o = mc.categorize_outbound({"subject": "RFQ - US GP n=500", "to_emails": ["rohit@cint.com"],
                                "gmail_thread_id": "t-we-asked", "direction": "outbound"}, _both_ctx())
    assert o["category"] == "vendor"


def test_both_party_uses_its_default_when_the_thread_is_unknown():
    assert _both_ctx().role("rohit@cint.com", "t-unknown") == "vendor"
    ctx = _ctx(relationships={"cint.com": "both"}, both_defaults={"cint.com": "client"})
    assert ctx.role("rohit@cint.com", None) == "client"


def test_relationship_for_one_address_beats_its_domain():
    ctx = _ctx(relationships={"ipsos.com": "client", "denis.popa@ipsos.com": "vendor"})
    assert ctx.party("denis.popa@ipsos.com") == "vendor"
    assert ctx.party("someone@ipsos.com") == "client"


class _Agg:
    def __init__(self, rows):
        self.rows = rows

    def aggregate(self, pipeline, **kw):
        return list(self.rows)


def test_rfq_direction_counts_who_opened_the_thread(monkeypatch):
    monkeypatch.setattr(mc, "_production_patterns",
                        lambda: (mc.re.compile("mailer-daemon"), mc.re.compile("undeliverable"), None))
    rows = [
        {"_id": "t1", "dir": "inbound", "f": "keya@hansaresearch.com", "s": "RFQ_Bev"},
        {"_id": "t2", "dir": "outbound", "to": ["rohit@cint.com", "x@surveyfieldwork.com"], "s": "RFQ - US GP"},
        {"_id": "t3", "dir": "inbound", "f": "mailer-daemon@google.com", "s": "RFQ x"},
    ]
    asked, ours = mc.rfq_thread_direction({"torpedo_gmail": {"email_metadata": _Agg(rows)}})
    assert asked == {"hansaresearch.com": 1} and ours == {"cint.com": 1}


def test_webmail_domain_never_makes_a_client():
    ctx = _ctx(client_domains={"gmail.com"})
    assert ctx.party("someone@gmail.com") is None


def test_unplaced_mail_is_queued_for_the_model():
    r = _in("Quick question", "someone@unknown-co.com", body="Hello there")
    assert r["category"] == "others" and r["needs_ai"] is True


# ---- outbound -------------------------------------------------------------------------

def test_outbound_bulk_mail_is_outreach():
    assert _out("SurveyFieldwork - One stop solution for all your research needs",
                ["x@acme.com"])["category"] == "outreach"


def test_outbound_to_own_domain_only_is_internal():
    assert _out("lunch", ["indira@surveyfieldwork.com"])["category"] == "internal"


def test_outbound_rfq_wins_over_bulk():
    assert _out("RFQ – Live Sound Engineers", ["v@vendor.com"])["category"] == "rfq"


# ---- persistence + model pass -----------------------------------------------------------

def test_system_mail_sets_the_badge_fields():
    fields = mc._update_for({"category": "automated", "reason": "bounce", "system_subtype": "bounce"}, None)
    assert fields["email_type"] == "system" and fields["system_subtype"] == "bounce"
    assert fields["ai_tier1_system_set"] is True and fields["ai_tier1_status"] == "done"


def test_pending_status_for_model_queue():
    assert mc._update_for({"category": "others", "reason": "x", "needs_ai": True}, None)["ai_tier1_status"] == "pending_ai"


class _Col:
    def __init__(self, docs):
        self.docs = docs
        self.updates = []

    def aggregate(self, pipeline):
        return list(self.docs)

    def update_one(self, q, u):
        self.updates.append((q, u))


def test_ai_pass_never_records_an_outage_as_a_verdict_and_stops_on_a_streak(monkeypatch):
    col = _Col([{"_id": i, "subject": "s", "from_email": "a@b.com"} for i in range(10)])
    monkeypatch.setattr(mc, "model_categorize", lambda doc: (None, "model unavailable: timeout"))
    stats = mc.run_ai_pass({"torpedo_gmail": {"email_metadata": col}}, limit=10)
    assert stats == {"attempted": 3, "resolved": 0, "unavailable": 3}
    assert col.updates == []


def test_ai_pass_records_model_verdicts(monkeypatch):
    col = _Col([{"_id": 1, "subject": "s", "from_email": "a@b.com"}])
    monkeypatch.setattr(mc, "model_categorize", lambda doc: ("vendor", "supplier pitch"))
    mc.run_ai_pass({"torpedo_gmail": {"email_metadata": col}}, limit=5)
    q, u = col.updates[0]
    assert u["$set"]["ai_tier1_category"] == "vendor"
    assert u["$set"]["ai_tier1_source"] == mc.SOURCE_AI and u["$set"]["ai_tier1_status"] == "done"


def test_model_only_rfq_is_kept_as_a_suggestion_not_a_label(monkeypatch):
    col = _Col([{"_id": 1, "subject": "Reset Password", "from_email": "researchers@theoremreach.com"}])
    monkeypatch.setattr(mc, "model_categorize", lambda doc: ("rfq", "asks for a quote"))
    mc.run_ai_pass({"torpedo_gmail": {"email_metadata": col}}, limit=5)
    s = col.updates[0][1]["$set"]
    assert s["ai_tier1_category"] == "others" and s["ai_tier1_model_suggestion"] == "rfq"
    assert s["ai_tier1_reason"].startswith("possible rfq (model only, unverified)")


def test_reset_password_notice_is_automated():
    assert _in("Reset Password", "researchers@theoremreach.com")["category"] == "automated"
