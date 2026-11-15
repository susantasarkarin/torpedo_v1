"""One config store for everything tunable (CRM plan 3.1 "Config, not code").

torpedo_settings.config holds one document per section ({_id: <section>});
SECTIONS below holds each section's defaults, which are also the documented
contract. get() = defaults overlaid with the stored values; set() accepts only
known keys, writes, and audit-logs the before/after.
"""
import copy
import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _deliverability():
    from messaging.deliverability import DEFAULTS
    return DEFAULTS


def _pricing():
    from pricing.engine import DEFAULTS
    return DEFAULTS


def _bu():
    try:
        from leads.outreach_config import BUCKETS
        return {"descriptions": {
            {"SFW": "SFW", "COGENTIX_RESEARCH": "COGENTIX", "BIM": "BIM"}.get(k, k):
                {"label": v.get("label"), "what_we_sell": v.get("description"), "ideal_buyer": v.get("ideal_buyer")}
            for k, v in BUCKETS.items()}}
    except Exception:
        return {"descriptions": {}}


SECTIONS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "deliverability": _deliverability,
    "pricing": _pricing,
    "bu": _bu,
    "ladder": lambda: __import__("platform_core.ladder", fromlist=["DEFAULTS"]).DEFAULTS,   # rules -> Haiku -> Sonnet (the "qwen" section and ladder.replace_local_model were retired 2026-11-15; stale keys in torpedo_settings.config are ignored)
    "mail": lambda: {
        "max_automated_per_contact_per_day": 1,
        "throttled_channels": ["outreach", "sales_outreach", "campaign", "nurture", "reengagement",
                               "finance", "ops", "rfq", "service_delivery"],
        "working_hours_ist": [10, 18],
    },
    "review_queue": lambda: {"sla_working_hours": 4, "archive_older_than_days": 90},
    "reengagement": lambda: __import__("reengage.rules", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.10
    "service_delivery": lambda: __import__("service_delivery.rules", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.13
    "web": lambda: __import__("web_tracking.rules", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.12
    "marketing": lambda: __import__("marketing.config", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.15 / MARKETING_PLAN 4.3
    "kpi": lambda: __import__("kpi.definitions", fromlist=["config_defaults"]).config_defaults(),   # 3.14
    "accounting": lambda: __import__("accounting.invoicing", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.9
    "panel": lambda: __import__("panel_rules.rules", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.7b
    "vendors": lambda: __import__("vendors.bids", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.7a
    "ops": lambda: __import__("ops.lifecycle", fromlist=["DEFAULTS"]).DEFAULTS,   # 3.6
    "rfq": lambda: {         # 3.4 / 3.5
        "mode": "shadow",                    # shadow: decisions only; live (owner): stamp RFQs + queue drafts
        "batch": 5,
        "lookback_days": 60,
        "default_methodology": "CAWI",
        "critical_fields": ["n", "loi_minutes", "country"],
        "client_defaults_seed": [            # crm_db.client_defaults rows take precedence
            {"match": "hansa", "defaults": {"ir_percent": 60, "country": "IN"}},
        ],
        "weighting": "completes",            # the price; recency is stored alongside
        "cpi_bounds_usd": {"min": None, "max": None},   # owner to set; unset = no bound check
        "client_history_tolerance": 0.4,     # > 40% from this client's recent median -> review
    },
    "entities": lambda: {    # owner enters these; blank blocks invoicing for that entity (3.9)
        "SFW": {"legal_name": "", "gstin": "", "pan": "", "address": "", "invoice_prefix": "SF", "bank_accounts": []},
        "COGENTIX": {"legal_name": "", "gstin": "", "pan": "", "address": "", "invoice_prefix": "CR", "bank_accounts": []},
        "BIM": {"legal_name": "", "gstin": "", "pan": "", "address": "", "invoice_prefix": "BIM", "bank_accounts": []},
    },
}


def _db():
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database("torpedo_settings")


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def defaults(section: str) -> Dict[str, Any]:
    if section not in SECTIONS:
        raise KeyError(f"unknown config section {section!r}")
    return copy.deepcopy(SECTIONS[section]())


def get(section: str, db=None) -> Dict[str, Any]:
    base = defaults(section)
    try:
        doc = (db or _db())["config"].find_one({"_id": section}) or {}
    except Exception:
        logger.warning("config section %s unreadable; using defaults", section, exc_info=True)
        return base
    doc.pop("_id", None)
    doc.pop("updated_at", None)
    doc.pop("updated_by", None)
    return _merge(base, {k: v for k, v in doc.items() if k in base})


def set(section: str, values: Dict[str, Any], actor: str, db=None, audit_db=None) -> Dict[str, Any]:
    """Write known keys only. Returns the effective section after the change."""
    base = defaults(section)
    unknown = sorted(k for k in values if k not in base)
    if unknown:
        raise ValueError(f"unknown keys for {section}: {', '.join(unknown)}")
    col = (db or _db())["config"]
    before = col.find_one({"_id": section}) or {}
    col.update_one({"_id": section}, {"$set": {**values, "updated_at": datetime.utcnow(), "updated_by": actor}},
                   upsert=True)
    try:
        from .audit import log_action
        log_action(actor=actor, action="update", entity_type="config", entity_id=section,
                   changes={k: {"before": before.get(k), "after": v} for k, v in values.items()},
                   reason="config change", db=audit_db)
    except Exception:
        logger.exception("config audit failed for %s", section)
    return get(section, db)
