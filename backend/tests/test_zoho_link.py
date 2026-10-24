"""Zoho invoice -> account alias -> project matching, and client PO capture."""
from datetime import datetime

from backfill import zoho_link as zl
from mail_pipeline import pipeline, rules
from tests._fakemongo import FakeDB


class _D:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, n):
        return self.db[n]


class _C:
    def __init__(self, **dbs):
        self.dbs = dbs

    def __getattr__(self, n):
        return _D(self.dbs[n])


ACCS = [{"_id": "a1", "name": "Hansa Research", "domain": "hansaresearch.com"},
        {"_id": "a2", "name": "Kantar"}, {"_id": "a3", "name": "Kantar India"},
        {"_id": "a4", "name": "Acme", "gstin": "27ABCDE1234F1Z5"}]


def test_customer_alias_order_gstin_domain_name_fuzzy():
    assert zl.resolve_customer({"name": "X", "gstin": "27abcde1234f1z5"}, ACCS)["account_id"] == "a4"
    assert zl.resolve_customer({"name": "Whatever Pvt Ltd", "email": "ap@hansaresearch.com"}, ACCS)["how"] == "billing_email_domain"
    r = zl.resolve_customer({"name": "HANSA RESEARCH PRIVATE LIMITED"}, ACCS)
    assert r == {"outcome": "auto", "account_id": "a1", "how": "normalised_name"}
    assert zl.resolve_customer({"name": "Hansa Researchh"}, ACCS)["outcome"] == "auto"
    assert zl.resolve_customer({"name": "Kantar Indiaa Ltd"}, ACCS)["outcome"] in ("auto", "review")
    assert zl.resolve_customer({"name": "Completely Different"}, ACCS)["outcome"] == "none"


def test_refs_and_po_keys():
    assert zl.po_key("HRG/PO/2026-118") == "HRGPO2026118"
    assert zl.refs_in("RFQ// 872657-B1, Essity Baby 2019") == {"872657B1"}
    assert "AA8423" in zl.refs_in("Re: AA8423 - Hong Kong Project")


def _proj(pid, **kw):
    base = {"id": pid, "name": pid, "account_id": "a1", "po": None, "threads": [], "refs": set(), "expected": 0,
            "expected_basis": "project value", "currency": None, "closed": datetime(2026, 3, 1)}
    return {**base, **kw}


def _inv(n, **kw):
    base = {"id": n, "number": n, "customer": "z1", "date": datetime(2026, 3, 20), "amount": 0, "currency": "INR",
            "po": None, "text": "", "linked_projects": []}
    return {**base, **kw}


def test_po_then_reference_then_amount_date_and_many_to_many():
    md = FakeDB()
    md["email_metadata"].insert_one({"gmail_thread_id": "t9", "subject": "Award", "body_plain": "Please proceed, PO No 4500777"})
    c = _C(torpedo_gmail=md)
    data = {"invoices": [_inv("I-PO", po="HRG-PO-55", amount=1),
                         _inv("I-THREAD", po="4500777", amount=1),
                         _inv("I-REF", text="Study AA8423 Hong Kong", amount=1),
                         _inv("I-AMT", amount=10150),
                         _inv("I-P1", amount=8000), _inv("I-P2", amount=12000),
                         _inv("I-BOTH", amount=7000, date=datetime(2026, 4, 1)),
                         _inv("I-LATE", amount=999, date=datetime(2026, 6, 1))],
            "customers": []}
    alias = {"z1": {"account_id": "a1"}}
    projects = [_proj("P-po", po="HRG/PO/55"), _proj("P-thread", threads=["t9"]), _proj("P-ref", refs={"AA8423"}),
                _proj("P-amt", expected=10000), _proj("P-split", expected=20000, closed=datetime(2026, 3, 10)),
                _proj("P-a", expected=3000, closed=datetime(2026, 3, 25)), _proj("P-b", expected=4000, closed=datetime(2026, 3, 25)),
                _proj("P-none", expected=123)]
    links = zl.match(c, data, alias, projects)
    meth = {p: ls[0]["method"] for p, ls in links.items()}
    assert meth["P-po"] == "po" and meth["P-thread"] == "po" and meth["P-ref"] == "reference"
    assert {x["invoice"] for x in links["P-amt"]} == {"I-AMT"}                      # within 2%
    assert {x["invoice"] for x in links["P-split"]} == {"I-P1", "I-P2"}            # one project, two invoices
    assert {x["invoice"] for x in links["P-a"]} == {"I-BOTH"} == {x["invoice"] for x in links["P-b"]}   # one invoice, two projects
    assert "P-none" not in links


def test_po_numbers_in_new_part_only_and_not_po_box():
    assert rules.po_numbers("Kindly find PO No: 4500123456 attached.\nOn Mon, X wrote:\n> PO 1111111") == ["4500123456"]
    assert rules.po_numbers("Purchase Order # HRG/PO/2026-118") == ["HRG/PO/2026-118"]
    assert rules.po_numbers("Send to P.O. Box 1234") == []


def test_client_mail_with_po_plans_set_po():
    acts = pipeline.plan_actions({"body_plain": "Approved. PO Number 7788123", "gmail_thread_id": "t1"},
                                 {"rfq_id": "o1"}, {"type": "client"}, {"category": "confirmation"})
    po = [a for a in acts if a["type"] == "set_po"]
    assert po and po[0]["po_numbers"] == ["7788123"] and po[0]["rfq_id"] == "o1"
    vendor = pipeline.plan_actions({"body_plain": "PO 7788123"}, {}, {"type": "vendor"}, {"category": "other"})
    assert not [a for a in vendor if a["type"] == "set_po"]
