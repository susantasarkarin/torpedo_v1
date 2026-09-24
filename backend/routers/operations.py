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
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import re
import os
import time
import hashlib
from dotenv import load_dotenv
from routers.finance import generate_customer_number


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


# Shared MongoDB serialization (ObjectId/datetime -> JSON) — consolidated
# from per-router copies into backend/utils.py.
from utils import serialize_doc, serialize_docs

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

# ----------------------------
# Router Setup
# ----------------------------
router = APIRouter(prefix="/api/operations", tags=["Operations"])

# ----------------------------
# MongoDB Connection
# ----------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()

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
def generate_account_number() -> str:
    """Generate unique account number"""
    count = accounts_collection.count_documents({}) + 1
    return f"ACC-{str(count).zfill(5)}"


def generate_invoice_number() -> str:
    """Generate unique invoice number"""
    count = invoices_collection.count_documents({}) + 1
    return f"INV-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def _safe_to_float(value: Any) -> float:
    """Convert mixed numeric/string values to float without raising."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return 0.0

        cleaned = cleaned.replace(",", "")
        cleaned = re.sub(r"(?i)inr|usd|eur|gbp", "", cleaned)
        cleaned = re.sub(r"[^\d.\-]", "", cleaned)
        if cleaned in ("", "-", ".", "-."):
            return 0.0

        try:
            return float(cleaned)
        except Exception:
            return 0.0
    return 0.0


def _safe_to_datetime(value: Any) -> Optional[datetime]:
    """Parse mixed datetime values (datetime/iso string/unix timestamp) safely."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.utcfromtimestamp(ts)
        except Exception:
            return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None

        candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except Exception:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                continue

    return None


# ============================================================
# UNIFIED ACCOUNTS ENDPOINTS (OPTIMIZED)
# ============================================================

@router.get("/accounts/")
def get_accounts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    account_type: Optional[str] = Query(None, description="Filter by type: client, customer, vendor, both"),
    status: Optional[str] = Query(None, description="Filter by status: active, inactive, prospect"),
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    bypass_cache: bool = Query(False, description="Force fresh data"),
):
    """Get unified accounts with optional filters, paginated (CACHED + BATCH OPTIMIZED)"""
    
    # Try cache first
    cache_key = _get_cache_key("accounts", type=account_type, status=status, search=search, page=page, page_size=page_size)
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
        
        total = accounts_collection.count_documents(query)
        skip = (page - 1) * page_size
        accounts = list(accounts_collection.find(query).sort("name", 1).skip(skip).limit(page_size))
        
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
        
        result = {"accounts": accounts, "total": total, "page": page, "page_size": page_size, "pages": max(1, -(-total // page_size))}
        _set_cached(cache_key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching accounts: {str(e)}")


@router.get("/accounts/{account_id}")
def get_account(account_id: str):
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
def create_account(account_data: Dict[str, Any] = Body(...)):
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
def update_account(account_id: str, account_data: Dict[str, Any] = Body(...)):
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
def link_account_to_customer(
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
def sync_accounts_from_clients():
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
# PROJECT LIST ENDPOINTS (COMPATIBILITY)
# ============================================================

@router.get("/projects/")
@router.get("/projects")
def list_operations_projects(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by project status"),
    search: Optional[str] = Query(None, description="Search by project name/client/survey/vendor"),
):
    """
    Lightweight projects list endpoint for Operations dashboard/table views.
    Keeps backward compatibility for clients calling /api/operations/projects.
    """
    try:
        query: Dict[str, Any] = {"is_deleted": {"$ne": True}}

        if status:
            query["projectStatus"] = status

        if search:
            query["$or"] = [
                {"projectName": {"$regex": search, "$options": "i"}},
                {"client": {"$regex": search, "$options": "i"}},
                {"surveyNo": {"$regex": search, "$options": "i"}},
                {"vendorName": {"$regex": search, "$options": "i"}},
            ]

        # PERF: Use $facet to get count + data in one round-trip, with projection
        _project_projection = {
            "projectName": 1, "client": 1, "surveyNo": 1, "vendorName": 1,
            "projectStatus": 1, "createdAt": 1, "updatedAt": 1, "countryCode": 1,
            "totalSample": 1, "sampleSize": 1, "ir": 1, "loi": 1, "cpi": 1,
            "projectType": 1, "methodology": 1, "clientLink": 1, "liveLink": 1,
        }
        projects = list(
            projects_collection.find(query, _project_projection)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )
        total = projects_collection.count_documents(query)

        for p in projects:
            p["_id"] = str(p["_id"])

        return {
            "projects": projects,
            "total": total,
            "limit": limit,
            "skip": skip,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching projects: {str(e)}")


# ============================================================
# PROJECT INVOICING ENDPOINTS
# ============================================================

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
def create_invoice_from_project(
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
def get_project_financials(project_id: str):
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
def get_projects_with_financials(
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
def get_operations_dashboard_kpis():
    """
    Get real-time KPIs for the Operations dashboard.
    Replaces mock data with actual aggregated metrics.
    """
    cache_key = _get_cache_key("dashboard_kpis")
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

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
        
        # Traffic metrics (from traffic_flow_db) — single aggregation instead of 3 separate full-scans
        try:
            traffic_pipeline = [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}}
            ]
            traffic_stats = {doc["_id"]: doc["count"] for doc in traffic_collection.aggregate(traffic_pipeline, maxTimeMS=8000)}
            total_traffic = sum(traffic_stats.values())
            completed_surveys = traffic_stats.get("COMPLETE", 0) + traffic_stats.get("complete", 0)
            terminated_surveys = (
                traffic_stats.get("TERMINATED", 0) + traffic_stats.get("terminated", 0)
                + traffic_stats.get("QUALITY_TERM", 0) + traffic_stats.get("OVERQUOTA", 0)
            )
            completion_rate = (completed_surveys / total_traffic * 100) if total_traffic > 0 else 0
        except Exception:
            total_traffic = 0
            completed_surveys = 0
            terminated_surveys = 0
            completion_rate = 0
        
        # Project value totals
        total_project_value = 0.0
        try:
            value_pipeline = [
                {"$group": {
                    "_id": None,
                    "total_value": {
                        "$sum": {
                            "$convert": {
                                "input": "$projectValue",
                                "to": "double",
                                "onError": 0,
                                "onNull": 0
                            }
                        }
                    },
                }}
            ]
            value_result = list(projects_collection.aggregate(value_pipeline))
            total_project_value = value_result[0].get("total_value", 0) if value_result else 0
        except Exception:
            # Fallback for malformed values or older Mongo operators.
            for project in projects_collection.find({}, {"projectValue": 1}):
                total_project_value += _safe_to_float(project.get("projectValue"))
        
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
        
        result = {
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
        _set_cached(cache_key, result, ttl=120)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard KPIs: {str(e)}")


@router.get("/dashboard/recent-activity")
def get_recent_activity(limit: int = Query(10, ge=1, le=50)):
    """Get recent activity across projects, invoices, and traffic"""
    cache_key = _get_cache_key("recent_activity", limit=limit)
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached
    try:
        activities = []
        
        # Recent projects (PERF: projection to fetch only needed fields)
        recent_projects = list(
            projects_collection.find(
                {},
                {"projectName": 1, "client": 1, "createdAt": 1, "updatedAt": 1}
            )
            .sort("createdAt", -1)
            .limit(limit)
        )
        for proj in recent_projects:
            proj_timestamp = (
                _safe_to_datetime(proj.get("createdAt"))
                or _safe_to_datetime(proj.get("updatedAt"))
            )
            activities.append({
                "type": "project",
                "action": "created",
                "title": proj.get("projectName", "Unknown Project"),
                "subtitle": f"Client: {proj.get('client', 'N/A')}",
                "timestamp": proj_timestamp,
                "id": str(proj["_id"])
            })
        
        # Recent invoices linked to projects (PERF: projection)
        recent_invoices = list(
            invoices_collection.find(
                {"project_id": {"$exists": True, "$ne": None}},
                {"invoice_number": 1, "total_amount": 1, "created_at": 1, "createdAt": 1, "updated_at": 1}
            )
            .sort("created_at", -1)
            .limit(limit)
        )
        for inv in recent_invoices:
            inv["total_amount"] = _safe_to_float(inv.get("total_amount"))
            inv["created_at"] = (
                _safe_to_datetime(inv.get("created_at"))
                or _safe_to_datetime(inv.get("createdAt"))
                or _safe_to_datetime(inv.get("updated_at"))
            )
            activities.append({
                "type": "invoice",
                "action": "created",
                "title": inv.get("invoice_number", "Unknown Invoice"),
                "subtitle": f"Amount: INR {inv.get('total_amount', 0):,.2f}",
                "timestamp": inv.get("created_at"),
                "id": str(inv["_id"])
            })
        
        # Sort all activities by timestamp
        activities.sort(key=lambda x: x.get("timestamp") or datetime.min, reverse=True)
        
        # Format timestamps
        for activity in activities:
            ts = activity.get("timestamp")
            if isinstance(ts, datetime):
                activity["timestamp"] = ts.isoformat()
            elif ts:
                parsed = _safe_to_datetime(ts)
                activity["timestamp"] = parsed.isoformat() if parsed else str(ts)
            else:
                activity["timestamp"] = None
        
        result = {"activities": activities[:limit]}
        _set_cached(cache_key, result, ttl=60)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recent activity: {str(e)}")


# ============================================================================
# ASYNC TASK MANAGEMENT ENDPOINTS
# For tracking long-running operations like email sync and AI processing
# ============================================================================

@router.get("/async/{operation_id}/status")
def get_async_operation_status(operation_id: str = Path(..., description="Operation ID")):
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
def cancel_async_operation(operation_id: str = Path(..., description="Operation ID")):
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
def list_active_async_operations(
    type: Optional[str] = Query(None, description="Filter by operation type (email_sync, ai_processing)")
):
    """
    List all active (running) async operations.
    """
    try:
        from tasks.api_tasks import list_active_operations as list_ops
        
        result = list_ops(type)
        return result
        
    except ImportError:
        return {"operations": [], "count": 0, "message": "Async task system not configured"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# ============================================================
# POTENTIAL CLIENT ENRICHMENT ENDPOINTS
# Uses OpenAI Web Search to gather lead/company information
# ============================================================

@router.get("/potential-clients/enriched")
def get_enriched_potential_clients(
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    skip: int = Query(0, ge=0, description="Records to skip for pagination"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confidence score filter")
):
    """
    Get all enriched potential clients with their lead/company data.
    Returns cached enrichment data from web search.
    """
    try:
        from leads.web_search_enrichment import get_all_enriched_leads, get_enrichment_stats
        
        leads = get_all_enriched_leads(limit=limit, skip=skip, min_confidence=min_confidence)
        stats = get_enrichment_stats()
        
        return {
            "leads": leads,
            "count": len(leads),
            "stats": stats
        }
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching enriched leads: {str(e)}")


@router.get("/potential-clients/enriched/{company_name}")
def get_enriched_client(company_name: str = Path(..., description="Company name to look up")):
    """
    Get enriched data for a specific potential client by company name.
    Returns cached data if available.
    """
    try:
        from leads.web_search_enrichment import get_enriched_lead
        
        lead = get_enriched_lead(company_name)
        
        if not lead:
            raise HTTPException(status_code=404, detail=f"No enriched data found for {company_name}")
        
        return lead
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching enriched lead: {str(e)}")


@router.post("/potential-clients/enrich")
def enrich_potential_client(
    company_name: str = Body(..., embed=True, description="Company name to enrich"),
    additional_context: Optional[str] = Body(None, embed=True, description="Additional context for enrichment"),
    force_refresh: bool = Body(False, embed=True, description="Force fresh web search, bypass cache")
):
    """
    Enrich a single potential client using OpenAI web search.
    Performs live web search to gather company and lead contact information.
    
    Returns detailed lead and company data including:
    - Lead Information: email, name, LinkedIn, title, department, seniority, etc.
    - Company Details: founded, headquarters, industry, employee count, revenue range, etc.
    """
    try:
        from leads.web_search_enrichment import enrich_company_with_websearch
        
        result = enrich_company_with_websearch(
            company_name=company_name,
            additional_context=additional_context,
            force_refresh=force_refresh
        )
        
        if result.get("error"):
            error_msg = result["error"]
            # Provide clearer error messages for known issues
            if "401" in str(error_msg) or "invalid_api_key" in str(error_msg).lower():
                raise HTTPException(
                    status_code=503, 
                    detail="OpenAI API key is invalid or expired. Please update the API key in Settings."
                )
            elif "rate limit" in str(error_msg).lower():
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
            raise HTTPException(status_code=422, detail=error_msg)
        
        return result
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error enriching client: {str(e)}")


@router.post("/potential-clients/enrich-batch")
def batch_enrich_potential_clients(
    company_names: List[str] = Body(..., embed=True, description="List of company names to enrich"),
    delay_seconds: float = Body(2.0, embed=True, description="Delay between API calls")
):
    """
    Batch enrich multiple potential clients using OpenAI web search.
    Includes rate limiting to avoid API throttling.
    
    Max 10 companies per batch for safety. Use auto-enrich for larger batches.
    """
    if len(company_names) > 10:
        raise HTTPException(
            status_code=400, 
            detail="Maximum 10 companies per batch. Use auto-enrich for larger lists."
        )
    
    try:
        from leads.web_search_enrichment import batch_enrich_companies
        
        results = batch_enrich_companies(
            company_names=company_names,
            delay_between_requests=delay_seconds
        )
        
        success_count = len([r for r in results if r.get("success", False)])
        
        return {
            "results": results,
            "total": len(company_names),
            "success_count": success_count,
            "failure_count": len(company_names) - success_count
        }
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error batch enriching clients: {str(e)}")


@router.post("/potential-clients/auto-enrich")
async def auto_enrich_new_potential_clients(
    company_names: List[str] = Body(..., embed=True, description="List of all current company names")
):
    """
    Auto-enrich new potential clients that haven't been enriched yet.
    Compares against existing enriched data and only processes new companies.
    
    Rate limited to 10 companies per call, with 3 second delays between requests.
    Returns count of enriched vs remaining to process.
    """
    try:
        from leads.web_search_enrichment import auto_enrich_new_companies
        import asyncio
        
        result = await auto_enrich_new_companies(company_names)
        return result
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error auto-enriching clients: {str(e)}")


@router.get("/potential-clients/enrichment-stats")
def get_potential_client_enrichment_stats():
    """
    Get statistics about potential client enrichment.
    Includes total enriched, high confidence count, and recent activity.
    """
    try:
        from leads.web_search_enrichment import get_enrichment_stats
        
        stats = get_enrichment_stats()
        return stats
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/potential-clients/unenriched")
def get_unenriched_potential_clients(
    company_names: List[str] = Query(..., description="List of all company names to check")
):
    """
    Get list of companies that haven't been enriched yet.
    Useful for identifying which companies need enrichment.
    """
    try:
        from leads.web_search_enrichment import get_unenriched_companies
        
        unenriched = get_unenriched_companies(company_names)
        
        return {
            "unenriched": unenriched,
            "count": len(unenriched),
            "total_checked": len(company_names)
        }
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Enrichment module not available: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# POTENTIAL CLIENTS ROSTER PERSISTENCE
# Stores the shared client roster in MongoDB so all users/devices
# see the same list rather than device-local localStorage.
# ============================================================
_ROSTER_DOC_ID = "potential_clients_roster"
_app_settings_collection = operations_db["app_settings"]


@router.get("/potential-clients/roster")
def get_clients_roster():
    """Return the persisted potential-client roster (shared across all users and devices)."""
    try:
        doc = _app_settings_collection.find_one({"_id": _ROSTER_DOC_ID})
        return {"roster": doc.get("clients", []) if doc else []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/potential-clients/roster")
def save_clients_roster(payload: Dict[str, Any] = Body(...)):
    """
    Save / merge the potential-client roster.
    Expected body: {"clients": [{"key": "...", "name": "..."}, ...]}
    """
    try:
        clients_data = payload.get("clients", [])
        if not isinstance(clients_data, list):
            raise HTTPException(status_code=422, detail="'clients' must be a list")
        _app_settings_collection.update_one(
            {"_id": _ROSTER_DOC_ID},
            {"$set": {"clients": clients_data, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        return {"ok": True, "count": len(clients_data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Project close → final invoice + CA package (Step 8)
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/close")
def close_project(
    project_id: str,
    payload: Dict[str, Any] = Body(default={}),
):
    """
    Close a project. Raises a final invoice for remaining unbilled value
    unless skip_final_invoice=true.
    """
    try:
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.get("status") in ("completed", "closed"):
            return {"message": "Project already closed", "project_id": project_id,
                    "status": project.get("status")}

        now = datetime.utcnow()
        skip_invoice = bool(payload.get("skip_final_invoice", False))
        notes = payload.get("notes") or ""
        invoice_result = None

        if not skip_invoice:
            project_value = float(project.get("projectValue") or project.get("amount") or 0)
            already = sum(float(i.get("total_amount") or 0)
                          for i in invoices_collection.find({"project_id": project_id}))
            remaining = max(0.0, project_value - already)
            if remaining > 0:
                invoice_result = create_invoice_from_project(
                    project_id,
                    {
                        "items": [{
                            "description": f"Final billing — {project.get('projectName') or project.get('name') or 'Project'}",
                            "quantity": 1,
                            "rate": remaining,
                            "tax_rate": payload.get("tax_rate", 18),
                        }],
                        "notes": notes or "Final invoice on project close",
                        "customer_id": payload.get("customer_id")
                            or project.get("customer_id")
                            or project.get("finance_customer_id"),
                    },
                )

        projects_collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": {"status": "completed", "closed_at": now,
                      "close_notes": notes, "updated_at": now}},
        )
        return {
            "message": "Project closed",
            "project_id": project_id,
            "status": "completed",
            "closed_at": now.isoformat(),
            "final_invoice": invoice_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error closing project: {e}")


@router.get("/projects/{project_id}/ca-package")
def get_project_ca_package(project_id: str):
    """Assemble invoices, payments, bills for CA tax filing."""
    try:
        project = projects_collection.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project = serialize_doc(project)
        invoices = [serialize_doc(i) for i in invoices_collection.find({"project_id": project_id})]
        invoice_ids = [i.get("_id") for i in invoices if i.get("_id")]
        payments = []
        if invoice_ids:
            payments = [serialize_doc(p) for p in payments_received_collection.find({
                "$or": [{"project_id": project_id}, {"invoice_id": {"$in": invoice_ids}}]
            })]
        bills = []
        try:
            bills = [serialize_doc(b) for b in bills_collection.find({"project_id": project_id})]
        except Exception:
            pass
        invoiced = sum(float(i.get("total_amount") or 0) for i in invoices)
        received = sum(float(p.get("amount") or p.get("amount_received") or 0) for p in payments)
        return {
            "project": {
                "id": project.get("_id"),
                "name": project.get("projectName") or project.get("name"),
                "client": project.get("client"),
                "status": project.get("status"),
                "closed_at": project.get("closed_at"),
                "project_value": project.get("projectValue") or project.get("amount"),
            },
            "invoices": invoices,
            "payments_received": payments,
            "bills": bills,
            "summary": {
                "invoiced_total": invoiced,
                "received_total": received,
                "outstanding": max(0.0, invoiced - received),
                "invoice_count": len(invoices),
                "payment_count": len(payments),
            },
            "generated_at": datetime.utcnow().isoformat(),
            "purpose": "CA tax filing package",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error building CA package: {e}")
