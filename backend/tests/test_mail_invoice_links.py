"""Invoice numbers in mail threads: every Zoho series format, nothing else."""
from backfill.mail_invoice_links import norm_no, tokens


def test_all_series_formats_and_spacing():
    t = tokens("Invoice CR/26-27/014 attached; old ones CR / 2627 / 011, SF/130/19-20, SF/20-21/165a and SF/24-25/006.")
    assert t == {"CR/26-27/014", "CR/2627/011", "SF/130/19-20", "SF/20-21/165A", "SF/24-25/006"}
    assert norm_no("sf/20-21/165a") == "SF/20-21/165A"


def test_lookalikes_are_ignored():
    assert tokens("SFW/2026 report, CRM/2026, 15/10/2026, PO 4500123") == set()
