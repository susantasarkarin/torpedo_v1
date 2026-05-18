"""Leads repository helpers for lead/contact move operations."""

from typing import Any, Dict, Optional

from bson import ObjectId


def find_lead_by_id(leads_col: Any, lead_id: str) -> Optional[Dict[str, Any]]:
    return leads_col.find_one({"_id": ObjectId(lead_id)})


def insert_contact(contacts_col: Any, contact_data: Dict[str, Any]):
    return contacts_col.insert_one(contact_data)


def delete_lead_by_id(leads_col: Any, lead_id: str):
    return leads_col.delete_one({"_id": ObjectId(lead_id)})
