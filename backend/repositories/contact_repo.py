"""Contact repository helpers for contacts + finance customers."""

from typing import Any, Dict, Iterable, Optional

from bson import ObjectId


def insert_contact(contacts_col: Any, contact_data: Dict[str, Any]):
    return contacts_col.insert_one(contact_data)


def list_contacts(contacts_col: Any):
    return list(contacts_col.find())


def update_contact_by_id(contacts_col: Any, contact_id: str, update_data: Dict[str, Any]):
    return contacts_col.update_one({"_id": ObjectId(contact_id)}, {"$set": update_data})


def find_customer_by_company_name(customers_col: Any, company_name: str) -> Optional[Dict[str, Any]]:
    return customers_col.find_one({"company_name": company_name})


def insert_customer(customers_col: Any, customer_data: Dict[str, Any]):
    return customers_col.insert_one(customer_data)


def update_customer_by_id(customers_col: Any, customer_id: Any, update_fields: Dict[str, Any]):
    return customers_col.update_one({"_id": customer_id}, {"$set": update_fields})


def list_customers(customers_col: Any) -> Iterable[Dict[str, Any]]:
    return customers_col.find()


def set_linked_customer_id(contacts_col: Any, contact_id: str, linked_customer_id: str):
    return contacts_col.update_one(
        {"_id": ObjectId(contact_id)},
        {"$set": {"linked_customer_id": linked_customer_id}},
    )
