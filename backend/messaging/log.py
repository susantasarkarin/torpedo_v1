"""
The unified send log.

Three send-log collections existed — `outreach_send_logs`, `panel_invitation_log`
and `send_logs` — so "how much mail did we send today" had three partial
answers and no total. The budget in outreach_mailer counted one of them and
believed it (TOR-06).

Everything that goes through the facade writes here:
`email_automation.email_send_log`.

Bodies are NEVER stored. The outreach mailer got this right and the reason
holds generally: the log is read during incident review by people who have no
business reading customer correspondence, it is the largest thing we would be
storing, and it is the part with retention obligations attached. Subject lines
are kept — they are needed to identify a campaign and are not the message.

The legacy collections are left alone. They are still written by the senders
that have not been migrated yet, and they are the historical record for
everything sent before this existed.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DB_NAME = "email_automation"
COLLECTION = "email_send_log"


def _col():
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database(DB_NAME)[COLLECTION]


def record(identity: str, to_email: str, subject: Optional[str],
           channel: str, status: str,
           provider_message_id: Optional[str] = None,
           error: Optional[str] = None,
           transactional: bool = False,
           metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Write one send-attempt record. Returns the inserted id.

    Failures are logged, never raised: losing a log line must not turn a
    delivered email into an exception the caller retries — that is how you send
    twice.
    """
    doc = {
        "identity": identity,
        "to_email": (to_email or "").strip().lower(),
        "subject": subject,
        "channel": channel,          # outreach | panel_invite | campaign | transactional | ...
        "status": status,            # sent | failed | suppressed | budget_blocked
        "provider_message_id": provider_message_id,
        "error": (error or None) and str(error)[:500],
        "transactional": bool(transactional),
        "metadata": metadata or {},
        "sent_at": datetime.utcnow(),
    }
    try:
        return str(_col().insert_one(doc).inserted_id)
    except Exception:
        logger.exception("failed to write send log for %s", to_email)
        return None


def count_sends(identity: Optional[str] = None,
                since: Optional[datetime] = None) -> int:
    """
    Count SUCCESSFUL sends. Suppressed and budget-blocked attempts are recorded
    for visibility but must not consume budget — they never reached a provider.
    """
    query: Dict[str, Any] = {"status": "sent"}
    if identity:
        query["identity"] = identity
    if since:
        query["sent_at"] = {"$gte": since}
    try:
        return _col().count_documents(query)
    except Exception:
        # Fail CLOSED: an uncountable log means an unknown quota. Reporting a
        # huge number blocks sending, which is the safe direction — the
        # alternative is reporting 0 and sending without any cap at all.
        logger.error("send-log count failed; reporting budget as exhausted",
                     exc_info=True)
        return 10 ** 9


def recent(limit: int = 100, identity: Optional[str] = None) -> list:
    query = {"identity": identity} if identity else {}
    try:
        return [
            {k: v for k, v in d.items() if k != "_id"}
            for d in _col().find(query).sort("sent_at", -1).limit(limit)
        ]
    except Exception:
        logger.warning("send-log read failed", exc_info=True)
        return []


def ensure_indexes() -> None:
    try:
        col = _col()
        col.create_index([("identity", 1), ("status", 1), ("sent_at", -1)],
                         background=True)
        col.create_index("to_email", background=True)
        col.create_index("sent_at", background=True)
    except Exception:
        logger.warning("send-log index creation failed", exc_info=True)
