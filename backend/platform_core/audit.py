"""Audit log for every automatic action (CRM plan 3.1): mail sent, status
changed, record linked, price calculated, ledger posted. One collection,
crm_db.audit_log, same shape as audit.AuditLogger so both readers work."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _db():
    try:
        from database import get_database
    except ImportError:
        from ..database import get_database
    return get_database("crm_db")


def log_action(*, actor: str, action: str, entity_type: str, entity_id: str,
               reason: str = "", source: Optional[str] = None,
               changes: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None,
               db=None) -> Optional[str]:
    """actor: 'system' or a user id. Never raises: an audit failure must not
    break the action it records (it is logged loudly instead)."""
    doc = {"timestamp": datetime.utcnow(), "user_id": actor, "action": action,
           "entity_type": entity_type, "entity_id": str(entity_id), "changes": changes,
           "metadata": {**(metadata or {}), "reason": reason, "source": source}}
    try:
        return str((db or _db())["audit_log"].insert_one(doc).inserted_id)
    except Exception:
        logger.exception("AUDIT WRITE FAILED: %s %s/%s", action, entity_type, entity_id)
        return None
