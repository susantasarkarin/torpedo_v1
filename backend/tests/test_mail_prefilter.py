"""
Tests for sales/mail_prefilter.py. Examples are constructed from general email
conventions, not copied from the benchmark set, so the rules aren't tuned to it.
The keep-cases matter most: a false skip silently drops a real RFQ.
"""
import pytest

from sales import mail_prefilter as pf


def doc(from_email="a@client.com", subject="", body="", direction="inbound"):
    return {"from_email": from_email, "subject": subject, "body_plain": body,
            "direction": direction}


@pytest.mark.parametrize("d,reason", [
    (doc(direction="outbound", from_email="susanta@cogentixresearch.com"), "own_outbound"),
    (doc(from_email="MAILER-DAEMON@googlemail.com", subject="Re: hello"), "bounce_sender"),
    (doc(from_email="postmaster@corp.example", subject="x"), "bounce_sender"),
    (doc(subject="Delivery Status Notification (Failure)"), "bounce_subject"),
    (doc(subject="Undelivered Mail Returned to Sender"), "bounce_subject"),
    (doc(subject="Mail delivery failed: returning message to sender"), "bounce_subject"),
    (doc(subject="Automatic reply: Away until Monday"), "auto_reply"),
    (doc(subject="Automatische Antwort: Urlaub"), "auto_reply"),
    (doc(subject="[TAG] Out of Office"), "auto_reply"),
    (doc(subject="Automatisch antwoord: Afwezig"), "auto_reply"),
    (doc(subject="Respuesta automática: fuera de la oficina"), "auto_reply"),
    (doc(from_email="statements@bank.example", subject="September"), "automated_sender"),
    (doc(from_email="jobs-listings@network.example", subject="New jobs"), "automated_sender"),
    (doc(subject="Invitation: Project sync @ Tue 3pm"), "calendar_invite"),
    (doc(subject="Updated invitation: Project sync"), "calendar_invite"),
    (doc(subject="Accepted: Project sync"), "calendar_invite"),
    (doc(subject="Hello", body="You have been invited to the following event.\nTitle: X"),
     "calendar_invite"),
    (doc(from_email="no-reply@service.example", subject="Welcome"), "automated_sender"),
    (doc(from_email="notifications@tool.example", subject="New comment"), "automated_sender"),
    (doc(from_email="donotreply@bank.example", subject="Statement"), "automated_sender"),
    (doc(subject="Reset your password"), "transactional"),
    (doc(subject="Your verification code is 123456"), "transactional"),
    (doc(subject="Invoice available for January"), "transactional"),
    (doc(subject="Your subscription is renewed"), "transactional"),
    (doc(subject="Payment Reminder - 3 invoices pending"), "transactional"),
    (doc(subject="Invoice 4471 is overdue"), "transactional"),
    (doc(from_email="susanta@bimwavesolutions.com", subject="Re: quote"), "internal_sender"),
    (doc(from_email="news@writer.substack.com", subject="Weekly essay"), "bulk_newsletter"),
    (doc(subject="Essay", body="View this post on the web at https://x.example/p/1"),
     "bulk_newsletter"),
    (doc(from_email="susanta@cogentixresearch.com", subject="Re: quote"), "internal_sender"),
    (doc(from_email="Indira Das <indira@surveyfieldwork.com>", subject="Feasibility"),
     "internal_sender"),
])
def test_skips_known_noise(d, reason):
    assert pf.skip_reason(d) == reason


@pytest.mark.parametrize("d", [
    doc(from_email="buyer@gmail.com", subject="RFQ: 500 completes, US gen pop", body="Need CPI"),
    doc(from_email="pm@bilendi.com", subject="RFQ Nieuwe aanvraag NL, DE en VS", body="quota"),
    doc(from_email="ops@hansaresearch.com", subject="RFQ_Study_HRG", body="Please quote"),
    doc(from_email="pm@ipsos.com", subject="Feasibility request - Germany B2B"),
    doc(from_email="buyer@client.com", subject="Please quote", body="Unsubscribe from our list"),
    doc(from_email="ap@client.com", subject="Re: Pending Invoices", body="will check"),
    doc(from_email="pm@client.com", subject="RFQ: 500 completes; payment terms net 30"),
    doc(from_email="pm@client.com", subject="Quote for panel: invoice terms 30 days"),
    doc(from_email="support@client.com", subject="Need sample for tracker study"),
    doc(from_email="susanta@cogentixresearch.com", subject="Fw: RFQ from client", body="see below"),
    doc(from_email="susanta@cogentixresearch.com", subject="FWD: bid request", body="see below"),
    doc(from_email="pm@client.com", subject="Invitation to bid on a tracking study"),
])
def test_keeps_things_that_could_be_real_rfqs(d):
    assert pf.skip_reason(d) is None


def test_configured_skip_domain(monkeypatch):
    monkeypatch.setenv("MAIL_PREFILTER_SKIP_DOMAINS", "pure-vendor.example")
    assert pf.skip_reason(doc(from_email="a@mail.pure-vendor.example",
                              subject="Panel pricing")) == "configured_skip_domain"
    monkeypatch.delenv("MAIL_PREFILTER_SKIP_DOMAINS")
    assert pf.skip_reason(doc(from_email="a@mail.pure-vendor.example",
                              subject="Panel pricing")) is None


def test_partition_counts_reasons_and_keeps_order():
    docs = [doc(subject="RFQ 1"), doc(subject="Reset your password"),
            doc(subject="RFQ 2"), doc(subject="Invitation: x")]
    kept, skipped = pf.partition(docs)
    assert [d["subject"] for d in kept] == ["RFQ 1", "RFQ 2"]
    assert skipped == {"transactional": 1, "calendar_invite": 1}
