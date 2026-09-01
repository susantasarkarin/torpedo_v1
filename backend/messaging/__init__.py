"""
messaging — the single outbound-email chokepoint (TOR-06).

    from messaging import send, SendResult

    result = send(
        to_email="a@example.com",
        subject="...",
        body_text="...",
        transport=my_ses_transport,     # returns a provider message id
        identity="outreach@cogentixresearch.com",
        channel="outreach",
    )
    if not result:
        log.info("not sent: %s (%s)", result.reason, result.category)

Every send is checked against ONE suppression list, counted against a
per-identity budget spanning all channels, and written to ONE log. See
facade.py for why that matters and log.py for what is deliberately not stored.
"""

from .facade import SendBlocked, SendResult, send, sending_enabled, status
from .budget import BudgetExceeded, usage as budget_usage
from .suppression import is_suppressed, suppress, unsuppress, reason_for

__all__ = [
    "send", "SendResult", "SendBlocked", "sending_enabled", "status",
    "BudgetExceeded", "budget_usage",
    "is_suppressed", "suppress", "unsuppress", "reason_for",
]
