"""RFQ study details read from the whole thread (2026-10-14).

The fill used to read one message with its quoted history cut off, once.
The real brief was often in that quote, a later client mail or an attachment.
"""
import io

from app.services import rfq_from_mail as rb
from app.services import rfq_thread_text as tt


def test_the_brief_in_the_quote_is_recovered():
    body = ("Hi Susanta,\n\nPlease share your redirects.\n\nThanks\n\n"
            "From: Ramiz\nSent: 01 October 2026\nSubject: RFQ_Brand Uplift Study\n\n"
            "Hi, need N=500 online in India, LOI 15 min, IR 30%, Gen pop 18-45.")
    from sales.reply_triage import strip_quoted
    own = strip_quoted(body)
    assert "N=500" not in own
    q = tt._quoted_part(body, own)
    assert "N=500" in q and "Please share your redirects" not in q


def test_windows_keep_only_pieces_with_study_signal_and_fit_the_size():
    text = "Thanks a lot!\n\nRegards, Ramiz\n\n" + "Sample n=300 in UK. " * 400
    ws = tt.windows(text, 2800)
    assert ws and all(len(w) <= 2800 for w in ws)
    assert not any(w.startswith("Thanks a lot") and "n=300" not in w for w in ws)


def test_merge_fills_only_empty_fields_latest_wins():
    rfq = {"country": "India", "loi": None, "sample_size": 0, "budget": 0, "currency": None}
    found = [("quoted", {"country": "UK", "loi": 10, "sample_size": 300}),
             ("own", {"sample_size": 500})]
    out = rb.merge_details(rfq, found)
    assert "country" not in out          # never overwrite what is there
    assert out["loi"] == 10
    assert out["sample_size"] == 500     # the client's later statement wins


def test_no_price_from_quoted_text():
    rfq = {"budget": 0, "currency": None}
    out = rb.merge_details(rfq, [("quoted", {"budget": 4500, "currency": "USD"})])
    assert out == {}


def test_methodology_terms_are_combined_once():
    out = rb.merge_details({}, [("own", {"methodology": "Online"}),
                                ("attachment", {"methodology": "Online, CATI"})])
    assert out["methodology"] == "Online, CATI"


def test_excel_brief_is_read():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Country", "Sample", "LOI", "IR"])
    ws.append(["Germany", 400, 12, 25])
    buf = io.BytesIO()
    wb.save(buf)
    t = tt.file_text("brief.xlsx", buf.getvalue())
    assert "Germany | 400 | 12 | 25" in t


def test_cached_attachment_text_is_not_refetched():
    msg = {"attachment_text_at": "x", "attachment_text": [{"filename": "a.pdf", "text": "N=200"}]}
    assert tt.attachment_texts(None, msg)[0]["text"] == "N=200"


def test_needs_details_until_read_with_whole_thread(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    monkeypatch.setattr(tt, "latest_ts", lambda c, r: now)
    assert rb._needs_details(None, {"country": "x"}) == now                  # old one-message read
    done = {k: "x" for k in rb.DETAIL_FIELDS}
    done.update(details_v=rb.DETAILS_V, details_seen_until=now - timedelta(days=1))
    assert rb._needs_details(None, done) is None                             # nothing missing
    gap = dict(done, deadline="")
    assert rb._needs_details(None, gap) == now                               # client wrote since
    assert rb._needs_details(None, dict(gap, details_seen_until=now)) is None


def test_quoted_history_never_overrides_the_clients_own_words():
    out = rb.merge_details({}, [("own", {"sample_size": 700}),
                                ("quoted", {"sample_size": 300, "country": "India"})])
    assert out["sample_size"] == 700
    assert out["country"] == "India"     # but it fills what they left empty


def test_a_signature_phone_number_is_not_a_brief():
    text = "Hi Susanta,\n\nPlease share your redirects.\n\nRamiz\nM: +91 9920367917"
    assert tt.windows(text, 1600) == []
    assert tt.windows("Specs: LOI: 10 minutes, Males 100%, total 700", 1600)


def test_quote_split_survives_blank_line_runs():
    from sales.reply_triage import strip_quoted
    body = "Hi,\n\n\n\nsee below\n\nFrom: X\nSent: today\n\nLOI 12 minutes, N=400"
    own = strip_quoted(body)
    q = tt._quoted_part(body, own)
    assert "see below" not in q and "N=400" in q
