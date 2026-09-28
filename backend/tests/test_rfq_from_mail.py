from app.services import rfq_from_mail as rb


def test_title_drops_reply_and_tag_prefixes_but_keeps_case():
    assert rb.clean_title("RE: [SFW-BCC] Fw: RFQ_Bread Buyer Study_HRG_SFW") == "RFQ_Bread Buyer Study_HRG_SFW"
    assert rb.clean_title("RFQ | Israel") == "RFQ | Israel"
    assert rb.clean_title("") == "RFQ"


def test_company_root_ignores_subdomains_and_second_level_suffixes():
    assert rb.registrable_root("research.clearlightscope.com") == "clearlightscope"
    assert rb.registrable_root("acme.co.uk") == "acme"
    assert rb.registrable_root("hansaresearch.com") == "hansaresearch"
    assert rb.root_site("research.clearlightscope.com") == "clearlightscope.com"


class _Accounts:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q):
        rx = q["website"]["$regex"]
        import re as _re
        return next((d for d in self.docs if d.get("website") and _re.search(rx, d["website"], _re.I)), None)

    def find(self, q, proj=None):
        import re as _re
        rx = q["name"]["$regex"]
        return [d for d in self.docs if _re.search(rx, d["name"], _re.I)]


def test_a_clean_existing_account_is_reused_not_a_person_named_one():
    accs = _Accounts([{"_id": 1, "name": "Adarsh V (Hansaresearch)"},
                      {"_id": 2, "name": "Hansa Research Group - dooblo"},
                      {"_id": 3, "name": "Hansa Research Group"}])
    got = rb._account_for(None, accs, "ramiz@hansaresearch.com")
    assert got == {"_id": "3", "name": "Hansa Research Group"}


def test_a_proper_name_beats_a_domain_named_account_with_the_website():
    accs = _Accounts([{"_id": 1, "name": "Hansaresearch", "website": "hansaresearch.com"},
                      {"_id": 3, "name": "Hansa Research Group"}])
    assert rb._account_for(None, accs, "ramiz@hansaresearch.com")["name"] == "Hansa Research Group"
    only_site = _Accounts([{"_id": 1, "name": "Hansaresearch", "website": "hansaresearch.com"}])
    assert rb._account_for(None, only_site, "ramiz@hansaresearch.com")["name"] == "Hansaresearch"


def test_our_quote_is_read_from_our_reply():
    q = rb.parse_quote("Hi Keya,\n\nCPI - 160 + taxes\n\nSusanta Sarkar")
    assert q == {"cpi": 160.0, "currency": None, "taxes_extra": True, "total": None,
                 "lines": [{"n": None, "cpi": 160.0}]}
    q = rb.parse_quote("CPI = INR 170 + taxes")
    assert q["cpi"] == 170.0 and q["currency"] == "INR"


def test_per_country_lines_carry_their_sample():
    q = rb.parse_quote("Phase 1 (Online Survey): North America (N=70): $10 per complete "
                       "UK (N=30): $10 per complete  Phase 2 (60-min Online IDI): $60 per completed interview")
    assert q["currency"] == "USD" and q["cpi"] == 10.0
    assert q["lines"][:2] == [{"n": 70, "cpi": 10.0}, {"n": 30, "cpi": 10.0}]


import pytest


@pytest.mark.parametrize("text,cpi,cur", [
    ("CPI for this study is INR 130 + taxes  Susanta Sarkar", 130, "INR"),
    ("Hi Ramiz,  Our quote for this study is INR 115+taxes.  We are fully feasible", 115, "INR"),
    ("Hi Shruti,  Can we execute this study for INR 130+taxes. Also request", 130, "INR"),
    ("CPI in this case is $10   Business Development", 10, "USD"),
    ("Thank you for the RFQ. Our CPI for this study will be 140 + taxes.", 140, None),
    ("The CPI for the Study is USD 2.4 + ( local taxes if any) Timeline 10 days", 2.4, "USD"),
    ("INR 150+taxes  Susanta Sarkar  Director", 150, "INR"),
    ("it was established that the rate is IDR 60,000 per visit. I would like", 60000, "IDR"),
    ("Our quote for Option 1 (Total 320 PP) is INR 120+taxes.  Our quote for Option 2 (Total 400 PP) "
     "is INR 115+taxes.", 120, "INR"),
    ("Our quote for the India portion of this study is INR 115+taxes. Whereas that of Japan would be "
     "USD 3.25+taxes", 115, "INR"),
])
def test_how_we_actually_quote(text, cpi, cur):
    q = rb.parse_quote(text)
    assert q and q["cpi"] == cpi and q["currency"] == cur


@pytest.mark.parametrize("text", [
    "IR: 40%. LOI 20 minutes. Timeline 10 days.",
    "Quota Full https://prod1-survey-field-work.secure.force.com/quotafull?rId=XXXX",
    "Our quote for Option 1 (Total 320 PP) will follow tomorrow",
    "The cost depends on 25 respondents per centre",
])
def test_things_that_are_not_prices(text):
    assert rb.parse_quote(text) is None


def test_a_total_is_not_a_cpi():
    q = rb.parse_quote("The total cost for this study is 70000+ taxes  We would require 10 days")
    assert q["cpi"] is None and q["total"] == 70000 and q["lines"] == []


def test_options_become_lines():
    q = rb.parse_quote("Our quote for Option 1 (Total 320 PP) is INR 120+taxes.  Our quote for Option 2 "
                       "(Total 400 PP) is INR 115+taxes.")
    assert [l["cpi"] for l in q["lines"]] == [120, 115]


def test_no_quote_in_a_mail_without_a_price():
    assert rb.parse_quote("Please find attached our costing. Regards") is None


def test_invented_details_are_dropped():
    # live answer for a mail that said only "The ID ... has been captured. Please go ahead."
    out = {"methodology": "Not specified", "country": "Not specified", "target_audience": "Not specified",
           "sample_size": 1000, "loi": 15, "ir": 5, "deadline": "Not specified", "budget": 5000, "currency": "Not"}
    assert rb.grounded_details(out, "The ID mentioned below has been captured. Please go ahead.") == {}


def test_details_the_mail_states_are_kept():
    text = ("RFQ_Brand Lift Study: Online survey in India, n=1,000 women 25-45, LOI 15 min, IR 30%. "
            "Budget USD 4,500. Need costs by Friday.")
    out = {"methodology": "Online survey", "country": "India", "target_audience": "women 25-45",
           "sample_size": 1000, "loi": 15, "ir": 30, "deadline": "Friday", "budget": 4500, "currency": "USD"}
    got = rb.grounded_details(out, text)
    assert got == {"methodology": "Online", "country": "India", "target_audience": "women 25-45",
                   "deadline": "Friday", "sample_size": 1000, "loi": 15, "ir": 30, "budget": 4500, "currency": "USD"}


def test_model_prose_is_not_kept_as_a_detail():
    text = "Please quote. TG: Age 30+, M/F. LOI: 20 minutes. IR: 40%. Market: PAN India. Online panel."
    out = {"methodology": "The project will use a household survey method to collect bi",
           "country": "PAN India", "deadline": "The deadline for the survey is",
           "target_audience": "The target audience will be selected from the specified age group",
           "sample_size": None, "loi": 20, "ir": 40, "budget": None, "currency": "INR"}
    got = rb.grounded_details(out, text)
    assert got == {"methodology": "Online, Panel", "country": "PAN India", "loi": 20, "ir": 40}


class _Agg:
    """email_metadata stand-in: first message per thread + the docs."""

    def __init__(self, docs):
        self.docs = docs

    def aggregate(self, pipeline, **kw):
        match = pipeline[0]["$match"]
        group = next(s["$group"] for s in pipeline if "$group" in s)
        if "gmail_thread_id" in match and "$in" in match["gmail_thread_id"]:
            ids = match["gmail_thread_id"]["$in"]
            rows = sorted((d for d in self.docs if d["gmail_thread_id"] in ids), key=lambda d: d["timestamp"])
            seen = {}
            for d in rows:
                seen.setdefault(d["gmail_thread_id"], {"_id": d["gmail_thread_id"], "dir": d["direction"],
                                                       "first_id": d["_id"]})
            return list(seen.values())
        rows = sorted((d for d in self.docs if d["direction"] == "inbound" and d.get("ai_tier1_category") == "rfq"
                       and d.get("mail_party") == "client"), key=lambda d: d["timestamp"])
        seen = {}
        for d in rows:
            seen.setdefault(d["gmail_thread_id"], {"_id": d["gmail_thread_id"], "mid": d["_id"]})
        return list(seen.values())

    def find(self, q, proj=None):
        ids = set(q["_id"]["$in"])
        return [d for d in self.docs if d["_id"] in ids]


def test_only_threads_the_client_opened_count():
    from datetime import datetime
    docs = [
        # Hansa asks us: an RFQ
        {"_id": 1, "gmail_thread_id": "t1", "direction": "inbound", "timestamp": datetime(2026, 9, 1),
         "ai_tier1_category": "rfq", "mail_party": "client", "subject": "RFQ_Bev", "from_email": "k@hansaresearch.com"},
        # we asked a supplier; their reply is labelled rfq but the thread is ours
        {"_id": 2, "gmail_thread_id": "t2", "direction": "outbound", "timestamp": datetime(2026, 9, 2),
         "subject": "RFQ - US GP", "from_email": "s@surveyfieldwork.com"},
        {"_id": 3, "gmail_thread_id": "t2", "direction": "inbound", "timestamp": datetime(2026, 9, 3),
         "ai_tier1_category": "rfq", "mail_party": "client", "subject": "RE: RFQ - US GP", "from_email": "x@y.com"},
    ]
    got = rb.candidates({"torpedo_gmail": {"email_metadata": _Agg(docs)}})
    assert [d["_id"] for d in got] == [1]
