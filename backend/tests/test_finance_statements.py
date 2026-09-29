"""Monthly statement of pending invoices per client, and the CA pack on the 5th."""
from datetime import datetime

from app.services import finance_automation as fa


class _Customers:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q, proj=None):
        import re
        rx = re.compile(q["name"]["$regex"], re.I)
        return [d for d in self.docs if rx.search(d.get("name", "")) and "@" in (d.get("email") or "")]


def test_billing_address_falls_back_to_the_accounts_contact_of_the_same_company():
    fin = {"customers": _Customers([
        {"name": "Keya Kundu | Hansa Research Group (Hansaresearch)", "email": "keya.kundu@hansaresearch.com"},
        {"name": "Accounts Payable | Hansa Research Group (Hansaresearch)", "email": "accountspayable@hansaresearch.com"},
    ])}
    assert fa.statement_recipient(fin, {"name": "Hansa Research Group Pvt Ltd", "email": ""}) == \
        "accountspayable@hansaresearch.com"
    assert fa.statement_recipient(fin, {"name": "X Co", "email": "ap@xco.com"}) == "ap@xco.com"


def test_statement_lists_each_invoice_and_totals_per_currency():
    now = datetime(2026, 10, 1)
    invs = [
        {"invoice_number": "SF/26-27/001", "invoice_date": datetime(2026, 7, 1), "due_date": datetime(2026, 7, 31),
         "currency_code": "INR", "total_amount": 118000, "balance_due": 118000, "po_reference": "PO-9"},
        {"invoice_number": "SF/26-27/004", "invoice_date": datetime(2026, 8, 1), "due_date": datetime(2026, 8, 31),
         "currency_code": "INR", "total_amount": 59000, "balance_due": 29500},
        {"invoice_number": "SF/26-27/005", "invoice_date": datetime(2026, 8, 5), "due_date": datetime(2026, 9, 4),
         "currency_code": "USD", "total_amount": 1000, "balance_due": 1000},
    ]
    st = fa.statement_html("Hansa Research Group", invs, now)
    assert "SF/26-27/001" in st["html"] and "PO-9" in st["html"] and "62" in st["html"]  # 62 days overdue
    assert st["total"] == "INR 147,500.00, USD 1,000.00"


def test_ca_pack_waits_for_the_5th():
    assert "day 5" in fa.run_monthly_ca_pack(datetime(2026, 10, 3))["skipped"]
