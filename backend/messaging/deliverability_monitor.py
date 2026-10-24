"""Daily deliverability check (CRM plan 3.11.12-15), one doc per run in
email_automation.deliverability_checks:

  per mailbox   7-day outreach sends / bounces / bounce rate, warm-up start,
                outreach_paused; a breach pauses the mailbox and alerts
  per domain    SPF / DKIM / DMARC verdicts from the 08:30 IST DNS check log
                (/var/log/campaign_platform/dns_auth_check.jsonl)
  complaints    not available until Google Postmaster Tools is connected
                (recorded as null, never as 0)
  seed test     needs seed inboxes in config `seed_addresses`; skipped if empty

Client, finance and project mail are never paused by this job: only the
mailbox's outreach flag is set.
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import deliverability as dlv

logger = logging.getLogger(__name__)
DNS_LOG = os.getenv("AUTH_CHECK_LOG", "/var/log/campaign_platform/dns_auth_check.jsonl")


def _db(name):
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database(name)


def latest_dns(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = path or DNS_LOG
    try:
        with open(path) as f:
            lines = [l for l in f if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("could not read %s", path)
        return None


def run_daily_checks(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    cfg = dlv.load_config()
    torpedo, gmail, crm = _db("torpedo"), _db("torpedo_gmail"), _db("crm_db")
    mailboxes: List[Dict[str, Any]] = []
    for mb in gmail["workspace_mailboxes"].find({"is_active": True},
                                                {"email": 1, "warmup_started_at": 1, "outreach_paused": 1}):
        email = mb.get("email")
        if not email:
            continue
        sent, bounced = dlv.mailbox_bounce_stats(torpedo, email, now, cfg)
        total = sent + bounced
        row = {"mailbox": email, "sent_7d": sent, "bounced_7d": bounced,
               "bounce_rate_7d": round(bounced / total, 4) if total else None,
               "daily_cap_today": dlv.warmup_limit(mb.get("warmup_started_at"), now, cfg),
               "warmup_started_at": mb.get("warmup_started_at"),
               "outreach_paused": bool(mb.get("outreach_paused")), "action": None}
        breach = dlv.bounce_breach(sent, bounced, cfg)
        if breach and not mb.get("outreach_paused"):
            dlv.pause_mailbox(gmail, crm, email, breach, now)
            row.update(outreach_paused=True, action=f"paused: {breach}")
        mailboxes.append(row)

    dns = latest_dns()
    domains = {d: {k: r[k]["pass"] for k in ("spf", "dkim", "dmarc")} | {"all_pass": r["pass"]}
               for d, r in ((dns or {}).get("results") or {}).items()}
    seeds = cfg.get("seed_addresses") if isinstance(cfg.get("seed_addresses"), list) else []
    doc = {"checked_at": now, "mailboxes": mailboxes,
           "domains": domains, "dns_checked_at": (dns or {}).get("checked_at"),
           "complaint_rate": None, "complaint_source": "Google Postmaster Tools not connected",
           "seed_test": "skipped: no seed_addresses configured" if not seeds else "pending",
           "thresholds": {k: cfg[k] for k in ("bounce_pause_rate", "bounce_min_sends", "complaint_stop_rate",
                                             "daily_cap_per_mailbox", "warmup_start_per_day")}}
    _db("email_automation")["deliverability_checks"].insert_one(dict(doc))
    logger.info("deliverability check: %d mailboxes, %d paused now, domains passing: %s",
                len(mailboxes), sum(1 for m in mailboxes if m["action"]),
                [d for d, v in domains.items() if v.get("all_pass")])
    return doc
