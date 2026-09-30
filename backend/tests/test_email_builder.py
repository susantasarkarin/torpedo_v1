"""Emails for generated leads: bounce-free structures, Hunter fallback, AI check."""
from collections import Counter
from datetime import datetime
from unittest.mock import patch

from app.services import email_structure as es
from leads import email_builder as eb

NOW = datetime(2026, 9, 30)


class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def find(self, q=None, proj=None):
        q = q or {}
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    ok &= d.get(k) in v["$in"]
                elif isinstance(v, dict) and "$ne" in v:
                    ok &= d.get(k) != v["$ne"]
                elif isinstance(v, dict) and "$nin" in v:
                    ok &= d.get(k) not in v["$nin"]
                else:
                    ok &= d.get(k) == v
            if ok:
                out.append(d)
        return _Cur(out)

    def find_one(self, q=None, proj=None):
        r = self.find(q).docs
        return r[0] if r else None

    def update_one(self, q, u, upsert=False):
        self.updates.append((q, u))


class _Cur:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self.docs[:n]

    def __iter__(self):
        return iter(self.docs)


def _addr(email, form, wrote=0, bounced=False, name=""):
    return {"_id": email, "domain": email.split("@")[1], "pattern_form": form, "wrote_to_us": wrote,
            "bounced": bounced, "name": name}


def test_bounced_addresses_teach_nothing():
    col = _Col([_addr("a.b@x.com", "{first}.{last}"), _addr("c.d@x.com", "{first}.{last}", bounced=True),
                _addr("ef@x.com", "{f}{last}", wrote=2)])
    assert es.domain_evidence(col, ["x.com"])["x.com"] == Counter({"{first}.{last}": 1, "{f}{last}": 2})


def test_mail_pool_structure_needs_agreement():
    client = {"email_automation": {"email_address_structures": _Col([
        _addr("keya.kundu@hansa.com", "{first}.{last}", wrote=3, name="Keya Kundu"),
        _addr("ramiz.j@hansa.com", "{first}.{last}")])}}
    s = eb.mail_pool_structure(client, "hansa.com")
    assert s["form"] == "{first}.{last}" and s["source"] == "mail_pool"
    assert s["examples"][0]["email"] == "keya.kundu@hansa.com"
    one = {"email_automation": {"email_address_structures": _Col([_addr("x.y@solo.com", "{first}.{last}")])}}
    assert eb.mail_pool_structure(one, "solo.com") is None  # one address we only wrote to is not enough


def test_names_drop_titles_initials_and_nicknames():
    assert eb.lead_names({"name": "Dr. Keya Kundu, PhD"}) == ("keya", "kundu")
    assert eb.lead_names({"name": "A L Jagannath (Jaggi)"}) == ("jagannath", "")
    assert eb.lead_names({"name": "José Álvarez"}) == ("jose", "alvarez")


def _ai(answer):
    from leads import local_slm_client
    return patch.object(local_slm_client, "chat_json", return_value=answer)


def test_ai_ok_and_guarded_correction():
    st = {"form": "{first}.{last}", "examples": []}
    lead = {"name": "Keya Kundu", "company_name": "Hansa"}
    with _ai({"domain_is_company": True, "email_correct": True, "corrected_email": "", "reason": "fits"}):
        assert eb.ai_check(lead, "hansa.com", st, "keya.kundu@hansa.com", "keya", "kundu", set())["verdict"] == "ok"
    with _ai({"domain_is_company": True, "email_correct": False, "corrected_email": "kkundu@hansa.com", "reason": "x"}):
        out = eb.ai_check(lead, "hansa.com", st, "keya.kundu@hansa.com", "keya", "kundu", set())
    assert out == {"verdict": "corrected", "email": "kkundu@hansa.com", "reason": "x"}
    # a correction off the domain, not a structure of the name, or bounced -> doubt
    for fix, bounced in (("keya@gmail.com", set()), ("sales@hansa.com", set()), ("kkundu@hansa.com", {"kkundu@hansa.com"})):
        with _ai({"domain_is_company": True, "email_correct": False, "corrected_email": fix, "reason": ""}):
            assert eb.ai_check(lead, "hansa.com", st, "keya.kundu@hansa.com", "keya", "kundu", bounced)["verdict"] == "doubt"
    with _ai({"domain_is_company": False, "email_correct": True, "corrected_email": "", "reason": "parent co"}):
        assert eb.ai_check(lead, "hansa.com", st, "keya.kundu@hansa.com", "keya", "kundu", set())["verdict"] == "domain_doubt"


def test_model_outage_is_not_a_verdict():
    from leads import local_slm_client
    with patch.object(local_slm_client, "chat_json", side_effect=local_slm_client.LocalSLMUnavailable("down")):
        out = eb.ai_check({"name": "K K"}, "h.com", {"form": "{first}", "examples": []}, "k@h.com", "k", "k", set())
    assert out["verdict"] == "unavailable"


def test_hunter_not_asked_without_a_key_or_over_the_monthly_cap(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    client = {"email_automation": {"hunter_lookups": _Col(), "hunter_usage": _Col()},
              "torpedo_settings": {"app_settings": _Col()}}
    assert eb.hunter_structure(client, "x.com", NOW) == (None, "hunter_not_configured")
    monkeypatch.setenv("HUNTER_API_KEY", "k")
    client["email_automation"]["hunter_usage"] = _Col([{"_id": "2026-09", "n": 25}])
    with patch.object(eb.requests, "get") as get:
        assert eb.hunter_structure(client, "x.com", NOW) == (None, "hunter_monthly_limit")
    get.assert_not_called()


def test_a_job_title_is_not_a_person():
    assert not eb.is_person_name({"name": "Creative Design Manager"})
    assert not eb.is_person_name({"name": "Rahul", "title": "rahul"})
    assert eb.is_person_name({"name": "Cindy Lai (Su Kwan)", "title": "Research Director"})


def test_linkedin_host_replaced_by_the_company_domain_our_mail_knows():
    client = {"email_automation": {"email_domain_structures": _Col([
        {"_id": "ipsos.com", "company_name": "Ipsos", "people": 40}])}}
    with patch.object(_Col, "find", lambda self, q=None, p=None: _Cur(self.docs)):
        assert eb.company_domain_for(client, {"company_domain": "in.linkedin.com", "company_name": "Ipsos"}) == "ipsos.com"
    assert eb.company_domain_for(client, {"company_domain": "kantar.com"}) == "kantar.com"
