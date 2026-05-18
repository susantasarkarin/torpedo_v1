"""
Finance Router - Complete CRUD endpoints for the Finance Module
Handles: Customers, Vendors, Items, Invoices, Bills, Purchase Orders, Expenses, Payments
"""

from fastapi import APIRouter, HTTPException, Body, Path, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import os
import csv
import io
from dotenv import load_dotenv

# RBAC imports for permission enforcement
try:
    from ..rbac.decorators import require_permission, require_any_permission
    from ..rbac.permissions import Permissions
except ImportError:
    try:
        from rbac.decorators import require_permission, require_any_permission
        from rbac.permissions import Permissions
    except ImportError:
        # Fallback: RBAC not available, create no-op decorators
        def require_permission(perm):
            def decorator(func):
                return func
            return decorator
        def require_any_permission(*perms):
            def decorator(func):
                return func
            return decorator
        class Permissions:
            FINANCE_INVOICE_READ = "finance.invoice.read"
            FINANCE_INVOICE_CREATE = "finance.invoice.create"
            FINANCE_INVOICE_UPDATE = "finance.invoice.update"
            FINANCE_INVOICE_DELETE = "finance.invoice.delete"
            FINANCE_BILL_READ = "finance.bill.read"
            FINANCE_BILL_CREATE = "finance.bill.create"
            FINANCE_BILL_UPDATE = "finance.bill.update"
            FINANCE_BILL_DELETE = "finance.bill.delete"
            ADMIN_ALL = "admin.*"

load_dotenv()

# ----------------------------
# Router Setup
# ----------------------------
router = APIRouter(prefix="/finance", tags=["Finance"])

# ----------------------------
# MongoDB Connection
# ----------------------------
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
finance_db = client["finance_db"]

# Collections
customers_collection = finance_db["customers"]
vendors_collection = finance_db["vendors"]
items_collection = finance_db["items"]
estimates_collection = finance_db["estimates"]
invoices_collection = finance_db["invoices"]
bills_collection = finance_db["bills"]
purchase_orders_collection = finance_db["purchase_orders"]
expenses_collection = finance_db["expenses"]
payments_received_collection = finance_db["payments_received"]
payments_made_collection = finance_db["payments_made"]

# email_automation DB for contacts linking
email_automation_db = client["email_automation"]
contacts_collection = email_automation_db["contacts"]

print("✅ Finance collections initialized")


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


def generate_invoice_number() -> str:
    """Generate unique invoice number"""
    count = invoices_collection.estimated_document_count() + 1
    return f"INV-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_estimate_number() -> str:
    """Generate unique estimate number"""
    count = estimates_collection.estimated_document_count() + 1
    return f"EST-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_bill_number() -> str:
    """Generate unique bill number"""
    count = bills_collection.estimated_document_count() + 1
    return f"BILL-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_po_number() -> str:
    """Generate unique purchase order number"""
    count = purchase_orders_collection.estimated_document_count() + 1
    return f"PO-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_expense_number() -> str:
    """Generate unique expense number"""
    count = expenses_collection.estimated_document_count() + 1
    return f"EXP-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_payment_number(prefix: str = "PMT") -> str:
    """Generate unique payment number"""
    count = payments_received_collection.estimated_document_count() + payments_made_collection.estimated_document_count() + 1
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m')}-{str(count).zfill(4)}"


def generate_sku() -> str:
    """Generate unique SKU for items"""
    count = items_collection.estimated_document_count() + 1
    return f"SKU-{str(count).zfill(5)}"


def generate_customer_number() -> str:
    """Generate unique customer number based on highest existing number"""
    # Find the highest existing customer number
    last_customer = customers_collection.find_one(
        {"customer_number": {"$regex": r"^CUST-\d+$"}},
        sort=[("customer_number", -1)]
    )
    if last_customer and last_customer.get("customer_number"):
        # Extract the number part and increment
        try:
            last_num = int(last_customer["customer_number"].replace("CUST-", ""))
            return f"CUST-{str(last_num + 1).zfill(5)}"
        except ValueError:
            pass
    # Fallback: count + 1
    count = customers_collection.count_documents({}) + 1
    return f"CUST-{str(count).zfill(5)}"


def generate_vendor_number() -> str:
    """Generate unique vendor number based on highest existing number"""
    # Find the highest existing vendor number
    last_vendor = vendors_collection.find_one(
        {"vendor_number": {"$regex": r"^VEND-\d+$"}},
        sort=[("vendor_number", -1)]
    )
    if last_vendor and last_vendor.get("vendor_number"):
        # Extract the number part and increment
        try:
            last_num = int(last_vendor["vendor_number"].replace("VEND-", ""))
            return f"VEND-{str(last_num + 1).zfill(5)}"
        except ValueError:
            pass
    # Fallback: count + 1
    count = vendors_collection.count_documents({}) + 1
    return f"VEND-{str(count).zfill(5)}"


# ----------------------------
# Validation Helpers
# ----------------------------
import re

def validate_email(email: str) -> bool:
    """Validate email format"""
    if not email:
        return True  # Email is optional
    email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
    return bool(re.match(email_regex, email))


def validate_phone(phone: str) -> bool:
    """Validate phone number format - accepts any reasonable phone format"""
    if not phone:
        return True  # Phone is optional
    # Remove common separators and whitespace
    phone_clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").replace(".", "")
    # Accept any phone number with at least 7 digits (allowing country codes like +1, +44, +91, etc.)
    phone_regex = r'^\+?[0-9]{7,15}$'
    return bool(re.match(phone_regex, phone_clean))


def validate_gstin(gstin: str) -> bool:
    """Validate GSTIN format"""
    if not gstin:
        return True  # GSTIN can be optional
    gstin_regex = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$'
    return bool(re.match(gstin_regex, gstin))


def validate_pan(pan: str) -> bool:
    """Validate PAN format"""
    if not pan:
        return True  # PAN is optional
    pan_regex = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
    return bool(re.match(pan_regex, pan))


def validate_ifsc(ifsc: str) -> bool:
    """Validate IFSC code format"""
    if not ifsc:
        return True  # IFSC is optional
    ifsc_regex = r'^[A-Z]{4}0[A-Z0-9]{6}$'
    return bool(re.match(ifsc_regex, ifsc))


def is_gstin_required(gst_treatment: str) -> bool:
    """Check if GSTIN is required based on GST treatment"""
    return gst_treatment in ["registered_regular", "registered_composition"]


# ----------------------------
# CSV Column Mapping Helper
# ----------------------------
def normalize_column_name(col: str) -> str:
    """Normalize column name for flexible matching"""
    if not col:
        return ""
    # Convert to lowercase, replace spaces/special chars with underscore
    normalized = col.lower().strip()
    normalized = re.sub(r'[\s\-\.\/\(\)]+', '_', normalized)
    normalized = re.sub(r'_+', '_', normalized)
    normalized = normalized.strip('_')
    return normalized


def map_csv_columns(row: dict, column_mappings: dict) -> dict:
    """
    Map CSV columns to expected field names using flexible matching.
    column_mappings: dict of {expected_field: [list of possible column names]}
    """
    result = {}
    
    # Normalize all keys in the row
    normalized_row = {}
    original_keys = {}
    for key, value in row.items():
        norm_key = normalize_column_name(key)
        normalized_row[norm_key] = value
        original_keys[norm_key] = key
    
    for field, possible_names in column_mappings.items():
        # Try each possible column name
        value = None
        for name in possible_names:
            norm_name = normalize_column_name(name)
            if norm_name in normalized_row:
                value = normalized_row[norm_name]
                break
        result[field] = value if value is not None else ""
    
    return result


# Column mappings for different entity types
CUSTOMER_COLUMN_MAPPINGS = {
    "name": ["name", "customer_name", "customer", "company", "company_name", "client_name", "client"],
    "customer_type": ["customer_type", "type", "customer type", "cust_type"],
    "company_name": ["company_name", "company", "organization", "org_name", "organisation"],
    "email": ["email", "email_address", "e-mail", "mail", "customer_email", "email id", "emailid"],
    "phone": ["phone", "phone_number", "mobile", "contact", "telephone", "tel", "mobile_number", "contact_number"],
    "gst_treatment": ["gst_treatment", "gst treatment", "gst_type", "tax_type"],
    "gstin": ["gstin", "gst_number", "gst_no", "gst", "gst number", "gstin_number"],
    "pan": ["pan", "pan_number", "pan_no", "pan number"],
    "billing_address_line1": ["billing_address_line1", "billing_address", "address", "address_line1", "street", "billing address"],
    "billing_address_city": ["billing_address_city", "city", "billing_city"],
    "billing_address_state": ["billing_address_state", "state", "billing_state"],
    "billing_address_pincode": ["billing_address_pincode", "pincode", "zip", "postal_code", "zip_code", "billing_pincode"],
    "payment_terms": ["payment_terms", "payment terms", "terms", "credit_days", "credit days"],
    "credit_limit": ["credit_limit", "credit limit", "credit"],
    "currency": ["currency", "currency_code", "curr"],
    "opening_balance": ["opening_balance", "opening balance", "balance", "open_balance"],
    "status": ["status", "customer_status", "active"],
    "notes": ["notes", "remarks", "comments", "description"],
}

VENDOR_COLUMN_MAPPINGS = {
    "name": ["name", "vendor_name", "vendor", "supplier_name", "supplier", "company_name", "company"],
    "vendor_type": ["vendor_type", "type", "supplier_type"],
    "company_name": ["company_name", "company", "organization", "org_name"],
    "email": ["email", "email_address", "e-mail", "mail", "vendor_email"],
    "phone": ["phone", "phone_number", "mobile", "contact", "telephone", "tel"],
    "gst_treatment": ["gst_treatment", "gst treatment", "gst_type"],
    "gstin": ["gstin", "gst_number", "gst_no", "gst", "gst number"],
    "pan": ["pan", "pan_number", "pan_no"],
    "billing_address_line1": ["billing_address_line1", "billing_address", "address", "address_line1", "street"],
    "billing_address_city": ["billing_address_city", "city", "billing_city"],
    "billing_address_state": ["billing_address_state", "state", "billing_state"],
    "billing_address_pincode": ["billing_address_pincode", "pincode", "zip", "postal_code"],
    "bank_name": ["bank_name", "bank", "bank name"],
    "account_number": ["account_number", "account_no", "account", "acc_number", "acc_no"],
    "ifsc_code": ["ifsc_code", "ifsc", "ifsc code"],
    "payment_terms": ["payment_terms", "payment terms", "terms"],
    "currency": ["currency", "currency_code"],
    "opening_balance": ["opening_balance", "opening balance", "balance"],
    "status": ["status", "vendor_status", "active"],
    "notes": ["notes", "remarks", "comments"],
}

INVOICE_COLUMN_MAPPINGS = {
    "invoice_number": ["invoice_number", "invoice_no", "invoice no", "invoice#", "inv_number", "inv_no", "invoice"],
    "customer_name": ["customer_name", "customer", "client_name", "client", "company_name", "company", "bill_to"],
    "invoice_date": ["invoice_date", "date", "inv_date", "invoice date", "created_date"],
    "due_date": ["due_date", "due", "payment_date", "due date", "payment due"],
    "currency_code": ["currency_code", "currency", "curr"],
    "subtotal": ["subtotal", "sub_total", "sub total", "amount_before_tax"],
    "tax_amount": ["tax_amount", "tax", "gst", "tax_total", "total_tax"],
    "discount_type": ["discount_type", "discount type"],
    "discount_value": ["discount_value", "discount", "disc"],
    "total": ["total", "total_amount", "grand_total", "amount", "invoice_amount", "invoice total"],
    "balance_due": ["balance_due", "balance", "due_amount", "outstanding"],
    "status": ["status", "invoice_status", "inv_status"],
    "payment_status": ["payment_status", "paid_status", "payment status"],
    "po_reference": ["po_reference", "po_number", "po", "purchase_order", "po reference"],
    "notes": ["notes", "remarks", "comments", "description", "memo"],
}

ESTIMATE_COLUMN_MAPPINGS = {
    "estimate_number": ["estimate_number", "estimate_no", "estimate no", "estimate#", "est_number", "est_no", "estimate", "quote_number", "quote"],
    "customer_name": ["customer_name", "customer", "client_name", "client", "company_name", "company", "bill_to"],
    "estimate_date": ["estimate_date", "date", "est_date", "estimate date", "created_date", "quote_date"],
    "expiry_date": ["expiry_date", "expiry", "valid_until", "valid_till", "expiry date", "expires"],
    "reference": ["reference", "ref", "reference_number", "ref_no"],
    "currency_code": ["currency_code", "currency", "curr"],
    "subtotal": ["subtotal", "sub_total", "sub total", "amount_before_tax"],
    "tax_amount": ["tax_amount", "tax", "gst", "tax_total", "total_tax"],
    "discount_type": ["discount_type", "discount type"],
    "discount_value": ["discount_value", "discount", "disc"],
    "total": ["total", "total_amount", "grand_total", "amount", "estimate_amount", "estimate total"],
    "status": ["status", "estimate_status", "est_status"],
    "notes": ["notes", "remarks", "comments", "description", "memo"],
    "terms": ["terms", "terms_and_conditions", "terms and conditions", "conditions"],
}

BILL_COLUMN_MAPPINGS = {
    "bill_number": ["bill_number", "bill_no", "bill no", "bill#", "vendor_invoice", "vendor_bill", "bill"],
    "vendor_name": ["vendor_name", "vendor", "supplier_name", "supplier", "company_name", "from"],
    "bill_date": ["bill_date", "date", "invoice_date", "bill date"],
    "due_date": ["due_date", "due", "payment_date", "due date"],
    "currency_code": ["currency_code", "currency", "curr"],
    "subtotal": ["subtotal", "sub_total", "sub total"],
    "tax_amount": ["tax_amount", "tax", "gst", "tax_total"],
    "total_amount": ["total_amount", "total", "amount", "grand_total", "bill_amount"],
    "balance_due": ["balance_due", "balance", "due_amount", "outstanding"],
    "status": ["status", "bill_status"],
    "notes": ["notes", "remarks", "comments", "description"],
}

ITEM_COLUMN_MAPPINGS = {
    "name": ["name", "item_name", "item", "product_name", "product", "service_name", "service", "description"],
    "sku": ["sku", "item_code", "code", "product_code", "item_id"],
    "description": ["description", "desc", "details", "item_description"],
    "type": ["type", "item_type", "product_type"],
    "unit": ["unit", "uom", "unit_of_measure", "measure"],
    "selling_price": ["selling_price", "sale_price", "price", "rate", "unit_price", "sell_price"],
    "purchase_price": ["purchase_price", "cost", "cost_price", "buy_price"],
    "tax_rate": ["tax_rate", "tax", "gst_rate", "tax_percent", "tax_percentage", "gst"],
    "hsn_sac_code": ["hsn_sac_code", "hsn", "sac", "hsn_code", "sac_code", "hsn/sac"],
    "track_inventory": ["track_inventory", "inventory", "track_stock"],
    "stock_quantity": ["stock_quantity", "stock", "quantity", "qty", "on_hand"],
    "low_stock_threshold": ["low_stock_threshold", "reorder_level", "min_stock", "low_stock"],
    "status": ["status", "item_status", "active"],
}


# ============================================================
# CUSTOMERS ENDPOINTS
# ============================================================

@router.get("/customers/")
async def get_customers(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by name, email, phone, or GSTIN"),
):
    """Get customers with linked contacts (paginated)"""
    import asyncio as _asyncio
    try:
        def _fetch():
            query = {}
            if search:
                query["$or"] = [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"phone": {"$regex": search, "$options": "i"}},
                    {"gstin": {"$regex": search, "$options": "i"}},
                    {"customer_number": {"$regex": search, "$options": "i"}},
                ]
            total = customers_collection.count_documents(query)
            skip = (page - 1) * page_size
            customers = list(customers_collection.find(query).sort("name", 1).skip(skip).limit(page_size))
            all_contacts = list(contacts_collection.find(
                {}, {"_id": 1, "name": 1, "firstName": 1, "lastName": 1,
                     "email": 1, "title": 1, "stage": 1,
                     "linked_customer_id": 1, "companyName": 1}
            ))
            contacts_by_customer_id: dict = {}
            contacts_by_company_name: dict = {}
            for contact in all_contacts:
                entry = {
                    "_id": str(contact["_id"]),
                    "name": contact.get("name") or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip(),
                    "email": contact.get("email", ""),
                    "title": contact.get("title", ""),
                    "stage": contact.get("stage", ""),
                }
                if contact.get("linked_customer_id"):
                    contacts_by_customer_id.setdefault(contact["linked_customer_id"], []).append(entry)
                if contact.get("companyName"):
                    contacts_by_company_name.setdefault(contact["companyName"], []).append(entry)
            result = []
            for customer in customers:
                cust_id = str(customer["_id"])
                company_name = customer.get("company_name") or customer.get("name")
                linked_contacts = contacts_by_customer_id.get(cust_id, [])
                if not linked_contacts and company_name:
                    linked_contacts = contacts_by_company_name.get(company_name, [])
                customer["linked_contacts"] = linked_contacts
                customer["linked_contacts_count"] = len(linked_contacts)
                result.append(customer)
            return result, total
        result, total = await _asyncio.to_thread(_fetch)
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "customers": serialize_docs(result),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching customers: {str(e)}")


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Get a single customer by ID"""
    try:
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        return serialize_doc(customer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching customer: {str(e)}")


@router.post("/customers/")
async def create_customer(customer_data: Dict[str, Any] = Body(...)):
    """Create a new customer with validation"""
    try:
        # Validate required fields
        if not customer_data.get("name"):
            raise HTTPException(status_code=400, detail="Customer name is required")
        
        # Validate email format
        if not validate_email(customer_data.get("email", "")):
            raise HTTPException(status_code=400, detail="Invalid email format")
        
        # Validate phone format
        if not validate_phone(customer_data.get("phone", "")):
            raise HTTPException(status_code=400, detail="Invalid phone number format")
        
        # Validate GST treatment and GSTIN
        gst_treatment = customer_data.get("gst_treatment", "unregistered")
        gstin = customer_data.get("gstin", "")
        
        if is_gstin_required(gst_treatment) and not gstin:
            raise HTTPException(
                status_code=400, 
                detail="GSTIN is required for Registered Business - Regular or Composition"
            )
        
        if gstin and not validate_gstin(gstin):
            raise HTTPException(status_code=400, detail="Invalid GSTIN format (e.g., 29ABCDE1234F1Z5)")
        
        # Validate PAN format
        if not validate_pan(customer_data.get("pan", "")):
            raise HTTPException(status_code=400, detail="Invalid PAN format (e.g., ABCDE1234F)")
        
        customer_data["created_at"] = datetime.utcnow()
        customer_data["updated_at"] = datetime.utcnow()
        customer_data["total_receivables"] = 0
        customer_data["total_paid"] = 0
        
        # Generate customer number if not provided
        if not customer_data.get("customer_number"):
            customer_data["customer_number"] = generate_customer_number()
        
        result = customers_collection.insert_one(customer_data)
        customer_data["_id"] = str(result.inserted_id)
        return customer_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating customer: {str(e)}")


@router.put("/customers/{customer_id}")
async def update_customer(customer_id: str, customer_data: Dict[str, Any] = Body(...)):
    """Update a customer"""
    try:
        current_customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not current_customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        customer_data.pop("_id", None)
        customer_data["updated_at"] = datetime.utcnow()
        
        result = customers_collection.update_one(
            {"_id": ObjectId(customer_id)},
            {"$set": customer_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        return {"message": "Customer updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating customer: {str(e)}")


@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str):
    """Delete a customer"""
    try:
        # Check if customer has invoices
        invoice_count = invoices_collection.count_documents({"customer_id": customer_id})
        if invoice_count > 0:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot delete customer with {invoice_count} invoices. Delete invoices first."
            )
        
        customer = customers_collection.find_one({"_id": ObjectId(customer_id)})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        
        customers_collection.delete_one({"_id": ObjectId(customer_id)})
        
        return {"message": "Customer deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting customer: {str(e)}")


@router.post("/customers/bulk-delete")
async def bulk_delete_customers(data: Dict[str, Any] = Body(...)):
    """Delete multiple customers by their IDs"""
    try:
        ids = data.get("ids", [])
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        # Check for customers with invoices
        object_ids = [ObjectId(id) for id in ids]
        customers_with_invoices = []
        for oid in object_ids:
            invoice_count = invoices_collection.count_documents({"customer_id": str(oid)})
            if invoice_count > 0:
                customer = customers_collection.find_one({"_id": oid})
                if customer:
                    customers_with_invoices.append(customer.get("name", str(oid)))
        
        if customers_with_invoices:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete customers with invoices: {', '.join(customers_with_invoices[:5])}"
            )
        
        result = customers_collection.delete_many({"_id": {"$in": object_ids}})
        
        return {
            "message": f"Successfully deleted {result.deleted_count} customers",
            "deleted_count": result.deleted_count
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete error: {str(e)}")


@router.get("/customers/export/csv")
async def export_customers_csv():
    """Export all customers to CSV format"""
    try:
        customers = list(customers_collection.find().sort("name", 1))
        
        output = io.StringIO()
        fieldnames = [
            "name", "customer_type", "company_name", "email", "phone", 
            "gst_treatment", "gstin", "pan", "billing_address_line1", "billing_address_city",
            "billing_address_state", "billing_address_pincode", "payment_terms", 
            "credit_limit", "currency", "opening_balance", "status", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for customer in customers:
            billing = customer.get("billing_address", {})
            row = {
                "name": customer.get("name", ""),
                "customer_type": customer.get("customer_type", "business"),
                "company_name": customer.get("company_name", ""),
                "email": customer.get("email", ""),
                "phone": customer.get("phone", ""),
                "gst_treatment": customer.get("gst_treatment", ""),
                "gstin": customer.get("gstin", ""),
                "pan": customer.get("pan", ""),
                "billing_address_line1": billing.get("line1", ""),
                "billing_address_city": billing.get("city", ""),
                "billing_address_state": billing.get("state", ""),
                "billing_address_pincode": billing.get("pincode", ""),
                "payment_terms": customer.get("payment_terms", 30),
                "credit_limit": customer.get("credit_limit", 0),
                "currency": customer.get("currency", "INR"),
                "opening_balance": customer.get("opening_balance", 0),
                "status": customer.get("status", "active"),
                "notes": customer.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=customers_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting customers: {str(e)}")


@router.post("/customers/import/csv")
async def import_customers_csv(file: UploadFile = File(...)):
    """Import customers from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, CUSTOMER_COLUMN_MAPPINGS)
                
                name = mapped.get("name", "").strip()
                if not name:
                    errors.append(f"Row {idx}: Customer name is required")
                    continue
                
                # Check if customer already exists
                existing = customers_collection.find_one({"name": name})
                if existing:
                    errors.append(f"Row {idx}: Customer '{name}' already exists")
                    continue
                
                customer_data = {
                    "name": name,
                    "customer_number": generate_customer_number(),
                    "customer_type": mapped.get("customer_type") or "business",
                    "company_name": mapped.get("company_name", ""),
                    "email": mapped.get("email", ""),
                    "phone": mapped.get("phone", ""),
                    "gst_treatment": mapped.get("gst_treatment") or "unregistered",
                    "gstin": mapped.get("gstin", ""),
                    "pan": mapped.get("pan", ""),
                    "billing_address": {
                        "line1": mapped.get("billing_address_line1", ""),
                        "city": mapped.get("billing_address_city", ""),
                        "state": mapped.get("billing_address_state", ""),
                        "pincode": mapped.get("billing_address_pincode", ""),
                        "country": "India"
                    },
                    "payment_terms": int(mapped.get("payment_terms") or 30),
                    "credit_limit": float(mapped.get("credit_limit") or 0),
                    "currency": mapped.get("currency") or "INR",
                    "opening_balance": float(mapped.get("opening_balance") or 0),
                    "status": mapped.get("status") or "active",
                    "notes": mapped.get("notes", ""),
                    "total_receivables": 0,
                    "total_paid": 0,
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                customers_collection.insert_one(customer_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} customers",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing customers: {str(e)}")


# ============================================================
# VENDORS ENDPOINTS
# ============================================================

@router.get("/vendors/")
async def get_vendors(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by name, email, or GSTIN"),
):
    """Get vendors (paginated)"""
    try:
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
                {"gstin": {"$regex": search, "$options": "i"}},
            ]
        total = vendors_collection.count_documents(query)
        skip = (page - 1) * page_size
        vendors = list(vendors_collection.find(query).sort("name", 1).skip(skip).limit(page_size))
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "vendors": serialize_docs(vendors),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vendors: {str(e)}")


# NOTE: This endpoint must be before {vendor_id} to avoid route conflicts
@router.get("/vendors/panel-vendors")
async def get_panel_vendors_for_linking():
    """
    Get all Operations panel vendors available for linking.
    Returns only vendors not yet linked to a finance vendor.
    """
    try:
        ops_db = client["email_automation"]
        ops_vendors = ops_db["vendors"]
        
        # Get panel vendors without finance link
        panel_vendors = list(ops_vendors.find(
            {"finance_vendor_id": {"$exists": False}},
            {"vendorName": 1, "vendorEmail": 1, "vid": 1, "vendorType": 1}
        ).sort("vendorName", 1))
        
        return [
            {
                "_id": str(v["_id"]),
                "vid": v.get("vid"),
                "name": v.get("vendorName"),
                "email": v.get("vendorEmail"),
                "type": v.get("vendorType", "Panel")
            }
            for v in panel_vendors
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching panel vendors: {str(e)}")


@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str):
    """Get a single vendor by ID"""
    try:
        vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return serialize_doc(vendor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vendor: {str(e)}")


@router.post("/vendors/")
async def create_vendor(vendor_data: Dict[str, Any] = Body(...)):
    """Create a new vendor with validation"""
    try:
        # Validate required fields
        if not vendor_data.get("name"):
            raise HTTPException(status_code=400, detail="Vendor name is required")
        
        # Validate email format
        if not validate_email(vendor_data.get("email", "")):
            raise HTTPException(status_code=400, detail="Invalid email format")
        
        # Validate phone format
        if not validate_phone(vendor_data.get("phone", "")):
            raise HTTPException(status_code=400, detail="Invalid phone number format")
        
        # Validate GST treatment and GSTIN
        gst_treatment = vendor_data.get("gst_treatment", "unregistered")
        gstin = vendor_data.get("gstin", "")
        
        if is_gstin_required(gst_treatment) and not gstin:
            raise HTTPException(
                status_code=400, 
                detail="GSTIN is required for Registered Business - Regular or Composition"
            )
        
        if gstin and not validate_gstin(gstin):
            raise HTTPException(status_code=400, detail="Invalid GSTIN format (e.g., 29ABCDE1234F1Z5)")
        
        # Validate PAN format
        if not validate_pan(vendor_data.get("pan", "")):
            raise HTTPException(status_code=400, detail="Invalid PAN format (e.g., ABCDE1234F)")
        
        # Validate IFSC code
        if not validate_ifsc(vendor_data.get("ifsc_code", "")):
            raise HTTPException(status_code=400, detail="Invalid IFSC format (e.g., SBIN0001234)")
        
        vendor_data["created_at"] = datetime.utcnow()
        vendor_data["updated_at"] = datetime.utcnow()
        vendor_data["total_payables"] = 0
        vendor_data["total_paid"] = 0
        
        result = vendors_collection.insert_one(vendor_data)
        vendor_data["_id"] = str(result.inserted_id)
        return vendor_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating vendor: {str(e)}")


@router.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, vendor_data: Dict[str, Any] = Body(...)):
    """Update a vendor"""
    try:
        vendor_data.pop("_id", None)
        vendor_data["updated_at"] = datetime.utcnow()
        
        result = vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {"$set": vendor_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating vendor: {str(e)}")


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: str):
    """
    Soft delete a billing vendor with safety checks.
    - Blocks if vendor has outstanding balance_due
    - Blocks if vendor has unpaid bills
    """
    try:
        # First check if the vendor exists
        vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        
        # Safety Check 1: Check for outstanding balance
        balance_due = vendor.get("balance_due", 0)
        if balance_due and float(balance_due) > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete vendor with outstanding balance of ${balance_due:.2f}. Clear balance first."
            )
        
        # Safety Check 2: Check for unpaid bills
        unpaid_bill_count = bills_collection.count_documents({
            "vendor_id": vendor_id,
            "status": {"$in": ["draft", "pending", "overdue", "partial"]}
        })
        if unpaid_bill_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete vendor with {unpaid_bill_count} unpaid bills. Pay or void bills first."
            )
        
        # Safety Check 3: Check if vendor has any bills at all (existing check, but modified message)
        bill_count = bills_collection.count_documents({"vendor_id": vendor_id})
        if bill_count > 0:
            # Soft delete - keep for historical records
            result = vendors_collection.update_one(
                {"_id": ObjectId(vendor_id)},
                {
                    "$set": {
                        "is_deleted": True,
                        "deleted_at": datetime.utcnow(),
                        "status": "archived"
                    }
                }
            )
            if result.matched_count == 0:
                raise HTTPException(status_code=404, detail="Vendor not found")
            return {"message": f"Vendor archived (soft delete) - has {bill_count} historical bills"}
        
        # No bills - perform soft delete anyway for consistency
        result = vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {"message": "Vendor deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting vendor: {str(e)}")


# =============================================================================
# Vendor Integration - Link Panel Vendors from Operations
# =============================================================================

@router.post("/vendors/{vendor_id}/link-panel-vendor")
async def link_panel_vendor(
    vendor_id: str,
    panel_vendor_id: str = Body(..., embed=True, description="The Operations panel vendor ID to link")
):
    """
    Link a finance vendor to an Operations panel vendor.
    This allows tracking both billing info and survey routing info for the same vendor.
    """
    try:
        # Verify finance vendor exists
        vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})
        if not vendor:
            raise HTTPException(status_code=404, detail="Finance vendor not found")
        
        # Verify panel vendor exists in operations
        ops_db = client["email_automation"]
        ops_vendors = ops_db["vendors"]
        
        panel_vendor = None
        try:
            panel_vendor = ops_vendors.find_one({"_id": ObjectId(panel_vendor_id)})
        except:
            pass
        
        if not panel_vendor:
            # Try by vid
            panel_vendor = ops_vendors.find_one({"vid": panel_vendor_id})
        
        if not panel_vendor:
            raise HTTPException(status_code=404, detail="Operations panel vendor not found")
        
        # Update finance vendor with panel vendor link
        vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {
                "$set": {
                    "panel_vendor_id": str(panel_vendor["_id"]),
                    "panel_vendor_vid": panel_vendor.get("vid"),
                    "panel_vendor_name": panel_vendor.get("vendorName"),
                    "is_panel_vendor": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # Update panel vendor with finance vendor link
        ops_vendors.update_one(
            {"_id": panel_vendor["_id"]},
            {
                "$set": {
                    "finance_vendor_id": vendor_id,
                    "finance_vendor_name": vendor.get("name"),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Vendors linked successfully",
            "finance_vendor_id": vendor_id,
            "panel_vendor_id": str(panel_vendor["_id"]),
            "panel_vendor_vid": panel_vendor.get("vid")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error linking vendors: {str(e)}")


@router.delete("/vendors/{vendor_id}/unlink-panel-vendor")
async def unlink_panel_vendor(vendor_id: str):
    """Unlink a finance vendor from its Operations panel vendor."""
    try:
        vendor = vendors_collection.find_one({"_id": ObjectId(vendor_id)})
        if not vendor:
            raise HTTPException(status_code=404, detail="Finance vendor not found")
        
        panel_vendor_id = vendor.get("panel_vendor_id")
        
        # Update finance vendor
        vendors_collection.update_one(
            {"_id": ObjectId(vendor_id)},
            {
                "$unset": {
                    "panel_vendor_id": "",
                    "panel_vendor_vid": "",
                    "panel_vendor_name": ""
                },
                "$set": {
                    "is_panel_vendor": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # Update panel vendor if exists
        if panel_vendor_id:
            try:
                ops_db = client["email_automation"]
                ops_vendors = ops_db["vendors"]
                ops_vendors.update_one(
                    {"_id": ObjectId(panel_vendor_id)},
                    {
                        "$unset": {
                            "finance_vendor_id": "",
                            "finance_vendor_name": ""
                        },
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )
            except:
                pass
        
        return {"success": True, "message": "Vendors unlinked successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error unlinking vendors: {str(e)}")


@router.get("/vendors/export/csv")
async def export_vendors_csv():
    """Export all vendors to CSV format"""
    try:
        vendors = list(vendors_collection.find().sort("name", 1))
        
        output = io.StringIO()
        fieldnames = [
            "name", "vendor_type", "company_name", "email", "phone",
            "gst_treatment", "gstin", "pan", "billing_address_line1", "billing_address_city",
            "billing_address_state", "billing_address_pincode", "payment_terms",
            "currency", "bank_name", "account_number", "ifsc_code", 
            "opening_balance", "status", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for vendor in vendors:
            billing = vendor.get("billing_address", {})
            row = {
                "name": vendor.get("name", ""),
                "vendor_type": vendor.get("vendor_type", "supplier"),
                "company_name": vendor.get("company_name", ""),
                "email": vendor.get("email", ""),
                "phone": vendor.get("phone", ""),
                "gst_treatment": vendor.get("gst_treatment", ""),
                "gstin": vendor.get("gstin", ""),
                "pan": vendor.get("pan", ""),
                "billing_address_line1": billing.get("line1", ""),
                "billing_address_city": billing.get("city", ""),
                "billing_address_state": billing.get("state", ""),
                "billing_address_pincode": billing.get("pincode", ""),
                "payment_terms": vendor.get("payment_terms", 30),
                "currency": vendor.get("currency", "INR"),
                "bank_name": vendor.get("bank_name", ""),
                "account_number": vendor.get("account_number", ""),
                "ifsc_code": vendor.get("ifsc_code", ""),
                "opening_balance": vendor.get("opening_balance", 0),
                "status": vendor.get("status", "active"),
                "notes": vendor.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=vendors_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting vendors: {str(e)}")


@router.post("/vendors/import/csv")
async def import_vendors_csv(file: UploadFile = File(...)):
    """Import vendors from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, VENDOR_COLUMN_MAPPINGS)
                
                name = mapped.get("name", "").strip()
                if not name:
                    errors.append(f"Row {idx}: Vendor name is required")
                    continue
                
                existing = vendors_collection.find_one({"name": name})
                if existing:
                    errors.append(f"Row {idx}: Vendor '{name}' already exists")
                    continue
                
                vendor_data = {
                    "name": name,
                    "vendor_number": generate_vendor_number(),
                    "vendor_type": mapped.get("vendor_type") or "supplier",
                    "company_name": mapped.get("company_name", ""),
                    "email": mapped.get("email", ""),
                    "phone": mapped.get("phone", ""),
                    "gst_treatment": mapped.get("gst_treatment") or "unregistered",
                    "gstin": mapped.get("gstin", ""),
                    "pan": mapped.get("pan", ""),
                    "billing_address": {
                        "line1": mapped.get("billing_address_line1", ""),
                        "city": mapped.get("billing_address_city", ""),
                        "state": mapped.get("billing_address_state", ""),
                        "pincode": mapped.get("billing_address_pincode", ""),
                        "country": "India"
                    },
                    "payment_terms": int(mapped.get("payment_terms") or 30),
                    "currency": mapped.get("currency") or "INR",
                    "bank_name": mapped.get("bank_name", ""),
                    "account_number": mapped.get("account_number", ""),
                    "ifsc_code": mapped.get("ifsc_code", ""),
                    "opening_balance": float(mapped.get("opening_balance") or 0),
                    "total_payables": 0,
                    "total_paid": 0,
                    "status": mapped.get("status") or "active",
                    "notes": mapped.get("notes", ""),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                vendors_collection.insert_one(vendor_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} vendors",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing vendors: {str(e)}")


# ============================================================
# ITEMS ENDPOINTS
# ============================================================

@router.get("/items/")
async def get_items(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by name, SKU, or description"),
):
    """Get items excluding soft-deleted (paginated)"""
    try:
        query = {"is_deleted": {"$ne": True}}
        if search:
            query["$and"] = [
                {"is_deleted": {"$ne": True}},
                {"$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"sku": {"$regex": search, "$options": "i"}},
                    {"description": {"$regex": search, "$options": "i"}},
                ]},
            ]
            del query["is_deleted"]
        total = items_collection.count_documents(query)
        skip = (page - 1) * page_size
        items = list(items_collection.find(query).sort("name", 1).skip(skip).limit(page_size))
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "items": serialize_docs(items),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching items: {str(e)}")


@router.get("/items/{item_id}")
async def get_item(item_id: str):
    """
    Get a single item by ID (excluding soft-deleted).
    P0.16: Returns 404 if item is soft-deleted.
    """
    try:
        item = items_collection.find_one({"_id": ObjectId(item_id), "is_deleted": {"$ne": True}})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return serialize_doc(item)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching item: {str(e)}")


@router.post("/items/")
async def create_item(item_data: Dict[str, Any] = Body(...)):
    """Create a new item"""
    try:
        if not item_data.get("name"):
            raise HTTPException(status_code=400, detail="Item name is required")
        
        if not item_data.get("sku"):
            item_data["sku"] = generate_sku()
        
        item_data["created_at"] = datetime.utcnow()
        item_data["updated_at"] = datetime.utcnow()
        
        result = items_collection.insert_one(item_data)
        item_data["_id"] = str(result.inserted_id)
        return item_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating item: {str(e)}")


@router.put("/items/{item_id}")
async def update_item(item_id: str, item_data: Dict[str, Any] = Body(...)):
    """Update an item"""
    try:
        item_data.pop("_id", None)
        item_data["updated_at"] = datetime.utcnow()
        
        result = items_collection.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": item_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"message": "Item updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating item: {str(e)}")


@router.delete("/items/{item_id}")
async def delete_item(item_id: str):
    """
    Soft delete an item with usage validation.
    P0.17: Checks if item is used in invoices or bills before deletion.
    P0.16: Uses soft delete instead of hard delete.
    """
    try:
        item = items_collection.find_one({"_id": ObjectId(item_id)})
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        item_name = item.get("name", "")
        item_sku = item.get("sku", "")
        
        # P0.17: Check if item is used in any invoice line items
        invoice_usage = invoices_collection.count_documents({
            "is_deleted": {"$ne": True},
            "items": {
                "$elemMatch": {
                    "$or": [
                        {"item_id": item_id},
                        {"item_id": str(item_id)},
                        {"sku": item_sku},
                        {"name": item_name}
                    ]
                }
            }
        })
        if invoice_usage > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete item '{item_name}' - used in {invoice_usage} invoice(s). Remove from invoices first."
            )
        
        # P0.17: Check if item is used in any bill line items
        bill_usage = bills_collection.count_documents({
            "is_deleted": {"$ne": True},
            "items": {
                "$elemMatch": {
                    "$or": [
                        {"item_id": item_id},
                        {"item_id": str(item_id)},
                        {"sku": item_sku},
                        {"name": item_name}
                    ]
                }
            }
        })
        if bill_usage > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete item '{item_name}' - used in {bill_usage} bill(s). Remove from bills first."
            )
        
        # Soft delete - set is_deleted flag instead of removing
        result = items_collection.update_one(
            {"_id": ObjectId(item_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        return {"message": "Item deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting item: {str(e)}")


@router.get("/items/export/csv")
async def export_items_csv():
    """Export all items to CSV"""
    try:
        items = list(items_collection.find().sort("name", 1))
        
        output = io.StringIO()
        fieldnames = [
            "name", "sku", "description", "type", "unit", 
            "selling_price", "purchase_price", "tax_rate", "hsn_sac_code",
            "track_inventory", "stock_quantity", "low_stock_threshold", "status"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for item in items:
            writer.writerow({
                "name": item.get("name", ""),
                "sku": item.get("sku", ""),
                "description": item.get("description", ""),
                "type": item.get("type", "goods"),
                "unit": item.get("unit", "nos"),
                "selling_price": item.get("selling_price", 0),
                "purchase_price": item.get("purchase_price", 0),
                "tax_rate": item.get("tax_rate", 18),
                "hsn_sac_code": item.get("hsn_sac_code", ""),
                "track_inventory": item.get("track_inventory", True),
                "stock_quantity": item.get("stock_quantity", 0),
                "low_stock_threshold": item.get("low_stock_threshold", 10),
                "status": item.get("status", "active"),
            })
        
        output.seek(0)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=items_export.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting items: {str(e)}")


@router.post("/items/import/csv")
async def import_items_csv(file: UploadFile = File(...)):
    """Import items from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, ITEM_COLUMN_MAPPINGS)
                
                name = mapped.get("name", "").strip()
                sku = mapped.get("sku", "").strip()
                
                if not name:
                    errors.append(f"Row {idx}: Item name is required")
                    continue
                
                # Check if item already exists by SKU or name
                existing = items_collection.find_one({
                    "$or": [
                        {"sku": sku} if sku else {"sku": ""},
                        {"name": name}
                    ]
                })
                if existing:
                    errors.append(f"Row {idx}: Item '{name}' or SKU '{sku}' already exists")
                    continue
                
                item_data = {
                    "name": name,
                    "sku": sku or generate_sku(),
                    "description": mapped.get("description", ""),
                    "type": mapped.get("type") or "goods",
                    "unit": mapped.get("unit") or "nos",
                    "selling_price": float(mapped.get("selling_price") or 0),
                    "purchase_price": float(mapped.get("purchase_price") or 0),
                    "tax_rate": float(mapped.get("tax_rate") or 18),
                    "hsn_sac_code": mapped.get("hsn_sac_code", ""),
                    "track_inventory": str(mapped.get("track_inventory") or "true").lower() in ("true", "1", "yes"),
                    "stock_quantity": int(float(mapped.get("stock_quantity") or 0)),
                    "low_stock_threshold": int(float(mapped.get("low_stock_threshold") or 10)),
                    "status": mapped.get("status") or "active",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                items_collection.insert_one(item_data)
                imported_count += 1
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        return {"imported": imported_count, "errors": errors}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing items: {str(e)}")


# ============================================================
# ESTIMATES ENDPOINTS
# ============================================================

@router.get("/estimates/")
async def get_estimates(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by estimate number or customer name"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """Get estimates with customer details, paginated"""
    try:
        match_stage = {"is_deleted": {"$ne": True}}
        if status:
            match_stage["status"] = status
        if search:
            match_stage["$or"] = [
                {"estimate_number": {"$regex": search, "$options": "i"}},
            ]
        skip = (page - 1) * page_size
        pipeline = [
            {"$match": match_stage},
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"estimate_number": {"$regex": search, "$options": "i"}},
                {"customer_name": {"$regex": search, "$options": "i"}},
            ]}})
            # Remove the pre-lookup search since we now search customer_name post-lookup
            match_stage.pop("$or", None)
            pipeline[0] = {"$match": match_stage}
        pipeline.extend([
            {"$sort": {"created_at": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(estimates_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "estimates": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching estimates: {str(e)}")


@router.get("/estimates/{estimate_id}")
async def get_estimate(estimate_id: str):
    """
    Get a single estimate by ID (excluding soft-deleted).
    P0.16: Returns 404 if estimate is soft-deleted.
    """
    try:
        estimate = estimates_collection.find_one({"_id": ObjectId(estimate_id), "is_deleted": {"$ne": True}})
        if not estimate:
            raise HTTPException(status_code=404, detail="Estimate not found")
        
        # Get customer name
        if estimate.get("customer_id"):
            customer = customers_collection.find_one({"_id": ObjectId(estimate["customer_id"])})
            if customer:
                estimate["customer_name"] = customer.get("name")
        
        return serialize_doc(estimate)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching estimate: {str(e)}")


@router.post("/estimates/")
async def create_estimate(estimate_data: Dict[str, Any] = Body(...)):
    """Create a new estimate"""
    try:
        if not estimate_data.get("customer_id"):
            raise HTTPException(status_code=400, detail="Customer is required")
        
        # Generate estimate number
        estimate_data["estimate_number"] = generate_estimate_number()
        estimate_data["status"] = estimate_data.get("status", "draft")
        estimate_data["created_at"] = datetime.utcnow()
        estimate_data["updated_at"] = datetime.utcnow()
        
        # Calculate totals
        items = estimate_data.get("items", [])
        subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
        tax_total = sum(item.get("tax_amount", 0) for item in items)
        estimate_data["subtotal"] = subtotal
        estimate_data["tax_total"] = tax_total
        estimate_data["total_amount"] = subtotal + tax_total
        
        result = estimates_collection.insert_one(estimate_data)
        estimate_data["_id"] = str(result.inserted_id)
        
        return estimate_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating estimate: {str(e)}")


@router.put("/estimates/{estimate_id}")
async def update_estimate(estimate_id: str, estimate_data: Dict[str, Any] = Body(...)):
    """Update an estimate"""
    try:
        estimate_data.pop("_id", None)
        estimate_data.pop("estimate_number", None)  # Don't allow changing estimate number
        estimate_data["updated_at"] = datetime.utcnow()
        
        result = estimates_collection.update_one(
            {"_id": ObjectId(estimate_id)},
            {"$set": estimate_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Estimate not found")
        return {"message": "Estimate updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating estimate: {str(e)}")


@router.delete("/estimates/{estimate_id}")
async def delete_estimate(estimate_id: str):
    """
    Soft delete an estimate.
    P0.16: Finance Soft Delete - marks as deleted instead of removing.
    """
    try:
        estimate = estimates_collection.find_one({"_id": ObjectId(estimate_id)})
        if not estimate:
            raise HTTPException(status_code=404, detail="Estimate not found")
        
        # Soft delete - set is_deleted flag instead of removing
        result = estimates_collection.update_one(
            {"_id": ObjectId(estimate_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        return {"message": "Estimate deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting estimate: {str(e)}")


@router.get("/estimates/export/csv")
async def export_estimates_csv():
    """Export all estimates to CSV format"""
    try:
        # Get all estimates with customer details
        pipeline = [
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
            {"$sort": {"created_at": -1}}
        ]
        estimates = list(estimates_collection.aggregate(pipeline))
        
        # Create CSV in memory
        output = io.StringIO()
        fieldnames = [
            "estimate_number", "customer_name", "estimate_date", "expiry_date", 
            "reference", "currency_code", "subtotal", "tax_amount", "discount_type", "discount_value",
            "total", "status", "notes", "terms"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for estimate in estimates:
            # Calculate totals
            items = estimate.get("items", [])
            subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
            tax_amount = sum(
                (item.get("quantity", 0) * item.get("rate", 0) * item.get("tax_rate", 0) / 100)
                for item in items
            )
            
            row = {
                "estimate_number": estimate.get("estimate_number", ""),
                "customer_name": estimate.get("customer_name", ""),
                "estimate_date": str(estimate.get("estimate_date", ""))[:10] if estimate.get("estimate_date") else "",
                "expiry_date": str(estimate.get("expiry_date", ""))[:10] if estimate.get("expiry_date") else "",
                "reference": estimate.get("reference", ""),
                "currency_code": estimate.get("currency_code", "INR"),
                "subtotal": round(subtotal, 2),
                "tax_amount": round(tax_amount, 2),
                "discount_type": estimate.get("discount_type", "flat"),
                "discount_value": estimate.get("discount_value", 0),
                "total": estimate.get("total", round(subtotal + tax_amount, 2)),
                "status": estimate.get("status", "draft"),
                "notes": estimate.get("notes", ""),
                "terms": estimate.get("terms", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=estimates_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting estimates: {str(e)}")


@router.post("/estimates/import/csv")
async def import_estimates_csv(file: UploadFile = File(...)):
    """Import estimates from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):  # Start at 2 for Excel row reference (header is row 1)
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, ESTIMATE_COLUMN_MAPPINGS)
                
                # Find customer by name
                customer_name = mapped.get("customer_name", "").strip()
                customer = customers_collection.find_one({"name": customer_name})
                customer_id = str(customer["_id"]) if customer else None
                
                if not customer_id:
                    errors.append(f"Row {idx}: Customer '{customer_name}' not found")
                    continue
                
                # Check if estimate number already exists
                estimate_number = mapped.get("estimate_number", "")
                if estimate_number:
                    existing = estimates_collection.find_one({"estimate_number": estimate_number})
                    if existing:
                        errors.append(f"Row {idx}: Estimate '{estimate_number}' already exists")
                        continue
                
                # Parse dates - support multiple date formats
                estimate_date = None
                expiry_date = None
                
                date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
                
                if mapped.get("estimate_date"):
                    for fmt in date_formats:
                        try:
                            estimate_date = datetime.strptime(mapped["estimate_date"], fmt)
                            break
                        except:
                            continue
                    if not estimate_date:
                        estimate_date = datetime.now()
                
                if mapped.get("expiry_date"):
                    for fmt in date_formats:
                        try:
                            expiry_date = datetime.strptime(mapped["expiry_date"], fmt)
                            break
                        except:
                            continue
                
                # Create estimate data
                estimate_data = {
                    "estimate_number": estimate_number or generate_estimate_number(),
                    "customer_id": customer_id,
                    "estimate_date": estimate_date or datetime.now(),
                    "expiry_date": expiry_date,
                    "reference": mapped.get("reference", ""),
                    "currency_code": mapped.get("currency_code") or "INR",
                    "items": [],  # Items need to be added separately
                    "discount_type": mapped.get("discount_type") or "flat",
                    "discount_value": float(mapped.get("discount_value") or 0),
                    "status": mapped.get("status") or "draft",
                    "notes": mapped.get("notes", ""),
                    "terms": mapped.get("terms", ""),
                    "total": float(mapped.get("total") or 0),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                estimates_collection.insert_one(estimate_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Successfully imported {imported_count} estimates",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing estimates: {str(e)}")


# ============================================================
# INVOICES ENDPOINTS
# ============================================================

@router.get("/invoices/")
@require_any_permission(Permissions.FINANCE_INVOICE_READ, Permissions.ADMIN_ALL)
async def get_invoices(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    customer_id: Optional[str] = Query(None, description="Filter by customer ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by invoice number or customer name"),
):
    """Get invoices with customer details, paginated"""
    try:
        match_stage = {"is_deleted": {"$ne": True}}
        if project_id:
            match_stage["project_id"] = project_id
        if customer_id:
            match_stage["customer_id"] = customer_id
        if status:
            match_stage["status"] = status

        skip = (page - 1) * page_size
        pipeline = [
            {"$match": match_stage},
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"invoice_number": {"$regex": search, "$options": "i"}},
                {"customer_name": {"$regex": search, "$options": "i"}},
            ]}})
        pipeline.extend([
            {"$sort": {"created_at": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(invoices_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "invoices": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoices: {str(e)}")


@router.get("/invoices/{invoice_id}")
@require_any_permission(Permissions.FINANCE_INVOICE_READ, Permissions.ADMIN_ALL)
async def get_invoice(invoice_id: str):
    """
    Get a single invoice by ID (excluding soft-deleted).
    P0.16: Returns 404 if invoice is soft-deleted.
    """
    try:
        invoice = invoices_collection.find_one({"_id": ObjectId(invoice_id), "is_deleted": {"$ne": True}})
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Get customer name
        if invoice.get("customer_id"):
            customer = customers_collection.find_one({"_id": ObjectId(invoice["customer_id"])})
            if customer:
                invoice["customer_name"] = customer.get("name")
        
        return serialize_doc(invoice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoice: {str(e)}")


@router.post("/invoices/")
@require_any_permission(Permissions.FINANCE_INVOICE_CREATE, Permissions.ADMIN_ALL)
async def create_invoice(invoice_data: Dict[str, Any] = Body(...)):
    """Create a new invoice"""
    try:
        if not invoice_data.get("customer_id"):
            raise HTTPException(status_code=400, detail="Customer is required")
        
        # Generate invoice number
        invoice_data["invoice_number"] = generate_invoice_number()
        invoice_data["status"] = invoice_data.get("status", "draft")
        invoice_data["created_at"] = datetime.utcnow()
        invoice_data["updated_at"] = datetime.utcnow()
        
        # Calculate totals
        items = invoice_data.get("items", [])
        subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
        tax_total = sum(item.get("tax_amount", 0) for item in items)
        invoice_data["subtotal"] = subtotal
        invoice_data["tax_total"] = tax_total
        invoice_data["total_amount"] = subtotal + tax_total
        invoice_data["balance_due"] = invoice_data["total_amount"]
        invoice_data["amount_paid"] = 0
        
        result = invoices_collection.insert_one(invoice_data)
        invoice_data["_id"] = str(result.inserted_id)
        
        # Update customer receivables
        customers_collection.update_one(
            {"_id": ObjectId(invoice_data["customer_id"])},
            {"$inc": {"total_receivables": invoice_data["total_amount"]}}
        )
        
        return invoice_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating invoice: {str(e)}")


@router.put("/invoices/{invoice_id}")
@require_any_permission(Permissions.FINANCE_INVOICE_UPDATE, Permissions.ADMIN_ALL)
async def update_invoice(invoice_id: str, invoice_data: Dict[str, Any] = Body(...)):
    """Update an invoice"""
    try:
        invoice_data.pop("_id", None)
        invoice_data.pop("invoice_number", None)  # Don't allow changing invoice number
        invoice_data["updated_at"] = datetime.utcnow()
        
        result = invoices_collection.update_one(
            {"_id": ObjectId(invoice_id)},
            {"$set": invoice_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return {"message": "Invoice updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating invoice: {str(e)}")


@router.delete("/invoices/{invoice_id}")
@require_any_permission(Permissions.FINANCE_INVOICE_DELETE, Permissions.ADMIN_ALL)
async def delete_invoice(invoice_id: str):
    """
    Soft delete an invoice.
    P0.16: Finance Soft Delete - marks as deleted instead of removing.
    """
    try:
        invoice = invoices_collection.find_one({"_id": ObjectId(invoice_id)})
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Update customer receivables
        if invoice.get("customer_id"):
            customers_collection.update_one(
                {"_id": ObjectId(invoice["customer_id"])},
                {"$inc": {"total_receivables": -invoice.get("balance_due", 0)}}
            )
        
        # Soft delete - set is_deleted flag instead of removing
        result = invoices_collection.update_one(
            {"_id": ObjectId(invoice_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        return {"message": "Invoice deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting invoice: {str(e)}")


@router.get("/invoices/export/csv")
async def export_invoices_csv():
    """Export all invoices to CSV format"""
    try:
        # Get all invoices with customer details
        pipeline = [
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
            {"$sort": {"created_at": -1}}
        ]
        invoices = list(invoices_collection.aggregate(pipeline))
        
        # Create CSV in memory
        output = io.StringIO()
        fieldnames = [
            "invoice_number", "customer_name", "invoice_date", "due_date", 
            "currency_code", "subtotal", "tax_amount", "discount_type", "discount_value",
            "total", "balance_due", "status", "payment_status", "payment_date", 
            "payment_reference", "po_reference", "notes", "terms_and_conditions"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for invoice in invoices:
            # Calculate totals
            items = invoice.get("items", [])
            subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
            tax_amount = sum(
                (item.get("quantity", 0) * item.get("rate", 0) * item.get("tax_rate", 0) / 100)
                for item in items
            )
            
            row = {
                "invoice_number": invoice.get("invoice_number", ""),
                "customer_name": invoice.get("customer_name", ""),
                "invoice_date": str(invoice.get("invoice_date", ""))[:10] if invoice.get("invoice_date") else "",
                "due_date": str(invoice.get("due_date", ""))[:10] if invoice.get("due_date") else "",
                "currency_code": invoice.get("currency_code", "INR"),
                "subtotal": round(subtotal, 2),
                "tax_amount": round(tax_amount, 2),
                "discount_type": invoice.get("discount_type", "flat"),
                "discount_value": invoice.get("discount_value", 0),
                "total": invoice.get("total", round(subtotal + tax_amount, 2)),
                "balance_due": invoice.get("balance_due", 0),
                "status": invoice.get("status", "draft"),
                "payment_status": invoice.get("payment_status", "unpaid"),
                "payment_date": str(invoice.get("payment_date", ""))[:10] if invoice.get("payment_date") else "",
                "payment_reference": invoice.get("payment_reference", ""),
                "po_reference": invoice.get("po_reference", ""),
                "notes": invoice.get("notes", ""),
                "terms_and_conditions": invoice.get("terms_and_conditions", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=invoices_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting invoices: {str(e)}")


@router.post("/invoices/import/csv")
async def import_invoices_csv(file: UploadFile = File(...)):
    """Import invoices from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):  # Start at 2 for Excel row reference (header is row 1)
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, INVOICE_COLUMN_MAPPINGS)
                
                # Find customer by name
                customer_name = mapped.get("customer_name", "").strip()
                customer = customers_collection.find_one({"name": customer_name})
                customer_id = str(customer["_id"]) if customer else None
                
                if not customer_id:
                    errors.append(f"Row {idx}: Customer '{customer_name}' not found")
                    continue
                
                # Check if invoice number already exists
                invoice_number = mapped.get("invoice_number", "")
                existing = invoices_collection.find_one({"invoice_number": invoice_number})
                if existing:
                    errors.append(f"Row {idx}: Invoice '{invoice_number}' already exists")
                    continue
                
                # Parse dates - support multiple date formats
                invoice_date = None
                due_date = None
                payment_date = None
                
                date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
                
                if mapped.get("invoice_date"):
                    for fmt in date_formats:
                        try:
                            invoice_date = datetime.strptime(mapped["invoice_date"], fmt)
                            break
                        except:
                            continue
                    if not invoice_date:
                        invoice_date = datetime.now()
                
                if mapped.get("due_date"):
                    for fmt in date_formats:
                        try:
                            due_date = datetime.strptime(mapped["due_date"], fmt)
                            break
                        except:
                            continue
                
                if mapped.get("payment_date"):
                    for fmt in date_formats:
                        try:
                            payment_date = datetime.strptime(mapped["payment_date"], fmt)
                            break
                        except:
                            continue
                
                # Create invoice data
                invoice_data = {
                    "invoice_number": invoice_number or generate_invoice_number(),
                    "customer_id": customer_id,
                    "invoice_date": invoice_date or datetime.now(),
                    "due_date": due_date,
                    "currency_code": mapped.get("currency_code") or "INR",
                    "items": [],  # Items need to be added separately
                    "discount_type": mapped.get("discount_type") or "flat",
                    "discount_value": float(mapped.get("discount_value") or 0),
                    "status": mapped.get("status") or "draft",
                    "payment_status": mapped.get("payment_status") or "unpaid",
                    "payment_date": payment_date,
                    "payment_reference": mapped.get("payment_reference", ""),
                    "po_reference": mapped.get("po_reference", ""),
                    "notes": mapped.get("notes", ""),
                    "terms_and_conditions": mapped.get("terms_and_conditions", ""),
                    "total": float(mapped.get("total") or 0),
                    "balance_due": float(mapped.get("balance_due") or 0),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                invoices_collection.insert_one(invoice_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} invoices",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing invoices: {str(e)}")


# ============================================================
# BILLS ENDPOINTS
# ============================================================

@router.get("/bills/")
@require_any_permission(Permissions.FINANCE_BILL_READ, Permissions.ADMIN_ALL)
async def get_bills(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    vendor_id: Optional[str] = Query(None, description="Filter by vendor ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by bill number or vendor name"),
):
    """Get bills with vendor details, paginated"""
    try:
        match_stage = {"is_deleted": {"$ne": True}}
        if project_id:
            match_stage["project_id"] = project_id
        if vendor_id:
            match_stage["vendor_id"] = vendor_id
        if status:
            match_stage["status"] = status

        skip = (page - 1) * page_size
        pipeline = [
            {"$match": match_stage},
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"bill_number": {"$regex": search, "$options": "i"}},
                {"vendor_name": {"$regex": search, "$options": "i"}},
            ]}})
        pipeline.extend([
            {"$sort": {"created_at": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(bills_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "bills": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bills: {str(e)}")


@router.get("/bills/{bill_id}")
@require_any_permission(Permissions.FINANCE_BILL_READ, Permissions.ADMIN_ALL)
async def get_bill(bill_id: str):
    """
    Get a single bill by ID (excluding soft-deleted).
    P0.16: Returns 404 if bill is soft-deleted.
    """
    try:
        bill = bills_collection.find_one({"_id": ObjectId(bill_id), "is_deleted": {"$ne": True}})
        if not bill:
            raise HTTPException(status_code=404, detail="Bill not found")
        
        # Get vendor name
        if bill.get("vendor_id"):
            vendor = vendors_collection.find_one({"_id": ObjectId(bill["vendor_id"])})
            if vendor:
                bill["vendor_name"] = vendor.get("name")
        
        return serialize_doc(bill)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bill: {str(e)}")


@router.post("/bills/")
@require_any_permission(Permissions.FINANCE_BILL_CREATE, Permissions.ADMIN_ALL)
async def create_bill(bill_data: Dict[str, Any] = Body(...)):
    """Create a new bill"""
    try:
        if not bill_data.get("vendor_id"):
            raise HTTPException(status_code=400, detail="Vendor is required")
        
        # Generate bill number if not provided
        if not bill_data.get("bill_number"):
            bill_data["bill_number"] = generate_bill_number()
        
        bill_data["status"] = bill_data.get("status", "pending")
        bill_data["created_at"] = datetime.utcnow()
        bill_data["updated_at"] = datetime.utcnow()
        
        # Calculate totals
        items = bill_data.get("items", [])
        subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
        tax_total = sum((item.get("quantity", 0) * item.get("rate", 0) * item.get("tax_rate", 0) / 100) for item in items)
        bill_data["subtotal"] = subtotal
        bill_data["tax_total"] = tax_total
        bill_data["total_amount"] = subtotal + tax_total
        bill_data["balance_due"] = bill_data["total_amount"]
        bill_data["amount_paid"] = 0
        
        result = bills_collection.insert_one(bill_data)
        bill_data["_id"] = str(result.inserted_id)
        
        # Update vendor payables
        vendors_collection.update_one(
            {"_id": ObjectId(bill_data["vendor_id"])},
            {"$inc": {"total_payables": bill_data["total_amount"]}}
        )
        
        return bill_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating bill: {str(e)}")


@router.put("/bills/{bill_id}")
@require_any_permission(Permissions.FINANCE_BILL_UPDATE, Permissions.ADMIN_ALL)
async def update_bill(bill_id: str, bill_data: Dict[str, Any] = Body(...)):
    """Update a bill"""
    try:
        bill_data.pop("_id", None)
        bill_data["updated_at"] = datetime.utcnow()
        
        result = bills_collection.update_one(
            {"_id": ObjectId(bill_id)},
            {"$set": bill_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Bill not found")
        return {"message": "Bill updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating bill: {str(e)}")


@router.delete("/bills/{bill_id}")
@require_any_permission(Permissions.FINANCE_BILL_DELETE, Permissions.ADMIN_ALL)
async def delete_bill(bill_id: str):
    """
    Soft delete a bill.
    P0.16: Finance Soft Delete - marks as deleted instead of removing.
    """
    try:
        bill = bills_collection.find_one({"_id": ObjectId(bill_id)})
        if not bill:
            raise HTTPException(status_code=404, detail="Bill not found")
        
        # Update vendor payables
        if bill.get("vendor_id"):
            vendors_collection.update_one(
                {"_id": ObjectId(bill["vendor_id"])},
                {"$inc": {"total_payables": -bill.get("balance_due", 0)}}
            )
        
        # Soft delete - set is_deleted flag instead of removing
        result = bills_collection.update_one(
            {"_id": ObjectId(bill_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "status": "deleted"
                }
            }
        )
        return {"message": "Bill deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting bill: {str(e)}")


@router.get("/bills/export/csv")
async def export_bills_csv():
    """Export all bills to CSV format"""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
            {"$sort": {"created_at": -1}}
        ]
        bills = list(bills_collection.aggregate(pipeline))
        
        output = io.StringIO()
        fieldnames = [
            "bill_number", "vendor_name", "bill_date", "due_date",
            "subtotal", "tax_amount", "total", "balance_due", "status", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for bill in bills:
            items = bill.get("items", [])
            subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
            tax_amount = sum(
                (item.get("quantity", 0) * item.get("rate", 0) * item.get("tax_rate", 0) / 100)
                for item in items
            )
            
            row = {
                "bill_number": bill.get("bill_number", ""),
                "vendor_name": bill.get("vendor_name", ""),
                "bill_date": str(bill.get("bill_date", ""))[:10] if bill.get("bill_date") else "",
                "due_date": str(bill.get("due_date", ""))[:10] if bill.get("due_date") else "",
                "subtotal": round(subtotal, 2),
                "tax_amount": round(tax_amount, 2),
                "total": bill.get("total", round(subtotal + tax_amount, 2)),
                "balance_due": bill.get("balance_due", 0),
                "status": bill.get("status", "pending"),
                "notes": bill.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=bills_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting bills: {str(e)}")


@router.post("/bills/import/csv")
async def import_bills_csv(file: UploadFile = File(...)):
    """Import bills from CSV file with flexible column mapping"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                # Map columns using flexible mapping
                mapped = map_csv_columns(row, BILL_COLUMN_MAPPINGS)
                
                vendor_name = mapped.get("vendor_name", "").strip()
                vendor = vendors_collection.find_one({"name": vendor_name})
                vendor_id = str(vendor["_id"]) if vendor else None
                
                if not vendor_id:
                    errors.append(f"Row {idx}: Vendor '{vendor_name}' not found")
                    continue
                
                bill_number = mapped.get("bill_number", "")
                existing = bills_collection.find_one({"bill_number": bill_number})
                if existing:
                    errors.append(f"Row {idx}: Bill '{bill_number}' already exists")
                    continue
                
                # Parse dates - support multiple date formats
                date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
                bill_date = None
                due_date = None
                
                if mapped.get("bill_date"):
                    for fmt in date_formats:
                        try:
                            bill_date = datetime.strptime(mapped["bill_date"], fmt)
                            break
                        except:
                            continue
                    if not bill_date:
                        bill_date = datetime.now()
                
                if mapped.get("due_date"):
                    for fmt in date_formats:
                        try:
                            due_date = datetime.strptime(mapped["due_date"], fmt)
                            break
                        except:
                            continue
                
                bill_data = {
                    "bill_number": bill_number or generate_bill_number(),
                    "vendor_id": vendor_id,
                    "bill_date": bill_date or datetime.now(),
                    "due_date": due_date,
                    "items": [],
                    "status": mapped.get("status") or "pending",
                    "notes": mapped.get("notes", ""),
                    "total": float(mapped.get("total") or 0),
                    "balance_due": float(mapped.get("balance_due") or 0),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                bills_collection.insert_one(bill_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} bills",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing bills: {str(e)}")


# ============================================================
# PURCHASE ORDERS ENDPOINTS
# ============================================================

@router.get("/purchase-orders/")
async def get_purchase_orders(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by PO number or vendor name"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """Get purchase orders with vendor details, paginated"""
    try:
        match_stage = {}
        if status:
            match_stage["status"] = status
        skip = (page - 1) * page_size
        pipeline = [
            {"$match": match_stage} if match_stage else {"$match": {}},
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"po_number": {"$regex": search, "$options": "i"}},
                {"vendor_name": {"$regex": search, "$options": "i"}},
            ]}})
        pipeline.extend([
            {"$sort": {"created_at": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(purchase_orders_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "purchase_orders": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching purchase orders: {str(e)}")


@router.post("/purchase-orders/")
async def create_purchase_order(po_data: Dict[str, Any] = Body(...)):
    """Create a new purchase order"""
    try:
        if not po_data.get("vendor_id"):
            raise HTTPException(status_code=400, detail="Vendor is required")
        
        # Generate PO number if not provided
        if not po_data.get("po_number"):
            po_data["po_number"] = generate_po_number()
        
        po_data["status"] = po_data.get("status", "draft")
        po_data["created_at"] = datetime.utcnow()
        po_data["updated_at"] = datetime.utcnow()
        
        # Calculate totals - compute tax from rate if tax_amount not provided
        items = po_data.get("items", [])
        for item in items:
            quantity = float(item.get("quantity", 0) or 0)
            rate = float(item.get("rate", 0) or 0)
            tax_rate = float(item.get("tax_rate", 0) or 0)
            item["amount"] = quantity * rate
            item["tax_amount"] = (quantity * rate * tax_rate) / 100
        
        subtotal = sum(float(item.get("amount", 0) or 0) for item in items)
        tax_total = sum(float(item.get("tax_amount", 0) or 0) for item in items)
        po_data["subtotal"] = subtotal
        po_data["tax_total"] = tax_total
        po_data["total_amount"] = subtotal + tax_total
        
        result = purchase_orders_collection.insert_one(po_data)
        po_data["_id"] = str(result.inserted_id)
        return po_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating purchase order: {str(e)}")


@router.put("/purchase-orders/{po_id}")
async def update_purchase_order(po_id: str, po_data: Dict[str, Any] = Body(...)):
    """Update a purchase order"""
    try:
        po_data.pop("_id", None)
        po_data["updated_at"] = datetime.utcnow()
        
        result = purchase_orders_collection.update_one(
            {"_id": ObjectId(po_id)},
            {"$set": po_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        return {"message": "Purchase order updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating purchase order: {str(e)}")


@router.delete("/purchase-orders/{po_id}")
async def delete_purchase_order(po_id: str):
    """Delete a purchase order"""
    try:
        result = purchase_orders_collection.delete_one({"_id": ObjectId(po_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        return {"message": "Purchase order deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting purchase order: {str(e)}")


@router.get("/purchase-orders/export/csv")
async def export_purchase_orders_csv():
    """Export all purchase orders to CSV format"""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
            {"$sort": {"created_at": -1}}
        ]
        pos = list(purchase_orders_collection.aggregate(pipeline))
        
        output = io.StringIO()
        fieldnames = [
            "po_number", "vendor_name", "order_date", "expected_delivery",
            "subtotal", "tax_amount", "total", "status", "shipping_address", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for po in pos:
            items = po.get("items", [])
            subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in items)
            tax_amount = sum(
                (item.get("quantity", 0) * item.get("rate", 0) * item.get("tax_rate", 0) / 100)
                for item in items
            )
            
            row = {
                "po_number": po.get("po_number", ""),
                "vendor_name": po.get("vendor_name", ""),
                "order_date": str(po.get("order_date", ""))[:10] if po.get("order_date") else "",
                "expected_delivery": str(po.get("expected_delivery", ""))[:10] if po.get("expected_delivery") else "",
                "subtotal": round(subtotal, 2),
                "tax_amount": round(tax_amount, 2),
                "total": po.get("total", round(subtotal + tax_amount, 2)),
                "status": po.get("status", "draft"),
                "shipping_address": po.get("shipping_address", ""),
                "notes": po.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=purchase_orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting purchase orders: {str(e)}")


@router.post("/purchase-orders/import/csv")
async def import_purchase_orders_csv(file: UploadFile = File(...)):
    """Import purchase orders from CSV file"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        # Try multiple encodings to handle various CSV formats
        for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = contents.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            decoded = contents.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                vendor = vendors_collection.find_one({"name": row.get("vendor_name", "").strip()})
                vendor_id = str(vendor["_id"]) if vendor else None
                
                if not vendor_id:
                    errors.append(f"Row {idx}: Vendor '{row.get('vendor_name')}' not found")
                    continue
                
                existing = purchase_orders_collection.find_one({"po_number": row.get("po_number", "")})
                if existing:
                    errors.append(f"Row {idx}: PO '{row.get('po_number')}' already exists")
                    continue
                
                order_date = None
                expected_delivery = None
                if row.get("order_date"):
                    try:
                        order_date = datetime.strptime(row["order_date"], "%Y-%m-%d")
                    except:
                        order_date = datetime.now()
                
                if row.get("expected_delivery"):
                    try:
                        expected_delivery = datetime.strptime(row["expected_delivery"], "%Y-%m-%d")
                    except:
                        expected_delivery = None
                
                po_data = {
                    "po_number": row.get("po_number") or generate_po_number(),
                    "vendor_id": vendor_id,
                    "order_date": order_date or datetime.now(),
                    "expected_delivery": expected_delivery,
                    "items": [],
                    "status": row.get("status", "draft"),
                    "shipping_address": row.get("shipping_address", ""),
                    "notes": row.get("notes", ""),
                    "total": float(row.get("total", 0) or 0),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                purchase_orders_collection.insert_one(po_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} purchase orders",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing purchase orders: {str(e)}")


# ============================================================
# EXPENSES ENDPOINTS
# ============================================================

@router.get("/expenses/")
async def get_expenses(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    category: Optional[str] = Query(None, description="Filter by category"),
    approval_status: Optional[str] = Query(None, description="Filter by approval status"),
    search: Optional[str] = Query(None, description="Search by description or expense number"),
):
    """Get expenses excluding soft-deleted (paginated)"""
    try:
        query = {"is_deleted": {"$ne": True}}
        if project_id:
            query["project_id"] = project_id
        if category:
            query["category"] = category
        if approval_status:
            query["approval_status"] = approval_status
        if search:
            query["$or"] = [
                {"description": {"$regex": search, "$options": "i"}},
                {"expense_number": {"$regex": search, "$options": "i"}},
            ]
        total = expenses_collection.count_documents(query)
        skip = (page - 1) * page_size
        expenses = list(expenses_collection.find(query).sort("expense_date", -1).skip(skip).limit(page_size))
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "expenses": serialize_docs(expenses),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching expenses: {str(e)}")


@router.post("/expenses/")
async def create_expense(expense_data: Dict[str, Any] = Body(...)):
    """Create a new expense"""
    try:
        if not expense_data.get("description"):
            raise HTTPException(status_code=400, detail="Description is required")
        if not expense_data.get("amount"):
            raise HTTPException(status_code=400, detail="Amount is required")
        
        expense_data["expense_number"] = generate_expense_number()
        expense_data["approval_status"] = expense_data.get("requires_approval", False) and "pending" or "approved"
        expense_data["created_at"] = datetime.utcnow()
        expense_data["updated_at"] = datetime.utcnow()
        
        result = expenses_collection.insert_one(expense_data)
        expense_data["_id"] = str(result.inserted_id)
        return expense_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating expense: {str(e)}")


@router.put("/expenses/{expense_id}")
async def update_expense(expense_id: str, expense_data: Dict[str, Any] = Body(...)):
    """Update an expense"""
    try:
        expense_data.pop("_id", None)
        expense_data["updated_at"] = datetime.utcnow()
        
        result = expenses_collection.update_one(
            {"_id": ObjectId(expense_id)},
            {"$set": expense_data}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Expense not found")
        return {"message": "Expense updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating expense: {str(e)}")


@router.delete("/expenses/{expense_id}")
async def delete_expense(expense_id: str):
    """
    Soft delete an expense.
    P0.16: Finance Soft Delete - marks as deleted instead of removing.
    """
    try:
        expense = expenses_collection.find_one({"_id": ObjectId(expense_id)})
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        
        # Soft delete - set is_deleted flag instead of removing
        result = expenses_collection.update_one(
            {"_id": ObjectId(expense_id)},
            {
                "$set": {
                    "is_deleted": True,
                    "deleted_at": datetime.utcnow(),
                    "approval_status": "deleted"
                }
            }
        )
        return {"message": "Expense deleted successfully (soft delete)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting expense: {str(e)}")


@router.post("/expenses/auto-categorize")
async def auto_categorize_expense(data: Dict[str, Any] = Body(...)):
    """Auto-categorize expense based on description"""
    description = data.get("description", "").lower()
    
    # Simple rule-based categorization
    category_rules = {
        "Office Supplies": ["office", "stationery", "paper", "pen", "printer"],
        "Travel": ["travel", "flight", "hotel", "uber", "taxi", "cab", "train"],
        "Meals & Entertainment": ["lunch", "dinner", "meal", "restaurant", "food", "coffee"],
        "Utilities": ["electricity", "water", "gas", "internet", "phone", "utility"],
        "Rent": ["rent", "lease", "property"],
        "Software & Subscriptions": ["software", "subscription", "saas", "cloud", "aws", "azure"],
        "Marketing": ["marketing", "advertising", "ads", "promotion", "campaign"],
        "Professional Services": ["consulting", "legal", "accounting", "professional"],
        "Equipment": ["equipment", "computer", "laptop", "hardware", "machine"],
        "Maintenance": ["maintenance", "repair", "service"],
        "Insurance": ["insurance", "premium"],
        "Training": ["training", "course", "workshop", "seminar"],
    }
    
    for category, keywords in category_rules.items():
        if any(keyword in description for keyword in keywords):
            return {"category": category}
    
    return {"category": "Miscellaneous"}


@router.get("/expenses/export/csv")
async def export_expenses_csv():
    """Export all expenses to CSV format"""
    try:
        expenses = list(expenses_collection.find().sort("expense_date", -1))
        
        output = io.StringIO()
        fieldnames = [
            "description", "amount", "currency_code", "category", "expense_date",
            "payment_method", "reference_number", "is_billable", "approval_status", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for expense in expenses:
            row = {
                "description": expense.get("description", ""),
                "amount": expense.get("amount", 0),
                "currency_code": expense.get("currency_code", "INR"),
                "category": expense.get("category", ""),
                "expense_date": str(expense.get("expense_date", ""))[:10] if expense.get("expense_date") else "",
                "payment_method": expense.get("payment_method", ""),
                "reference_number": expense.get("reference_number", ""),
                "is_billable": expense.get("is_billable", False),
                "approval_status": expense.get("approval_status", "pending"),
                "notes": expense.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=expenses_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting expenses: {str(e)}")


@router.post("/expenses/import/csv")
async def import_expenses_csv(file: UploadFile = File(...)):
    """Import expenses from CSV file"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        decoded = contents.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                expense_date = None
                if row.get("expense_date"):
                    try:
                        expense_date = datetime.strptime(row["expense_date"], "%Y-%m-%d")
                    except:
                        expense_date = datetime.now()
                
                expense_data = {
                    "description": row.get("description", ""),
                    "amount": float(row.get("amount", 0) or 0),
                    "currency_code": row.get("currency_code", "INR"),
                    "category": row.get("category", "Miscellaneous"),
                    "expense_date": expense_date or datetime.now(),
                    "payment_method": row.get("payment_method", "bank_transfer"),
                    "reference_number": row.get("reference_number", ""),
                    "is_billable": row.get("is_billable", "").lower() == "true",
                    "approval_status": row.get("approval_status", "pending"),
                    "notes": row.get("notes", ""),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
                
                expenses_collection.insert_one(expense_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} expenses",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing expenses: {str(e)}")


# ============================================================
# PAYMENTS ENDPOINTS
# ============================================================

@router.get("/payments/received/")
async def get_payments_received(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by payment number or customer name"),
):
    """Get payments received, paginated"""
    try:
        skip = (page - 1) * page_size
        pipeline = [
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"payment_number": {"$regex": search, "$options": "i"}},
                {"customer_name": {"$regex": search, "$options": "i"}},
            ]}})
        pipeline.extend([
            {"$sort": {"payment_date": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(payments_received_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "payments": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching payments received: {str(e)}")


@router.get("/payments/made/")
async def get_payments_made(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(None, description="Search by payment number or vendor name"),
):
    """Get payments made, paginated"""
    try:
        skip = (page - 1) * page_size
        pipeline = [
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
        ]
        if search:
            pipeline.append({"$match": {"$or": [
                {"payment_number": {"$regex": search, "$options": "i"}},
                {"vendor_name": {"$regex": search, "$options": "i"}},
            ]}})
        pipeline.extend([
            {"$sort": {"payment_date": -1}},
            {"$facet": {
                "metadata": [{"$count": "total"}],
                "data": [{"$skip": skip}, {"$limit": page_size}],
            }},
        ])
        result = list(payments_made_collection.aggregate(pipeline))
        data = result[0]["data"] if result else []
        total = result[0]["metadata"][0]["total"] if result and result[0]["metadata"] else 0
        import math
        pages = math.ceil(total / page_size) if total > 0 else 1
        return {
            "payments": serialize_docs(data),
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching payments made: {str(e)}")


@router.post("/payments/received/")
async def create_payment_received(payment_data: Dict[str, Any] = Body(...)):
    """Record a payment received from a customer"""
    try:
        if not payment_data.get("customer_id"):
            raise HTTPException(status_code=400, detail="Customer is required")
        if not payment_data.get("amount"):
            raise HTTPException(status_code=400, detail="Amount is required")
        
        payment_data["payment_number"] = generate_payment_number("RCV")
        payment_data["created_at"] = datetime.utcnow()
        
        result = payments_received_collection.insert_one(payment_data)
        payment_data["_id"] = str(result.inserted_id)
        
        # Update invoice if linked
        if payment_data.get("invoice_id"):
            invoices_collection.update_one(
                {"_id": ObjectId(payment_data["invoice_id"])},
                {
                    "$inc": {
                        "amount_paid": payment_data["amount"],
                        "balance_due": -payment_data["amount"]
                    }
                }
            )
            # Check if fully paid
            invoice = invoices_collection.find_one({"_id": ObjectId(payment_data["invoice_id"])})
            if invoice and invoice.get("balance_due", 0) <= 0:
                invoices_collection.update_one(
                    {"_id": ObjectId(payment_data["invoice_id"])},
                    {"$set": {"status": "paid"}}
                )
        
        # Update customer totals
        customers_collection.update_one(
            {"_id": ObjectId(payment_data["customer_id"])},
            {
                "$inc": {
                    "total_paid": payment_data["amount"],
                    "total_receivables": -payment_data["amount"]
                }
            }
        )
        
        return payment_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recording payment: {str(e)}")


@router.post("/payments/made/")
async def create_payment_made(payment_data: Dict[str, Any] = Body(...)):
    """Record a payment made to a vendor"""
    try:
        if not payment_data.get("vendor_id"):
            raise HTTPException(status_code=400, detail="Vendor is required")
        if not payment_data.get("amount"):
            raise HTTPException(status_code=400, detail="Amount is required")
        
        payment_data["payment_number"] = generate_payment_number("PAY")
        payment_data["created_at"] = datetime.utcnow()
        
        result = payments_made_collection.insert_one(payment_data)
        payment_data["_id"] = str(result.inserted_id)
        
        # Update bill if linked
        if payment_data.get("bill_id"):
            bills_collection.update_one(
                {"_id": ObjectId(payment_data["bill_id"])},
                {
                    "$inc": {
                        "amount_paid": payment_data["amount"],
                        "balance_due": -payment_data["amount"]
                    }
                }
            )
            # Check if fully paid
            bill = bills_collection.find_one({"_id": ObjectId(payment_data["bill_id"])})
            if bill and bill.get("balance_due", 0) <= 0:
                bills_collection.update_one(
                    {"_id": ObjectId(payment_data["bill_id"])},
                    {"$set": {"status": "paid"}}
                )
        
        # Update vendor totals
        vendors_collection.update_one(
            {"_id": ObjectId(payment_data["vendor_id"])},
            {
                "$inc": {
                    "total_paid": payment_data["amount"],
                    "total_payables": -payment_data["amount"]
                }
            }
        )
        
        return payment_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recording payment: {str(e)}")


@router.get("/payments/received/export/csv")
async def export_payments_received_csv():
    """Export all payments received to CSV format"""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "customers",
                    "let": {"customer_id": {"$toObjectId": "$customer_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$customer_id"]}}}
                    ],
                    "as": "customer"
                }
            },
            {"$unwind": {"path": "$customer", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"customer_name": "$customer.name"}},
            {"$project": {"customer": 0}},
            {"$sort": {"payment_date": -1}}
        ]
        payments = list(payments_received_collection.aggregate(pipeline))
        
        output = io.StringIO()
        fieldnames = [
            "customer_name", "amount", "currency_code", "payment_date",
            "payment_method", "reference_number", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for payment in payments:
            row = {
                "customer_name": payment.get("customer_name", ""),
                "amount": payment.get("amount", 0),
                "currency_code": payment.get("currency_code", "INR"),
                "payment_date": str(payment.get("payment_date", ""))[:10] if payment.get("payment_date") else "",
                "payment_method": payment.get("payment_method", ""),
                "reference_number": payment.get("reference_number", ""),
                "notes": payment.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=payments_received_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting payments received: {str(e)}")


@router.post("/payments/received/import/csv")
async def import_payments_received_csv(file: UploadFile = File(...)):
    """Import payments received from CSV file"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        decoded = contents.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                customer = customers_collection.find_one({"name": row.get("customer_name", "").strip()})
                customer_id = str(customer["_id"]) if customer else None
                
                if not customer_id:
                    errors.append(f"Row {idx}: Customer '{row.get('customer_name')}' not found")
                    continue
                
                payment_date = None
                if row.get("payment_date"):
                    try:
                        payment_date = datetime.strptime(row["payment_date"], "%Y-%m-%d")
                    except:
                        payment_date = datetime.now()
                
                payment_data = {
                    "customer_id": customer_id,
                    "amount": float(row.get("amount", 0) or 0),
                    "currency_code": row.get("currency_code", "INR"),
                    "payment_date": payment_date or datetime.now(),
                    "payment_method": row.get("payment_method", "bank_transfer"),
                    "reference_number": row.get("reference_number", ""),
                    "notes": row.get("notes", ""),
                    "created_at": datetime.now(),
                }
                
                payments_received_collection.insert_one(payment_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} payments received",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing payments received: {str(e)}")


@router.get("/payments/made/export/csv")
async def export_payments_made_csv():
    """Export all payments made to CSV format"""
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "vendors",
                    "let": {"vendor_id": {"$toObjectId": "$vendor_id"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$vendor_id"]}}}
                    ],
                    "as": "vendor"
                }
            },
            {"$unwind": {"path": "$vendor", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"vendor_name": "$vendor.name"}},
            {"$project": {"vendor": 0}},
            {"$sort": {"payment_date": -1}}
        ]
        payments = list(payments_made_collection.aggregate(pipeline))
        
        output = io.StringIO()
        fieldnames = [
            "vendor_name", "amount", "currency_code", "payment_date",
            "payment_method", "reference_number", "notes"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for payment in payments:
            row = {
                "vendor_name": payment.get("vendor_name", ""),
                "amount": payment.get("amount", 0),
                "currency_code": payment.get("currency_code", "INR"),
                "payment_date": str(payment.get("payment_date", ""))[:10] if payment.get("payment_date") else "",
                "payment_method": payment.get("payment_method", ""),
                "reference_number": payment.get("reference_number", ""),
                "notes": payment.get("notes", ""),
            }
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=payments_made_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting payments made: {str(e)}")


@router.post("/payments/made/import/csv")
async def import_payments_made_csv(file: UploadFile = File(...)):
    """Import payments made from CSV file"""
    try:
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV")
        
        contents = await file.read()
        decoded = contents.decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded))
        
        imported_count = 0
        errors = []
        
        for idx, row in enumerate(reader, start=2):
            try:
                vendor = vendors_collection.find_one({"name": row.get("vendor_name", "").strip()})
                vendor_id = str(vendor["_id"]) if vendor else None
                
                if not vendor_id:
                    errors.append(f"Row {idx}: Vendor '{row.get('vendor_name')}' not found")
                    continue
                
                payment_date = None
                if row.get("payment_date"):
                    try:
                        payment_date = datetime.strptime(row["payment_date"], "%Y-%m-%d")
                    except:
                        payment_date = datetime.now()
                
                payment_data = {
                    "vendor_id": vendor_id,
                    "amount": float(row.get("amount", 0) or 0),
                    "currency_code": row.get("currency_code", "INR"),
                    "payment_date": payment_date or datetime.now(),
                    "payment_method": row.get("payment_method", "bank_transfer"),
                    "reference_number": row.get("reference_number", ""),
                    "notes": row.get("notes", ""),
                    "created_at": datetime.now(),
                }
                
                payments_made_collection.insert_one(payment_data)
                imported_count += 1
                
            except Exception as row_error:
                errors.append(f"Row {idx}: {str(row_error)}")
        
        return {
            "message": f"Imported {imported_count} payments made",
            "imported": imported_count,
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error importing payments made: {str(e)}")


# ============================================================
# DASHBOARD ENDPOINTS
# ============================================================

@router.get("/dashboard/summary")
async def get_dashboard_summary():
    """Get finance dashboard summary data"""
    try:
        # Calculate date ranges
        today = datetime.utcnow()
        start_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_of_year = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Revenue (from invoices) - use aggregation instead of iterating
        invoice_stats_pipeline = [
            {"$facet": {
                "total_count": [{"$count": "count"}],
                "total_sales": [
                    {"$match": {"status": {"$in": ["sent", "paid"]}}},
                    {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$total_amount", 0]}}}}
                ],
                "outstanding_receivables": [
                    {"$match": {"status": {"$ne": "paid"}}},
                    {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$balance_due", 0]}}}}
                ],
                "overdue_count": [
                    {"$match": {"due_date": {"$lt": today.isoformat()}, "status": {"$ne": "paid"}}},
                    {"$count": "count"}
                ],
                "recent": [
                    {"$sort": {"created_at": -1}},
                    {"$limit": 5}
                ]
            }}
        ]
        invoice_stats = list(invoices_collection.aggregate(invoice_stats_pipeline))
        inv = invoice_stats[0] if invoice_stats else {}
        
        total_invoices = inv.get("total_count", [{}])[0].get("count", 0) if inv.get("total_count") else 0
        total_sales = inv.get("total_sales", [{}])[0].get("total", 0) if inv.get("total_sales") else 0
        outstanding_receivables = inv.get("outstanding_receivables", [{}])[0].get("total", 0) if inv.get("outstanding_receivables") else 0
        overdue_invoices = inv.get("overdue_count", [{}])[0].get("count", 0) if inv.get("overdue_count") else 0
        recent_invoices = inv.get("recent", [])
        
        # Expenses - aggregation
        total_expenses_result = list(expenses_collection.aggregate([
            {"$match": {"approval_status": "approved"}},
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}}
        ]))
        total_expenses = total_expenses_result[0]["total"] if total_expenses_result else 0
        
        # Bills total - aggregation with facet
        bills_stats_pipeline = [
            {"$facet": {
                "total_bills": [
                    {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$total_amount", 0]}}}}
                ],
                "outstanding_payables": [
                    {"$match": {"status": {"$ne": "paid"}}},
                    {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$balance_due", 0]}}}}
                ]
            }}
        ]
        bills_stats = list(bills_collection.aggregate(bills_stats_pipeline))
        bs = bills_stats[0] if bills_stats else {}
        total_bills = bs.get("total_bills", [{}])[0].get("total", 0) if bs.get("total_bills") else 0
        outstanding_payables = bs.get("outstanding_payables", [{}])[0].get("total", 0) if bs.get("outstanding_payables") else 0
        
        # Payments - aggregation
        payments_received_result = list(payments_received_collection.aggregate([
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}}
        ]))
        payments_received_total = payments_received_result[0]["total"] if payments_received_result else 0
        
        payments_made_result = list(payments_made_collection.aggregate([
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}}
        ]))
        payments_made_total = payments_made_result[0]["total"] if payments_made_result else 0
        
        # Net profit
        net_profit = total_sales - total_expenses - total_bills
        profit_margin = (net_profit / total_sales * 100) if total_sales > 0 else 0
        
        # Recent activities
        recent_payments = list(payments_received_collection.find().sort("created_at", -1).limit(5))
        
        activities = []
        for inv in recent_invoices:
            activities.append({
                "type": "invoice",
                "description": f"Invoice {inv.get('invoice_number')} created",
                "amount": inv.get("total_amount", 0),
                "date": inv.get("created_at", datetime.utcnow()).isoformat()
            })
        for pmt in recent_payments:
            activities.append({
                "type": "payment",
                "description": f"Payment {pmt.get('payment_number')} received",
                "amount": pmt.get("amount", 0),
                "date": pmt.get("created_at", datetime.utcnow()).isoformat()
            })
        
        # Sort activities by date
        activities.sort(key=lambda x: x["date"], reverse=True)
        
        # Top customers by revenue
        top_customers_pipeline = [
            {"$match": {"status": {"$in": ["sent", "paid"]}}},
            {"$group": {"_id": "$customer_id", "total": {"$sum": "$total_amount"}}},
            {"$sort": {"total": -1}},
            {"$limit": 5}
        ]
        top_customer_data = list(invoices_collection.aggregate(top_customers_pipeline))
        
        top_customers = []
        for tc in top_customer_data:
            if tc["_id"]:
                try:
                    customer = customers_collection.find_one({"_id": ObjectId(tc["_id"])})
                    if customer:
                        top_customers.append({
                            "name": customer.get("name", "Unknown"),
                            "revenue": tc["total"]
                        })
                except:
                    pass
        
        return {
            "kpis": {
                "revenue": {
                    "total_sales": total_sales,
                    "total_invoices": total_invoices
                },
                "expenses": {
                    "total": total_expenses + total_bills
                },
                "profitability": {
                    "net_profit": net_profit,
                    "profit_margin": round(profit_margin, 1)
                },
                "cash_flow": {
                    "net_flow": payments_received_total - payments_made_total
                },
                "receivables": {
                    "outstanding": outstanding_receivables,
                    "overdue_count": overdue_invoices
                },
                "payables": {
                    "outstanding": outstanding_payables
                }
            },
            "recent_activities": activities[:10],
            "top_customers": top_customers,
            "unread_notifications": []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard data: {str(e)}")


# ============================================
# ASYNC BACKGROUND TASK ENDPOINTS
# ============================================

@router.post("/async/export/{export_type}")
async def start_async_export(
    export_type: str = Path(..., description="Type: customers, invoices, bills"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """
    Start an async export task. Returns operation_id for polling.
    Supported types: customers, invoices, bills
    """
    try:
        from tasks.async_helpers import start_finance_export
        
        result = start_finance_export(export_type, start_date, end_date)
        return {
            "success": True,
            "message": f"Export started for {export_type}",
            **result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/import/{import_type}")
async def start_async_import(
    import_type: str = Path(..., description="Type: customers, invoices"),
    file: UploadFile = File(...)
):
    """
    Start an async import task from CSV file. Returns operation_id for polling.
    Supported types: customers, invoices
    """
    try:
        from tasks.async_helpers import start_finance_import
        
        # Read file content
        csv_content = (await file.read()).decode('utf-8')
        
        result = start_finance_import(import_type, csv_content)
        return {
            "success": True,
            "message": f"Import started for {import_type}",
            "filename": file.filename,
            **result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/summary")
async def start_async_finance_summary(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """
    Generate comprehensive finance summary report in background.
    Returns operation_id for polling progress.
    """
    try:
        from tasks.async_helpers import start_finance_summary
        
        result = start_finance_summary(start_date, end_date)
        return {
            "success": True,
            "message": "Finance summary generation started",
            **result
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/customers/bulk-delete")
async def start_async_bulk_delete_customers(
    data: Dict[str, Any] = Body(...)
):
    """
    Bulk delete customers in background with dependency checking.
    Returns operation_id for polling progress.
    """
    try:
        from tasks.async_helpers import start_bulk_delete_customers
        
        customer_ids = data.get("customer_ids", [])
        if not customer_ids:
            raise HTTPException(status_code=400, detail="No customer_ids provided")
        
        result = start_bulk_delete_customers(customer_ids)
        return {
            "success": True,
            "message": f"Bulk delete started for {len(customer_ids)} customers",
            **result
        }
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=503, detail="Async task system not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/async/exports/{export_id}")
async def get_export_file(export_id: str):
    """
    Download a completed export file.
    """
    try:
        from backend.db_pools import get_api_collection
        from bson import ObjectId
        
        exports_collection = get_api_collection('export_files')
        export = exports_collection.find_one({'_id': ObjectId(export_id)})
        
        if not export:
            raise HTTPException(status_code=404, detail="Export not found")
        
        content = export.get('content', '')
        export_type = export.get('type', 'export')
        
        return StreamingResponse(
            io.StringIO(content),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={export_type}_{export_id}.csv"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
