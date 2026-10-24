"""Section 6 additions: job-run log, consolidated receivables, bank import."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from bson import ObjectId

from accounting import runner as arun
from platform_core import job_runs
from tests._fakemongo import FakeDB

NOW = datetime(2026, 10, 26, 4, 0)    # Monday


def test_job_run_log_records_ok_error_and_missed(monkeypatch):
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
    db = FakeDB()
    monkeypatch.setattr(job_runs, "_col", lambda: db["job_runs"])
    job_runs.record(SimpleNamespace(code=EVENT_JOB_EXECUTED, job_id="a", exception=None))
    job_runs.record(SimpleNamespace(code=EVENT_JOB_ERROR, job_id="a", exception=RuntimeError("boom")))
    job_runs.record(SimpleNamespace(code=EVENT_JOB_MISSED, job_id="b", exception=None))
    a, b = db["job_runs"].find_one({"_id": "a"}), db["job_runs"].find_one({"_id": "b"})
    assert a["runs"] == 2 and a["status"] == "error" and "boom" in a["last_error"]
    assert b["status"] == "missed" and b["missed"] == 1


def _setup(monkeypatch):
    d = {n: FakeDB() for n in ("finance_db", "email_automation", "crm_db")}
    monkeypatch.setattr(arun, "_gd", lambda: (lambda name: d[name]))
    from platform_core import config_store
    monkeypatch.setattr(config_store, "get", lambda s, db=None: config_store.defaults(s))
    return d


def test_receivables_shadow_plans_consolidated_mails_without_holding(monkeypatch):
    d = _setup(monkeypatch)
    cid = d["finance_db"]["customers"].insert_one({"email": "ap@client.com", "crm_account_id": "acc1"}).inserted_id
    for n, due in (("A", NOW + timedelta(days=3)), ("B", NOW - timedelta(days=10)), ("C", NOW - timedelta(days=80))):
        d["finance_db"]["invoices"].insert_one({"invoice_number": n, "status": "overdue", "balance_due": 100,
                                                "due_date": due, "customer_id": str(cid)})
    s = arun.receivables(now=NOW)
    assert s == {"mode": "shadow", "upcoming": 1, "overdue": 1, "credit_hold_accounts": 1}
    over = d["email_automation"]["finance_decisions"].find_one({"kind": "overdue_mail"})
    assert over["invoices"] == ["B", "C"]


def test_bank_import_once_per_file_with_suggestions(monkeypatch, tmp_path):
    d = _setup(monkeypatch)
    d["finance_db"]["invoices"].insert_one({"invoice_number": "SF-1", "invoice_date": NOW - timedelta(days=20), "balance_due": 5000,
                                            "currency_code": "INR", "status": "overdue", "customer_id": "c", "customer_name": "Acme Labs"})
    (tmp_path / "SFW").mkdir()
    (tmp_path / "SFW" / "oct.csv").write_text("Date,Narration,Ref,Debit,Credit\n25/10/2026,NEFT ACME LABS SF-1,U1,,5000\n")
    s1 = arun.bank_import(now=NOW, root=str(tmp_path))
    s2 = arun.bank_import(now=NOW, root=str(tmp_path))
    assert s1["files"] == 1 and s1["auto"] == 1 and s2["files"] == 0
    t = d["finance_db"]["bank_transactions"].find_one({})
    assert t["bu"] == "SFW" and t["auto_match"]["invoices"] == ["SF-1"] and t["status"] == "suggested"
    assert d["finance_db"]["invoices"].find_one({})["balance_due"] == 5000      # never touched in shadow
