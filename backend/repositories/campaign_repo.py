"""Campaign repository helpers (lists, contacts, reports)."""

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId


def create_campaign_report(reports_col: Any, campaign_id: str, subject: str) -> None:
    reports_col.insert_one(
        {
            "campaignId": campaign_id,
            "subject": subject,
            "sent": [],
            "opens": [],
            "clicks": [],
            "createdAt": datetime.utcnow(),
        }
    )


def append_sent_event(reports_col: Any, campaign_id: str, email: str) -> None:
    reports_col.update_one(
        {"campaignId": campaign_id},
        {"$push": {"sent": {"email": email, "time": datetime.utcnow()}}},
    )


def find_list_by_name(lists_col: Any, list_name: str) -> Optional[Dict[str, Any]]:
    return lists_col.find_one({"name": list_name})


def contact_exists(contacts_col: Any, query: Dict[str, Any]) -> bool:
    return contacts_col.find_one(query) is not None


def insert_contact(contacts_col: Any, contact: Dict[str, Any]):
    return contacts_col.insert_one(contact)


def delete_list_by_id(lists_col: Any, list_id: str):
    return lists_col.delete_one({"_id": ObjectId(list_id)})


def delete_contacts_by_list_id(contacts_col: Any, list_id: str):
    return contacts_col.delete_many({"listId": list_id})
