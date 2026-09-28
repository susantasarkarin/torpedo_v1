"""
Gaps the 2026-09-28 shadow replay of the whole mail history found in the
won -> close -> finance flow.
"""
from datetime import datetime, timedelta

from app.services import finance_automation as fa


class _Invoices:
    def __init__(self, docs):
        self.docs = docs
        self.updates = []

    def find(self, q):
        class _C(list):
            def limit(self, n):
                return self[:n]
        lo, hi = q["created_at"]["$gte"], q["created_at"]["$lte"]
        return _C(d for d in self.docs if d["status"] == "draft" and "draft_nudged_at" not in d
                  and lo <= d["created_at"] <= hi)

    def update_one(self, q, u):
        self.updates.append((q, u))


def test_nurture_finds_the_thread_for_a_prospect_found_in_the_mail_pool(monkeypatch):
    from sales import nurture

    class _Mailboxes:
        def find_one(self, q):
            return {"email": "susanta@surveyfieldwork.com", "display_name": "Susanta"}

    monkeypatch.setattr(nurture, "_db", lambda name: {"workspace_mailboxes": _Mailboxes()})
    lead = {"mail_pool": {"triage": {"mailbox_id": "696b529f87549d9a1c9c0dcc", "gmail_thread_id": "t-9"}}}
    box = nurture._thread_mailbox(lead)
    assert box == {"email": "susanta@surveyfieldwork.com", "display_name": "Susanta", "thread_id": "t-9"}


def test_unsent_drafts_get_one_task_each(monkeypatch):
    now = datetime(2026, 9, 28)
    inv = _Invoices([
        {"_id": 1, "status": "draft", "invoice_number": "INV-1", "created_at": now - timedelta(days=5)},
        {"_id": 2, "status": "draft", "invoice_number": "INV-2", "created_at": now - timedelta(days=1)},    # too new
        {"_id": 3, "status": "draft", "invoice_number": "INV-3", "created_at": now - timedelta(days=200)},  # too old
        {"_id": 4, "status": "sent", "invoice_number": "INV-4", "created_at": now - timedelta(days=5)},
    ])
    monkeypatch.setattr(fa, "_fin", lambda: {"invoices": inv})
    tasks = []
    monkeypatch.setattr(fa, "_crm", lambda kind, doc: tasks.append((kind, doc)))
    assert fa.flag_unsent_drafts(now) == 1
    assert tasks[0][0] == "tasks" and "INV-1" in tasks[0][1]["title"]
    assert inv.updates[0][1]["$set"]["draft_nudged_at"] == now
