"""Phase 4 backfill helpers and idempotent dry-run/apply behaviour."""
from datetime import datetime

from backfill import steps


def test_majority_domain_needs_more_than_half_and_ignores_free_mail():
    assert steps.majority_domain(["a@acme.com", "b@acme.com", "c@gmail.com", "d@other.com"]) == "acme.com"
    assert steps.majority_domain(["a@acme.com", "b@other.com"]) is None
    assert steps.majority_domain(["a@gmail.com", "x@surveyfieldwork.com"]) is None
    assert steps.business_domain("https://www.acme.co.uk/x") == "acme.co.uk"


def test_subject_bu_tag_only_when_unambiguous():
    assert steps.subject_bu("RFQ_Home Safety Study_HRG_SFW") == "SFW"
    assert steps.subject_bu("[BIM] plant survey") == "BIM"
    assert steps.subject_bu("SFW and BIM joint") is None
    assert steps.subject_bu("Crowd sourcing study") is None


def test_account_index_domain_then_name_with_review_band():
    idx = steps.AccountIndex([{"_id": "1", "name": "Hansa Research Group", "domain": "hansaresearch.com"},
                              {"_id": "2", "name": "Acme Insights Pvt Ltd"},
                              {"_id": "3", "name": "Twin Co"}, {"_id": "4", "name": "Twin Co"}])
    assert idx.resolve("whatever", "hansaresearch.com") == ("auto", "1", "domain")
    assert idx.resolve("ACME Insights Private Limited", None)[:2] == ("auto", "2")
    assert idx.resolve("Twin Co", None)[0] == "review"
    assert idx.resolve("Acme Insite", None)[0] in ("review", "auto")
    assert idx.resolve("", None)[0] == "orphan"


class _C:
    """Minimal client over FakeDBs with bulk_write support."""
    def __init__(self, **dbs):
        self.dbs = dbs

    def __getattr__(self, n):
        return _D(self.dbs[n])

    def __getitem__(self, n):
        return _D(self.dbs[n])


class _D:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, n):
        return self.db[n]

    def __getitem__(self, n):
        return self.db[n]


def test_estimates_archive_dry_run_writes_nothing():
    from tests._fakemongo import FakeDB
    fin, crm = FakeDB(), FakeDB()
    crm["opportunities"].insert_one({"_id": "o1"})
    fin["estimates"].insert_one({"status": "draft", "opportunity_id": "o1"})
    fin["estimates"].insert_one({"status": "draft", "opportunity_id": "gone"})
    rep = steps.estimates_archive(_C(finance_db=fin, crm_db=crm), apply=False, now=datetime(2026, 10, 24))
    assert rep == {"linked_kept": 1, "archived": 1}
    assert not any(e.get("archived_backlog") for e in fin["estimates"].docs)


def test_plausible_domain_rejects_sentence_domains():
    assert steps.plausible_domain("unilever.com")
    assert not steps.plausible_domain("unibailafterfirstjoiningthecompanywestfieldinaustraliain1999hewas.com")


def test_ledger_opening_posts_once_and_balances():
    from tests._fakemongo import FakeDB
    fin = FakeDB()
    fin["invoice_fx"].insert_one({"currency": "USD", "rate": 84.0, "rate_date": "2026-01-01"})
    fin["invoices"].insert_one({"status": "paid", "branch": "Survey Fieldwork", "invoice_number": "SF/1", "invoice_date": datetime(2026, 5, 1),
                                "subtotal": 100, "tax_total": 0, "amount_paid": 100, "currency_code": "USD", "customer_id": "c1"})
    fin["invoices"].insert_one({"status": "written_off", "branch": "Cogentix Research", "invoice_number": "CR/1",
                                "invoice_date": datetime(2026, 5, 1), "subtotal": 500, "tax_total": 90, "amount_paid": 0,
                                "currency_code": "INR", "customer_id": "c2"})
    fin["journal"].insert_many = lambda docs: [fin["journal"].insert_one(d) for d in docs]
    fin["journal"].create_index = lambda *a, **k: None
    c = _C(finance_db=fin)
    r1 = steps.ledger_opening(c, apply=True, now=datetime(2026, 10, 24))
    assert r1["inserted"] == 4 and r1["trial_balance"]["SFW"]["balanced"] and r1["trial_balance"]["SFW"]["ar_1100"] == 0
    assert r1["trial_balance"]["COGENTIX"]["ar_1100"] == 0
    r2 = steps.ledger_opening(c, apply=True, now=datetime(2026, 10, 24))
    assert "inserted" not in r2
