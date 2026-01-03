"""
Unified Account Model
Links Operations Clients and Finance Customers into a unified entity.
This provides cross-module visibility for the CRM.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class AccountType(str, Enum):
    CLIENT = "client"           # Operations - receives surveys
    CUSTOMER = "customer"       # Finance - billed for services
    VENDOR = "vendor"           # Can be supplier/panel vendor
    BOTH = "both"               # Both client and customer


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROSPECT = "prospect"
    CHURNED = "churned"


class Address(BaseModel):
    line1: Optional[str] = ""
    line2: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    pincode: Optional[str] = ""
    country: Optional[str] = "India"


class BankDetails(BaseModel):
    bank_name: Optional[str] = ""
    account_number: Optional[str] = ""
    ifsc_code: Optional[str] = ""
    branch: Optional[str] = ""


class Account(BaseModel):
    """
    Unified Account that bridges Operations and Finance.
    Can be linked to:
    - Operations Clients (projects, traffic)
    - Finance Customers (invoices, payments)
    - Finance Vendors (bills, expenses)
    """
    
    # Core Identity
    name: str = Field(..., description="Account/Company name")
    account_type: AccountType = AccountType.CLIENT
    status: AccountStatus = AccountStatus.ACTIVE
    
    # Reference Numbers
    account_number: Optional[str] = None  # Unified account reference
    customer_number: Optional[str] = None  # Finance customer reference
    vendor_number: Optional[str] = None    # Finance vendor reference
    
    # Cross-Module Links (MongoDB ObjectId as strings)
    finance_customer_id: Optional[str] = None  # Link to finance_db.customers
    finance_vendor_id: Optional[str] = None    # Link to finance_db.vendors
    operations_client_id: Optional[str] = None # Link to email_automation.clients (if separate)
    
    # Contact Information
    primary_contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    
    # Address
    billing_address: Optional[Address] = None
    shipping_address: Optional[Address] = None
    
    # Financial Info
    gst_treatment: Optional[str] = "unregistered"
    gstin: Optional[str] = None
    pan: Optional[str] = None
    currency: Optional[str] = "INR"
    payment_terms: Optional[int] = 30  # Days
    credit_limit: Optional[float] = 0
    
    # Bank Details (for vendors)
    bank_details: Optional[BankDetails] = None
    
    # Industry & Segmentation
    industry: Optional[str] = None
    segment: Optional[str] = None
    source: Optional[str] = None  # How they became a customer (referral, lead, etc.)
    
    # Sales Info
    sales_person: Optional[str] = None
    account_manager: Optional[str] = None
    
    # Tags for flexible categorization
    tags: Optional[List[str]] = []
    
    # Notes
    notes: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AccountSummary(BaseModel):
    """Summary view of account for listings"""
    _id: str
    name: str
    account_type: AccountType
    status: AccountStatus
    email: Optional[str] = None
    phone: Optional[str] = None
    industry: Optional[str] = None
    
    # Aggregated metrics
    total_projects: Optional[int] = 0
    active_projects: Optional[int] = 0
    total_invoiced: Optional[float] = 0
    total_receivables: Optional[float] = 0
    total_paid: Optional[float] = 0


class ProjectFinancials(BaseModel):
    """Financial summary for a project"""
    project_id: str
    project_name: str
    
    # Revenue
    project_value: float = 0          # Expected value
    invoiced_amount: float = 0        # Amount invoiced
    received_amount: float = 0        # Amount received
    outstanding_amount: float = 0     # Amount pending
    
    # Costs
    total_costs: float = 0            # Bills + Expenses
    vendor_costs: float = 0           # Bills to vendors
    other_expenses: float = 0         # Other expenses
    
    # Profitability
    gross_profit: float = 0           # invoiced - costs
    profit_margin: float = 0          # profit / invoiced * 100
    
    # Linked Documents
    invoice_ids: List[str] = []
    bill_ids: List[str] = []
    expense_ids: List[str] = []
