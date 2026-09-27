"""Tests for app/services/finance_automation.py -- overdue marking, reminder
milestones, reference-match auto-reconcile, and the monthly CA pack."""
from datetime import datetime, timedelta

import pytest

from app.services import finance_automation as fa


# ---- reminder milestone logic -----------------------------------------------

def test_first_milestone_reached_is_returned():
    assert fa.due_milestone(3, already_sent=[]) == 1


def test_highest_reached_milestone_wins_over_lower_unset_ones():
    assert fa.due_milestone(20, already_sent=[]) == 15


def test_already_sent_milestones_are_skipped():
    assert fa.due_milestone(20, already_sent=[1, 7, 15]) is None


def test_not_yet_at_first_milestone_returns_none():
    assert fa.due_milestone(0, already_sent=[]) is None


def test_reminder_text_names_the_invoice_amount_and_days():
    inv = {"invoice_number": "SF/25-26/010", "currency": "USD", "total_amount": 5000,
           "amount_paid": 1000, "due_date": datetime(2026, 1, 1)}
    out = fa.reminder_text(inv, {"name": "Acme Research"}, days_overdue=10)
    assert "SF/25-26/010" in out["subject"] and "4,000.00" in out["subject"]
    assert "Acme Research" in out["body"] and "10 day" in out["body"]


# ---- in-memory Mongo fakes ---------------------------------------------------

class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, doc, query):
        for k, v in (query or {}).items():
            if k in ("$or",):
                if not any(self._match(doc, s) for s in v):
                    return False
            elif isinstance(v, dict):
                if "$in" in v and doc.get(k) not in v["$in"]:
                    return False
                if "$lt" in v and not (doc.get(k) is not None and doc.get(k) < v["$lt"]):
                    return False
                if "$gt" in v and not (doc.get(k) is not None and doc.get(k) > v["$gt"]):
                    return False
                if "$ne" in v and doc.get(k) == v["$ne"]:
                    return False
                if "$exists" in v and (k in doc) != v["$exists"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def find(self, query=None, *a, **k):
        docs = [d for d in self.docs if self._match(d, query or {})]
        class _Cur(list):
            def limit(self, n):
                return self[:n]
        return _Cur(docs)

    def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if self._match(d, query or {}):
                return d
        return None

    def count_documents(self, query=None):
        return len(self.find(query))

    def insert_one(self, doc):
        doc.setdefault("_id", f"id{len(self.docs)}")
        self.docs.append(doc)

    def update_one(self, query, update, upsert=False):
        d = self.find_one(query)
        if d is None:
            if upsert:
                d = dict(query)
                d.update(update.get("$set", {}))
                self.docs.append(d)
            return
        d.update(update.get("$set", {}))
        for k, v in (update.get("$push") or {}).items():
            d.setdefault(k, []).append(v)
        for k, v in (update.get("$addToSet") or {}).items():
            d.setdefault(k, [])
            if v not in d[k]:
                d[k].append(v)

    def update_many(self, query, update):
        n = 0
        for d in self.find(query):
            d.update(update.get("$set", {}))
            n += 1
        class _R:
            modified_count = n
        return _R()


class _Client(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _client(invoices=None, customers=None, payments=None):
    fin = {"invoices": _Col(invoices), "customers": _Col(customers),
          "payments_received": _Col(payments), "ca_packs": _Col(),
          "bills": _Col(), "expenses": _Col()}
    return _Client({"finance_db": fin})


CUST1 = "64b000000000000000000010"


def _invoice(**kw):
    base = {"_id": "inv1", "invoice_number": "SF/25-26/001", "status": "sent",
            "total_amount": 5000, "amount_paid": 0, "currency": "USD",
            "customer_id": CUST1, "is_deleted": False}
    base.update(kw)
    return base


# ---- mark_overdue_invoices ---------------------------------------------------

def test_sent_invoice_past_due_becomes_overdue(monkeypatch):
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=5), balance_due=5000)
    client = _client(invoices=[inv])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    n = fa.mark_overdue_invoices(now)
    assert n == 1 and inv["status"] == "overdue"


def test_fully_paid_invoice_is_not_marked_overdue(monkeypatch):
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=5), balance_due=0)
    client = _client(invoices=[inv])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    fa.mark_overdue_invoices(now)
    assert inv["status"] == "sent"


# ---- run_invoice_reminders ----------------------------------------------------

def test_drafts_a_reminder_at_first_milestone(monkeypatch):
    from bson import ObjectId
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=1), balance_due=5000)
    cust = {"_id": ObjectId(CUST1), "name": "Acme Research", "email": "ap@acme.com"}
    client = _client(invoices=[inv], customers=[cust])
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    monkeypatch.setattr(fa, "_draft", lambda to, subject, body, attachments=None:
                        {"success": True, "draft_id": "d1"})
    tasks = []
    monkeypatch.setattr(fa, "_crm", lambda kind, doc: tasks.append(doc))

    stats = fa.run_invoice_reminders(now)

    assert stats["drafted"] == 1
    assert inv["followups"][0]["milestone"] == 1
    assert len(tasks) == 1


def test_no_duplicate_reminder_within_the_same_milestone(monkeypatch):
    from bson import ObjectId
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=3), balance_due=5000,
                   followups=[{"kind": "auto_reminder", "milestone": 1}])
    cust = {"_id": ObjectId(CUST1), "name": "Acme Research", "email": "ap@acme.com"}
    client = _client(invoices=[inv], customers=[cust])
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    monkeypatch.setattr(fa, "_draft", lambda *a, **k: pytest.fail("must not re-draft"))
    monkeypatch.setattr(fa, "_crm", lambda *a, **k: None)

    stats = fa.run_invoice_reminders(now)
    assert stats["drafted"] == 0


def test_very_old_backlog_invoice_is_left_for_a_person(monkeypatch):
    from bson import ObjectId
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=fa.REMINDER_MAX_AGE_DAYS + 30), balance_due=4000)
    client = _client(invoices=[inv], customers=[{"_id": ObjectId(CUST1), "email": "x@x.com"}])
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    monkeypatch.setattr(fa, "_draft", lambda *a, **k: pytest.fail("must not draft"))
    monkeypatch.setattr(fa, "_crm", lambda *a, **k: None)

    stats = fa.run_invoice_reminders(now)
    assert stats["too_old"] == 1 and stats["drafted"] == 0


def test_customer_with_no_email_is_flagged_not_silently_skipped(monkeypatch):
    from bson import ObjectId
    now = datetime.utcnow()
    inv = _invoice(due_date=now - timedelta(days=2), balance_due=5000)
    client = _client(invoices=[inv], customers=[{"_id": ObjectId(CUST1), "name": "Acme"}])
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    tasks = []
    monkeypatch.setattr(fa, "_crm", lambda kind, doc: tasks.append(doc))

    stats = fa.run_invoice_reminders(now)
    assert stats["no_email"] == 1
    assert "no email" in inv["followups"][0]["error"]
    assert tasks  # a person still gets a task to chase it manually


# ---- auto_reconcile_payments -------------------------------------------------

def test_payment_referencing_exactly_one_open_invoice_is_applied(monkeypatch):
    inv = _invoice(status="sent", balance_due=5000, total_amount=5000, amount_paid=0)
    payment = {"_id": "p1", "amount": 5000, "reference": "Payment for SF/25-26/001", "notes": ""}
    client = _client(invoices=[inv], payments=[payment])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    stats = fa.auto_reconcile_payments()

    assert stats["applied"] == 1
    assert inv["status"] == "paid" and inv["amount_paid"] == 5000


def test_payment_matching_no_invoice_number_is_left_alone(monkeypatch):
    inv = _invoice(status="sent", balance_due=5000, total_amount=5000, amount_paid=0)
    payment = {"_id": "p1", "amount": 5000, "reference": "wire transfer", "notes": ""}
    client = _client(invoices=[inv], payments=[payment])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    stats = fa.auto_reconcile_payments()
    assert stats["applied"] == 0 and inv["status"] == "sent"


def test_payment_referencing_multiple_invoice_numbers_is_ambiguous(monkeypatch):
    inv1 = _invoice(_id="inv1", invoice_number="SF/25-26/001", status="sent",
                    balance_due=5000, total_amount=5000, amount_paid=0)
    inv2 = _invoice(_id="inv2", invoice_number="SF/25-26/002", status="sent",
                    balance_due=3000, total_amount=3000, amount_paid=0)
    payment = {"_id": "p1", "amount": 8000, "reference": "SF/25-26/001 and SF/25-26/002", "notes": ""}
    client = _client(invoices=[inv1, inv2], payments=[payment])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    stats = fa.auto_reconcile_payments()
    assert stats["applied"] == 0 and stats["ambiguous"] == 1
    assert inv1["status"] == "sent" and inv2["status"] == "sent"


def test_already_applied_payment_is_not_reconsidered(monkeypatch):
    inv = _invoice(status="sent", balance_due=5000, total_amount=5000, amount_paid=0)
    payment = {"_id": "p1", "amount": 5000, "amount_unapplied": 0,
              "invoice_ids": ["some-other-invoice"], "reference": "SF/25-26/001"}
    client = _client(invoices=[inv], payments=[payment])
    monkeypatch.setattr(fa, "_mongo", lambda: client)

    stats = fa.auto_reconcile_payments()
    assert stats["payments_checked"] == 0


# ---- CA pack -------------------------------------------------------------------

def test_ca_pack_without_ca_email_is_built_but_not_sent(monkeypatch):
    now = datetime(2026, 2, 3)
    inv = {"invoice_number": "SF/25-26/001", "invoice_date": datetime(2026, 1, 15),
          "total_amount": 5000, "is_deleted": False}
    client = _client(invoices=[inv])
    client["finance_db"]["bills"] = _Col()
    client["finance_db"]["expenses"] = _Col()
    client["finance_db"]["payments_received"] = _Col()
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    monkeypatch.delenv("CA_EMAIL", raising=False)
    monkeypatch.setattr(fa, "_crm", lambda *a, **k: None)

    result = fa.run_monthly_ca_pack(now)

    assert result["summary"]["invoices"] == 1
    assert "draft_id" not in result or not result.get("draft_id")
    assert "not set" in result["error"]


def test_ca_pack_is_prepared_once_per_period(monkeypatch):
    now = datetime(2026, 2, 3)
    client = _client(invoices=[])
    for name in ("bills", "expenses", "payments_received"):
        client["finance_db"][name] = _Col()
    monkeypatch.setattr(fa, "_mongo", lambda: client)
    monkeypatch.setenv("CA_EMAIL", "ca@firm.com")
    monkeypatch.setattr(fa, "_draft", lambda *a, **k: {"success": True, "draft_id": "d1"})
    monkeypatch.setattr(fa, "_crm", lambda *a, **k: None)

    fa.run_monthly_ca_pack(now)
    second = fa.run_monthly_ca_pack(now)
    assert "skipped" in second
