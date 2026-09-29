"""AI-first RFQ decisions: the model decides, a guard checks it against the mail."""
from app.services import rfq_ai


def _model(monkeypatch, answer):
    monkeypatch.setattr(rfq_ai, "_ask", lambda *a, **k: answer)


LIVE_MAIL = ("Hi Susanta, Please find the live survey link below for your reference: "
             "https://hansacheetah.com/router?tid=HVtReSPf&uid=[identifier]")


def test_live_link_accepted_when_the_mail_carries_their_link(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "test_link_only": False, "study_name": "Project KSI", "reason": "x"})
    d, status = rfq_ai.live_link("RE: RFQ - Project KSI 2026", LIVE_MAIL)
    assert status == "ai" and d["url"].startswith("https://hansacheetah.com/router")


def test_mails_without_a_link_never_reach_the_model(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "test_link_only": False, "study_name": "", "reason": ""})
    # never a win: either not worth asking, or the model's "yes" fails the check
    assert rfq_ai.live_link("Re: RFQ", "Kindly send us the live links so we can launch")[1] in (
        "not_candidate", "guard_rejected")


def test_our_own_redirect_links_are_not_their_live_link(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "test_link_only": False, "study_name": "", "reason": ""})
    text = "The survey is live. Terminate: https://prod1-survey-field-work.secure.force.com/surveyterminate?rId=X"
    assert rfq_ai.live_link("Re: RFQ", text)[1] == "not_candidate"


def test_a_promise_of_a_live_link_is_not_a_live_link(monkeypatch):
    # live, 2026-09-28: the model called this "sent" because of the signature homepage
    _model(monkeypatch, {"live_link_sent": True, "test_link_only": False, "study_name": "DS5465", "reason": ""})
    text = ("Hello Indira  Please be on hold for the live link and let you know once the live link is ready.  "
            "Mukul  Supply Management  https://datanalservices.com/  https://www.linkedin.com/in/mukul-g")
    assert rfq_ai.live_link("Re: DS5465", text)[1] in ("not_candidate", "guard_rejected")


def test_live_link_block_with_test_and_live_urls(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "test_link_only": False, "study_name": "UK", "reason": ""})
    text = ("Below are the test and live links for each market. UK: Test link: https://emea.focusvision.com/survey/"
            "selfserve/28e9/211200?test=1  LIVE LINK https://emea.focusvision.com/survey/selfserve/28e9/211200?prcode=10")
    d, status = rfq_ai.live_link("RFQ Marketing", text)
    assert status == "ai" and "focusvision.com/survey" in d["url"]


# cases from the 2026-09-28 dry run on real mail

def test_test_links_are_not_live_even_with_live_in_the_subject(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "told_to_launch": False, "test_link_only": False,
                         "study_name": "Live Sound Engineers", "reason": ""})
    text = ("Hi Susanta, I'm stepping in for Aleena on this project. Please find the test links below: "
            "NA: https://visiondatahub.com/Screen?rtid=4KidPJFE&ruid=[identifier]")
    assert rfq_ai.live_link("Re: RFQ – Live Sound Engineers & SIers Recruitment", text)[1] in (
        "not_candidate", "guard_rejected")


def test_not_live_is_not_live_and_a_logo_is_not_a_link(monkeypatch):
    _model(monkeypatch, {"live_link_sent": True, "told_to_launch": False, "test_link_only": False,
                         "study_name": "NR14288_CG", "reason": ""})
    text = ("Hi Team, The market is not live please pause the study for now and kindly make the study live "
            "tomorrow morning for only 10 completes. [Logo]<https://www.neotericresearch.in/assets/img/logo.png>")
    d, status = rfq_ai.live_link("RE: NR14288_CG", text)
    assert status == "guard_rejected" or not (d["live_link_sent"] or d["told_to_launch"])


def test_a_launch_instruction_is_a_win(monkeypatch):
    _model(monkeypatch, {"live_link_sent": False, "told_to_launch": True, "test_link_only": False,
                         "study_name": "NR14303_CG", "reason": ""})
    d, status = rfq_ai.live_link("RE: NR14303_CG", "Hi Team, The test ID is captured please launch the study "
                                                   "for 20 completes. Regards, Ankush")
    assert status == "ai" and d["told_to_launch"] and not d["live_link_sent"] and d["url"] is None


def test_a_go_ahead_with_a_po_is_commissioned(monkeypatch):
    _model(monkeypatch, {"live_link_sent": False, "told_to_launch": False, "commissioned": True,
                         "test_link_only": False, "study_name": "Advertising DM's", "reason": ""})
    d, status = rfq_ai.live_link("RE: FW: RFQ - Advertising DM's // A-17611",
                                 "Hello Rahul, Thank you for this, we would like to go ahead with this project! "
                                 "I have also updated the subject line with our PO number – A-17611")
    assert status == "ai" and d["commissioned"]


def test_a_supplier_offering_us_is_not_a_win(monkeypatch):
    _model(monkeypatch, {"live_link_sent": False, "told_to_launch": False, "commissioned": True,
                         "test_link_only": False, "study_name": "", "reason": ""})
    d, status = rfq_ai.live_link("RE: Coleman Research", "Hi Rahul, We are feasible for this survey request under "
                                 "the following specifications. We look forward to your thoughts on next steps, "
                                 "go ahead with this")
    assert status == "guard_rejected"


def test_model_outage_is_not_a_verdict(monkeypatch):
    _model(monkeypatch, None)
    assert rfq_ai.live_link("Re: RFQ", LIVE_MAIL) == (None, "unavailable")


def test_quote_numbers_must_be_in_the_reply(monkeypatch):
    _model(monkeypatch, {"quoted": True, "cpi": 1000, "total": 5000, "currency": "USD", "taxes_extra": False})
    assert rfq_ai.quote("Hi Ramiz, please find attached.")[1] == "guard_rejected"


def test_quote_read_by_the_model_is_kept_when_the_mail_says_it(monkeypatch):
    _model(monkeypatch, {"quoted": True, "cpi": 115, "total": None, "currency": "INR", "taxes_extra": True})
    q, status = rfq_ai.quote("Hi Ramiz, Our quote for this study is INR 115+taxes.")
    assert status == "ai" and q == {"quoted": True, "cpi": 115, "total": None, "currency": "INR", "taxes_extra": True}


def test_a_currency_the_mail_does_not_show_is_dropped(monkeypatch):
    _model(monkeypatch, {"quoted": True, "cpi": 140, "total": None, "currency": "USD", "taxes_extra": True})
    q, _ = rfq_ai.quote("Our CPI for this study will be 140 + taxes.")
    assert q["cpi"] == 140 and q["currency"] is None


def test_live_link_mail_is_matched_to_the_rfq_by_company_and_study_words():
    from datetime import datetime
    from app.services import rfq_from_mail as rb

    class _Opp:
        def __init__(self, docs):
            self.docs = docs

        def find_one(self, q):
            return next((d for d in self.docs if q.get("metadata.rfq.gmail_thread_ids") in
                         d["metadata"]["rfq"].get("gmail_thread_ids", [])), None)

        def find(self, q, proj=None):
            import re
            rx = q["metadata.rfq.from_email"]["$regex"]
            lo, hi = q["metadata.rfq.received_at"]["$gte"], q["metadata.rfq.received_at"]["$lte"]
            return [d for d in self.docs if re.search(rx, d["metadata"]["rfq"]["from_email"], re.I)
                    and lo <= d["metadata"]["rfq"]["received_at"] <= hi]

    docs = [
        {"_id": 1, "title": "RFQ_FinPulse_HRG_SFW", "metadata": {"rfq": {"from_email": "r@hansaresearch.com",
         "received_at": datetime(2026, 9, 1), "gmail_thread_ids": ["t1"]}}},
        {"_id": 2, "title": "RFQ_Project Bio_HRG_SFW", "metadata": {"rfq": {"from_email": "r@hansaresearch.com",
         "received_at": datetime(2026, 9, 5), "gmail_thread_ids": ["t2"]}}},
    ]
    client = {"crm_db": {"opportunities": _Opp(docs)}}
    mail = {"gmail_thread_id": "other", "from_email": "keya@hansaresearch.com", "timestamp": datetime(2026, 9, 20),
            "subject": "Live link: FinPulse"}
    assert rb._rfq_for_live_link(client, mail, "FinPulse")["_id"] == 1
    same_thread = {"gmail_thread_id": "t2", "from_email": "x@y.com", "timestamp": datetime(2026, 9, 20), "subject": ""}
    assert rb._rfq_for_live_link(client, same_thread, "")["_id"] == 2
