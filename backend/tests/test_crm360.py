"""Account 360 (CRM plan 3.8): one page, money per currency, BU never guessed."""
from datetime import datetime

import pytest
from bson import ObjectId

from tests._fakemongo import FakeDB
from crm360 import view


@pytest.fixture
def dbs(monkeypatch):
    d = {n: FakeDB() for n in ("crm_db", "finance_db", "torpedo_gmail", "email_automation")}
    monkeypatch.setattr(view, "_gd", lambda name: d[name])
    return d


def test_outstanding_is_per_currency_and_excludes_paid_and_draft(dbs):
    acc = ObjectId()
    cust = dbs["finance_db"]["customers"].insert_one({"crm_account_id": str(acc), "name": "Hansa"}).inserted_id
    for status, bal, cur in (("overdue", 100.0, "USD"), ("sent", 2000.0, "INR"), ("paid", 50.0, "USD"),
                             ("draft", 999.0, "INR"), ("partial", 25.5, "USD")):
        dbs["finance_db"]["invoices"].insert_one({"customer_id": str(cust), "status": status, "balance_due": bal,
                                                  "currency_code": cur, "invoice_date": datetime(2026, 10, 1)})
    f = view.finance(str(acc))
    assert f["outstanding_by_currency"] == {"USD": 125.5, "INR": 2000.0}
    assert len(f["invoices"]) == 5


def test_billing_entity_wins_over_receiving_mailbox():
    """Hansa: 440 RFQs into a Cogentix mailbox, invoiced by SFW -> SFW."""
    inv = [{"branch": "Survey Fieldwork"}] * 24
    rfqs = [{"metadata": {"rfq": {"mailbox_id": "m1"}}}] * 440
    out = view.derive_bu(inv, rfqs, {"m1": "COGENTIX"})
    assert out["bu"] == "SFW" and out["decided_by"] == "invoice_branch" and "another BU" in out["note"]


def test_mailbox_is_fallback_and_ties_are_not_guessed():
    rfqs = [{"metadata": {"rfq": {"mailbox_id": "m1"}}}]
    assert view.derive_bu([], rfqs, {"m1": "BIM"})["bu"] == "BIM"
    tie = view.derive_bu([{"branch": "Survey Fieldwork"}, {"branch": "Cogentix Research"}], [], {})
    assert tie["bu"] is None and "tie" in tie["note"]
    assert view.derive_bu([], [], {})["bu"] is None


def test_webmail_never_matches_a_whole_account():
    doms = view._account_domains({"domain": ""}, [{"email": "x@gmail.com"}, {"email": "y@acme.com"}])
    assert doms == ["acme.com"]


def test_communication_groups_by_thread_and_counts_categories(dbs):
    md = dbs["torpedo_gmail"]["email_metadata"]
    md.insert_one({"mail_counterparty": "raj@acme.com", "gmail_thread_id": "t1", "subject": "RFQ", "timestamp": datetime(2026, 10, 1),
                   "direction": "inbound", "ai_tier1_category": "rfq"})
    md.insert_one({"mail_counterparty": "raj@acme.com", "gmail_thread_id": "t1", "subject": "Re: RFQ", "timestamp": datetime(2026, 10, 2),
                   "direction": "outbound", "ai_tier1_category": "rfq"})
    out = view.communication(["raj@acme.com"], [])
    assert out["messages"] == 2 and len(out["threads"]) == 1 and out["categories"] == {"rfq": 2}
    assert [m["direction"] for m in out["threads"][0]["messages"]] == ["inbound", "outbound"]
