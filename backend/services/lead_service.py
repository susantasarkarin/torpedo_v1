"""
Lead Service
============
Business logic for lead lifecycle operations.

Extracted from routers/legacy_leads.py (Phase 10).

Note: CSV import delegates to leads.canonical_ingestion — that is already
a service layer. The service here handles the cross-collection move operation.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

logger = logging.getLogger(__name__)


def move_lead_to_contacts(
    lead_id: str,
    stage: str,
    leads_col: Any,
    contacts_col: Any,
) -> Optional[Dict[str, Any]]:
    """
    Atomically (at app level) move a lead to the contacts collection.

    Steps:
      1. Fetch lead document.
      2. Copy fields to contacts with new stage + timestamps.
      3. Hard-delete from leads.

    Returns the new contact dict (with _id as string), or None if not found.

    WARNING: This is not a true atomic operation — a crash between step 2 and
    step 3 would leave a duplicate. A future improvement is a MongoDB
    multi-document transaction here.
    """
    lead = leads_col.find_one({"_id": ObjectId(lead_id)})
    if lead is None:
        return None

    contact_data = {k: v for k, v in lead.items() if k != "_id"}
    contact_data["stage"] = stage
    contact_data["movedFromLeadAt"] = datetime.utcnow()
    contact_data["createdAt"] = lead.get("createdAt", datetime.utcnow())
    contact_data["updatedAt"] = datetime.utcnow()

    result = contacts_col.insert_one(contact_data)
    contact_data["_id"] = str(result.inserted_id)

    leads_col.delete_one({"_id": ObjectId(lead_id)})
    logger.info("Lead %s moved to contacts (stage=%s, contact_id=%s)", lead_id, stage, contact_data["_id"])
    return contact_data
