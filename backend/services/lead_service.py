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

try:
    from repositories import leads_repo
except ImportError:
    from ..repositories import leads_repo

logger = logging.getLogger(__name__)


def _enriched_col(leads_col: Any):
    """The collection the Leads UI actually lists from.

    GET /leads (leads/router.py) pages over `leads_enriched` (22,074 docs),
    but this move endpoint was handed `leads` (334 docs) — so every convert
    of a lead visible in the UI looked up an id that isn't in that
    collection, returned None, and 404'd. Nothing was ever created: zero
    leads in the whole system had ever reached a converted state.
    """
    try:
        return leads_col.database["leads_enriched"]
    except Exception:  # pragma: no cover - defensive, keeps the old path working
        return None


def _mirror_to_spine(lead: Dict[str, Any], contact_id: str) -> None:
    """Also create the CRM-spine account/contact, so a converted lead shows
    up on the Accounts page (which reads the spine via the sales_accounts
    mirror), not only on Contacts. Best-effort: a spine failure must not
    lose the conversion itself."""
    try:
        try:
            from app.services import crm_service
        except ImportError:
            from ..app.services import crm_service

        company = (lead.get("company_name") or lead.get("company") or "").strip()
        email = (lead.get("email") or "").strip().lower()
        name = (lead.get("name")
                or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
                or email)

        account_id = None
        if company:
            account, _ = crm_service.get_or_create_account(
                company, defaults={"account_type": "client",
                                   "metadata": {"source": "lead_conversion"}})
            account_id = account["_id"]

        if email:
            crm_service.get_or_create_contact(
                email, defaults={"name": name or None,
                                 "title": lead.get("title"),
                                 "phone": lead.get("phone"),
                                 "account_id": account_id,
                                 "metadata": {"source": "lead_conversion",
                                              "legacy_contact_id": contact_id}})
    except Exception as e:
        logger.warning("Lead %s: spine mirror failed (non-fatal): %s",
                       lead.get("_id"), e)


def move_lead_to_contacts(
    lead_id: str,
    stage: str,
    leads_col: Any,
    contacts_col: Any,
) -> Optional[Dict[str, Any]]:
    """
    Move a lead into the contacts collection and mirror it onto the CRM spine.

    Steps:
      1. Fetch the lead — from `leads_enriched` (what the UI lists) first,
         falling back to `leads` for legacy ids.
      2. Copy fields to contacts with new stage + timestamps.
      3. Mark the source lead converted.

    Returns the new contact dict (with _id as string), or None if not found.

    Step 3 used to hard-delete the source row. That is safe for the 334-doc
    legacy `leads` collection it was originally written against, but not for
    `leads_enriched`, where the row carries the outreach/bounce history the
    sending pipeline reads — so the enriched path marks it converted instead.
    """
    lead = None
    source_col = leads_col
    enriched = _enriched_col(leads_col)
    if enriched is not None:
        lead = leads_repo.find_lead_by_id(enriched, lead_id)
        if lead is not None:
            source_col = enriched
    if lead is None:
        lead = leads_repo.find_lead_by_id(leads_col, lead_id)
        source_col = leads_col
    if lead is None:
        return None

    contact_data = {k: v for k, v in lead.items() if k != "_id"}
    contact_data["stage"] = stage
    contact_data["movedFromLeadAt"] = datetime.utcnow()
    contact_data["createdAt"] = lead.get("createdAt", datetime.utcnow())
    contact_data["updatedAt"] = datetime.utcnow()
    # The Contacts page renders companyName, not company/company_name.
    if not contact_data.get("companyName"):
        contact_data["companyName"] = (lead.get("company_name")
                                       or lead.get("company") or None)

    # `contacts` has a UNIQUE index on email, so a blind insert raised
    # DuplicateKeyError (surfacing as a 500) whenever the lead's address was
    # already a contact — which is common now that the CRM spine's 2,779
    # contacts are mirrored into this collection. Upsert on email instead, so
    # converting an already-known person updates and links that contact
    # rather than failing, and clicking Convert twice is harmless.
    email = (contact_data.get("email") or "").strip().lower()
    if email:
        contact_data["email"] = email
        existing = contacts_col.find_one({"email": email}, {"_id": 1})
        if existing:
            # Don't clobber an established contact wholesale — only fill in
            # what the conversion actually establishes.
            contacts_col.update_one(
                {"_id": existing["_id"]},
                {"$set": {k: v for k, v in contact_data.items()
                          if k in ("stage", "movedFromLeadAt", "updatedAt",
                                   "companyName", "title", "phone", "name")
                          and v is not None}},
            )
            contact_data["_id"] = str(existing["_id"])
        else:
            contact_data["_id"] = str(
                leads_repo.insert_contact(contacts_col, contact_data).inserted_id)
    else:
        contact_data["_id"] = str(
            leads_repo.insert_contact(contacts_col, contact_data).inserted_id)

    if source_col is enriched:
        source_col.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {"converted_to_contact_id": contact_data["_id"],
                      "converted_at": datetime.utcnow(),
                      "lead_stage": stage,
                      "updated_at": datetime.utcnow()}},
        )
    else:
        leads_repo.delete_lead_by_id(source_col, lead_id)

    _mirror_to_spine(lead, contact_data["_id"])

    logger.info("Lead %s moved to contacts (stage=%s, contact_id=%s, source=%s)",
                lead_id, stage, contact_data["_id"], source_col.name)
    return contact_data
