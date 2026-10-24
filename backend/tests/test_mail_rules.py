"""3.3 rules decided in code: bounces, OOO return, reconnect date, transfers, signals."""
from datetime import date, datetime

from mail_pipeline import rules as r

RECV = datetime(2026, 10, 24, 10, 0)   # Saturday


def test_hard_bounce_by_dsn_code_and_recipient():
    body = "Final-Recipient: rfc822; jane@acme.com\nStatus: 5.1.1\nDiagnostic-Code: smtp; 550 5.1.1 user unknown"
    b = r.parse_bounce("Undeliverable: hello", body)
    assert b == {"kind": "hard", "code": "5.1.1", "recipient": "jane@acme.com"}


def test_soft_bounce_by_4xx_and_mailbox_full():
    assert r.parse_bounce("Delivery delayed", "Status: 4.4.7 message delayed")["kind"] == "soft"
    assert r.parse_bounce("Undeliverable", "Status: 5.2.2 mailbox full")["kind"] == "soft"
    assert r.parse_bounce("Delivery Status", "Mailbox is full, try again later")["kind"] == "soft"


def test_unreadable_bounce_is_treated_as_hard():
    assert r.parse_bounce("Undeliverable", "something went wrong")["kind"] == "hard"


def test_gmail_style_bounce_recipient():
    b = r.parse_bounce("Delivery Status Notification (Failure)",
                       "Your message wasn't delivered to amit@example.co.in because the address couldn't be found")
    assert b["kind"] == "hard" and b["recipient"] == "amit@example.co.in"


def test_ooo_return_dates():
    assert r.ooo_return_date("I am out of the office until 3 November with limited access", RECV) == date(2026, 11, 3)
    assert r.ooo_return_date("Back on Monday, Nov 2nd", RECV) == date(2026, 11, 2)
    assert r.ooo_return_date("I will be back on 05/11/2026", RECV) == date(2026, 11, 5)
    assert r.ooo_return_date("Out until January 5", RECV) == date(2027, 1, 5)       # next year
    assert r.ooo_return_date("I am away", RECV) is None


def test_next_working_day_skips_weekend():
    assert r.next_working_day(date(2026, 10, 30)) == date(2026, 11, 2)              # Fri -> Mon


def test_reconnect_later():
    assert r.reconnect_date("Please reach out in 2 weeks", RECV) == date(2026, 11, 7)
    assert r.reconnect_date("Let's connect next quarter", RECV) == date(2027, 1, 23)
    assert r.reconnect_date("Can you follow up in January?", RECV) == date(2027, 1, 1)
    assert r.reconnect_date("Not right now, thanks", RECV) == date(2026, 11, 7)      # default 14 days
    assert r.reconnect_date("Sounds good, send the deck", RECV) is None


def test_transfer_target():
    ours = {"surveyfieldwork.com"}
    t = "I'm not the right person, please contact priya.k@acme.com who handles vendors."
    assert r.transfer_target(t, ours, "raj@acme.com") == "priya.k@acme.com"
    assert r.transfer_target("Wrong person, sorry", ours, "raj@acme.com") == "unknown"
    assert r.transfer_target("Thanks, interested", ours, "raj@acme.com") is None


def test_signals():
    assert r.signals("Please go ahead with the project, PO attached")["confirmation"]
    assert r.signals("Kindly share the redirect links for the survey")["redirect_request"]
    assert r.signals("Please quote: India n=500, LOI 15, IR 40%")["rfq"]
    assert not r.signals("Thanks for the note")["rfq"]
