"""
Tests for sales/mail_pool_rfq_extract.py -- the two-stage small-model pipeline.
Model calls are faked; what's under test is the code around the model: prompt
order, verdict handling, grounding (the fabricated-value blocker), refs, and
that model failures raise instead of looking like "no RFQ".
"""
from unittest.mock import patch

import pytest

from leads import local_slm_client as slm
from sales import mail_pool_rfq_extract as ex


def rfq_doc(**kw):
    d = {"_id": "e1", "gmail_thread_id": "t9", "from_email": "buyer@client.example",
         "subject": "Quote needed", "date": "2026-01-05",
         "body_plain": "Hi, please quote: 300 completes, US, LOI 15 min, IR 30%, online survey."}
    d.update(kw)
    return d


# ---- strip_quoted ---------------------------------------------------------

def test_strip_quoted_cuts_at_reply_marker():
    body = "Thanks, done.\n\nOn Mon, Jan 5, 2026 at 3:00 PM Bob <b@x.com> wrote:\n> old text"
    assert ex.strip_quoted(body) == "Thanks, done."


def test_strip_quoted_cuts_at_outlook_header_and_gt_quotes():
    assert ex.strip_quoted("Ok\nFrom: A\nSent: Monday\nTo: B\nold") == "Ok"
    assert ex.strip_quoted("Ok\n> quoted\n> more") == "Ok"


def test_strip_quoted_leaves_plain_body_alone():
    assert ex.strip_quoted("Just this.") == "Just this."


# ---- classify -------------------------------------------------------------

def test_classify_puts_the_email_last_so_the_fixed_prefix_can_be_cached():
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"is_rfq": True}

    with patch.object(slm, "chat_json", side_effect=fake):
        assert ex.classify_is_rfq("Sub X", "a@b.com", "body text") is True
    assert seen["max_tokens"] == ex.CLASSIFY_MAX_TOKENS
    assert seen["user"].index("Now the email to judge.") < seen["user"].index("Sub X")
    assert seen["user"].rstrip().endswith("Answer:")


@pytest.mark.parametrize("raw,expected", [
    ({"is_rfq": False}, False), ({"is_rfq": "yes"}, True), ({"is_rfq": "No"}, False)])
def test_classify_coerces_verdict(raw, expected):
    with patch.object(slm, "chat_json", return_value=raw):
        assert ex.classify_is_rfq("s", "a@b.com", "b") is expected


def test_classify_unusable_answer_raises_not_false():
    with patch.object(slm, "chat_json", return_value={"answer": "maybe"}):
        with pytest.raises(ex.RFQModelError):
            ex.classify_is_rfq("s", "a@b.com", "b")


def test_classify_transport_failure_raises():
    with patch.object(slm, "chat_json", side_effect=slm.LocalSLMUnavailable("down")):
        with pytest.raises(ex.RFQModelError):
            ex.classify_is_rfq("s", "a@b.com", "b")


def test_classify_only_sees_the_newest_message():
    seen = {}
    with patch.object(slm, "chat_json",
                      side_effect=lambda **kw: seen.update(kw) or {"is_rfq": False}):
        ex.classify_is_rfq("s", "a@b.com", "Thanks!\n\nOn Mon, Jan 5 Bob wrote:\n> please quote 500 n")
    assert "please quote 500" not in seen["user"]


# ---- grounding ------------------------------------------------------------

def test_numbers_must_appear_near_a_matching_keyword():
    text = "Need 300 completes, LOI 15 min, IR 30%. Call +91 98200 12345."
    g, dropped = ex.ground_fields({"sample_size": 300, "loi": 15, "ir": 30}, text)
    assert (g["sample_size"], g["loi"], g["ir"]) == (300, 15, 30) and not dropped


def test_invented_number_is_dropped_and_reported():
    g, dropped = ex.ground_fields({"sample_size": 1000, "loi": 20}, "Need 300 completes, 15 min.")
    assert g["sample_size"] is None and g["loi"] is None
    assert {d["field"] for d in dropped} == {"sample_size", "loi"}


def test_number_present_but_not_near_its_keyword_is_dropped():
    g, _ = ex.ground_fields({"sample_size": 2026}, "Sent 5 Jan 2026 about a study.")
    assert g["sample_size"] is None


def test_thousands_separator_and_fractional_ir():
    g, _ = ex.ground_fields({"sample_size": 11000, "ir": 0.3},
                            "Total 11,000 completes at 30% incidence.")
    assert g["sample_size"] == 11000 and g["ir"] == 0.3


def test_country_alias_kept_and_wrong_country_dropped():
    g, dropped = ex.ground_fields({"country": "Australia"}, "AU / N30 10% / 15 min")
    assert g["country"] == "Australia"
    g, dropped = ex.ground_fields({"country": "UK"}, "AU / N30 10% / 15 min")
    assert g["country"] is None and dropped[0]["field"] == "country"


def test_country_list_keeps_only_named_countries():
    g, dropped = ex.ground_fields({"country": "US, India, Brazil"}, "Markets: US and India.")
    assert g["country"] == "US, India"
    assert dropped[0]["value"] == "Brazil"


def test_methodology_needs_support_and_a_signature_does_not_count():
    sig = "Regards,\nRamiz\nDeputy Manager||Panel Management"
    g, _ = ex.ground_fields({"methodology": "Online Panel"}, "Please quote 300 n.\n" + sig)
    assert g["methodology"] is None
    g, _ = ex.ground_fields({"methodology": "Online Panel"}, "Online panel sample needed.")
    assert g["methodology"] == "Online Panel"
    g, _ = ex.ground_fields({"methodology": "F2F"}, "Face-to-face interviews in 5 cities.")
    assert g["methodology"] == "F2F"
    g, _ = ex.ground_fields({"methodology": "CATI"}, "Online survey only.")
    assert g["methodology"] is None


def test_target_audience_needs_wording_from_the_email():
    txt = "Audience: retail decision-makers in grocery stores"
    g, _ = ex.ground_fields({"target_audience": "Retail decision-makers"}, txt)
    assert g["target_audience"] == "Retail decision-makers"
    g, dropped = ex.ground_fields({"target_audience": "Consumers of luxury cars"}, txt)
    assert g["target_audience"] is None and dropped


def test_currency_needs_a_mention():
    assert ex.ground_fields({"currency": "USD"}, "CPI $4.05")[0]["currency"] == "USD"
    assert ex.ground_fields({"currency": "EUR"}, "CPI $4.05")[0]["currency"] is None


def test_deadline_explicit_date_becomes_iso_and_vague_phrase_moves_to_timeline():
    g, _ = ex.ground_fields({"deadline": "December 15, 2025"}, "Reply by December 15, 2025 please")
    assert g["deadline"] == "2025-12-15"
    g, _ = ex.ground_fields({"deadline": "next Friday"}, "Send your quote by next Friday")
    assert g["deadline"] is None and g["timeline"] == "next Friday"


def test_phrase_not_in_email_is_dropped():
    g, dropped = ex.ground_fields({"deadline": "April 15, 2023", "timeline": "6 weeks"},
                                  "No dates here.")
    assert g["deadline"] is None and g["timeline"] is None and len(dropped) == 2


# ---- per-email pipeline ---------------------------------------------------

def _model(classify, extract):
    def fake(**kw):
        return classify if kw["max_tokens"] == ex.CLASSIFY_MAX_TOKENS else extract
    return fake


def test_prefiltered_email_never_reaches_the_model():
    with patch.object(slm, "chat_json", side_effect=AssertionError("model called")):
        r = ex.analyze_email(rfq_doc(subject="Delivery Status Notification (Failure)"))
    assert r.skipped_reason == "bounce_subject" and r.rfq is None


def test_classified_not_rfq_stops_before_extraction():
    calls = []
    with patch.object(slm, "chat_json",
                      side_effect=lambda **kw: calls.append(kw["max_tokens"]) or {"is_rfq": False}):
        r = ex.analyze_email(rfq_doc())
    assert r.is_rfq is False and r.rfq is None and calls == [ex.CLASSIFY_MAX_TOKENS]


def test_rfq_gets_code_made_ref_source_id_and_grounded_fields():
    extract = {"title": "US online survey", "summary": "300 completes in the US",
               "sample_size": 300, "country": "US", "loi": 15, "ir": 30,
               "methodology": "online survey", "budget": 9999, "currency": "USD",
               "target_audience": None, "deadline": None, "timeline": None}
    with patch.object(slm, "chat_json", side_effect=_model({"is_rfq": True}, extract)):
        r = ex.analyze_email(rfq_doc())
    rfq = r.rfq
    assert rfq["ref"] == "thr-t9" and rfq["source_email_id"] == "e1"
    assert (rfq["sample_size"], rfq["loi"], rfq["ir"], rfq["country"]) == (300, 15, 30, "US")
    assert rfq["budget"] is None and rfq["currency"] is None       # invented -> dropped
    assert {d["field"] for d in rfq["grounding_dropped"]} == {"budget", "currency"}
    assert rfq["pipeline"] == ex.PIPELINE_VERSION and rfq["status"] == "open"


def test_ref_falls_back_to_email_id_without_a_thread():
    assert ex.make_ref({"_id": "abc"}) == "em-abc"


def test_second_mail_in_a_known_thread_makes_no_second_rfq_and_skips_extraction():
    calls = []
    with patch.object(slm, "chat_json",
                      side_effect=lambda **kw: calls.append(kw["max_tokens"]) or {"is_rfq": True}):
        r = ex.analyze_email(rfq_doc(), known_refs=["thr-t9"])
    assert r.rfq is None and calls == [ex.CLASSIFY_MAX_TOKENS]


def test_model_failure_raises_never_no_rfq():
    with patch.object(slm, "chat_json", side_effect=slm.LocalSLMUnavailable("timeout")):
        with pytest.raises(ex.RFQModelError):
            ex.analyze_email(rfq_doc())


# ---- scan_chunk -----------------------------------------------------------

def test_scan_chunk_returns_none_when_any_call_fails():
    docs = [rfq_doc(_id="a", gmail_thread_id="t1"), rfq_doc(_id="b", gmail_thread_id="t2")]
    answers = iter([{"is_rfq": False}, slm.LocalSLMUnavailable("down")])

    def fake(**kw):
        v = next(answers)
        if isinstance(v, Exception):
            raise v
        return v

    with patch.object(slm, "chat_json", side_effect=fake):
        assert ex.scan_chunk([], docs) is None


def test_scan_chunk_collects_rfqs_counts_and_respects_the_ledger():
    docs = [rfq_doc(_id="a", gmail_thread_id="t1", subject="Delivery Status Notification"),
            rfq_doc(_id="b", gmail_thread_id="t2"),
            rfq_doc(_id="c", gmail_thread_id="t3"),
            rfq_doc(_id="d", gmail_thread_id="t4")]
    extract = {"title": "T", "summary": "S", "sample_size": 300, "country": "US"}
    with patch.object(slm, "chat_json", side_effect=_model({"is_rfq": True}, extract)):
        out = ex.scan_chunk([{"ref": "thr-t3"}], docs)
    assert [r["ref"] for r in out["new_rfqs"]] == ["thr-t2", "thr-t4"]
    assert out["rfq_updates"] == []
    assert out["stats"] == {"skipped": 1, "classified_no": 0, "known_thread": 1, "rfq": 2}


def test_both_stages_constrain_the_output_with_a_schema():
    seen = {}
    with patch.object(slm, "chat_json",
                      side_effect=lambda **kw: seen.__setitem__(kw["max_tokens"], kw.get("json_schema")) or (
                          {"is_rfq": True} if kw["max_tokens"] == ex.CLASSIFY_MAX_TOKENS
                          else {"title": "T"})):
        ex.analyze_email(rfq_doc())
    assert seen == {ex.CLASSIFY_MAX_TOKENS: ex.CLASSIFY_SCHEMA, ex.EXTRACT_MAX_TOKENS: ex.EXTRACT_SCHEMA}


def test_extract_schema_covers_every_field_the_pipeline_reads():
    assert set(ex.EXTRACT_SCHEMA["required"]) == set(ex.EXTRACT_SCHEMA["properties"])
    for f in ("sample_size", "loi", "ir", "budget", "country", "methodology", "target_audience",
              "currency", "deadline", "timeline", "title", "summary"):
        assert f in ex.EXTRACT_SCHEMA["properties"]


def test_chunk_runs_every_classification_before_any_extraction():
    order = []

    def fake(**kw):
        stage = "classify" if kw["max_tokens"] == ex.CLASSIFY_MAX_TOKENS else "extract"
        order.append(stage)
        return {"is_rfq": True} if stage == "classify" else {"title": "T"}

    docs = [rfq_doc(_id="a", gmail_thread_id="t1"), rfq_doc(_id="b", gmail_thread_id="t2"),
            rfq_doc(_id="c", gmail_thread_id="t3")]
    with patch.object(slm, "chat_json", side_effect=fake):
        results = ex.analyze_chunk(docs)
    assert order == ["classify"] * 3 + ["extract"] * 3
    assert [r.rfq["ref"] for r in results] == ["thr-t1", "thr-t2", "thr-t3"]


def test_chunk_dedups_two_mails_of_the_same_thread():
    docs = [rfq_doc(_id="a", gmail_thread_id="t1"), rfq_doc(_id="b", gmail_thread_id="t1")]
    with patch.object(slm, "chat_json", side_effect=_model({"is_rfq": True}, {"title": "T"})):
        results = ex.analyze_chunk(docs)
    assert results[0].rfq and results[1].rfq is None
