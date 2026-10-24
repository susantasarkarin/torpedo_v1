"""Rules that decide whether and how a cold mail goes out (CRM plan 3.11, 3.2.5)."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from messaging import deliverability as d

NOW = datetime(2026, 10, 26, 6, 0)          # Monday 06:00 UTC = 11:30 IST


def test_warmup_starts_at_20_and_grows_20pct_per_week_to_the_cap():
    assert d.warmup_limit(None, NOW) == 20
    assert d.warmup_limit(NOW - timedelta(days=6), NOW) == 20
    assert d.warmup_limit(NOW - timedelta(days=7), NOW) == 24
    assert d.warmup_limit(NOW - timedelta(days=14), NOW) == 28
    assert d.warmup_limit(NOW - timedelta(days=200), NOW) == 80


def test_effective_cap_is_the_tighter_of_env_and_warmup():
    assert d.effective_daily_cap(500, None, NOW) == 20
    assert d.effective_daily_cap(10, None, NOW) == 10


def test_bounce_pause_needs_min_volume_and_rate_above_3pct():
    assert d.bounce_breach(sent=10, bounced=5) is None            # 15 sends < 20 minimum
    assert d.bounce_breach(sent=97, bounced=3) is None            # exactly 3% is allowed
    assert "bounce rate" in d.bounce_breach(sent=96, bounced=4)  # 4% pauses


def test_bu_switch_missing_or_paused_means_closed():
    db = {"outreach_kill_switch": MagicMock()}
    db["outreach_kill_switch"].find_one.return_value = None
    assert d.bu_outreach_open(db, "sfw") is False
    db["outreach_kill_switch"].find_one.return_value = {"_id": "bu:sfw", "paused": True}
    assert d.bu_outreach_open(db, "sfw") is False
    db["outreach_kill_switch"].find_one.return_value = {"_id": "bu:sfw", "paused": False}
    assert d.bu_outreach_open(db, "sfw") is True


def test_send_window_in_recipient_timezone():
    assert d.next_send_time(NOW, "IN") is None                          # 11:30 IST Monday
    nxt = d.next_send_time(NOW, "US")                                    # 02:00 New York
    assert nxt == datetime(2026, 10, 26, 13, 0)                          # 09:00 EDT
    sat = datetime(2026, 10, 31, 6, 0)                                   # Saturday
    assert d.next_send_time(sat, "India").weekday() == 0                 # moved to Monday
    assert d.next_send_time(NOW, None) is None                           # default IST


def test_first_touch_requires_reverify_pass_but_follow_ups_do_not():
    assert d.verified_for_first_touch({}, 1)[0] is False
    assert d.verified_for_first_touch({"reverify": {"outcome": "pending"}}, 1)[0] is False
    assert d.verified_for_first_touch({"reverify": {"outcome": "pass"}}, 1)[0] is True
    assert d.verified_for_first_touch({}, 2)[0] is True


def test_reference_id_is_stable_and_added_once():
    lead = {"lead_id": "696fa389a9271ee50c3d1352"}
    assert d.ref_id(lead) == "L-3D1352"
    s = d.subject_with_ref("Fieldwork in India", "L-3D1352")
    assert s == "Fieldwork in India [L-3D1352]"
    assert d.subject_with_ref(s, "L-3D1352") == s


def test_first_mail_is_plain_text_with_one_link_no_images():
    html = ('<p>Hi Asha,</p><p>We run fieldwork. <a href="https://a.example/x">Our panel</a> and '
            '<a href="https://b.example/y">case study</a>.</p><img src="https://t.example/p.gif" width="1">')
    body = d.first_mail_plain(html, "Indira", "Survey Fieldwork", "https://u.example/unsub?t=1")
    assert "<" not in body and "img" not in body
    main = body.split("--")[0]
    assert d.count_links(main) == 1 and "case study" in main
    assert "https://u.example/unsub" in body               # unsubscribe always present
    assert "Indira" in body and "Survey Fieldwork" in body


def test_monitor_pauses_breaching_mailbox_and_records_null_complaints(monkeypatch, tmp_path):
    from messaging import deliverability_monitor as mon
    dns = tmp_path / "dns.jsonl"
    dns.write_text('{"checked_at": "x", "results": {"surveyfieldwork.com": {"spf": {"pass": false}, '
                   '"dkim": {"pass": false}, "dmarc": {"pass": false}, "pass": false}}}\n')
    monkeypatch.setattr(mon, "DNS_LOG", str(dns))
    monkeypatch.setattr(mon.dlv, "load_config", lambda: dict(d.DEFAULTS))
    mailbox = MagicMock(); mailbox.find.return_value = [{"email": "in@surveyfieldwork.com"}]
    sends = MagicMock(); sends.count_documents.side_effect = [70, 30]      # 30% bounce
    inserted = []
    checks = MagicMock(); checks.insert_one.side_effect = lambda doc: inserted.append(doc)
    paused = []
    monkeypatch.setattr(mon.dlv, "pause_mailbox", lambda g, c, e, r, n: paused.append(e))
    dbs = {"torpedo": {"outreach_sends_v2": sends}, "torpedo_gmail": {"workspace_mailboxes": mailbox},
           "crm_db": {}, "email_automation": {"deliverability_checks": checks}}
    monkeypatch.setattr(mon, "_db", lambda name: dbs[name])
    doc = mon.run_daily_checks(NOW)
    assert paused == ["in@surveyfieldwork.com"]
    assert doc["mailboxes"][0]["bounce_rate_7d"] == 0.3
    assert doc["complaint_rate"] is None
    assert doc["domains"]["surveyfieldwork.com"]["all_pass"] is False
    assert inserted
