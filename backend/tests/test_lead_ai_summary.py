"""The lead page AI summary describes the lead, never our own pitch."""

from leads.service import build_ai_summary

OUR_PITCH = {"direction": "outbox", "ai_summary": "Indira Das from Survey Fieldwork pitches panels"}
THEIR_REPLY = {"direction": "inbox", "ai_summary": "The sender says Kantar has in-house fieldwork."}


def test_conversation_summary_wins():
    lead = {"mail_pool": {"model_summary": "Kantar declined; has in-house fieldwork."}}
    assert build_ai_summary(lead, [THEIR_REPLY]) == ("Kantar declined; has in-house fieldwork.", "conversation")


def test_only_their_emails_are_summarised():
    assert build_ai_summary({}, [OUR_PITCH, THEIR_REPLY]) == (THEIR_REPLY["ai_summary"], "emails")


def test_our_pitch_alone_falls_back_to_their_latest_email():
    assert build_ai_summary({"conversation_summary": "raw text"}, [OUR_PITCH]) == ("raw text", "latest_email")
