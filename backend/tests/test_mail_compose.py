"""Mail summaries and reply drafts: checks reject invented facts; drafts are suggestions only."""
from mail_pipeline import compose

MAIL = ("Hi team, we liked your note. We run 3 studies a year in India and need a vendor for a 1,200 n "
        "online survey in March. Can you share your panel size and a short call slot next week? Thanks, Priya")


def _model(answer, seen=None):
    def run(**kw):
        if seen is not None:
            seen.append(kw)
        problems = kw["code_check"](answer, kw["body"]) if kw.get("code_check") else []
        return {"status": "ok" if not problems else "failed", "data": answer if not problems else None,
                "problems": problems, "tier": "haiku"}
    return run


def test_short_mail_is_its_own_summary_without_a_model():
    out = compose.summarize({}, "Thanks, received. Will revert by Friday.", model=None)
    assert out["tier"] == "rules" and out["summary"].startswith("Thanks")


def test_summary_with_an_invented_number_is_rejected():
    assert compose.summary_check({"summary": "Priya needs 1,200 n in India.", "asks": []}, MAIL) == []
    probs = compose.summary_check({"summary": "Priya needs 5000 completes.", "asks": []}, MAIL)
    assert probs and "5000" in probs[0]
    out = compose.summarize({"subject": "Re"}, MAIL + " " + MAIL, _model({"summary": "Needs 5000 completes", "asks": [], "deadline": None}))
    assert out is None


def test_good_draft_is_accepted_and_signoff_stripped():
    body = ("Hi Priya,\n\nThank you for coming back to us. Happy to help with the 1,200 n online survey in India in "
            "March. Our panel covers the profiles you are likely to need, and I can walk you through feasibility on a "
            "short call. Would Tuesday or Wednesday next week suit you for a quick chat?\n\nBest regards,\nAnita")
    seen = []
    out = compose.draft_reply({"from_name": "Priya Shah", "from_email": "priya@client.com", "subject": "Your note"}, MAIL,
                              purpose="positive_reply_draft", bu="SFW",
                              bu_facts={"label": "Survey Fieldwork", "what_we_sell": "online sample and fieldwork"},
                              model=_model({"body": body}, seen))
    assert out and out["subject"] == "Re: Your note" and "Anita" not in out["body"] and out["body"].startswith("Hi Priya")
    assert seen[0]["enqueue_on_fail"] is False and seen[0]["task"] == "reply_draft"


def test_draft_checks_reject_invented_prices_placeholders_and_missing_name():
    chk = compose.draft_check_factory("Priya", "FACTS: online sample")
    long_ok = "Hi Priya, " + "we can help with this study and will share details shortly. " * 4
    assert chk({"body": long_ok}, MAIL) == []
    assert any("numbers" in p for p in chk({"body": long_ok + " CPI is 4.5 USD."}, MAIL))
    assert any("placeholder" in p for p in chk({"body": long_ok + " [Your Name]"}, MAIL))
    assert any("greet" in p for p in chk({"body": long_ok.replace("Hi Priya", "Hello there")}, MAIL))
    assert any("guarantee" in p for p in chk({"body": long_ok + " We guarantee results."}, MAIL))
    assert any("words" in p for p in chk({"body": "Hi Priya, sure."}, MAIL))


def test_first_name_from_display_or_address():
    assert compose.first_name('"Priya Shah"', "x@y.com") == "Priya"
    assert compose.first_name("", "raj.kumar@client.com") == "Raj"
    assert compose.first_name("", "info@client.com") == "Info" or compose.first_name("", "ab@c.com") is None
