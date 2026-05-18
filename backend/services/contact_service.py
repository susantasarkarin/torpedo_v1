"""
Contact Service
===============
Business logic for contact lifecycle management, including the
finance_db.customers auto-sync.

Extracted from routers/legacy_contacts.py (Phase 10).

Key design note:
  The GET /contacts/ endpoint performs a self-healing write
  (sets linked_customer_id if missing) — this is preserved faithfully.
  Future work: move that repair into a background task.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

try:
    from repositories import contact_repo
except ImportError:
    from ..repositories import contact_repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Customer sync helpers
# ---------------------------------------------------------------------------

def _build_new_customer(contact_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a finance_db.customers document from contact fields."""
    addr = {
        "line1": contact_data.get("companyHeadquarters", ""),
        "line2": "",
        "city": "",
        "state": "",
        "pincode": "",
        "country": "India",
    }
    return {
        "name": contact_data["companyName"],
        "customer_type": "business",
        "company_name": contact_data["companyName"],
        "email": contact_data.get("companyEmail", ""),
        "phone": "",
        "gst_treatment": "unregistered",
        "gstin": "",
        "pan": "",
        "billing_address": addr,
        "shipping_address": dict(addr),
        "same_as_billing": True,
        "payment_terms": 30,
        "credit_limit": 0,
        "currency": "INR",
        "opening_balance": 0,
        "notes": "",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


def _sync_customer_from_contact(
    contact_data: Dict[str, Any],
    customers_col: Any,
) -> Optional[str]:
    """
    Upsert a customer record from contact company data.
    Returns the linked_customer_id string (new or existing).
    """
    company_name = contact_data.get("companyName")
    if not company_name:
        return None

    existing = contact_repo.find_customer_by_company_name(customers_col, company_name)
    if existing:
        update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
        if contact_data.get("companyEmail"):
            update_fields["email"] = contact_data["companyEmail"]
        if contact_data.get("companyHeadquarters"):
            update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
            update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
        contact_repo.update_customer_by_id(customers_col, existing["_id"], update_fields)
        return str(existing["_id"])
    else:
        result = contact_repo.insert_customer(customers_col, _build_new_customer(contact_data))
        return str(result.inserted_id)


# ---------------------------------------------------------------------------
# Contact CRUD with finance sync
# ---------------------------------------------------------------------------

def create_contact(
    contact_data: Dict[str, Any],
    contacts_col: Any,
    customers_col: Any,
) -> Dict[str, Any]:
    """
    Create a contact and sync the associated company to finance_db.customers.
    Returns the inserted contact dict (with _id as string).
    """
    contact_data["stage"] = contact_data.get("stage", "RFQ")
    contact_data["createdAt"] = datetime.utcnow()
    contact_data["updatedAt"] = datetime.utcnow()

    linked_customer_id = _sync_customer_from_contact(contact_data, customers_col)
    contact_data["linked_customer_id"] = linked_customer_id

    result = contact_repo.insert_contact(contacts_col, contact_data)
    contact_data["_id"] = str(result.inserted_id)
    logger.info("Contact created: %s (customer_id=%s)", contact_data.get("email"), linked_customer_id)
    return contact_data


def get_all_contacts(contacts_col: Any, customers_col: Any) -> List[Dict[str, Any]]:
    """
    Fetch all contacts with linked customer data resolved.
    Self-heals linked_customer_id if companyName matches but ID is missing.

    NOTE: This performs a write-on-read to repair missing links.
    """
    contacts = contact_repo.list_contacts(contacts_col)
    all_customers = {str(c["_id"]): c for c in contact_repo.list_customers(customers_col)}

    for contact in contacts:
        contact["_id"] = str(contact["_id"])
        for date_field in ["createdAt", "updatedAt", "movedFromLeadAt", "addedOn"]:
            if date_field in contact:
                contact[date_field] = (
                    contact[date_field].isoformat()
                    if isinstance(contact[date_field], datetime)
                    else str(contact[date_field])
                )

        linked_id = contact.get("linked_customer_id")
        if linked_id and linked_id in all_customers:
            customer = all_customers[linked_id]
            contact["linked_customer"] = {
                "_id": str(customer["_id"]),
                "name": customer.get("name", ""),
                "company_name": customer.get("company_name", ""),
                "email": customer.get("email", ""),
                "status": customer.get("status", "active"),
            }
        elif contact.get("companyName"):
            for cid, customer in all_customers.items():
                if customer.get("company_name") == contact["companyName"]:
                    contact["linked_customer_id"] = cid
                    contact["linked_customer"] = {
                        "_id": cid,
                        "name": customer.get("name", ""),
                        "company_name": customer.get("company_name", ""),
                        "email": customer.get("email", ""),
                        "status": customer.get("status", "active"),
                    }
                    # Self-heal: persist the discovered link
                    contact_repo.set_linked_customer_id(contacts_col, contact["_id"], cid)
                    break

    return contacts


def update_contact(
    contact_id: str,
    contact_data: Dict[str, Any],
    contacts_col: Any,
    customers_col: Any,
) -> int:
    """
    Update contact fields and conditionally sync company to finance_db.customers.
    Returns matched_count (0 means not found).
    """
    contact_data["updatedAt"] = datetime.utcnow()
    result = contact_repo.update_contact_by_id(contacts_col, contact_id, contact_data)

    if result.matched_count > 0 and contact_data.get("companyName"):
        existing_customer = contact_repo.find_customer_by_company_name(customers_col, contact_data["companyName"])
        if existing_customer:
            update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
            if contact_data.get("companyEmail"):
                update_fields["email"] = contact_data["companyEmail"]
            if contact_data.get("companyHeadquarters"):
                update_fields["billing_address.line1"] = contact_data["companyHeadquarters"]
                update_fields["shipping_address.line1"] = contact_data["companyHeadquarters"]
            contact_repo.update_customer_by_id(customers_col, existing_customer["_id"], update_fields)
            contact_repo.set_linked_customer_id(contacts_col, contact_id, str(existing_customer["_id"]))

    return result.matched_count
