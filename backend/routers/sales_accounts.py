"""
Sales Accounts Router
Manages accounts specifically for the Sales module (separate from Finance/Operations)
"""

from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel
from typing import List, Optional, Any
from bson import ObjectId
from datetime import datetime
from pymongo import MongoClient
import os

router = APIRouter(prefix="/sales", tags=["Sales Accounts"])

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
# Sales accounts stored in email_automation database (same as leads, contacts)
db = client["email_automation"]
accounts_collection = db["sales_accounts"]

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
    # Links to other modules
    linked_operations_client_id: Optional[str] = None
    linked_finance_customer_id: Optional[str] = None

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
    linked_operations_client_id: Optional[str] = None
    linked_finance_customer_id: Optional[str] = None

def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

# ========================
# Sales Accounts Endpoints
# ========================

@router.get("/accounts")
async def get_all_sales_accounts(
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by name/company")
):
    """Get all sales accounts"""
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
        
        accounts = list(accounts_collection.find(query).sort("created_at", -1))
        return [serialize_doc(acc) for acc in accounts]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accounts/{account_id}")
async def get_sales_account(account_id: str):
    """Get a single sales account by ID"""
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return serialize_doc(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accounts")
async def create_sales_account(account: SalesAccountCreate):
    """Create a new sales account"""
    try:
        account_data = account.dict()
        account_data["created_at"] = datetime.utcnow()
        account_data["updated_at"] = datetime.utcnow()
        
        result = accounts_collection.insert_one(account_data)
        account_data["_id"] = str(result.inserted_id)
        return account_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/accounts/{account_id}")
async def update_sales_account(account_id: str, account: SalesAccountUpdate):
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
async def delete_sales_account(account_id: str):
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
async def link_operations_client(account_id: str, client_id: str = Body(..., embed=True)):
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
async def link_finance_customer(account_id: str, customer_id: str = Body(..., embed=True)):
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
async def unlink_operations_client(account_id: str):
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
async def unlink_finance_customer(account_id: str):
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
