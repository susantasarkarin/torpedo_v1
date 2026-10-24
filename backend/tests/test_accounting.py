"""In-house accounting (CRM plan 3.9): double entry, GST, invoices, receivables, reconciliation."""
from datetime import date

import pytest

from accounting import invoicing as inv
from accounting import ledger, reconcile

WB_GSTIN = "19ABCDE1234F1Z5"      # West Bengal (19); fictitious
MH_GSTIN = "27ABCDE1234F1Z5"      # Maharashtra (27); fictitious


def test_entries_must_balance_and_use_known_accounts():
    with pytest.raises(ledger.LedgerError):
        ledger.entry(entity="SFW", on=date(2026, 10, 1), memo="x", source={},
                     lines=[{"account": "1100", "debit": 100}, {"account": "4000", "credit": 90}])
    with pytest.raises(ledger.LedgerError):
        ledger.entry(entity="SFW", on=date(2026, 10, 1), memo="x", source={},
                     lines=[{"account": "9999", "debit": 1}, {"account": "4000", "credit": 1}])


def test_gst_split_by_place_of_supply_and_lut_for_exports():
    assert inv.gst_split(1000, entity_gstin=WB_GSTIN, client_country="IN", client_gstin=WB_GSTIN)["cgst"] == 90
    inter = inv.gst_split(1000, entity_gstin=WB_GSTIN, client_country="IN", client_gstin=MH_GSTIN)
    assert inter["type"] == "inter" and inter["igst"] == 180
    exp = inv.gst_split(1000, entity_gstin=WB_GSTIN, client_country="US")
    assert exp["type"] == "export_lut" and exp["tax"] == 0 and "LUT" in exp["note"]
    assert "blocked" in inv.gst_split(1000, entity_gstin="", client_country="IN", client_gstin=WB_GSTIN)
    assert "blocked" in inv.gst_split(1000, entity_gstin=WB_GSTIN, client_country="IN")


def test_numbering_per_series_and_financial_year():
    assert inv.next_number("SF", "INV", date(2026, 10, 1), ["SF-INV-2627-0007", "CR-INV-2627-0100"]) == "SF-INV-2627-0008"
    assert inv.next_number("SF", "INV", date(2027, 4, 1), ["SF-INV-2627-0007"]) == "SF-INV-2728-0001"


def test_invoice_amount_partial_and_checks():
    a = inv.invoice_amount(accepted_completes=480, cpi=240, change_orders=[{"amount": 5000}], fees=[{"amount": 2000}],
                           discounts=[{"amount": 1000}], already_billed=50000)
    assert a["taxable"] == 480 * 240 + 5000 + 2000 - 1000 - 50000
    c = inv.invoice_checks(taxable=118000, quotation_total=100000, account={"requires_po": True}, po_number=None)
    assert c["hold"] and c["review"] and not c["send"]
    assert inv.invoice_checks(taxable=101000, quotation_total=100000, account={}, po_number=None)["send"]


def test_invoice_credit_note_receipt_with_client_tds_keep_books_balanced():
    gst = inv.gst_split(100000, entity_gstin=WB_GSTIN, client_country="IN", client_gstin=MH_GSTIN)
    i = {"number": "SF-INV-2627-0001", "date": date(2026, 10, 1), "taxable": 100000, "gst": gst, "customer_id": "c1"}
    cn = inv.credit_note(i, 20, 500, "client rejected 20 IDs")
    assert cn["taxable"] == 10000 and cn["gst"]["igst"] == 1800
    tds = 100000 * 0.10
    entries = [inv.post_invoice(i, "SFW"),
               inv.post_credit_note(cn, "SFW", date(2026, 10, 10), "SF-CN-2627-0001"),
               inv.post_receipt(entity="SFW", on=date(2026, 11, 1), invoice_number=i["number"],
                                ar_settled=118000 - 11800, received=106200 - tds, tds=tds)]
    tb = ledger.trial_balance(entries, "SFW")
    assert tb["balanced"]
    b = ledger.balances(entries, "SFW")
    assert b.get("1100", 0) == 0 and b["1150"] == 10000 and b["2120"] == -(18000 - 1800)
    bs = ledger.balance_sheet(entries, "SFW", date(2026, 12, 31))
    assert bs["balanced"]
    pl = ledger.profit_and_loss(entries, "SFW", date(2026, 4, 1), date(2027, 3, 31))
    assert pl["net_profit"] == 90000


def test_fx_difference_on_a_foreign_receipt_goes_to_fx_account():
    e = inv.post_receipt(entity="COGENTIX", on=date(2026, 11, 1), invoice_number="CR-INV-2627-0002",
                         ar_settled=84000, received=83500, bank_charges=300)
    lines = {l["account"]: l for l in e["lines"]}
    assert lines["4900"]["debit"] == 200 and lines["1100"]["credit"] == 84000


def test_reversal_not_edit():
    i = {"number": "X", "date": date(2026, 10, 1), "taxable": 100, "gst": {}, "customer_id": "c"}
    e = inv.post_invoice(i, "BIM")
    r = ledger.reversal(e, date(2026, 10, 2), "wrong client", "e1")
    assert r["reverses"] == "e1" and ledger.balances([e, r], "BIM") == {"1100": 0.0, "4000": 0.0}


def test_vendor_bill_tds_needs_configured_section():
    assert "review" in inv.vendor_bill_tds(10000, "194C")
    t = inv.vendor_bill_tds(10000, "194C", {**inv.DEFAULTS, "tds_sections": {"194C": 0.02}})
    assert t["tds"] == 200 and t["net_payable"] == 9800
    e = inv.post_vendor_bill(entity="SFW", on=date(2026, 10, 5), bill_no="B1", taxable=10000, input_gst=1800, tds=200, vendor_id="v1")
    assert ledger.trial_balance([e], "SFW")["balanced"]


def test_receivables_are_consolidated_with_credit_hold():
    today = date(2026, 10, 26)     # Monday
    invs = [{"number": "A", "status": "sent", "balance_due": 10, "contact_email": "x@c.com", "due_date": date(2026, 10, 30), "account_id": "a1"},
            {"number": "B", "status": "sent", "balance_due": 10, "contact_email": "x@c.com", "due_date": date(2026, 10, 1), "account_id": "a1"},
            {"number": "C", "status": "overdue", "balance_due": 10, "contact_email": "x@c.com", "due_date": date(2026, 8, 1), "account_id": "a1"},
            {"number": "D", "status": "paid", "balance_due": 0, "contact_email": "x@c.com", "due_date": date(2026, 8, 1), "account_id": "a1"}]
    r = inv.receivable_mails(invs, today, last_overdue_mail={})
    assert r["upcoming"] == [{"to": "x@c.com", "invoices": ["A"]}]
    assert r["overdue"][0]["invoices"] == ["B", "C"] and r["credit_hold_accounts"] == ["a1"]
    again = inv.receivable_mails(invs, today, last_overdue_mail={"x@c.com": date(2026, 10, 20)})
    assert again["overdue"] == []


def test_bank_csv_parse_and_receipt_matching():
    text = ("Txn Date,Narration,Ref No,Withdrawal,Deposit\n"
            "01/11/2026,NEFT HANSA RESEARCH SF-INV-2627-0001,UTR1,,96200.00\n"
            "02/11/2026,Bank charges,,118.00,\n")
    lines = reconcile.parse_statement_csv(text)
    assert [l["amount"] for l in lines] == [96200.0, -118.0]
    opens = [{"number": "SF-INV-2627-0001", "date": date(2026, 10, 1), "balance_due": 106200, "taxable": 100000,
              "customer_id": "c1", "customer_name": "Hansa Research Group"}]
    m = reconcile.match_receipt(lines[0], opens)
    assert m["auto"] and m["match"]["how"] == "net of 10% TDS" and m["match"]["tds"] == 10000


def test_bundled_receipt_and_unclear_goes_to_review():
    opens = [{"number": n, "date": date(2026, 10, 1), "balance_due": v, "customer_id": "c1", "customer_name": "Acme Insights"}
             for n, v in (("I1", 1000), ("I2", 2500), ("I3", 700))]
    m = reconcile.match_receipt({"date": date(2026, 11, 1), "amount": 3500, "reference": "", "narration": "ACME INSIGHTS"}, opens)
    assert m["auto"] and m["match"]["invoices"] == ["I1", "I2"]
    unclear = reconcile.match_receipt({"date": date(2026, 11, 1), "amount": 999, "reference": "", "narration": "?"}, opens)
    assert not unclear["auto"]


def test_gst_and_tds_reconciliation():
    out = reconcile.gst_outward([{"number": "A", "client_gstin": MH_GSTIN, "taxable": 100, "tax": 18},
                                 {"number": "B", "client_gstin": MH_GSTIN, "taxable": 100, "tax": 18}],
                                [{"gstin": MH_GSTIN, "number": "A", "taxable": 100, "tax": 18},
                                 {"gstin": MH_GSTIN, "number": "Z", "taxable": 5, "tax": 1}])
    assert out["matched"] == ["A"] and out["missing_in_gstr1"] == ["B"] and out["extra_in_gstr1"] == ["Z"]
    inw = reconcile.gst_inward([{"bill_no": "P1", "vendor_gstin": WB_GSTIN, "input_gst": 18}], [])
    assert inw["vendor_not_filed"] == ["P1"]
    t = reconcile.tds_receivable([{"tds": 1000, "client_tan": "CALH00000A"}], [{"tan": "CALH00000A", "tds": 900}])
    assert not t["all_ok"]
    assert reconcile.tds_payable(500, 500, 500)["ok"]


def test_aging_and_margin():
    a = reconcile.aging([{"due_date": date(2026, 10, 1), "balance_due": 10}, {"due_date": date(2026, 6, 1), "balance_due": 5}],
                        date(2026, 10, 26))
    assert a["1-30"] == 10 and a["90+"] == 5
    assert reconcile.project_margin(1000, 300, 100)["margin_pct"] == 0.6
