"""
PER-ENTITY CAMPAIGN CONFIGURATION
=================================

One config object per business entity. Loaded from environment, never
hardcoded in the mailer.

WHAT THIS REPLACES
------------------
outreach_config exposed ONE sender identity and ONE cap pair for all three
brands:

    SENDER_EMAIL, SENDER_NAME, SENDER_POSTAL_ADDRESS, UNSUBSCRIBE_BASE_URL
    SEND_DAILY_CAP = 200, SEND_HOURLY_CAP = 25

So the three entities were indistinguishable to a recipient, shared one
reputation, and one entity exhausting the cap starved the others.

SELECTION IS BY ARBITRATED BUCKET, NOT ICP MEMBERSHIP
-----------------------------------------------------
Each campaign runs over lead_interests whose ARBITRATION-WINNING bucket equals
that entity's bucket. Selecting by ICP membership is what let one person land
in three campaigns: several ICPs may legitimately want the same human, and
only the arbitrated winner may send.

CAPS ARE ENFORCED PER ENTITY *AND* GLOBALLY
-------------------------------------------
Per entity so one brand cannot consume another's allowance. Globally because
while the entities share a sending domain, the combined volume is what the
receiving providers actually see — three brands each politely under their own
cap can still add up to a spike from one IP.

UNSUBSCRIBE IS BRANDED PER ENTITY, GLOBAL IN EFFECT
---------------------------------------------------
The link may carry the entity so the recipient sees the brand they know. What
it writes is global suppression on the PERSON, suppressing all three. Branding
the link is presentation; scoping the effect would be the original bug.

SAFETY POSTURE IS PRESERVED, NOT REPLACED
-----------------------------------------
Dry-run remains the default, sending still requires an explicit --send, a
placeholder pitch or missing postal address or missing unsubscribe URL still
refuses outright, bodies are still never logged, spacing is still randomized.
This module adds per-entity resolution underneath those rules; it does not
relax any of them.

Configuration (env, per entity, suffixed with the entity key):
    OUTREACH_SFW_SENDING_DOMAIN, OUTREACH_SFW_FROM_ADDRESS, ...
    OUTREACH_COGENTIX_RESEARCH_SENDING_DOMAIN, ...
    OUTREACH_BIM_SENDING_DOMAIN, ...
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from .outreach_config import BUCKETS, PITCH_PLACEHOLDER
except ImportError:  # pragma: no cover - direct execution
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from leads.outreach_config import BUCKETS, PITCH_PLACEHOLDER


# Global ceiling across ALL entities combined. Not the sum of the per-entity
# caps — the receiving providers see the total, so the total is what is capped.
GLOBAL_DAILY_CAP = int(os.getenv("OUTREACH_GLOBAL_DAILY_CAP", "200"))
GLOBAL_HOURLY_CAP = int(os.getenv("OUTREACH_GLOBAL_HOURLY_CAP", "25"))


def _env(entity: str, key: str, default: str = "") -> str:
    return os.getenv(f"OUTREACH_{entity}_{key}", default).strip()


def _env_int(entity: str, key: str, default: int) -> int:
    try:
        return int(_env(entity, key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(entity: str, key: str, default: bool) -> bool:
    return _env(entity, key, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass
class CampaignConfig:
    entity: str
    display_name: str
    bucket: str
    sending_domain: str = ""
    from_address: str = ""
    reply_to: str = ""
    postal_address: str = ""
    unsubscribe_endpoint: str = ""
    email_template_set: str = ""
    pitch_text: str = ""
    hourly_cap: int = 0
    daily_cap: int = 0
    send_window: Tuple[int, int] = (9, 17)
    send_window_tz: str = "UTC"
    min_confidence_threshold: float = 0.7
    active: bool = False

    # -- blockers ---------------------------------------------------------

    def send_blockers(self) -> List[str]:
        """
        Everything preventing this entity from sending. Empty means clear.

        Same refusals as the single-entity mailer, resolved per entity so one
        brand's missing postal address cannot be masked by another's being set.
        """
        blockers: List[str] = []
        if not self.active:
            blockers.append(f"{self.entity}: campaign is not active (kill switch)")
        if not self.pitch_text.strip() or PITCH_PLACEHOLDER in self.pitch_text:
            blockers.append(f"{self.entity}: pitch copy is still a placeholder")
        if not self.postal_address.strip():
            blockers.append(f"{self.entity}: postal address unset (required by CAN-SPAM)")
        if not self.unsubscribe_endpoint.strip():
            blockers.append(f"{self.entity}: unsubscribe URL unset (unsubscribe must work)")
        if not self.from_address.strip():
            blockers.append(f"{self.entity}: from_address unset")
        if not self.sending_domain.strip():
            blockers.append(f"{self.entity}: sending_domain unset")
        return blockers

    @property
    def may_send(self) -> bool:
        return not self.send_blockers()

    def unsubscribe_url(self, token: str) -> str:
        """
        Branded per entity, GLOBAL in effect.

        The entity appears in the link so the recipient sees the brand they
        recognise. What the endpoint writes is suppression on the PERSON,
        which suppresses all three. Scoping the effect per entity would be the
        original bug wearing a nicer URL.
        """
        base = self.unsubscribe_endpoint.rstrip("/")
        return f"{base}/{token}?e={self.entity.lower()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity": self.entity,
            "display_name": self.display_name,
            "bucket": self.bucket,
            "sending_domain": self.sending_domain,
            "from_address": self.from_address,
            "reply_to": self.reply_to,
            "postal_address": self.postal_address,
            "unsubscribe_endpoint": self.unsubscribe_endpoint,
            "email_template_set": self.email_template_set,
            "hourly_cap": self.hourly_cap,
            "daily_cap": self.daily_cap,
            "send_window": list(self.send_window),
            "send_window_tz": self.send_window_tz,
            "min_confidence_threshold": self.min_confidence_threshold,
            "active": self.active,
            "may_send": self.may_send,
            "blockers": self.send_blockers(),
        }


def load(entity: str) -> CampaignConfig:
    """Build one entity's config from environment + its bucket metadata."""
    bucket_cfg = BUCKETS.get(entity, {})
    window_raw = _env(entity, "SEND_WINDOW", "9-17")
    try:
        start, end = (int(x) for x in window_raw.split("-", 1))
    except (TypeError, ValueError):
        start, end = 9, 17

    return CampaignConfig(
        entity=entity,
        display_name=bucket_cfg.get("label", entity),
        bucket=entity,
        sending_domain=_env(entity, "SENDING_DOMAIN"),
        from_address=_env(entity, "FROM_ADDRESS"),
        reply_to=_env(entity, "REPLY_TO") or _env(entity, "FROM_ADDRESS"),
        postal_address=_env(entity, "POSTAL_ADDRESS"),
        unsubscribe_endpoint=_env(entity, "UNSUBSCRIBE_URL"),
        email_template_set=_env(entity, "TEMPLATE_SET", bucket_cfg.get("storage_dir", "")),
        pitch_text=_env(entity, "PITCH") or bucket_cfg.get("pitch", ""),
        hourly_cap=_env_int(entity, "HOURLY_CAP", 10),
        daily_cap=_env_int(entity, "DAILY_CAP", 60),
        send_window=(start, end),
        send_window_tz=_env(entity, "SEND_WINDOW_TZ", "UTC"),
        min_confidence_threshold=float(_env(entity, "MIN_CONFIDENCE", "0.7") or 0.7),
        # Kill switch defaults OFF. An entity sends only when someone turns it
        # on deliberately — the whole remediation exists because sending
        # happened that nobody chose.
        active=_env_bool(entity, "ACTIVE", False),
    )


def load_all() -> Dict[str, CampaignConfig]:
    return {entity: load(entity) for entity in BUCKETS}


# ---------------------------------------------------------------------------
# Domain separation checks
# ---------------------------------------------------------------------------

def shared_domain_conflicts(configs: Dict[str, CampaignConfig] = None) -> List[str]:
    """
    Entities sharing a sending domain.

    Reputation attaches to the domain, so while these are shared one entity's
    bounces damage the others and a per-entity circuit breaker cannot isolate
    the damage. Reported rather than auto-corrected: silently switching an
    entity to a fresh domain would put a cold domain under current volume,
    which lands in spam. Separation needs a warm-up plan.
    """
    configs = configs or load_all()
    by_domain: Dict[str, List[str]] = {}
    for cfg in configs.values():
        if cfg.sending_domain:
            by_domain.setdefault(cfg.sending_domain.lower(), []).append(cfg.entity)
    return [
        f"{domain} is shared by {', '.join(sorted(entities))} — reputation is "
        f"pooled; separate with a warm-up plan, never abruptly"
        for domain, entities in by_domain.items() if len(entities) > 1
    ]


def distinct_postal_addresses(configs: Dict[str, CampaignConfig] = None) -> List[str]:
    """
    CAN-SPAM requires a valid physical address for the sender. Two entities
    presenting the same address are either one business wearing two names, or
    a copy-paste error. Both are worth surfacing.
    """
    configs = configs or load_all()
    by_addr: Dict[str, List[str]] = {}
    for cfg in configs.values():
        if cfg.postal_address:
            by_addr.setdefault(cfg.postal_address.strip().lower(), []).append(cfg.entity)
    return [f"postal address shared by {', '.join(sorted(entities))}"
            for entities in by_addr.values() if len(entities) > 1]


# ---------------------------------------------------------------------------
# Cap arithmetic — per entity AND global
# ---------------------------------------------------------------------------

def remaining_allowance(
    entity: str,
    sent_today: int,
    sent_this_hour: int,
    global_sent_today: int,
    global_sent_this_hour: int,
    configs: Dict[str, CampaignConfig] = None,
) -> Dict[str, Any]:
    """
    How many sends this entity may still make, honouring BOTH its own caps and
    the global ceiling. The binding constraint is whichever is smaller.
    """
    configs = configs or load_all()
    cfg = configs.get(entity) or load(entity)

    entity_daily = max(0, cfg.daily_cap - sent_today)
    entity_hourly = max(0, cfg.hourly_cap - sent_this_hour)
    global_daily = max(0, GLOBAL_DAILY_CAP - global_sent_today)
    global_hourly = max(0, GLOBAL_HOURLY_CAP - global_sent_this_hour)

    allowed = min(entity_daily, entity_hourly, global_daily, global_hourly)
    binding = min(
        (entity_daily, "entity_daily"), (entity_hourly, "entity_hourly"),
        (global_daily, "global_daily"), (global_hourly, "global_hourly"),
        key=lambda pair: pair[0],
    )[1]
    return {"entity": entity, "allowed": allowed, "binding_constraint": binding,
            "entity_daily_remaining": entity_daily,
            "entity_hourly_remaining": entity_hourly,
            "global_daily_remaining": global_daily,
            "global_hourly_remaining": global_hourly}


def render_status() -> str:
    configs = load_all()
    lines = ["", "=" * 68, "  PER-ENTITY CAMPAIGN CONFIG", "=" * 68]
    for entity, cfg in configs.items():
        lines.append(f"  {cfg.display_name} ({entity})   "
                     f"{'SENDABLE' if cfg.may_send else 'BLOCKED'}")
        lines.append(f"    domain {cfg.sending_domain or '(unset)':<28} "
                     f"caps {cfg.hourly_cap}/h {cfg.daily_cap}/d")
        for b in cfg.send_blockers():
            lines.append(f"    - {b}")
    for warning in shared_domain_conflicts(configs) + distinct_postal_addresses(configs):
        lines.append(f"  WARNING: {warning}")
    lines += [f"  global ceiling: {GLOBAL_HOURLY_CAP}/h  {GLOBAL_DAILY_CAP}/d",
              "=" * 68, ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_status())
