"""
Tests for sales/reply_triage.py. The reply texts are real replies to our cold
outreach (2026-04..09), trimmed; the 2026-09-26 benchmark showed the local
model calling ~43% of declines "Interested", mostly because it read our own
quoted pitch -- these tests pin the fixes for that.
"""
from datetime import datetime, timedelta

import pytest

from sales import reply_triage as rt


QUOTED_PITCH = (
    "\n\nFrom: indira@surveyfieldwork.com <indira@surveyfieldwork.com>\n"
    "Sent: Thursday, April 16, 2026 9:44 AM\nTo: Kumar, Anuja\nSubject: When others say no\n\n"
    "Hi Anuja,\nIf you have anything like that coming up, I'd be glad to show you how we "
    "approach it differently.\nOpen to a short chat?\n"
)


# ---- stripping the quoted thread ------------------------------------------

def test_strip_removes_outlook_quoted_thread():
    assert rt.strip_quoted("Not Interested. Thanks." + QUOTED_PITCH) == "Not Interested. Thanks."


def test_strip_removes_gmail_on_wrote_block():
    body = "Yes sure. Thank you\n\nOn Sat, Jun 20, 2026 at 9:45 PM Indira Das <indira@x.com> wrote:\n> Worth keeping us as a backup?"
    assert rt.strip_quoted(body) == "Yes sure. Thank you"


def test_strip_removes_single_line_outlook_header():
    body = "Thank you. Best regards Wiryadi From: Indira Das <indira@x.com> Sent: Tuesday, 18 August 2026 To: w@x.com Subject: hi"
    assert rt.strip_quoted(body).startswith("Thank you. Best regards Wiryadi")
    assert "Subject" not in rt.strip_quoted(body)


def test_quoted_pitch_can_never_make_a_decline_positive():
    result = rt.triage_reply("Not Interested. Thanks." + QUOTED_PITCH, use_model=False)
    assert result["verdict"] == "negative"


# ---- deterministic rules, on real replies ---------------------------------

@pytest.mark.parametrize("reply", [
    "After evaluating last year's projects and forecasting our upcoming needs, we don't see an "
    "opportunity to partner at this time. However, I will reach out directly should our needs change.",
    "We currently have very low volume of projects so there is no need for this. Once I have a need, I will reach out.",
    "As mentioned before, thank you for all the emails you have sent us. If we ever need your help, we will contact you.",
    "Hi Indira, Thanks for reaching out, we don’t have a requirement. Regards, Miriam",
    "Sorry nothing needed at this time.",
    "We are however, currently not out sourcing this service.",
    "For these audience I revert to our own field team to source.",
    "ACI Research Services has ceased trading.",
])
def test_real_declines_are_negative(reply):
    assert rt.rule_verdict(reply)["verdict"] == "negative"


@pytest.mark.parametrize("reply", [
    "Please remove me from your mailing list.",
    "Hi Indira, Kindly keep me off your list.",
    "I hope you will unsubscribe me from your list",
])
def test_unsubscribe_requests_are_negative(reply):
    assert rt.rule_verdict(reply)["verdict"] == "negative"


@pytest.mark.parametrize("reply", [
    "We are currently preparing a proposal and would like to check your feasibility and costs for the following markets: France, Germany",
    "Can you send me your company credentials or capability deck if you have any?",
    "Hi Indira, We can do this tommorow 6 pm. If that works.",
    "Are you supporting quant or qual? Please be more specific with your average CPI's range",
])
def test_explicit_asks_are_positive(reply):
    assert rt.rule_verdict(reply)["verdict"] == "positive"


def test_referral_to_a_colleague_needs_a_human():
    reply = "We manage the offline data collection component for SSA. You are now in contact with Patrick regarding the online."
    assert rt.rule_verdict(reply)["verdict"] == "needs_human"


def test_referral_name_match_is_case_sensitive():
    # "speak to are" came out of an unstripped quoted pitch; it is not a name.
    assert rt.rule_verdict("a lot of research teams we speak to are struggling") is None


def test_out_of_office_is_auto_reply():
    assert rt.rule_verdict("Hi I am on leave from 15th June to 20th June 2026.")["verdict"] == "auto_reply"


def test_legal_language_needs_a_human():
    assert rt.rule_verdict("Stop this or we will take legal action.")["verdict"] == "needs_human"


def test_decline_plus_ask_is_mixed_and_needs_a_human():
    reply = "We don't have any specific project requirements. Could you share your rate card anyway?"
    assert rt.rule_verdict(reply)["verdict"] == "needs_human"


def test_bare_thank_you_is_left_undecided_for_the_model():
    assert rt.rule_verdict("Thank you. Best regards Wiryadi") is None


@pytest.mark.parametrize("reply", [
    "I actually do not ever purchase sample. My practice specializes in advanced analytics.",
    "Hi Meera\n\nYou are approaching wrong audience",
    "Thanks a lot for connecting.\n\nWill definitely connect if there's any project",
])
def test_declines_seen_in_the_wider_reply_set_are_negative(reply):
    assert rt.rule_verdict(reply)["verdict"] == "negative"


@pytest.mark.parametrize("reply", [
    # A vendor answering OUR request for a quote -- its "not in a position to
    # offer face-to-face" is about one element, not a decline of us.
    "Thank you for the opportunity of pitching for your home food deliveries project. We have "
    "attached your cost sheet. Currently we are not in a position to offer face-to-face groups.",
    # A vendor pitching back, with its own CPI table.
    "Are You looking for an experienced Sociological Surveys \"end-level\" Provider for Europe and Asia? CPI tables below.",
])
def test_vendors_quoting_or_selling_to_us_need_a_human(reply):
    assert rt.rule_verdict(reply)["verdict"] == "needs_human"


def test_a_meeting_invite_from_the_prospect_is_positive():
    body = "________________________________________________________________\nMicrosoft Teams meeting\nJoin on your computer"
    out = rt.triage_reply(body, subject="Invitation: Intro call @ Fri 5 Jun 2pm", use_model=False)
    assert out["verdict"] == "positive"


def test_a_decline_quoting_an_old_invite_is_not_positive():
    body = "We are not interested, thanks.\n\nOn Mon, Jun 1 Meera wrote:\n> Microsoft Teams meeting\n> Join on your computer"
    assert rt.triage_reply(body, subject="RE: intro", use_model=False)["verdict"] == "negative"


def test_empty_reply_needs_a_human():
    assert rt.rule_verdict("")["verdict"] == "needs_human"


# ---- model policy -----------------------------------------------------------

def test_model_only_positive_is_held_for_a_human_by_default(monkeypatch):
    monkeypatch.delenv("REPLY_TRIAGE_TRUST_MODEL_POSITIVE", raising=False)
    monkeypatch.setattr(rt, "model_verdict", lambda r, s="": {"verdict": "positive", "reason": "warm"})
    out = rt.triage_reply("Thank you for your warm welcome, genuinely excited.")
    assert out["verdict"] == "needs_human"
    assert out["method"] == "model_unconfirmed"
    assert out["model_verdict"] == "positive"


def test_model_positive_can_be_trusted_by_flag(monkeypatch):
    monkeypatch.setenv("REPLY_TRIAGE_TRUST_MODEL_POSITIVE", "true")
    monkeypatch.setattr(rt, "model_verdict", lambda r, s="": {"verdict": "positive", "reason": "warm"})
    assert rt.triage_reply("Thank you for your warm welcome.")["verdict"] == "positive"


def test_model_negative_is_used(monkeypatch):
    monkeypatch.setattr(rt, "model_verdict", lambda r, s="": {"verdict": "negative", "reason": "no"})
    out = rt.triage_reply("We are a qualitative recruiter and find people for qual studies!")
    assert (out["verdict"], out["method"]) == ("negative", "model")


def test_model_unavailable_falls_back_to_needs_human(monkeypatch):
    monkeypatch.setattr(rt, "model_verdict", lambda r, s="": None)
    out = rt.triage_reply("Thank you.")
    assert (out["verdict"], out["method"]) == ("needs_human", "fallback")


# ---- batch job: writes onto the record the Leads page reads ---------------

class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, doc, query):
        # Operator conditions ($or, $regex, ...) are treated as matching: these
        # tests control exactly which docs exist.
        return all(doc.get(k) == v for k, v in query.items()
                   if not k.startswith("$") and not isinstance(v, dict))

    def find(self, query=None, *a, **k):
        docs = [d for d in self.docs if self._match(d, query or {})]
        class _Cur(list):
            def limit(self, n):
                return self[:n]
        return _Cur(docs)

    def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if self._match(d, query or {}):
                return d
        return None

    def insert_one(self, doc):
        doc.setdefault("_id", f"id{len(self.docs)}")
        self.docs.append(doc)

    def update_one(self, query, update):
        d = self.find_one(query)
        if d is not None:
            d.update(update.get("$set", {}))


class _Client(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _client(promoted, enriched, reply_body):
    gmail = {"email_metadata": _Col([{"body_plain": reply_body, "subject": "RE: fieldwork support",
                                       "direction": "inbound",
                                       "gmail_message_id": "m1", "gmail_thread_id": "t1",
                                       "mailbox_id": "mb1", "timestamp": datetime.utcnow()}])}
    return _Client({"email_automation": {"leads": _Col(promoted), "leads_enriched": _Col(enriched)},
                    "torpedo_gmail": gmail})


def _promoted(email, days_ago=1):
    return {"_id": "p-" + email, "email": email, "source": "outreach_reply", "name": "Sean Lee",
            "outreach_replied_at": datetime.utcnow() - timedelta(days=days_ago)}


def test_batch_puts_an_unseen_replier_on_the_leads_page(monkeypatch):
    client = _client([_promoted("sean@x.com")], [], "Could you take a look at these requirements and let us know if feasible?")
    monkeypatch.setattr(rt, "_mongo", lambda: client)
    started = []
    import sales.nurture as nurture
    monkeypatch.setattr(nurture, "start_nurture", lambda lid, started_by="": started.append(lid) or True)

    stats = rt.run_reply_triage_batch(use_model=False)

    enriched = client["email_automation"]["leads_enriched"].docs
    assert len(enriched) == 1
    assert enriched[0]["source"] == "outreach_reply"
    assert enriched[0]["lead_status"] == "Positive"
    assert enriched[0]["lead_status_source"] == "reply_triage"
    assert stats["positive"] == 1 and stats["nurture_started"] == 1 and len(started) == 1


def test_batch_never_overwrites_a_status_a_person_set(monkeypatch):
    existing = {"_id": "e1", "email": "casey@x.com", "lead_status": "Positive", "lead_status_source": "human"}
    client = _client([_promoted("casey@x.com")], [existing], "we don't see an opportunity to partner at this time.")
    monkeypatch.setattr(rt, "_mongo", lambda: client)

    rt.run_reply_triage_batch(use_model=False)

    assert existing["lead_status"] == "Positive"          # human decision kept
    assert existing["reply_sentiment"] == "negative"       # triage still recorded


def test_old_positive_is_labelled_but_does_not_autostart_nurture(monkeypatch):
    client = _client([_promoted("old@x.com", days_ago=90)], [], "Can you send me your capability deck?")
    monkeypatch.setattr(rt, "_mongo", lambda: client)
    import sales.nurture as nurture
    monkeypatch.setattr(nurture, "start_nurture", lambda *a, **k: pytest.fail("must not start"))

    stats = rt.run_reply_triage_batch(use_model=False)
    assert stats["positive"] == 1 and stats["nurture_started"] == 0
