"""Clients and leads that fell through the cracks: who counts, and the text checks."""
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services import reengagement as re_

NOW = datetime(2026, 9, 29)


def test_quote_is_silent_only_between_a_week_and_six_months_with_no_client_mail():
    q = NOW - timedelta(days=10)
    assert re_.quote_is_silent(q, None, NOW)
    assert re_.quote_is_silent(q, q - timedelta(days=2), NOW)          # their mail came before the quote
    assert not re_.quote_is_silent(q, q + timedelta(days=1), NOW)      # they answered
    assert not re_.quote_is_silent(NOW - timedelta(days=3), None, NOW)  # too soon
    assert not re_.quote_is_silent(NOW - timedelta(days=200), None, NOW)
    assert not re_.quote_is_silent(None, None, NOW)


def test_dormant_client():
    won = NOW - timedelta(days=400)
    assert re_.is_dormant(NOW - timedelta(days=150), won, False, NOW)
    assert not re_.is_dormant(NOW - timedelta(days=30), won, False, NOW)   # still talking
    assert not re_.is_dormant(NOW - timedelta(days=150), won, True, NOW)   # something open with them
    assert not re_.is_dormant(None, NOW - timedelta(days=365 * 6), False, NOW)  # too long ago


def test_positive_lead_gone_quiet():
    lead = {"lead_status": "Positive"}
    old = NOW - timedelta(days=40)
    assert re_.positive_is_quiet(lead, old, NOW)
    assert not re_.positive_is_quiet(lead, NOW - timedelta(days=5), NOW)
    assert not re_.positive_is_quiet({**lead, "nurture": {"status": "active"}}, old, NOW)
    assert not re_.positive_is_quiet({**lead, "stage": "won"}, old, NOW)
    assert not re_.positive_is_quiet({"lead_status": "Negative"}, old, NOW)


def test_cooldown():
    assert re_.due(None, NOW)
    assert not re_.due({"next_eligible_at": NOW + timedelta(days=1)}, NOW)
    assert re_.due({"next_eligible_at": NOW - timedelta(days=1)}, NOW)


def test_text_checks_refuse_invented_numbers_links_and_missing_greeting():
    ok = "Hi Keya, " + "just checking whether you had a chance to review the quote we sent. " * 3
    assert re_.check_text(ok, "Keya", "Keya Hansa") is None
    assert "number" in re_.check_text(ok + " It is 20% off.", "Keya", "Keya")
    assert re_.check_text(ok + " See https://x.com", "Keya", "") == "link or placeholder"
    assert re_.check_text(ok.replace("Hi Keya", "Hello"), "Keya", "") == "does not greet them by name"
    assert re_.check_text("Hi Keya, thanks.", "Keya", "")  # too short


def test_sign_off_trimmed():
    assert re_._trim_sign_off("Hi Keya,\n\nBody here.\n\nBest regards,\nSusanta") == "Hi Keya,\n\nBody here."


def test_falls_back_to_the_template_when_the_model_is_down():
    from leads import local_slm_client
    with patch.object(local_slm_client, "chat_json", side_effect=local_slm_client.LocalSLMUnavailable("down")):
        out = re_.write_check_in("quote_no_reply", {"first": "Keya", "company": "Hansa", "what": "Iceland B2B"})
    assert out["source"] == "template" and out["subject"] == "Re: Iceland B2B" and "Hi Keya" in out["body"]


def test_model_text_used_when_it_passes():
    from leads import local_slm_client
    body = "Hi Keya, " + "we wanted to see if the quote for Iceland B2B works for you and whether anything should change. " * 2
    with patch.object(local_slm_client, "chat_json", return_value={"subject": "Quote", "body": body + "\nBest,\nSusanta"}):
        out = re_.write_check_in("quote_no_reply", {"first": "Keya", "company": "Hansa", "what": "Iceland B2B"})
    assert out["source"] == "ai" and out["subject"] == "Re: Iceland B2B" and not out["body"].endswith("Susanta")


def test_positive_older_than_a_year_is_not_picked_back_up():
    assert not re_.positive_is_quiet({"lead_status": "Positive"}, NOW - timedelta(days=400), NOW)


def test_our_own_people_are_not_prospects():
    assert re_.is_own({"company_name": "Survey Fieldwork", "email": "someone@gmail.com"})
    assert re_.is_own({"company_name": "", "email": "a@cogentixresearch.com"})
    assert not re_.is_own({"company_name": "Hansa Research Group", "email": "k@hansaresearch.com"})


def test_reply_subject_keeps_the_thread():
    assert re_._reply_subject("Re: [External] Re: fieldwork support") == "Re: fieldwork support"
    assert re_._reply_subject("") == "Following up"


def test_model_subject_never_leaks_our_labels():
    from leads import local_slm_client
    body = "Hi Lucy, " + "picking up where we left off on fieldwork support in APAC, would a short call help? " * 2
    with patch.object(local_slm_client, "chat_json", return_value={"subject": "Positive response from Lucy", "body": body}):
        out = re_.write_check_in("positive_quiet", {"first": "Lucy", "what": "RE: fieldwork support"})
    assert out["subject"] == "Re: fieldwork support"


def test_model_sign_off_and_placeholder_company_cut():
    body = "Hi Ramiz,\n\nWe sent you a quote a few weeks ago.\n\nBest regards,\nYour Company Name"
    assert re_._trim_sign_off(body) == "Hi Ramiz,\n\nWe sent you a quote a few weeks ago."
    assert re_.check_text("Hi Ramiz, " + "word " * 25 + "from Your Company", "Ramiz", "") == "link or placeholder"


def test_our_rfq_codes_and_domains_stay_out_of_the_letter():
    assert re_.study_name("RFQ_Fitted Homes Study_HRG_SFW") == "Fitted Homes Study"
    assert re_.study_name("RFQ SG B2B (SF-134859)") == "SG B2B (SF-134859)"
    assert re_.company_display("hdfclife.com") == "your team"
    assert re_.company_display("Hansa Research Group") == "Hansa Research Group"


def test_quote_draft_keeps_the_threads_subject():
    from leads import local_slm_client
    with patch.object(local_slm_client, "chat_json", side_effect=local_slm_client.LocalSLMUnavailable("down")):
        out = re_.write_check_in("quote_no_reply", {"first": "Ramiz", "what": "RFQ_Fitted Homes Study_HRG_SFW",
                                                    "thread_subject": "RE: Fitted Homes - costs"})
    assert out["subject"] == "Re: Fitted Homes - costs" and "Fitted Homes Study" in out["body"]
    assert "HRG" not in out["body"]


def test_draft_that_talks_about_the_reader_is_refused():
    body = ("Hi Vaishali, We had a previous positive interaction with Trackopinion. We noticed they asked for "
            "the requested information in their reply. Let us re-open the conversation and arrange a brief call.")
    assert re_.check_text(body, "Vaishali", "") == "internal wording"
