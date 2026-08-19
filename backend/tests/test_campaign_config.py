"""
PHASE 3 — per-entity campaign configuration

The three entities shared one sender identity and one cap pair. These pin the
separation, and pin that none of the existing safety refusals were relaxed to
get it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leads import campaign_config as cc  # noqa: E402
from leads.outreach_config import PITCH_PLACEHOLDER  # noqa: E402


ENTITIES = ("SFW", "COGENTIX_RESEARCH", "BIM")


def _configure(monkeypatch, entity, **overrides):
    defaults = {
        "SENDING_DOMAIN": f"{entity.lower()}.example.com",
        "FROM_ADDRESS": f"hello@{entity.lower()}.example.com",
        "POSTAL_ADDRESS": f"{entity} House, {entity} Street",
        "UNSUBSCRIBE_URL": f"https://{entity.lower()}.example.com/u",
        "PITCH": f"real pitch copy for {entity}",
        "ACTIVE": "1",
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setenv(f"OUTREACH_{entity}_{key}", str(value))


# ===========================================================================
# Separation
# ===========================================================================

def test_every_entity_has_its_own_config():
    configs = cc.load_all()
    assert set(configs) == set(ENTITIES)


def test_each_entity_resolves_its_own_sending_identity(monkeypatch):
    for e in ENTITIES:
        _configure(monkeypatch, e)
    configs = cc.load_all()
    domains = {c.sending_domain for c in configs.values()}
    froms = {c.from_address for c in configs.values()}
    assert len(domains) == 3, "entities must not share a sending domain"
    assert len(froms) == 3


def test_shared_sending_domain_is_reported_not_auto_corrected(monkeypatch):
    """
    Silently switching an entity to a fresh domain puts a COLD domain under
    current volume, which lands in spam. Separation needs a warm-up plan, so
    this reports and leaves the decision to a human.
    """
    for e in ENTITIES:
        _configure(monkeypatch, e, SENDING_DOMAIN="shared.example.com")
    conflicts = cc.shared_domain_conflicts()
    assert len(conflicts) == 1
    assert "warm-up" in conflicts[0]
    # and it has NOT rewritten anything
    assert cc.load("SFW").sending_domain == "shared.example.com"


def test_duplicate_postal_addresses_are_flagged(monkeypatch):
    for e in ENTITIES:
        _configure(monkeypatch, e, POSTAL_ADDRESS="One Shared Street")
    assert cc.distinct_postal_addresses(), "CAN-SPAM address reuse must surface"


# ===========================================================================
# Safety posture preserved — none of these may regress
# ===========================================================================

def test_kill_switch_defaults_off(monkeypatch):
    for key in list(os.environ):
        if key.startswith("OUTREACH_SFW_"):
            monkeypatch.delenv(key, raising=False)
    cfg = cc.load("SFW")
    assert cfg.active is False, (
        "an entity must send only when someone turns it on deliberately")
    assert not cfg.may_send


def test_placeholder_pitch_blocks_sending(monkeypatch):
    _configure(monkeypatch, "SFW", PITCH=PITCH_PLACEHOLDER)
    assert any("placeholder" in b for b in cc.load("SFW").send_blockers())


def test_missing_postal_address_blocks_sending(monkeypatch):
    _configure(monkeypatch, "SFW", POSTAL_ADDRESS="")
    assert any("CAN-SPAM" in b for b in cc.load("SFW").send_blockers())


def test_missing_unsubscribe_url_blocks_sending(monkeypatch):
    _configure(monkeypatch, "SFW", UNSUBSCRIBE_URL="")
    assert any("unsubscribe" in b for b in cc.load("SFW").send_blockers())


def test_a_fully_configured_active_entity_may_send(monkeypatch):
    _configure(monkeypatch, "SFW")
    cfg = cc.load("SFW")
    assert cfg.may_send, cfg.send_blockers()


def test_one_entity_being_blocked_does_not_mask_another(monkeypatch):
    """
    Resolved per entity. With a single shared identity, one brand's missing
    postal address was invisible if another brand had one set.
    """
    _configure(monkeypatch, "SFW")
    _configure(monkeypatch, "BIM", POSTAL_ADDRESS="")
    assert cc.load("SFW").may_send
    assert not cc.load("BIM").may_send


# ===========================================================================
# Unsubscribe — branded per entity, global in effect
# ===========================================================================

def test_unsubscribe_link_is_branded_per_entity(monkeypatch):
    for e in ENTITIES:
        _configure(monkeypatch, e)
    urls = {cc.load(e).unsubscribe_url("tok123") for e in ENTITIES}
    assert len(urls) == 3, "each brand shows the recipient a link they recognise"
    assert all("tok123" in u for u in urls), "the person token must survive"


def test_unsubscribe_token_is_the_same_across_entities(monkeypatch):
    """
    Branding is presentation; the token identifies the PERSON. The same token
    on every brand's link is what makes one unsubscribe suppress all three.
    """
    for e in ENTITIES:
        _configure(monkeypatch, e)
    assert all("tok123" in cc.load(e).unsubscribe_url("tok123") for e in ENTITIES)


# ===========================================================================
# Caps — per entity AND global
# ===========================================================================

def test_entity_cap_binds_when_lower(monkeypatch):
    _configure(monkeypatch, "SFW", DAILY_CAP="10")
    r = cc.remaining_allowance("SFW", sent_today=8, sent_this_hour=0,
                               global_sent_today=0, global_sent_this_hour=0)
    assert r["allowed"] == 2
    assert r["binding_constraint"] == "entity_daily"


def test_global_ceiling_binds_even_when_entity_has_headroom(monkeypatch):
    """
    Three brands each politely under their own cap still add up to one spike
    from one IP. The receiving providers see the total.
    """
    _configure(monkeypatch, "SFW", DAILY_CAP="1000", HOURLY_CAP="1000")
    r = cc.remaining_allowance("SFW", sent_today=0, sent_this_hour=0,
                               global_sent_today=cc.GLOBAL_DAILY_CAP - 3,
                               global_sent_this_hour=0)
    assert r["allowed"] == 3
    assert r["binding_constraint"] == "global_daily"


def test_one_entity_cannot_consume_anothers_allowance(monkeypatch):
    for e in ENTITIES:
        _configure(monkeypatch, e, DAILY_CAP="50", HOURLY_CAP="50")
    exhausted = cc.remaining_allowance("SFW", sent_today=50, sent_this_hour=0,
                                       global_sent_today=50, global_sent_this_hour=0)
    untouched = cc.remaining_allowance("BIM", sent_today=0, sent_this_hour=0,
                                       global_sent_today=50, global_sent_this_hour=0)
    assert exhausted["allowed"] == 0
    assert untouched["allowed"] > 0, "BIM starved by SFW exhausting its own cap"


def test_allowance_never_goes_negative(monkeypatch):
    _configure(monkeypatch, "SFW", DAILY_CAP="10")
    r = cc.remaining_allowance("SFW", sent_today=999, sent_this_hour=999,
                               global_sent_today=999, global_sent_this_hour=999)
    assert r["allowed"] == 0


def test_status_render_does_not_leak_pitch_or_bodies(monkeypatch):
    """Bodies and copy are never logged. The status view is not an exception."""
    _configure(monkeypatch, "SFW", PITCH="SECRET PITCH COPY")
    assert "SECRET PITCH COPY" not in cc.render_status()
