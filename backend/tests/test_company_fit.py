"""The company decides the ICP; the search that found a person does not."""
import pytest

from leads import company_fit as cf
from leads.canonical_ingestion import compute_icp_basket


def basket(**fields):
    return compute_icp_basket(fields).get("classification_basket")


def test_bimwave_search_tag_alone_no_longer_makes_basket_c():
    """The Ipsos-gets-BIM-mail bug: the search job's ICP was taken as the answer."""
    assert basket(icp_segment="bimwave", icp_source="search", title="Research Manager",
                  company_name="Ipsos") == "E"


def test_company_type_beats_the_search_tag():
    assert basket(icp_segment="bimwave", icp_source="search", company_icp_type="mr_agency") == "A"
    assert basket(icp_segment="survey_fieldwork", icp_source="search", company_icp_type="aec") == "C"
    assert basket(icp_segment="cogentix", company_icp_type="other") == "E"


def test_a_segment_set_by_a_person_still_counts():
    assert basket(icp_segment="bimwave") == "C"


def test_search_hint_adds_to_real_evidence():
    # industry alone (+4) ties nothing; the hint just confirms the winner
    assert basket(icp_segment="bimwave", icp_source="search", company_industry="Construction") == "C"


@pytest.mark.parametrize("text,expected", [
    ("Ipsos | LinkedIn ... Industry: Market Research · Company size 10,001+", "mr_agency"),
    ("Arup | Industry: Civil Engineering", "aec"),
    ("Hindustan Unilever | Industry: Consumer Goods", "brand"),
    ("Infosys | Industry: IT Services and IT Consulting", "other"),
    ("We are an architecture practice delivering BIM coordination", "aec"),
    ("Global market research company helping brands understand consumers", "mr_agency"),
    ("Welcome to our page", None),
])
def test_type_from_linkedin_text(text, expected):
    assert cf.type_from_text(text)[0] == expected


def test_seed_names_match_whole_words_only():
    assert cf.seed_type("Ipsos India Pvt Ltd") == "mr_agency"
    assert cf.seed_type("", "kantar.com") == "mr_agency"
    assert cf.seed_type("Survey Fieldwork") is None       # us, not a seed hit
    assert cf.seed_type("Lucid Motors") is None


def test_company_key_ignores_platform_domains():
    assert cf.company_key("Ipsos", "in.linkedin.com") == "name:ipsos"
    assert cf.company_key("Ipsos", "https://www.ipsos.com/en") == "ipsos.com"
    assert cf.company_key("", "") == ""


@pytest.mark.parametrize("doc,business,title,verdict", [
    ({"type": "mr_agency"}, "bimwave", "", "mismatch"),
    ({"type": "mr_agency"}, "sfw", "Research Director", "fit"),
    ({"type": "aec"}, "bimwave", "Talent Acquisition Lead", "mismatch"),
    ({"type": "brand", "relationship": "client"}, "cogentix", "", "excluded"),
    (None, "sfw", "", "unknown"),
    ({"type": "aec"}, "unknown_business", "", "fit"),
])
def test_decide(doc, business, title, verdict):
    assert cf.decide(doc, business, title)[0] == verdict


def test_page_text_takes_only_the_company_page():
    items = [{"link": "https://in.linkedin.com/in/someone", "title": "Someone - Ipsos"},
             {"link": "https://www.linkedin.com/company/ipsos", "title": "Ipsos | LinkedIn",
              "snippet": "Industry: Market Research"}]
    text, url = cf._page_text(items, "Ipsos")
    assert url.endswith("/company/ipsos") and "Market Research" in text


class _Col:
    def __init__(self):
        self.docs = {}

    def find_one(self, q, proj=None):
        if "_id" in q:
            return self.docs.get(q["_id"])
        return None

    def update_one(self, q, u, upsert=False):
        d = self.docs.setdefault(q["_id"], {"_id": q["_id"]})
        for k, v in (u.get("$setOnInsert") or {}).items():
            d.setdefault(k, v)
        d.update(u.get("$set") or {})
        for k, v in (u.get("$inc") or {}).items():
            d[k] = d.get(k, 0) + v


class _DB(dict):
    def __missing__(self, k):
        self[k] = _Col()
        return self[k]


def test_ipsos_in_the_bimwave_chain_is_a_mismatch():
    client = {"email_automation": _DB()}
    assert cf.check("bimwave", "Ipsos", "ipsos.com", "Research Manager", client=client)[0] == "mismatch"
    assert cf.check("sfw", "Ipsos", "ipsos.com", "Research Manager", client=client)[0] == "fit"


def test_unknown_company_is_queued_and_waits():
    client = {"email_automation": _DB()}
    assert cf.check("bimwave", "Acme Builders", "acmebuilders.in", client=client)[0] == "unknown"
    queued = client["email_automation"]["company_types"].docs["acmebuilders.in"]
    assert queued["status"] == "pending" and queued["mailable_leads"] == 1


# --- the AI check and the move + resend (leads/icp_check.py) ----------------
from datetime import datetime  # noqa: E402

from leads import icp_check as ic  # noqa: E402

CAMPS = [{"campaign_id": "c-sfw", "business": "sfw", "is_active": True},
         {"campaign_id": "c-cog", "business": "cogentix", "is_active": True},
         {"campaign_id": "c-bim", "business": "bimwave", "is_active": True}]


class _Rows:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.inserted = []

    def find(self, q=None, proj=None):
        return [d for d in self.docs if all(d.get(k) == v for k, v in (q or {}).items()
                                            if not isinstance(v, dict))]

    def find_one(self, q=None, proj=None):
        r = self.find(q)
        return r[0] if r else None

    def update_one(self, q, u, upsert=False):
        for d in self.docs:
            if d.get("_id") == q.get("_id"):
                d.update(u.get("$set") or {})

    def insert_one(self, doc):
        self.inserted.append(doc)


class _T(dict):
    def __missing__(self, k):
        self[k] = _Rows()
        return self[k]

    @property
    def client(self):
        return {"email_automation": _T()}


def _tdb(rows):
    t = _T()
    t["outreach_campaigns_v2"] = _Rows(CAMPS)
    t["outreach_leads_v2"] = _Rows(rows)
    return t


def _person(rows, expected="sfw", blocked=False):
    return {"email": "a@ipsos.com", "rows": rows, "company": "Ipsos", "title": "Research Manager",
            "expected": expected, "blocked": blocked}


NOW = datetime(2026, 10, 21)


def test_got_bim_mail_before_gets_moved_and_resent_from_step_one():
    rows = [{"_id": 1, "campaign_id": "c-bim", "workflow_status": "completed", "current_step": 4}]
    t = _tdb(rows)
    assert ic.reconcile(t, _person(rows), {"aligned": True}, NOW) == "resend_new_row"
    new = t["outreach_leads_v2"].inserted[0]
    assert new["campaign_id"] == "c-sfw" and new["current_step"] == 0 and new["workflow_status"] == "not_started"


def test_live_wrong_row_is_retired_and_paused_right_row_resumed():
    rows = [{"_id": 1, "campaign_id": "c-bim", "workflow_status": "in_sequence", "current_step": 1},
            {"_id": 2, "campaign_id": "c-sfw", "workflow_status": "paused_duplicate_brand", "current_step": 0}]
    t = _tdb(rows)
    assert ic.reconcile(t, _person(rows), {"aligned": True}, NOW) == "resumed"
    by_id = {d["_id"]: d for d in t["outreach_leads_v2"].docs}
    assert by_id[1]["workflow_status"] == "moved_to_correct_bucket"
    assert by_id[2]["workflow_status"] == "not_started"


def test_ai_disagreeing_holds_and_sends_nothing():
    rows = [{"_id": 1, "campaign_id": "c-sfw", "workflow_status": "not_started", "current_step": 0}]
    t = _tdb(rows)
    assert ic.reconcile(t, _person(rows), {"aligned": False, "qwen": "cogentix"}, NOW) == "held_for_review"
    assert t["outreach_leads_v2"].docs[0]["workflow_status"] == "icp_review"
    assert not t["outreach_leads_v2"].inserted


def test_someone_who_bounced_or_replied_is_never_resent():
    rows = [{"_id": 1, "campaign_id": "c-bim", "workflow_status": "bounced", "current_step": 1}]
    t = _tdb(rows)
    assert ic.reconcile(t, _person(rows, blocked=True), {"aligned": True}, NOW) == "blocked_no_resend"
    assert not t["outreach_leads_v2"].inserted


def test_website_body_words_do_not_decide():
    head = "Acme Cloud | Cloud hosting for developers"
    body = "We help retail, banking and construction customers. Follow us on social media."
    assert cf.type_from_text(head)[0] is None
    assert cf.type_from_text((head + " || " + body).split(" || ")[0])[0] is None


class _TypesCol:
    def __init__(self):
        self.docs = {}

    def update_one(self, q, u, upsert=False):
        self.docs.setdefault(q["_id"], {"_id": q["_id"]}).update(u.get("$set") or {})


class _EA(dict):
    def __missing__(self, k):
        self[k] = _TypesCol() if k == "company_types" else _Rows()
        return self[k]


def _resolve(monkeypatch, site, answer):
    db = _EA()
    monkeypatch.setattr(cf, "website_text", lambda d: site)
    monkeypatch.setattr(cf, "_model_confirms", lambda n, t, c: answer)
    monkeypatch.setattr(cf, "rebasket_company", lambda *a: 0)
    doc = {"_id": "x.com", "name": "X", "domain": "x.com", "priority": 1}
    r = cf.resolve_one(db, doc, NOW, allow_google=False, allow_model=True)
    return r, db["company_types"].docs["x.com"]


def test_industry_found_but_ai_says_no_goes_to_a_person(monkeypatch):
    r, doc = _resolve(monkeypatch, "X | Global market research agency || ...", "no")
    assert r == "review" and "type" not in doc and doc["proposed_type"] == "mr_agency"


def test_industry_and_ai_agree_sets_the_type(monkeypatch):
    r, doc = _resolve(monkeypatch, "X | Global market research agency || ...", "yes")
    assert r == "typed" and doc["type"] == "mr_agency" and doc["ai_confirmed"] is True


def test_model_outage_is_retried_not_a_verdict(monkeypatch):
    r, doc = _resolve(monkeypatch, "X | Global market research agency || ...", None)
    assert r == "model_unavailable" and doc["status"] == "needs_model" and "type" not in doc


def test_rule_typed_waits_for_the_ai_when_the_model_is_not_called(monkeypatch):
    db = _EA()
    monkeypatch.setattr(cf, "website_text", lambda d: "X | Civil engineering and construction || ...")
    r = cf.resolve_one(db, {"_id": "x.com", "name": "X", "domain": "x.com"}, NOW,
                       allow_google=False, allow_model=False)
    assert r == "needs_model" and db["company_types"].docs["x.com"]["proposed_type"] == "aec"


def test_research_firm_naming_its_brand_clients_stays_a_research_firm():
    head = ("Global Strategy and Innovation Consultants - Egg Strategy | providing branding, insight, strategy, "
            "qualitative research and quantitative research for leading CPG, Health and Lifestyle brands.")
    assert cf.type_from_text(head)[0] == "mr_agency"


def test_one_google_call_types_five_companies(monkeypatch):
    db = _EA()
    docs = [{"_id": f"c{i}.com", "name": n, "domain": f"c{i}.com"} for i, n in
            enumerate(["Ipsos", "COWI", "Unilever", "Infosys", "Nobody Ltd"])]
    calls = []

    async def fake_search(q, num=10):
        calls.append(q)
        return [{"link": "https://www.linkedin.com/company/ipsos", "title": "Ipsos | LinkedIn",
                 "snippet": "Industry: Market Research"},
                {"link": "https://www.linkedin.com/company/cowi", "title": "COWI - LinkedIn",
                 "snippet": "Industry: Civil Engineering"},
                {"link": "https://www.linkedin.com/company/unilever", "title": "Unilever | LinkedIn",
                 "snippet": "Industry: Manufacturing of consumer goods"},
                {"link": "https://www.linkedin.com/company/infosys-bpm", "title": "Infosys BPM | LinkedIn",
                 "snippet": "Industry: IT Services"}]
    monkeypatch.setattr(cf, "_search", fake_search)
    assert cf.linkedin_batch(db, docs, NOW) == 4
    assert len(calls) == 1 and calls[0].count(" OR ") == 4
    got = db["company_types"].docs
    assert "Market Research" in got["c0.com"]["linkedin_text"]
    assert got["c4.com"]["linkedin_text"] == "" and got["c4.com"]["linkedin_at"] == NOW


def test_a_page_must_be_that_company_not_one_sharing_a_word():
    items = [{"link": "https://www.linkedin.com/company/global-x", "title": "Global Research Partners | LinkedIn",
              "snippet": "Industry: Market Research"}]
    assert cf._page_text(items, "Research Now")[0] == ""


def test_a_research_firm_never_passes_as_a_brand(monkeypatch):
    db = _EA()
    monkeypatch.setattr(cf, "website_text", lambda d: "GWI | Audience profiles for marketers || ...")
    monkeypatch.setattr(cf, "_model_confirms", lambda n, t, c: "yes")   # yes to everything
    monkeypatch.setattr(cf, "_model_type", lambda n, t: "brand")
    monkeypatch.setattr(cf, "rebasket_company", lambda *a: 0)
    doc = {"_id": "gwi.com", "name": "GWI", "domain": "gwi.com", "linkedin_at": NOW}
    r = cf.resolve_one(db, doc, NOW, allow_google=False, allow_model=True)
    assert r == "review" and "type" not in db["company_types"].docs["gwi.com"]


def test_unsafe_guessed_address_is_never_resent():
    assert "bounce_recovery_alt" in ic.UNSAFE_SOURCES
