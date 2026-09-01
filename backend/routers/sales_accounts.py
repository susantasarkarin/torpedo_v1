"""
Sales Accounts Router
Manages accounts specifically for the Sales module (separate from Finance/Operations)
"""

from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from bson import ObjectId
from datetime import datetime
from pymongo import MongoClient
import logging
import os


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


logger = logging.getLogger(__name__)

# Shared MongoDB serialization (ObjectId/datetime -> JSON) — consolidated
# from per-router copies into backend/utils.py.
from utils import serialize_doc, serialize_docs

router = APIRouter(prefix="/sales", tags=["Sales Accounts"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
# Sales accounts stored in email_automation database (same as leads, contacts)
db = client["email_automation"]
accounts_collection = db["sales_accounts"]

# Joined-in modules for the account 360 view.
finance_db = client["finance_db"]
customers_collection = finance_db["customers"]
invoices_collection = finance_db["invoices"]
estimates_collection = finance_db["estimates"]

# Operations lives in the same email_automation database.
projects_collection = db["projects"]
clients_collection = db["clients"]
contacts_collection = db["contacts"]
leads_collection = db["leads_enriched"]

# ========================
# Pydantic Models
# ========================

class SalesAccountCreate(BaseModel):
    account_name: str
    company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = "active"  # active, inactive, prospect
    # Company details (auto-filled from leads)
    employee_count: Optional[str] = None
    employee_count_range: Optional[str] = None
    revenue_range: Optional[str] = None
    company_type: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    # Links to other modules
    linked_operations_client_id: Optional[str] = None
    linked_finance_customer_id: Optional[str] = None
    created_from_lead_id: Optional[str] = None
    contact_ids: Optional[List[str]] = []

class SalesAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    employee_count: Optional[str] = None
    employee_count_range: Optional[str] = None
    revenue_range: Optional[str] = None
    company_type: Optional[str] = None
    company_linkedin_url: Optional[str] = None
    linked_operations_client_id: Optional[str] = None
    linked_finance_customer_id: Optional[str] = None
    contact_ids: Optional[List[str]] = None

# ========================
# Sales Accounts Endpoints
# ========================

@router.get("/accounts")
def get_all_sales_accounts(
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by name/company"),
    limit: int = Query(0, ge=0, le=1000, description="Chunk size (0 = all, for legacy callers)"),
    skip: int = Query(0, ge=0, description="Records to skip (chunked loading)"),
):
    """Get sales accounts. Pass limit/skip to load in chunks."""
    try:
        query = {}
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"account_name": {"$regex": search, "$options": "i"}},
                {"company_name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}}
            ]

        cursor = accounts_collection.find(query).sort("created_at", -1)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return [serialize_doc(acc) for acc in cursor]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accounts/{account_id}")
def get_sales_account(account_id: str):
    """Get a single sales account by ID"""
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return serialize_doc(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accounts")
def create_sales_account(account: SalesAccountCreate):
    """Create a new sales account"""
    try:
        account_data = account.dict()
        account_data["created_at"] = datetime.utcnow()
        account_data["updated_at"] = datetime.utcnow()
        
        result = accounts_collection.insert_one(account_data)
        account_data["_id"] = str(result.inserted_id)

        # Mirror into the canonical CRM spine (best-effort, non-fatal)
        try:
            from app.services.spine_connector import mirror_sales_account_to_spine
            spine_id = mirror_sales_account_to_spine(
                account_data.get("company_name") or account_data.get("account_name"),
                source_id=account_data["_id"],
                extra={"industry": account_data.get("industry")},
            )
            if spine_id:
                accounts_collection.update_one(
                    {"_id": ObjectId(account_data["_id"])},
                    {"$set": {"crm_account_id": spine_id}})
                account_data["crm_account_id"] = spine_id
        except Exception:
            pass

        return account_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/accounts/{account_id}")
def update_sales_account(account_id: str, account: SalesAccountUpdate):
    """Update a sales account"""
    try:
        update_data = {k: v for k, v in account.dict().items() if v is not None}
        update_data["updated_at"] = datetime.utcnow()
        
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        
        updated = accounts_collection.find_one({"_id": ObjectId(account_id)})
        return serialize_doc(updated)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/accounts/{account_id}")
def delete_sales_account(account_id: str):
    """Delete a sales account"""
    try:
        result = accounts_collection.delete_one({"_id": ObjectId(account_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Account deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========================
# Account Linking Endpoints
# ========================

@router.post("/accounts/{account_id}/link-operations-client")
def link_operations_client(account_id: str, client_id: str = Body(..., embed=True)):
    """Link a sales account to an operations client"""
    try:
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": {
                "linked_operations_client_id": client_id,
                "updated_at": datetime.utcnow()
            }}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Operations client linked successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accounts/{account_id}/link-finance-customer")
def link_finance_customer(account_id: str, customer_id: str = Body(..., embed=True)):
    """Link a sales account to a finance customer"""
    try:
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": {
                "linked_finance_customer_id": customer_id,
                "updated_at": datetime.utcnow()
            }}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Finance customer linked successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/accounts/{account_id}/unlink-operations-client")
def unlink_operations_client(account_id: str):
    """Unlink operations client from sales account"""
    try:
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": {
                "linked_operations_client_id": None,
                "updated_at": datetime.utcnow()
            }}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Operations client unlinked successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/accounts/{account_id}/unlink-finance-customer")
def unlink_finance_customer(account_id: str):
    """Unlink finance customer from sales account"""
    try:
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": {
                "linked_finance_customer_id": None,
                "updated_at": datetime.utcnow()
            }}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Finance customer unlinked successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========================
# Account 360 Overview
# ========================

def _num(doc: Dict[str, Any], *keys: str) -> float:
    """
    First numeric value among `keys`.

    Finance documents came in from several importers and disagree on field
    names (total vs total_amount vs grand_total), so read tolerantly rather
    than silently reporting 0 for half the rows.
    """
    for key in keys:
        value = doc.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _account_contacts(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Contacts for an account, gathered from the three places they actually live:

      1. account.contact_ids       -> leads_enriched (manually attached)
      2. contacts.account_relationships -> keyed by normalized company name
         (written by the email CRM pipeline)
      3. contacts.company          -> plain name match (older rows)

    Deduplicated by lowercased email.
    """
    found: Dict[str, Dict[str, Any]] = {}

    def _add(doc: Dict[str, Any], origin: str) -> None:
        email = (doc.get("email") or "").strip().lower()
        key = email or str(doc.get("_id"))
        if key in found:
            return
        name = (
            doc.get("name")
            or " ".join(filter(None, [doc.get("firstName"), doc.get("lastName")])).strip()
            or " ".join(filter(None, [doc.get("first_name"), doc.get("last_name")])).strip()
            or email
        )
        found[key] = {
            "_id": str(doc.get("_id")),
            "name": name,
            "email": email,
            "phone": doc.get("phone"),
            "designation": doc.get("designation") or doc.get("title"),
            "linkedin": doc.get("linkedin"),
            "country": doc.get("country"),
            "last_seen_date": doc.get("last_seen_date"),
            "source": origin,
        }

    for cid in account.get("contact_ids", []) or []:
        try:
            doc = leads_collection.find_one({"_id": ObjectId(cid)})
        except Exception:
            continue
        if doc:
            _add(doc, "linked")

    company = account.get("company_name") or account.get("account_name") or ""
    normalized = account.get("normalized_name")

    if normalized:
        country = (account.get("country") or "").strip().lower()
        rel_key = f"{normalized}|{country}"
        for doc in contacts_collection.find(
            {f"account_relationships.{rel_key}": {"$exists": True}}
        ).limit(500):
            _add(doc, "email_pipeline")

    if company:
        for doc in contacts_collection.find(
            {"company": {"$regex": f"^{company.strip()}$", "$options": "i"}}
        ).limit(500):
            _add(doc, "company_match")

    return list(found.values())


@router.get("/accounts/{account_id}/overview")
def get_account_overview(account_id: str):
    """
    Account 360: the account plus everything hanging off it — contacts, RFQs
    from the CRM spine, the finance rollup, and operations projects.

    Every section is independently fault-tolerant: one module being down or
    unlinked degrades that panel to empty with a reason, rather than 500-ing
    the whole page.
    """
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid account id")

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    overview: Dict[str, Any] = {
        "account": serialize_doc(account),
        "contacts": [],
        "rfqs": {"items": [], "stats": {}},
        "finance": {"linked": False},
        "operations": {"linked": False},
    }

    # --- Contacts -------------------------------------------------------
    try:
        overview["contacts"] = _account_contacts(account)
    except Exception as e:
        logger.warning(f"Account {account_id}: contact rollup failed: {e}")
        overview["contacts_error"] = str(e)

    # --- RFQs (CRM spine) -----------------------------------------------
    # sales_accounts rows carry crm_account_id once the spine reconcile has
    # run; without it there is no key to query opportunities by.
    try:
        crm_account_id = account.get("crm_account_id")
        if crm_account_id:
            from app.services import spine_rfq

            listing = spine_rfq.list_rfqs(account_id=crm_account_id, limit=200)
            items = listing["rfqs"]
            by_state: Dict[str, int] = {}
            value_open = 0.0
            value_won = 0.0
            for r in items:
                state = r.get("state", "open")
                by_state[state] = by_state.get(state, 0) + 1
                amount = r.get("final_value") or 0
                try:
                    amount = float(amount)
                except (TypeError, ValueError):
                    amount = 0.0
                if state == "open":
                    value_open += amount
                elif state == "won":
                    value_won += amount

            overview["rfqs"] = {
                "items": items,
                "total": listing["total"],
                "stats": {
                    "by_state": by_state,
                    "open_value": value_open,
                    "won_value": value_won,
                },
            }
        else:
            overview["rfqs"]["reason"] = (
                "Account is not linked to the CRM spine yet — it gets a "
                "crm_account_id on the next spine reconcile."
            )
    except Exception as e:
        logger.warning(f"Account {account_id}: RFQ rollup failed: {e}")
        overview["rfqs"]["error"] = str(e)

    # --- Finance --------------------------------------------------------
    try:
        customer_id = account.get("linked_finance_customer_id")
        customer = None
        if customer_id:
            try:
                customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
            except Exception:
                customer = None

        if customer:
            cid = str(customer["_id"])
            invoices = list(
                invoices_collection.find({"customer_id": cid})
                .sort("created_at", -1)
                .limit(100)
            )
            estimates = list(
                estimates_collection.find({"customer_id": cid})
                .sort("created_at", -1)
                .limit(100)
            )

            billed = sum(_num(i, "total_amount", "total", "grand_total", "amount") for i in invoices)
            outstanding = sum(_num(i, "balance_due", "balance", "due_amount") for i in invoices)

            overview["finance"] = {
                "linked": True,
                "customer": serialize_doc(customer),
                "invoices": serialize_docs(invoices),
                "estimates": serialize_docs(estimates),
                "totals": {
                    "invoice_count": len(invoices),
                    "estimate_count": len(estimates),
                    "lifetime_billed": billed,
                    "outstanding": outstanding,
                    "collected": billed - outstanding,
                },
            }
        else:
            overview["finance"]["reason"] = (
                "No finance customer linked. Use POST "
                f"/sales/accounts/{account_id}/link-finance-customer."
            )
    except Exception as e:
        logger.warning(f"Account {account_id}: finance rollup failed: {e}")
        overview["finance"]["error"] = str(e)

    # --- Operations -----------------------------------------------------
    try:
        ops_client_id = account.get("linked_operations_client_id")
        ops_client = None
        if ops_client_id:
            try:
                ops_client = clients_collection.find_one({"_id": ObjectId(ops_client_id)})
            except Exception:
                ops_client = None

        if ops_client:
            # operations.projects reference their client by NAME, not by id.
            name = ops_client.get("name", "")
            projects = list(
                projects_collection.find({
                    "$or": [
                        {"client_id": str(ops_client["_id"])},
                        {"client": {"$regex": f"^{name.strip()}$", "$options": "i"}},
                    ]
                }).sort("created_at", -1).limit(100)
            )

            by_status: Dict[str, int] = {}
            for p in projects:
                key = p.get("status") or "unknown"
                by_status[key] = by_status.get(key, 0) + 1

            overview["operations"] = {
                "linked": True,
                "client": serialize_doc(ops_client),
                "projects": serialize_docs(projects),
                "totals": {
                    "project_count": len(projects),
                    "by_status": by_status,
                },
            }
        else:
            overview["operations"]["reason"] = (
                "No operations client linked. Use POST "
                f"/sales/accounts/{account_id}/link-operations-client."
            )
    except Exception as e:
        logger.warning(f"Account {account_id}: operations rollup failed: {e}")
        overview["operations"]["error"] = str(e)

    return overview


# ========================
# Account Contacts Endpoints
# ========================

@router.get("/accounts/{account_id}/contacts")
def get_account_contacts(account_id: str):
    """Get all contacts (leads) linked to a sales account"""
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        contact_ids = account.get("contact_ids", [])
        if not contact_ids:
            return {"account_id": account_id, "contacts": [], "total": 0}
        
        # Fetch contacts from leads_enriched collection
        leads_collection = db["leads_enriched"]
        contacts = []
        for cid in contact_ids:
            try:
                contact = leads_collection.find_one({"_id": ObjectId(cid)})
                if contact:
                    contacts.append(serialize_doc(contact))
            except Exception:
                pass
        
        return {
            "account_id": account_id,
            "account_name": account.get("account_name"),
            "contacts": contacts,
            "total": len(contacts)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/contacts/{contact_id}")
def add_contact_to_account(account_id: str, contact_id: str):
    """Add a contact (lead) to a sales account"""
    try:
        # Verify account exists
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Verify contact exists
        leads_collection = db["leads_enriched"]
        contact = leads_collection.find_one({"_id": ObjectId(contact_id)})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Add contact to account
        accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$addToSet": {"contact_ids": contact_id}, "$set": {"updated_at": datetime.utcnow()}}
        )
        
        # Update contact with account_id
        leads_collection.update_one(
            {"_id": ObjectId(contact_id)},
            {"$set": {"account_id": account_id, "updated_at": datetime.utcnow()}}
        )
        
        return {"message": "Contact added to account successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/accounts/{account_id}/contacts/{contact_id}")
def remove_contact_from_account(account_id: str, contact_id: str):
    """Remove a contact from a sales account"""
    try:
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$pull": {"contact_ids": contact_id}, "$set": {"updated_at": datetime.utcnow()}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Remove account_id from contact
        leads_collection = db["leads_enriched"]
        leads_collection.update_one(
            {"_id": ObjectId(contact_id)},
            {"$unset": {"account_id": ""}, "$set": {"updated_at": datetime.utcnow()}}
        )
        
        return {"message": "Contact removed from account successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
