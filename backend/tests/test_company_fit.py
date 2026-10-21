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
