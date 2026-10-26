"""Invoice numbers in mail threads: every Zoho series format, nothing else."""
from backfill.mail_invoice_links import norm_no, tokens


def test_all_series_formats_and_spacing():
    t = tokens("Invoice CR/26-27/014 attached; old ones CR / 2627 / 011, SF/130/19-20, SF/20-21/165a and SF/24-25/006.")
    assert t == {"CR/26-27/014", "CR/2627/011", "SF/130/19-20", "SF/20-21/165A", "SF/24-25/006"}
    assert norm_no("sf/20-21/165a") == "SF/20-21/165A"


def test_lookalikes_are_ignored():
    assert tokens("SFW/2026 report, CRM/2026, 15/10/2026, PO 4500123") == set()


def test_study_name_needs_a_code_or_two_words_and_one_project():
    from backfill.mail_invoice_links import name_match
    cands = [("a", "Cashfree Brand Study Post Phase"), ("b", "SYM253222 Nicotine Pouch"), ("c", "Cashfree NPS Tracker")]
    assert name_match("Re: Cashfree Brand Study | Post Phase", cands) == ["a"]
    assert name_match("Invoice SF/22-23/009 - SYM253222", cands) == ["b"]
    assert name_match("IPSOS USA - Pending Invoices as on 29th March 2021", cands) == []
    assert name_match("Cashfree", cands) == []                    # one word is not enough


def test_client_po_from_label_or_sap_subject():
    from backfill.mail_invoice_links import mail_pos
    assert mail_pos("PAYMENT FOLLOWUP - 4502427110", "please release SF/23-24/012") == {"4502427110"}
    assert mail_pos("Invoice", "PO No: 1059273 for SF/23-24/012") == {"1059273"}
    assert mail_pos("Pending Invoices", "SF/23-24/012 due 2024") == set()
