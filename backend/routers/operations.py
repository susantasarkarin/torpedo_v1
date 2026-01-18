"""
Operations Router - Integrates Operations with Finance Module
Handles: 
- Unified Accounts (bridging Clients/Customers)
- Project Invoicing (create invoice from project)
- Project Cost Tracking (link bills/expenses to projects)
- Operations Dashboard KPIs
- OPTIMIZED: Includes caching and batch loading for performance
"""

from fastapi import APIRouter, HTTPException, Body, Query, Depends, Path
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import os
import time
import hashlib
from dotenv import load_dotenv
from routers.finance import generate_customer_number

load_dotenv()

# ============== CACHING ==============
_operations_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 60  # 1 minute for operations data

def _get_cache_key(prefix: str, **kwargs) -> str:
    params = sorted(kwargs.items())
    param_str = "&".join(f"{k}={v}" for k, v in params if v is not None)
    return f"ops:{prefix}:{hashlib.md5(param_str.encode()).hexdigest()}"

def _get_cached(key: str) -> Optional[Any]:
    if key in _operations_cache:
        entry = _operations_cache[key]
        if time.time() < entry['expires_at']:
            return entry['value']
        del _operations_cache[key]
    return None

def _set_cached(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS):
    _operations_cache[key] = {'value': value, 'expires_at': time.time() + ttl}
    if len(_operations_cache) > 50:
        now = time.time()
        expired = [k for k, v in _operations_cache.items() if now >= v['expires_at']]
        for k in expired:
            del _operations_cache[k]

def invalidate_operations_cache():
    """Clear operations cache after mutations"""
    _operations_cache.clear()

# ----------------------------
# Router Setup
# ----------------------------
router = APIRouter(prefix="/operations", tags=["Operations"])

# ----------------------------
# MongoDB Connection
# ----------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)

# Operations Database (email_automation - contains projects, clients)
operations_db = client["email_automation"]
projects_collection = operations_db["projects"]
clients_collection = operations_db["clients"]
vendors_collection = operations_db["vendors"]  # Panel vendors

# Finance Database
finance_db = client["finance_db"]
customers_collection = finance_db["customers"]
finance_vendors_collection = finance_db["vendors"]
invoices_collection = finance_db["invoices"]
bills_collection = finance_db["bills"]
expenses_collection = finance_db["expenses"]
payments_received_collection = finance_db["payments_received"]
payments_made_collection = finance_db["payments_made"]

# Unified Accounts collection (in operations_db for now)
accounts_collection = operations_db["accounts"]

# Traffic Database
traffic_db = client["traffic_flow_db"]
traffic_collection = traffic_db["url_parameters"]

print("✅ Operations router initialized with Finance integration")


# ----------------------------
# Helper Functions
# ----------------------------
def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable format"""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def serialize_docs(docs: list) -> list:
    """Convert list of MongoDB documents to JSON-serializable format"""
    return [serialize_doc(doc) for doc in docs]


def generate_account_number() -> str:
    """Generate unique account number"""
    count = accounts_collection.count_documents({}) + 1
    return f"ACC-{str(count).zfill(5)}"


def generate_invoice_number() -> str:
    """Generate unique invoice number"""
    count = invoices_collection.count_documents({}) + 1
    return f"INV-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


# ============================================================
# UNIFIED ACCOUNTS ENDPOINTS (OPTIMIZED)
# ============================================================

@router.get("/accounts/")
async def get_accounts(
    account_type: Optional[str] = Query(None, description="Filter by type: client, customer, vendor, both"),
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, prospect"),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    bypass_cache: bool = Query(False, description="Force fresh data"),
):
    """Get all unified accounts with optional filters (CACHED + BATCH OPTIMIZED)"""
    
    # Try cache first
    cache_key = _get_cache_key("accounts", type=account_type, status=status, search=search)
    if not bypass_cache:
        cached = _get_cached(cache_key)
        if cached:
            return cached
    
    try:
        query = {}
        
        if account_type:
            query["account_type"] = account_type
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"phone": {"$regex": search, "$options": "i"}},
            ]
        
        # Fetch accounts with projection for faster query
        accounts = list(accounts_collection.find(query).sort("name", 1))
        
        # BATCH: Get all account names for project counting
        account_names = [a.get("name") for a in accounts if a.get("name")]
        
        # BATCH: Get project counts in one aggregation instead of N queries
        if account_names:
            project_counts = list(projects_collection.aggregate([
                {"$match": {"client": {"$in": account_names}}},
                {"$group": {
                    "_id": "$client",
                    "total": {"$sum": 1},
                    "active": {"$sum": {"$cond": [
                        {"$in": ["$projectStatus", ["Active", "In Progress", "Live"]]},
                        1, 0
                    ]}}
                }}
            ]))
            project_map = {p["_id"]: p for p in project_counts}
        else:
            project_map = {}
        
        # BATCH: Get invoice totals for all customer IDs in one aggregation
        customer_ids = [a.get("finance_customer_id") for a in accounts if a.get("finance_customer_id")]
        if customer_ids:
            invoice_totals = list(invoices_collection.aggregate([
                {"$match": {"customer_id": {"$in": customer_ids}}},
                {"$group": {
                    "_id": "$customer_id",
                    "total_invoiced": {"$sum": "$total_amount"},
                    "total_receivables": {"$sum": "$balance_due"},
                    "total_paid": {"$sum": "$amount_paid"}
                }}
            ]))
            invoice_map = {str(i["_id"]): i for i in invoice_totals}
        else:
            invoice_map = {}
        
        # Enrich accounts with batch data
        for account in accounts:
            account["_id"] = str(account["_id"])
            name = account.get("name")
            
            # Apply project counts from batch
            if name and name in project_map:
                account["total_projects"] = project_map[name]["total"]
                account["active_projects"] = project_map[name]["active"]
            else:
                account["total_projects"] = 0
                account["active_projects"] = 0
            
            # Apply invoice totals from batch
            cust_id = account.get("finance_customer_id")
            if cust_id and str(cust_id) in invoice_map:
                inv = invoice_map[str(cust_id)]
                account["total_invoiced"] = inv.get("total_invoiced", 0)
                account["total_receivables"] = inv.get("total_receivables", 0)
                account["total_paid"] = inv.get("total_paid", 0)
        
        result = {"accounts": accounts}
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching accounts: {str(e)}")


@router.get("/accounts/{account_id}")
async def get_account(account_id: str):
    """Get a single account with full details including linked projects and invoices"""
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = serialize_doc(account)
        
        # Get linked projects
        if account.get("name"):
            projects = list(projects_collection.find({
                "client": {"$regex": f"^{account['name']}$", "$options": "i"}
            }).sort("createdAt", -1).limit(10))
            account["recent_projects"] = serialize_docs(projects)
        
        # Get linked invoices
        if account.get("finance_customer_id"):
            invoices = list(invoices_collection.find({
                "customer_id": account["finance_customer_id"]
            }).sort("created_at", -1).limit(10))
            account["recent_invoices"] = serialize_docs(invoices)
        
        return account
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching account: {str(e)}")


@router.post("/accounts/")
async def create_account(account_data: Dict[str, Any] = Body(...)):
    """Create a new unified account"""
    try:
        if not account_data.get("name"):
            raise HTTPException(status_code=400, detail="Account name is required")
        
        # Check for duplicates
        existing = accounts_collection.find_one({
            "name": {"$regex": f"^{account_data['name']}$", "$options": "i"}
        })
        if existing:
            raise HTTPException(status_code=400, detail=f"Account '{account_data['name']}' already exists")
        
        account_data["account_number"] = generate_account_number()
        account_data["account_type"] = account_data.get("account_type", "client")
        account_data["status"] = account_data.get("status", "active")
        account_data["created_at"] = datetime.utcnow()
        account_data["updated_at"] = datetime.utcnow()
        
        result = accounts_collection.insert_one(account_data)
        account_data["_id"] = str(result.inserted_id)
        
        return {"message": "Account created successfully", "account": account_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating account: {str(e)}")


@router.put("/accounts/{account_id}")
async def update_account(account_id: str, account_data: Dict[str, Any] = Body(...)):
    """Update an account"""
    try:
        account_data.pop("_id", None)
        account_data.pop("account_number", None)
        account_data["updated_at"] = datetime.utcnow()
        
        result = accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": account_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        
        return {"message": "Account updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating account: {str(e)}")


@router.post("/accounts/{account_id}/link-customer")
async def link_account_to_customer(
    account_id: str,
    data: Dict[str, Any] = Body(...)
):
    """Link an account to a finance customer (or create one)"""
    try:
        account = accounts_collection.find_one({"_id": ObjectId(account_id)})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        customer_id = data.get("customer_id")
        
        if customer_id:
            # Link to existing customer
            customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
            if not customer:
                raise HTTPException(status_code=404, detail="Customer not found")
        else:
            # Create new customer from account data
            customer_data = {
                "name": account.get("name"),
                "customer_number": generate_customer_number(),
                "customer_type": "business",
                "company_name": account.get("name"),
                "email": account.get("email", ""),
                "phone": account.get("phone", ""),
                "gst_treatment": account.get("gst_treatment", "unregistered"),
                "gstin": account.get("gstin", ""),
                "pan": account.get("pan", ""),
                "billing_address": account.get("billing_address", {}),
                "payment_terms": account.get("payment_terms", 30),
                "currency": account.get("currency", "INR"),
                "status": "active",
                "notes": f"Auto-created from Account: {account.get('account_number')}",
                "total_receivables": 0,
                "total_paid": 0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
            result = customers_collection.insert_one(customer_data)
            customer_id = str(result.inserted_id)
        
        # Update account with customer link
        accounts_collection.update_one(
            {"_id": ObjectId(account_id)},
            {
                "$set": {
                    "finance_customer_id": customer_id,
                    "account_type": "both" if account.get("account_type") in ["vendor", "client"] else "customer",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {"message": "Account linked to customer", "customer_id": customer_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error linking account: {str(e)}")


@router.post("/accounts/sync-from-clients")
async def sync_accounts_from_clients():
    """
    Sync existing Operations clients into Unified Accounts.
    Creates accounts for clients that don't have one yet.
    """
    try:
        # Get all unique client names from projects
        client_names = projects_collection.distinct("client")
        
        synced = 0
        skipped = 0
        
        for client_name in client_names:
            if not client_name or not client_name.strip():
                continue
                
            # Check if account already exists
            existing = accounts_collection.find_one({
                "name": {"$regex": f"^{client_name.strip()}$", "$options": "i"}
            })
            
            if existing:
                skipped += 1
                continue
            
            # Create new account
            account_data = {
                "name": client_name.strip(),
                "account_number": generate_account_number(),
                "account_type": "client",
                "status": "active",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "notes": "Auto-synced from Operations projects"
            }
            accounts_collection.insert_one(account_data)
            synced += 1
        
        return {
            "message": f"Synced {synced} new accounts, skipped {skipped} existing",
            "synced": synced,
            "skipped": skipped
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing accounts: {str(e)}")


# ============================================================
# PROJECT INVOICING ENDPOINTS
# ============================================================

import hashlib

def generate_idempotency_key(project_id: str, items: List[Dict]) -> str:
    """
    Generate idempotency key for invoice creation.
    Format: project:{project_id}:inv:{YYYYMMDD}:{line_items_hash}
    P0.14: Invoice Creation Idempotency
    """
    date_str = datetime.utcnow().strftime("%Y%m%d")
    # Create hash of line items (sorted for consistency)
    items_str = str(sorted([str(item) for item in items])) if items else ""
    items_hash = hashlib.sha256(items_str.encode()).hexdigest()[:12]
    return f"project:{project_id}:inv:{date_str}:{items_hash}"


@router.post("/projects/{project_id}/invoice")
async def create_invoice_from_project(
    project_id: str,
    invoice_data: Dict[str, Any] = Body(default={})
):
    """
    Create an invoice from a project.
    Auto-populates invoice with project details.
    P0.14: Includes idempotency check to prevent duplicate invoices.
    """
    try:
        # Get project
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project = serialize_doc(project)
        
        # Find or create customer
        customer_id = invoice_data.get("customer_id")
        
        if not customer_id:
            # Try to find customer by client name
            client_name = project.get("client", "")
            if client_name:
                customer = customers_collection.find_one({
                    "name": {"$regex": f"^{client_name}$", "$options": "i"}
                })
                if customer:
                    customer_id = str(customer["_id"])
                else:
                    # Check unified accounts
                    account = accounts_collection.find_one({
                        "name": {"$regex": f"^{client_name}$", "$options": "i"}
                    })
                    if account and account.get("finance_customer_id"):
                        customer_id = account["finance_customer_id"]
        
        if not customer_id:
            raise HTTPException(
                status_code=400, 
                detail="Customer not found. Please link the client to a finance customer first."
            )
        
        # Build invoice items from project
        project_value = float(project.get("projectValue", 0) or 0)
        cpi = float(project.get("cpi", 0) or 0)
        sample_size = int(project.get("totalCompletesRequired", 0) or 0)
        
        items = invoice_data.get("items", [])
        
        if not items:
            # Auto-generate item from project
            if cpi > 0 and sample_size > 0:
                items = [{
                    "description": f"Survey Research - {project.get('projectName', 'Project')}",
                    "details": f"Survey No: {project.get('surveyNo', 'N/A')} | LOI: {project.get('loi', 'N/A')} mins",
                    "quantity": sample_size,
                    "rate": cpi,
                    "tax_rate": invoice_data.get("tax_rate", 18),
                    "tax_amount": (sample_size * cpi) * (invoice_data.get("tax_rate", 18) / 100),
                }]
            elif project_value > 0:
                items = [{
                    "description": f"Survey Research - {project.get('projectName', 'Project')}",
                    "details": f"Survey No: {project.get('surveyNo', 'N/A')}",
                    "quantity": 1,
                    "rate": project_value,
                    "tax_rate": invoice_data.get("tax_rate", 18),
                    "tax_amount": project_value * (invoice_data.get("tax_rate", 18) / 100),
                }]
        
        # Calculate totals
        subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
        tax_total = sum(item.get("tax_amount", 0) for item in items)
        total_amount = subtotal + tax_total
        
        # P0.14: Generate idempotency key and check for duplicates
        idempotency_key = generate_idempotency_key(project_id, items)
        existing_invoice = invoices_collection.find_one({
            "idempotency_key": idempotency_key,
            "is_deleted": {"$ne": True}
        })
        if existing_invoice:
            # Return existing invoice instead of creating duplicate
            existing_invoice["_id"] = str(existing_invoice["_id"])
            return {
                "message": "Duplicate invoice detected - returning existing invoice",
                "invoice": existing_invoice,
                "duplicate": True
            }
        
        # Create invoice
        new_invoice = {
            "invoice_number": generate_invoice_number(),
            "idempotency_key": idempotency_key,
            "customer_id": customer_id,
            "project_id": project_id,  # Link to project
            "project_name": project.get("projectName"),
            "survey_no": project.get("surveyNo"),
            "invoice_date": invoice_data.get("invoice_date", datetime.utcnow().strftime("%Y-%m-%d")),
            "due_date": invoice_data.get("due_date", (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")),
            "items": items,
            "subtotal": subtotal,
            "tax_total": tax_total,
            "total_amount": total_amount,
            "balance_due": total_amount,
            "amount_paid": 0,
            "status": "draft",
            "currency_code": invoice_data.get("currency_code", "INR"),
            "notes": invoice_data.get("notes", f"Invoice for project: {project.get('projectName')}"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        
        result = invoices_collection.insert_one(new_invoice)
        new_invoice["_id"] = str(result.inserted_id)
        
        # Update project with invoice reference
        projects_collection.update_one(
            {"_id": ObjectId(project_id)},
            {
                "$push": {"invoice_ids": str(result.inserted_id)},
                "$set": {"last_invoiced_at": datetime.utcnow()}
            }
        )
        
        # Update customer receivables
        customers_collection.update_one(
            {"_id": ObjectId(customer_id)},
            {"$inc": {"total_receivables": total_amount}}
        )
        
        return {
            "message": "Invoice created from project",
            "invoice": new_invoice
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating invoice: {str(e)}")


@router.get("/projects/{project_id}/financials")
async def get_project_financials(project_id: str):
    """
    Get comprehensive financial summary for a project.
    Includes revenue, costs, and profitability metrics.
    """
    try:
        # Get project
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project = serialize_doc(project)
        
        # Get linked invoices
        invoices = list(invoices_collection.find({"project_id": project_id}))
        invoice_ids = [str(inv["_id"]) for inv in invoices]
        
        # Calculate invoice totals
        invoiced_amount = sum(inv.get("total_amount", 0) for inv in invoices)
        received_amount = sum(inv.get("amount_paid", 0) for inv in invoices)
        outstanding_amount = sum(inv.get("balance_due", 0) for inv in invoices)
        
        # Get linked bills (vendor costs)
        bills = list(bills_collection.find({"project_id": project_id}))
        bill_ids = [str(bill["_id"]) for bill in bills]
        vendor_costs = sum(bill.get("total_amount", 0) for bill in bills)
        
        # Get linked expenses
        expenses = list(expenses_collection.find({"project_id": project_id}))
        expense_ids = [str(exp["_id"]) for exp in expenses]
        other_expenses = sum(exp.get("amount", 0) for exp in expenses)
        
        # Calculate profitability
        total_costs = vendor_costs + other_expenses
        gross_profit = invoiced_amount - total_costs
        profit_margin = (gross_profit / invoiced_amount * 100) if invoiced_amount > 0 else 0
        
        return {
            "project_id": project_id,
            "project_name": project.get("projectName"),
            "survey_no": project.get("surveyNo"),
            "client": project.get("client"),
            
            # Revenue
            "project_value": float(project.get("projectValue", 0) or 0),
            "invoiced_amount": round(invoiced_amount, 2),
            "received_amount": round(received_amount, 2),
            "outstanding_amount": round(outstanding_amount, 2),
            
            # Costs
            "total_costs": round(total_costs, 2),
            "vendor_costs": round(vendor_costs, 2),
            "other_expenses": round(other_expenses, 2),
            
            # Profitability
            "gross_profit": round(gross_profit, 2),
            "profit_margin": round(profit_margin, 2),
            
            # Document counts
            "invoice_count": len(invoices),
            "bill_count": len(bills),
            "expense_count": len(expenses),
            
            # Document IDs
            "invoice_ids": invoice_ids,
            "bill_ids": bill_ids,
            "expense_ids": expense_ids,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching project financials: {str(e)}")


@router.get("/projects/with-financials")
async def get_projects_with_financials(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    client: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """Get all projects with their financial summaries"""
    try:
        query = {}
        if client:
            query["client"] = {"$regex": client, "$options": "i"}
        if status:
            query["projectStatus"] = status
        
        # Get total count
        total = projects_collection.count_documents(query)
        
        # Pagination
        skip = (page - 1) * page_size
        projects = list(
            projects_collection.find(query)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(page_size)
        )
        
        # Enrich with financial data
        result = []
        for project in projects:
            project_id = str(project["_id"])
            project["_id"] = project_id
            
            # Get invoice totals
            invoice_pipeline = [
                {"$match": {"project_id": project_id}},
                {"$group": {
                    "_id": None,
                    "invoiced": {"$sum": "$total_amount"},
                    "received": {"$sum": "$amount_paid"},
                    "outstanding": {"$sum": "$balance_due"},
                    "count": {"$sum": 1}
                }}
            ]
            invoice_result = list(invoices_collection.aggregate(invoice_pipeline))
            
            if invoice_result:
                project["invoiced_amount"] = invoice_result[0].get("invoiced", 0)
                project["received_amount"] = invoice_result[0].get("received", 0)
                project["outstanding_amount"] = invoice_result[0].get("outstanding", 0)
                project["invoice_count"] = invoice_result[0].get("count", 0)
            else:
                project["invoiced_amount"] = 0
                project["received_amount"] = 0
                project["outstanding_amount"] = 0
                project["invoice_count"] = 0
            
            # Get cost totals
            bill_total = bills_collection.aggregate([
                {"$match": {"project_id": project_id}},
                {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}}
            ])
            expense_total = expenses_collection.aggregate([
                {"$match": {"project_id": project_id}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ])
            
            bill_result = list(bill_total)
            expense_result = list(expense_total)
            
            project["total_costs"] = (
                (bill_result[0].get("total", 0) if bill_result else 0) +
                (expense_result[0].get("total", 0) if expense_result else 0)
            )
            
            # Calculate profit
            project["gross_profit"] = project["invoiced_amount"] - project["total_costs"]
            
            result.append(project)
        
        return {
            "projects": result,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching projects: {str(e)}")


# ============================================================
# OPERATIONS DASHBOARD KPIs
# ============================================================

@router.get("/dashboard/kpis")
async def get_operations_dashboard_kpis():
    """
    Get real-time KPIs for the Operations dashboard.
    Replaces mock data with actual aggregated metrics.
    """
    try:
        now = datetime.utcnow()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_of_last_month = (start_of_month - timedelta(days=1)).replace(day=1)
        
        # Project metrics
        total_projects = projects_collection.count_documents({})
        active_projects = projects_collection.count_documents({
            "projectStatus": {"$in": ["Active", "In Progress", "Live", "Pending"]}
        })
        completed_projects = projects_collection.count_documents({
            "projectStatus": {"$in": ["Completed", "Closed"]}
        })
        
        # Projects this month
        projects_this_month = projects_collection.count_documents({
            "createdAt": {"$gte": start_of_month}
        })
        projects_last_month = projects_collection.count_documents({
            "createdAt": {"$gte": start_of_last_month, "$lt": start_of_month}
        })
        
        # Calculate project growth
        project_growth = 0
        if projects_last_month > 0:
            project_growth = ((projects_this_month - projects_last_month) / projects_last_month) * 100
        
        # Client metrics
        unique_clients = len(projects_collection.distinct("client"))
        
        # Revenue metrics (from invoices linked to projects)
        revenue_pipeline = [
            {"$match": {"project_id": {"$exists": True, "$ne": None}}},
            {"$group": {
                "_id": None,
                "total_invoiced": {"$sum": "$total_amount"},
                "total_received": {"$sum": "$amount_paid"},
                "total_outstanding": {"$sum": "$balance_due"}
            }}
        ]
        revenue_result = list(invoices_collection.aggregate(revenue_pipeline))
        
        if revenue_result:
            total_invoiced = revenue_result[0].get("total_invoiced", 0)
            total_received = revenue_result[0].get("total_received", 0)
            total_outstanding = revenue_result[0].get("total_outstanding", 0)
        else:
            total_invoiced = 0
            total_received = 0
            total_outstanding = 0
        
        # Traffic metrics (from traffic_flow_db)
        try:
            total_traffic = traffic_collection.count_documents({})
            completed_surveys = traffic_collection.count_documents({"status": "COMPLETE"})
            terminated_surveys = traffic_collection.count_documents({"status": "TERMINATED"})
            
            completion_rate = (completed_surveys / total_traffic * 100) if total_traffic > 0 else 0
        except Exception:
            total_traffic = 0
            completed_surveys = 0
            terminated_surveys = 0
            completion_rate = 0
        
        # Project value totals
        value_pipeline = [
            {"$group": {
                "_id": None,
                "total_value": {"$sum": {"$toDouble": {"$ifNull": ["$projectValue", 0]}}},
            }}
        ]
        value_result = list(projects_collection.aggregate(value_pipeline))
        total_project_value = value_result[0].get("total_value", 0) if value_result else 0
        
        # Status breakdown
        status_pipeline = [
            {"$group": {
                "_id": "$projectStatus",
                "count": {"$sum": 1}
            }}
        ]
        status_breakdown = {
            item["_id"]: item["count"] 
            for item in projects_collection.aggregate(status_pipeline)
            if item["_id"]
        }
        
        return {
            # Project KPIs
            "projects": {
                "total": total_projects,
                "active": active_projects,
                "completed": completed_projects,
                "this_month": projects_this_month,
                "growth_percent": round(project_growth, 1),
                "total_value": round(total_project_value, 2),
                "status_breakdown": status_breakdown
            },
            
            # Client KPIs
            "clients": {
                "total": unique_clients,
            },
            
            # Revenue KPIs
            "revenue": {
                "total_invoiced": round(total_invoiced, 2),
                "total_received": round(total_received, 2),
                "total_outstanding": round(total_outstanding, 2),
                "collection_rate": round((total_received / total_invoiced * 100) if total_invoiced > 0 else 0, 1)
            },
            
            # Traffic KPIs
            "traffic": {
                "total": total_traffic,
                "completed": completed_surveys,
                "terminated": terminated_surveys,
                "completion_rate": round(completion_rate, 1)
            },
            
            # Timestamp
            "updated_at": now.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard KPIs: {str(e)}")


@router.get("/dashboard/recent-activity")
async def get_recent_activity(limit: int = Query(10, ge=1, le=50)):
    """Get recent activity across projects, invoices, and traffic"""
    try:
        activities = []
        
        # Recent projects
        recent_projects = list(
            projects_collection.find()
            .sort("createdAt", -1)
            .limit(limit)
        )
        for proj in recent_projects:
            activities.append({
                "type": "project",
                "action": "created",
                "title": proj.get("projectName", "Unknown Project"),
                "subtitle": f"Client: {proj.get('client', 'N/A')}",
                "timestamp": proj.get("createdAt"),
                "id": str(proj["_id"])
            })
        
        # Recent invoices linked to projects
        recent_invoices = list(
            invoices_collection.find({"project_id": {"$exists": True, "$ne": None}})
            .sort("created_at", -1)
            .limit(limit)
        )
        for inv in recent_invoices:
            activities.append({
                "type": "invoice",
                "action": "created",
                "title": inv.get("invoice_number", "Unknown Invoice"),
                "subtitle": f"Amount: ₹{inv.get('total_amount', 0):,.2f}",
                "timestamp": inv.get("created_at"),
                "id": str(inv["_id"])
            })
        
        # Sort all activities by timestamp
        activities.sort(key=lambda x: x.get("timestamp") or datetime.min, reverse=True)
        
        # Format timestamps
        for activity in activities:
            if activity.get("timestamp"):
                activity["timestamp"] = activity["timestamp"].isoformat()
        
        return {"activities": activities[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recent activity: {str(e)}")


# ============================================================================
# ASYNC TASK MANAGEMENT ENDPOINTS
# For tracking long-running operations like email sync and AI processing
# ============================================================================

@router.get("/async/{operation_id}/status")
async def get_async_operation_status(operation_id: str = Path(..., description="Operation ID")):
    """
    Get the status of an async operation.
    Used by frontend polling to track progress of email sync, AI processing, etc.
    """
    try:
        from tasks.api_tasks import get_operation_status as get_status
        from celery_app import get_task_status
        
        # Try Redis status store first
        result = get_status(operation_id)
        
        if result.get('status') == 'not_found':
            # Also check Celery task status
            celery_result = get_task_status(operation_id)
            if celery_result and celery_result.get('status') != 'PENDING':
                return celery_result
            
            raise HTTPException(status_code=404, detail="Operation not found")
        
        return result
        
    except HTTPException:
        raise
    except ImportError:
        # Celery not yet configured - return placeholder
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/{operation_id}/cancel")
async def cancel_async_operation(operation_id: str = Path(..., description="Operation ID")):
    """
    Cancel a running async operation.
    """
    try:
        from tasks.api_tasks import cancel_operation as do_cancel
        
        result = do_cancel(operation_id)
        return result
        
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/async/active")
async def list_active_async_operations(
    type: Optional[str] = Query(None, description="Filter by operation type (email_sync, ai_processing)")
):
    """
    List all active (running) async operations.
    """
    try:
        from tasks.api_tasks import list_active_operations as list_ops
        
        result = list_ops(type)
        return result
        
    except ImportError as e:
        import traceback
        error_details = traceback.format_exc()
        return {"operations": [], "count": 0, "message": f"Import error: {str(e)}", "details": error_details}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/async/cleanup")
async def cleanup_old_async_operations(
    max_age_hours: int = Query(24, ge=1, le=168, description="Max age in hours for completed operations")
):
    """
    Clean up old completed async operations from status store.
    """
    try:
        from tasks.api_tasks import cleanup_old_operations as do_cleanup
        
        result = do_cleanup(max_age_hours)
        return result
        
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
