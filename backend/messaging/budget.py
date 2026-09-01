"""
Global send budget — one place that knows how much mail has gone out.

Thirteen modules can put mail on the wire. Caps existed in exactly one of them
(`leads/outreach_mailer.py`), and it computed them by counting a single
collection — `outreach_send_logs` — so the panel senders, the campaign senders
and the Gmail services were all invisible to it. Nothing anywhere saw total
volume. That is the shape of the August over-send incident: past the Gmail
2,000/day cap, 45% bounce rate (TOR-06).

Budgets are enforced PER SENDING IDENTITY, because that is what the provider
rate-limits and what reputation attaches to — not per campaign, not per module.

Counts come from the unified send log (`messaging.log`), so every channel's
volume lands in the same ledger and the cap actually means something.

  provider limits, for calibration:
    Gmail / Workspace  2,000 recipients/day per account (hard, enforced by Google)
    SES                per-account daily quota, visible via GetSendQuota

Defaults sit well under those so a burst cannot walk into a provider-side
block. Override per identity with SEND_BUDGET_<IDENTITY>_DAILY, or globally
with SEND_BUDGET_DEFAULT_DAILY / _HOURLY.
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_DAILY = int(os.getenv("SEND_BUDGET_DEFAULT_DAILY", "1500"))
DEFAULT_HOURLY = int(os.getenv("SEND_BUDGET_DEFAULT_HOURLY", "200"))

# Reserve held back from the daily budget for transactional mail — password
# resets, survey invitations someone is waiting on. Bulk sending stops at
# (daily - reserve) so a campaign cannot consume the quota a real user needs.
TRANSACTIONAL_RESERVE = int(os.getenv("SEND_BUDGET_TRANSACTIONAL_RESERVE", "150"))

_ENV_SAFE = re.compile(r"[^A-Z0-9]+")


class BudgetExceeded(Exception):
    """Raised when a send would exceed the identity's budget."""

    def __init__(self, identity: str, window: str, used: int, limit: int):
        self.identity, self.window, self.used, self.limit = identity, window, used, limit
        super().__init__(
            f"send budget exceeded for {identity}: {used}/{limit} in the last {window}"
        )


def _limits_for(identity: str) -> Dict[str, int]:
    key = _ENV_SAFE.sub("_", (identity or "default").upper()).strip("_")
    return {
        "daily": int(os.getenv(f"SEND_BUDGET_{key}_DAILY", DEFAULT_DAILY)),
        "hourly": int(os.getenv(f"SEND_BUDGET_{key}_HOURLY", DEFAULT_HOURLY)),
    }


def usage(identity: str) -> Dict[str, Any]:
    """Sends attributed to this identity in the trailing day and hour."""
    from .log import count_sends

    now = datetime.utcnow()
    limits = _limits_for(identity)
    day = count_sends(identity, since=now - timedelta(days=1))
    hour = count_sends(identity, since=now - timedelta(hours=1))
    return {
        "identity": identity,
        "sent_today": day,
        "daily_limit": limits["daily"],
        "daily_remaining": max(0, limits["daily"] - day),
        "sent_this_hour": hour,
        "hourly_limit": limits["hourly"],
        "hourly_remaining": max(0, limits["hourly"] - hour),
        "transactional_reserve": TRANSACTIONAL_RESERVE,
        "bulk_remaining": max(0, limits["daily"] - TRANSACTIONAL_RESERVE - day),
    }


def check(identity: str, transactional: bool = False) -> None:
    """
    Raise BudgetExceeded if one more send would break the budget.

    Transactional mail may draw on the reserve; bulk mail may not. That is the
    whole point of the reserve — a campaign that fills the daily quota must not
    stop a password reset from going out.
    """
    state = usage(identity)
    if state["hourly_remaining"] <= 0:
        raise BudgetExceeded(identity, "hour",
                             state["sent_this_hour"], state["hourly_limit"])
    if transactional:
        if state["daily_remaining"] <= 0:
            raise BudgetExceeded(identity, "day",
                                 state["sent_today"], state["daily_limit"])
    elif state["bulk_remaining"] <= 0:
        raise BudgetExceeded(
            identity, "day (bulk, reserve withheld)",
            state["sent_today"], state["daily_limit"] - TRANSACTIONAL_RESERVE)


def allows(identity: str, transactional: bool = False) -> Optional[str]:
    """Non-raising form: returns the blocking reason, or None when clear."""
    try:
        check(identity, transactional=transactional)
        return None
    except BudgetExceeded as exc:
        return str(exc)
