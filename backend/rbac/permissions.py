"""
Permission Definitions
======================

Hierarchical permission constants organized by module.
Format: MODULE_ENTITY_ACTION

Modules:
- FINANCE: Invoices, bills, payments, expenses
- SALES: Leads, contacts, RFQs, deals
- OPS: Projects, resources, traffic
- ADMIN: Users, roles, system settings
"""

from enum import Enum
from typing import Dict, List, Set


class PermissionCategory(str, Enum):
    """Top-level permission categories (modules)."""
    FINANCE = "finance"
    SALES = "sales"
    OPS = "ops"
    ADMIN = "admin"
    SYSTEM = "system"


class Permissions:
    """
    All permission constants.
    Naming: {MODULE}_{ENTITY}_{ACTION}
    """
    
    # ========================================
    # FINANCE MODULE
    # ========================================
    
    # Invoices
    FINANCE_INVOICE_READ = "finance.invoice.read"
    FINANCE_INVOICE_CREATE = "finance.invoice.create"
    FINANCE_INVOICE_UPDATE = "finance.invoice.update"
    FINANCE_INVOICE_DELETE = "finance.invoice.delete"
    FINANCE_INVOICE_APPROVE = "finance.invoice.approve"
    FINANCE_INVOICE_SEND = "finance.invoice.send"
    
    # Bills
    FINANCE_BILL_READ = "finance.bill.read"
    FINANCE_BILL_CREATE = "finance.bill.create"
    FINANCE_BILL_UPDATE = "finance.bill.update"
    FINANCE_BILL_DELETE = "finance.bill.delete"
    FINANCE_BILL_APPROVE = "finance.bill.approve"
    
    # Payments
    FINANCE_PAYMENT_READ = "finance.payment.read"
    FINANCE_PAYMENT_CREATE = "finance.payment.create"
    FINANCE_PAYMENT_APPROVE = "finance.payment.approve"
    
    # Expenses
    FINANCE_EXPENSE_READ = "finance.expense.read"
    FINANCE_EXPENSE_CREATE = "finance.expense.create"
    FINANCE_EXPENSE_APPROVE = "finance.expense.approve"
    
    # Customers/Vendors
    FINANCE_CUSTOMER_READ = "finance.customer.read"
    FINANCE_CUSTOMER_CREATE = "finance.customer.create"
    FINANCE_CUSTOMER_UPDATE = "finance.customer.update"
    FINANCE_CUSTOMER_DELETE = "finance.customer.delete"
    
    FINANCE_VENDOR_READ = "finance.vendor.read"
    FINANCE_VENDOR_CREATE = "finance.vendor.create"
    FINANCE_VENDOR_UPDATE = "finance.vendor.update"
    FINANCE_VENDOR_DELETE = "finance.vendor.delete"
    
    # ========================================
    # SALES MODULE
    # ========================================
    
    # Leads
    SALES_LEAD_READ = "sales.lead.read"
    SALES_LEAD_CREATE = "sales.lead.create"
    SALES_LEAD_UPDATE = "sales.lead.update"
    SALES_LEAD_DELETE = "sales.lead.delete"
    SALES_LEAD_ASSIGN = "sales.lead.assign"
    SALES_LEAD_CONVERT = "sales.lead.convert"
    
    # Contacts
    SALES_CONTACT_READ = "sales.contact.read"
    SALES_CONTACT_CREATE = "sales.contact.create"
    SALES_CONTACT_UPDATE = "sales.contact.update"
    SALES_CONTACT_DELETE = "sales.contact.delete"
    
    # RFQs
    SALES_RFQ_READ = "sales.rfq.read"
    SALES_RFQ_CREATE = "sales.rfq.create"
    SALES_RFQ_UPDATE = "sales.rfq.update"
    SALES_RFQ_DELETE = "sales.rfq.delete"
    SALES_RFQ_CONVERT = "sales.rfq.convert"
    SALES_RFQ_CLOSE = "sales.rfq.close"
    
    # Deals/Opportunities
    SALES_DEAL_READ = "sales.deal.read"
    SALES_DEAL_CREATE = "sales.deal.create"
    SALES_DEAL_UPDATE = "sales.deal.update"
    SALES_DEAL_CLOSE = "sales.deal.close"
    
    # Campaigns
    SALES_CAMPAIGN_READ = "sales.campaign.read"
    SALES_CAMPAIGN_CREATE = "sales.campaign.create"
    SALES_CAMPAIGN_UPDATE = "sales.campaign.update"
    SALES_CAMPAIGN_SEND = "sales.campaign.send"
    
    # ========================================
    # OPERATIONS MODULE
    # ========================================
    
    # Projects
    OPS_PROJECT_READ = "ops.project.read"
    OPS_PROJECT_CREATE = "ops.project.create"
    OPS_PROJECT_UPDATE = "ops.project.update"
    OPS_PROJECT_DELETE = "ops.project.delete"
    OPS_PROJECT_ASSIGN = "ops.project.assign"
    
    # Traffic/Survey
    OPS_TRAFFIC_READ = "ops.traffic.read"
    OPS_TRAFFIC_CREATE = "ops.traffic.create"
    OPS_TRAFFIC_UPDATE = "ops.traffic.update"
    
    # Resources
    OPS_RESOURCE_READ = "ops.resource.read"
    OPS_RESOURCE_ASSIGN = "ops.resource.assign"
    
    # Support/Tickets
    OPS_TICKET_READ = "ops.ticket.read"
    OPS_TICKET_CREATE = "ops.ticket.create"
    OPS_TICKET_UPDATE = "ops.ticket.update"
    OPS_TICKET_DELETE = "ops.ticket.delete"
    OPS_TICKET_ASSIGN = "ops.ticket.assign"
    OPS_TICKET_CLOSE = "ops.ticket.close"
    OPS_SLA_MANAGE = "ops.sla.manage"
    
    # ========================================
    # ADMIN MODULE
    # ========================================
    
    # Users
    ADMIN_USER_READ = "admin.user.read"
    ADMIN_USER_CREATE = "admin.user.create"
    ADMIN_USER_UPDATE = "admin.user.update"
    ADMIN_USER_DELETE = "admin.user.delete"
    ADMIN_USER_DEACTIVATE = "admin.user.deactivate"
    
    # Roles
    ADMIN_ROLE_READ = "admin.role.read"
    ADMIN_ROLE_CREATE = "admin.role.create"
    ADMIN_ROLE_UPDATE = "admin.role.update"
    ADMIN_ROLE_DELETE = "admin.role.delete"
    ADMIN_ROLE_ASSIGN = "admin.role.assign"
    
    # Settings
    ADMIN_SETTINGS_READ = "admin.settings.read"
    ADMIN_SETTINGS_UPDATE = "admin.settings.update"
    
    # Approval Rules (Settings)
    SETTINGS_APPROVAL_VIEW = "settings.approval.view"
    SETTINGS_APPROVAL_CREATE = "settings.approval.create"
    SETTINGS_APPROVAL_UPDATE = "settings.approval.update"
    SETTINGS_APPROVAL_DELETE = "settings.approval.delete"
    
    # Super Admin
    ADMIN_ALL = "admin.*"
    
    # Audit
    ADMIN_AUDIT_READ = "admin.audit.read"
    
    # ========================================
    # SYSTEM MODULE (MCP/Automation)
    # ========================================
    
    SYSTEM_MCP_READ = "system.mcp.read"
    SYSTEM_MCP_OVERRIDE = "system.mcp.override"
    SYSTEM_APPROVAL_READ = "system.approval.read"
    SYSTEM_APPROVAL_MANAGE = "system.approval.manage"
    
    # ========================================
    # Helper Methods
    # ========================================
    
    @classmethod
    def all_permissions(cls) -> List[str]:
        """Get all defined permissions."""
        return [
            value for name, value in vars(cls).items()
            if isinstance(value, str) and not name.startswith("_") and "." in value
        ]
    
    @classmethod
    def by_category(cls, category: PermissionCategory) -> List[str]:
        """Get all permissions for a category/module."""
        prefix = category.value + "."
        return [p for p in cls.all_permissions() if p.startswith(prefix)]
    
    @classmethod
    def read_permissions(cls) -> List[str]:
        """Get all read-only permissions."""
        return [p for p in cls.all_permissions() if p.endswith(".read")]
    
    @classmethod
    def write_permissions(cls) -> List[str]:
        """Get all write permissions (create, update, delete)."""
        return [
            p for p in cls.all_permissions()
            if any(p.endswith(action) for action in [".create", ".update", ".delete"])
        ]
    
    @classmethod
    def approval_permissions(cls) -> List[str]:
        """Get all approval-related permissions."""
        return [p for p in cls.all_permissions() if p.endswith(".approve")]


# ========================================
# Predefined Role Templates
# ========================================

ROLE_TEMPLATES: Dict[str, Dict[str, any]] = {
    "admin": {
        "name": "Administrator",
        "description": "Full system access",
        "permissions": Permissions.all_permissions(),
        "is_system_role": True,
    },
    "finance_manager": {
        "name": "Finance Manager",
        "description": "Full finance access with approvals",
        "permissions": [
            *Permissions.by_category(PermissionCategory.FINANCE),
            Permissions.ADMIN_AUDIT_READ,
        ],
        "is_system_role": True,
    },
    "finance_user": {
        "name": "Finance User",
        "description": "Create/edit finance records, no approvals",
        "permissions": [
            Permissions.FINANCE_INVOICE_READ,
            Permissions.FINANCE_INVOICE_CREATE,
            Permissions.FINANCE_INVOICE_UPDATE,
            Permissions.FINANCE_BILL_READ,
            Permissions.FINANCE_BILL_CREATE,
            Permissions.FINANCE_BILL_UPDATE,
            Permissions.FINANCE_EXPENSE_READ,
            Permissions.FINANCE_EXPENSE_CREATE,
            Permissions.FINANCE_PAYMENT_READ,
            Permissions.FINANCE_CUSTOMER_READ,
            Permissions.FINANCE_CUSTOMER_CREATE,
            Permissions.FINANCE_CUSTOMER_UPDATE,
            Permissions.FINANCE_VENDOR_READ,
            Permissions.FINANCE_VENDOR_CREATE,
            Permissions.FINANCE_VENDOR_UPDATE,
        ],
        "is_system_role": True,
    },
    "sales_manager": {
        "name": "Sales Manager",
        "description": "Full sales access with team management",
        "permissions": [
            *Permissions.by_category(PermissionCategory.SALES),
            Permissions.OPS_PROJECT_READ,
            Permissions.FINANCE_INVOICE_READ,
            Permissions.FINANCE_CUSTOMER_READ,
            Permissions.ADMIN_AUDIT_READ,
        ],
        "is_system_role": True,
    },
    "sales_rep": {
        "name": "Sales Representative",
        "description": "Basic sales access, no closures",
        "permissions": [
            Permissions.SALES_LEAD_READ,
            Permissions.SALES_LEAD_CREATE,
            Permissions.SALES_LEAD_UPDATE,
            Permissions.SALES_CONTACT_READ,
            Permissions.SALES_CONTACT_CREATE,
            Permissions.SALES_CONTACT_UPDATE,
            Permissions.SALES_RFQ_READ,
            Permissions.SALES_RFQ_CREATE,
            Permissions.SALES_RFQ_UPDATE,
            Permissions.SALES_CAMPAIGN_READ,
        ],
        "is_system_role": True,
    },
    "ops_manager": {
        "name": "Operations Manager",
        "description": "Full operations and project access",
        "permissions": [
            *Permissions.by_category(PermissionCategory.OPS),
            Permissions.SALES_RFQ_READ,
            Permissions.FINANCE_INVOICE_READ,
            Permissions.FINANCE_BILL_READ,
        ],
        "is_system_role": True,
    },
    "viewer": {
        "name": "Viewer",
        "description": "Read-only access across modules",
        "permissions": Permissions.read_permissions(),
        "is_system_role": True,
    },
}
