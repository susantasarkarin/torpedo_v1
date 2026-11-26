"""Marketing > Newsletter: design, audience, test-before-approve, paced sending, unsubscribe."""
from datetime import datetime, timedelta

import pytest

from marketing import newsletter as N
from tests._fakemongo import FakeDB

NOW = datetime(2026, 11, 23, 6, 0)
CFG = {"daily_cap_per_mailbox": 3, "per_tick_per_mailbox": 2, "max_attempts": 2, "brands": {}}


@pytest.fixture
def world(monkeypatch):
    dbs = {}

    def gd(name):
        return dbs.setdefault(name, FakeDB())

    monkeypatch.setattr(N, "public_base", lambda: "https://torpedo.example")
    monkeypatch.setattr(N, "_cfg", lambda: CFG)
    mail = gd("torpedo_gmail")
    for e in ("news@surveyfieldwork.com", "hello@cogentixresearch.com", "ops@bimwavesolutions.com"):
        mail["workspace_mailboxes"].insert_one({"email": e, "display_name": e.split("@")[0], "is_active": True})
    crm = gd("crm_db")
    crm["leads"].insert_one({"email": "Asha@Client.com", "firstName": "Asha", "company": "Client Co", "status": "new"})
    crm["leads"].insert_one({"email": "gone@client.com", "status": "disqualified"})
    crm["contacts"].insert_one({"email": "asha@client.com", "name": "Asha K", "company": "Client Co"})
    crm["contacts"].insert_one({"email": "dnd@client.com", "dnd": True})
    crm["accounts"].insert_one({"email": "info@bigco.com", "name": "BigCo", "status": "active"})
    gd("email_automation")["vendors"].insert_one({"vendor_name": "Sample Vendor", "email": "sales@vendor.com",
                                                  "contact_name": "Ravi Shah"})
    gd("finance_db")["vendors"].insert_one({"vendor_name": "Printer", "email": "billing@printer.com", "status": "inactive"})
    gd("campaign_platform")["panelists"].insert_one({"email": "member@gmail.com"})
    return gd


def nl_doc(gd, **kw):
    doc = {"name": "Nov", "subject": "News for {{company}}", "preheader": "Hi {{first_name}}",
           "blocks": N.clean_blocks([{"type": "heading", "text": "Hello {{first_name}}"},
                                     {"type": "text", "text": "Read **this** [here](https://surveyfieldwork.com/x)."},
                                     {"type": "button", "label": "Book a call", "url": "https://surveyfieldwork.com/call"}]),
           "bus": ["SFW"], "senders": {"SFW": ["news@surveyfieldwork.com"]},
           "audience": {"SFW": {"sources": ["crm_leads", "crm_contacts"], "mailbox_scope": "bu", "extra_emails": [],
                                "exclude_emails": []}},
           "status": "draft", "history": []}
    doc.update(kw)
    doc["_id"] = gd(N.DB)[N.NEWSLETTERS].insert_one(doc).inserted_id
    return gd(N.DB)[N.NEWSLETTERS].find_one({"_id": doc["_id"]})


class Sender:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def __call__(self, **kw):
        self.sent.append(kw)
        if kw["to"][0] in self.fail:
            return {"success": False, "error": "boom"}
        return {"success": True, "message_id": f"m{len(self.sent)}"}


def test_blocks_are_validated_and_rendered_safely():
    with pytest.raises(ValueError):
        N.clean_blocks([{"type": "script"}])
    with pytest.raises(ValueError):
        N.clean_blocks([{"type": "button", "label": "x", "url": "javascript:alert(1)"}])
    blocks = N.clean_blocks([{"type": "text", "text": "<b>hi</b> **bold** [ok](https://a.com)"},
                             {"type": "image", "src": "media:abc_logo.png", "width": 9999}])
    assert blocks[1]["width"] == 536
    subject, html, text = N.render({"subject": "S {{first_name}}", "blocks": blocks}, "SFW", {"first_name": "Asha"},
                                   unsubscribe_url="https://u/x", cfg=CFG)
    assert subject == "S Asha"
    assert "&lt;b&gt;hi&lt;/b&gt;" in html and "<strong>bold</strong>" in html and 'href="https://a.com"' in html
    assert "/api/marketing/newsletter/img/abc_logo.png" in html and "Survey Fieldwork" in html
    assert 'href="https://u/x"' in html and "Unsubscribe: https://u/x" in text
    assert N.render({"subject": "Hi {{first_name}}", "blocks": []}, "BIM", cfg=CFG)[0] == "Hi there"


def test_audience_dedupes_and_excludes(world):
    gd = world
    nl = nl_doc(gd, audience={"SFW": {"sources": ["crm_leads", "crm_contacts", "crm_accounts", "ops_vendors",
                                                  "billing_vendors"], "mailbox_scope": "bu",
                                      "extra_emails": ["member@gmail.com", "noreply@x.com", "boss@surveyfieldwork.com",
                                                       "blocked@bigco.com"],
                                      "exclude_emails": ["info@bigco.com"]}})
    a = N.audience(gd, nl, "SFW", is_suppressed=lambda e: e == "blocked@bigco.com")
    emails = {r["email"] for r in a["recipients"]}
    assert emails == {"asha@client.com", "sales@vendor.com"}
    asha = next(r for r in a["recipients"] if r["email"] == "asha@client.com")
    assert asha["first_name"] == "Asha" and asha["sources"] == ["crm_leads", "crm_contacts"]
    assert a["excluded"] == {"invalid_or_role": 2, "suppressed": 1, "panel": 1, "excluded_by_hand": 1}


def test_harvest_collects_external_contacts_per_bu(world):
    gd = world
    mail = gd("torpedo_gmail")
    box = mail["workspace_mailboxes"].find_one({"email": "news@surveyfieldwork.com"})
    md = mail["email_metadata"]
    md.insert_one({"mailbox_id": str(box["_id"]), "direction": "inbound", "from_email": "Priya@Agency.in",
                   "from_name": "Priya Rao", "timestamp": NOW - timedelta(days=3), "synced_at": NOW - timedelta(hours=2)})
    md.insert_one({"mailbox_id": str(box["_id"]), "direction": "outbound", "from_email": "news@surveyfieldwork.com",
                   "to_emails": ["client@agency.in", "member@gmail.com"], "cc_emails": ["hello@cogentixresearch.com"],
                   "timestamp": NOW - timedelta(days=1), "synced_at": NOW - timedelta(hours=1)})
    md.insert_one({"mailbox_id": str(box["_id"]), "direction": "inbound", "from_email": "no-reply@accounts.google.com",
                   "synced_at": NOW - timedelta(hours=1)})
    r = N.harvest(gd, now=NOW)
    assert r["new_contacts"] == 2
    c = gd(N.DB)[N.CONTACTS].find_one({"email": "priya@agency.in"})
    assert c["name"] == "Priya Rao" and c["bus"] == ["SFW"] and c["mailboxes"] == ["news@surveyfieldwork.com"]
    assert N.harvest(gd, now=NOW)["scanned"] == 0                       # incremental
    nl = nl_doc(gd, audience={"SFW": {"sources": ["mailbox_contacts"], "mailbox_scope": "bu"},
                              "BIM": {"sources": ["mailbox_contacts"], "mailbox_scope": "bu"}})
    assert N.audience(gd, nl, "SFW", is_suppressed=lambda e: False)["count"] == 2
    assert N.audience(gd, nl, "BIM", is_suppressed=lambda e: False)["count"] == 0


def test_approval_needs_a_test_of_the_current_design(world):
    gd = world
    nl = nl_doc(gd)
    with pytest.raises(ValueError, match="send a test"):
        N.approve(gd, nl, actor="owner", now=NOW)
    s = Sender()
    assert N.send_test(gd, nl, ["me@cogentixresearch.com"], actor="me", sender=s, now=NOW)["ok"]
    assert s.sent[0]["subject"].startswith("[TEST] News for Test Company")
    assert s.sent[0]["list_unsubscribe_url"].endswith("/one-click")
    nl = gd(N.DB)[N.NEWSLETTERS].find_one({"_id": nl["_id"]})
    changed = {**nl, "subject": "Changed"}
    with pytest.raises(ValueError, match="send a test"):
        N.approve(gd, changed, actor="owner", now=NOW)
    N.approve(gd, nl, actor="owner", when=NOW + timedelta(hours=2), now=NOW)
    nl = gd(N.DB)[N.NEWSLETTERS].find_one({"_id": nl["_id"]})
    assert nl["status"] == "scheduled" and nl["approved_by"] == "owner"


def test_problems_and_blocker(world, monkeypatch):
    gd = world
    nl = nl_doc(gd, senders={"SFW": ["someone@else.com"]}, subject="")
    p = N.problems(nl, gd)
    assert "add a subject" in p and any("not an active attached mailbox" in x for x in p)
    monkeypatch.setattr(N, "public_base", lambda: "")
    assert any("OUTREACH_PUBLIC_BASE_URL" in x for x in N.problems(nl_doc(gd), gd))


def test_tick_paces_caps_retries_and_finishes(world):
    gd = world
    nl = nl_doc(gd, status="scheduled", scheduled_for=NOW - timedelta(minutes=1),
                audience={"SFW": {"sources": [], "extra_emails": [f"p{i}@client{i}.com" for i in range(6)]}})
    s = Sender(fail={"p1@client1.com"})
    r = N.tick(gd, now=NOW, sender=s, is_suppressed=lambda e: e == "p5@client5.com", cfg=CFG)   # p5 left out at start
    assert r["started"] == [str(nl["_id"])] and len(s.sent) == 2           # 2 per tick per mailbox
    assert s.sent[0]["from_email"] == "news@surveyfieldwork.com"
    for i in range(1, 6):
        N.tick(gd, now=NOW + timedelta(minutes=i), sender=s, is_suppressed=lambda e: False, cfg=CFG)
    st = N.stats(gd, nl["_id"])
    assert st["sent"] == 3                                                  # daily cap of 3 per mailbox
    assert st["queued"] >= 1
    nl = gd(N.DB)[N.NEWSLETTERS].find_one({"_id": nl["_id"]})
    assert nl["status"] == "sending"
    late = lambda e: e == "p4@client4.com"                                  # unsubscribed after the list was built
    # the cap is a rolling 24 h (Google's window): still capped just before 24 h after the first sends
    before = len(s.sent)
    N.tick(gd, now=NOW + timedelta(hours=23, minutes=59), sender=s, is_suppressed=late, cfg=CFG)
    assert len(s.sent) == before
    N.tick(gd, now=NOW + timedelta(days=1, minutes=10), sender=s, is_suppressed=late, cfg=CFG)
    N.tick(gd, now=NOW + timedelta(days=1, minutes=11), sender=s, is_suppressed=late, cfg=CFG)
    st = N.stats(gd, nl["_id"])
    assert st["queued"] == 0 and st["failed"] == 1 and st["sent"] == 3 and st["skipped"] == 1
    assert "p4@client4.com" not in [m["to"][0] for m in s.sent]
    assert gd(N.DB)[N.NEWSLETTERS].find_one({"_id": nl["_id"]})["status"] == "sent"
    rows = gd(N.DB)[N.RECIPIENTS].find({"email": "p1@client1.com"})
    assert rows[0]["attempts"] == 2 and rows[0]["error"] == "boom"


def test_interrupted_rows_are_not_resent(world):
    gd = world
    nl = nl_doc(gd, status="sending")
    gd(N.DB)[N.RECIPIENTS].insert_one({"newsletter_id": nl["_id"], "bu": "SFW", "email": "x@y.com", "status": "sending",
                                       "claimed_at": NOW - timedelta(hours=1)})
    s = Sender()
    N.tick(gd, now=NOW, sender=s, is_suppressed=lambda e: False, cfg=CFG)
    assert s.sent == [] and gd(N.DB)[N.RECIPIENTS].find_one({"email": "x@y.com"})["status"] == "failed"


def test_cancel_skips_the_rest(world):
    gd = world
    nl = nl_doc(gd, status="sending")
    gd(N.DB)[N.RECIPIENTS].insert_one({"newsletter_id": nl["_id"], "bu": "SFW", "email": "x@y.com", "status": "queued"})
    assert N.set_status(gd, nl, "cancel", actor="me", now=NOW) == "cancelled"
    assert gd(N.DB)[N.RECIPIENTS].find_one({"email": "x@y.com"})["reason"] == "cancelled"
    with pytest.raises(ValueError):
        N.set_status(gd, gd(N.DB)[N.NEWSLETTERS].find_one({"_id": nl["_id"]}), "resume", actor="me")


def test_clean_keeps_only_known_bus_and_sources():
    out = N.clean({"name": "x", "bus": ["SFW", "XYZ", "SFW"], "senders": {"SFW": ["A@b.com"], "XYZ": ["c@d.com"]},
                   "audience": {"SFW": {"sources": ["crm_leads", "panel_members"], "extra_emails": "a@b.com, bad, c@d.co"}}})
    assert out["bus"] == ["SFW"] and out["senders"] == {"SFW": ["a@b.com"]}
    assert out["audience"]["SFW"]["sources"] == ["crm_leads"]
    assert out["audience"]["SFW"]["extra_emails"] == ["a@b.com", "c@d.co"]


def test_subject_is_one_line_even_if_a_name_has_a_newline(world):
    nl = {"subject": "Hi {{name}}\nBcc: x@evil.com", "blocks": []}
    subject, _, _ = N.render(nl, "SFW", {"name": "A\r\nB"})
    assert "\n" not in subject and "\r" not in subject


def test_only_approved_bulk_senders_send(world, monkeypatch):
    """2026-11-26: newsletters go out only from the approved bulk senders."""
    from messaging import deliverability
    monkeypatch.setattr(deliverability, "bulk_senders", lambda: frozenset({"hello@cogentixresearch.com"}))
    gd = world
    nl = nl_doc(gd, status="sending", bus=["COGENTIX"],
                senders={"COGENTIX": ["news@surveyfieldwork.com", "hello@cogentixresearch.com"]},
                audience={"COGENTIX": {"sources": [], "extra_emails": ["a@client.com", "b@client.com"]}})
    N.start(gd, nl, now=NOW, is_suppressed=lambda e: False)
    s = Sender()
    r = N.tick(gd, now=NOW, sender=s, is_suppressed=lambda e: False, cfg=CFG)
    assert {m["from_email"] for m in s.sent} == {"hello@cogentixresearch.com"}
    assert r["sender_blocked"] == ["news@surveyfieldwork.com"]
    assert [m["email"] for m in N.sender_mailboxes(gd)] == ["hello@cogentixresearch.com"]
    assert "news@surveyfieldwork.com is not an approved bulk sender" in N.problems(nl, gd)


def test_google_throttle_requeues_and_rests_the_mailbox(world):
    """2026-11-26: a 429 'User-rate limit exceeded' is not a bad recipient. The row goes back to the
    queue without using an attempt and the mailbox rests until Google's retry time."""
    gd = world
    nl = nl_doc(gd, status="sending", audience={"SFW": {"sources": [], "extra_emails": ["a@c1.com", "b@c2.com"]}})
    N.start(gd, nl, now=NOW, is_suppressed=lambda e: False)
    err = ('Gmail API error: <HttpError 429 when requesting https://gmail.googleapis.com/... returned '
           '"User-rate limit exceeded.  Retry after 2026-11-23T06:20:00.123Z (Mail sending)"')

    class Throttled(Sender):
        def __call__(self, **kw):
            self.sent.append(kw)
            return {"success": False, "error": err}

    s = Throttled()
    r = N.tick(gd, now=NOW, sender=s, is_suppressed=lambda e: False, cfg=CFG)
    assert len(s.sent) == 1 and r["held"] == ["news@surveyfieldwork.com"]          # stops at the first 429
    st = N.stats(gd, nl["_id"])
    assert st["queued"] == 2 and st["failed"] == 0
    assert all(int(x.get("attempts") or 0) == 0 for x in gd(N.DB)[N.RECIPIENTS].find({}))
    N.tick(gd, now=NOW + timedelta(minutes=10), sender=s, is_suppressed=lambda e: False, cfg=CFG)
    assert len(s.sent) == 1                                                          # resting until 06:21
    ok = Sender()
    N.tick(gd, now=NOW + timedelta(minutes=22), sender=ok, is_suppressed=lambda e: False, cfg=CFG)
    assert len(ok.sent) == 2 and N.stats(gd, nl["_id"])["sent"] == 2


def test_rate_limited_detection():
    assert N.rate_limited('HttpError 429 ... "User-rate limit exceeded.  Retry after 2026-11-26T07:46:42.635Z (Mail sending)"')
    assert not N.rate_limited("HttpError 400 Invalid To header")
    assert not N.rate_limited(None)
