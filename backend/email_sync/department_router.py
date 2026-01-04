"""
DEPARTMENT AUTO-ROUTING
=======================

Automatically routes classified emails to appropriate departments:
- Sales: Leads, discovery calls, demos
- Finance: Invoices, payments, billing
- Operations: RFQs, orders, delivery
- Support: Tickets, complaints

Creates appropriate records in each department's system based on email content.
"""

import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)


# Category to department mapping
CATEGORY_DEPARTMENT_MAP = {
    # Sales
    "inbound_lead": "sales",
    "meeting_request": "sales",
    "demo_request": "sales",
    "pricing_inquiry": "sales",
    "interested": "sales",
    "discovery": "sales",
    "outreach": "sales",
    
    # Finance
    "invoice": "finance",
    "payment_confirmation": "finance",
    "payment_reminder": "finance",
    "billing_dispute": "finance",
    "banking": "finance",
    
    # Operations
    "rfq_request": "operations",
    "quote_response": "operations",
    "negotiation": "operations",
    "contract_discussion": "operations",
    "purchase_order": "operations",
    "delivery_update": "operations",
    "vendor_communication": "operations",
    
    # Support
    "support_request": "support",
    "complaint": "support",
    "feedback": "support",
    "onboarding": "support",
    
    # Low priority / No routing
    "newsletter": None,
    "promotional": None,
    "spam": None,
    "social_notification": None,
    "out_of_office": None,
    "bounce": None,
    "unsubscribe": None,
    "auto_reply": None,
    "internal": None,
    "other": None,
    "uncategorized": None,
}


class DepartmentRouter:
    """
    Routes emails to appropriate departments and creates relevant records.
    """
    
    def __init__(self, db: MongoClient):
        """
        Initialize department router.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        
        # Department handlers
        self.handlers = {
            "sales": SalesHandler(db),
            "finance": FinanceHandler(db),
            "operations": OperationsHandler(db),
            "support": SupportHandler(db),
        }
        
        # Routing log
        self.routing_log = db["email_routing_log"]
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            self.routing_log.create_index([("email_id", 1)], unique=True)
            self.routing_log.create_index([("department", 1), ("routed_at", -1)])
            self.routing_log.create_index([("created_record_type", 1)])
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
    
    def route_email(self, email_id: str) -> Dict[str, Any]:
        """
        Route an email to the appropriate department.
        
        Args:
            email_id: ID of the email to route
            
        Returns:
            Dict with routing result
        """
        # Check if already routed
        existing = self.routing_log.find_one({"email_id": email_id})
        if existing:
            return {
                "status": "already_routed",
                "department": existing.get("department"),
                "created_record_id": existing.get("created_record_id")
            }
        
        # Get email
        email = self.db["emails"].find_one({"_id": ObjectId(email_id)})
        if not email:
            return {"status": "error", "error": "Email not found"}
        
        # Determine department from category
        category = email.get("b2b_category") or email.get("category")
        if not category:
            return {"status": "skipped", "reason": "No category"}
        
        department = CATEGORY_DEPARTMENT_MAP.get(category)
        if not department:
            return {"status": "skipped", "reason": f"No routing for category: {category}"}
        
        # Route to handler
        handler = self.handlers.get(department)
        if not handler:
            return {"status": "error", "error": f"No handler for department: {department}"}
        
        try:
            result = handler.handle(email)
            
            # Log routing
            log_entry = {
                "email_id": email_id,
                "department": department,
                "category": category,
                "routed_at": datetime.utcnow(),
                "created_record_type": result.get("record_type"),
                "created_record_id": result.get("record_id"),
                "action_taken": result.get("action"),
                "success": result.get("success", True)
            }
            self.routing_log.insert_one(log_entry)
            
            # Mark email as routed
            self.db["emails"].update_one(
                {"_id": ObjectId(email_id)},
                {
                    "$set": {
                        "routed_to_department": department,
                        "routed_at": datetime.utcnow(),
                        "routing_record_id": result.get("record_id")
                    }
                }
            )
            
            return {
                "status": "routed",
                "department": department,
                **result
            }
            
        except Exception as e:
            logger.error(f"Routing failed for email {email_id}: {e}")
            return {"status": "error", "error": str(e)}
    
    def route_batch(self, email_ids: List[str]) -> Dict[str, Any]:
        """Route multiple emails"""
        results = {
            "routed": 0,
            "skipped": 0,
            "errors": 0,
            "already_routed": 0,
            "details": []
        }
        
        for email_id in email_ids:
            result = self.route_email(email_id)
            status = result.get("status")
            
            if status == "routed":
                results["routed"] += 1
            elif status == "skipped":
                results["skipped"] += 1
            elif status == "already_routed":
                results["already_routed"] += 1
            else:
                results["errors"] += 1
                results["details"].append({"email_id": email_id, "error": result.get("error")})
        
        return results
    
    def route_unrouted_emails(self, limit: int = 100) -> Dict[str, Any]:
        """Route all unrouted classified emails"""
        unrouted = self.db["emails"].find({
            "b2b_category": {"$exists": True},
            "routed_to_department": {"$exists": False}
        }).limit(limit)
        
        email_ids = [str(e["_id"]) for e in unrouted]
        return self.route_batch(email_ids)


class SalesHandler:
    """Handles routing to Sales department"""
    
    def __init__(self, db: MongoClient):
        self.db = db
        self.leads = db["email_leads"]
        self.accounts = db["sales_accounts"]
    
    def handle(self, email: Dict) -> Dict[str, Any]:
        """Handle a sales-related email"""
        category = email.get("b2b_category") or email.get("category")
        
        # Extract sender info
        from_addr = email.get("from_address", {})
        if isinstance(from_addr, dict):
            from_email = from_addr.get("email", "")
            from_name = from_addr.get("name", "")
        else:
            from_email = str(from_addr)
            from_name = ""
        
        # Check for existing lead
        existing_lead = self.leads.find_one({"email": from_email})
        
        if existing_lead:
            # Update existing lead
            update = {
                "last_activity_at": datetime.utcnow(),
                "last_email_id": str(email["_id"]),
                "$inc": {"email_count": 1}
            }
            
            # Upgrade status if showing interest
            if category in ("meeting_request", "demo_request", "interested"):
                update["status"] = "interested"
                update["qualified_at"] = datetime.utcnow()
            
            self.leads.update_one(
                {"_id": existing_lead["_id"]},
                {"$set": update}
            )
            
            return {
                "success": True,
                "action": "updated_lead",
                "record_type": "lead",
                "record_id": str(existing_lead["_id"])
            }
        else:
            # Create new lead
            name_parts = from_name.split(" ", 1) if from_name else ["", ""]
            
            lead = {
                "email": from_email,
                "first_name": name_parts[0] if name_parts else "",
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "source": "inbound_email",
                "source_email_id": str(email["_id"]),
                "status": "new",
                "created_at": datetime.utcnow(),
                "last_activity_at": datetime.utcnow(),
                "email_count": 1,
                "category_at_creation": category,
                
                # Extract company from email domain
                "company_domain": from_email.split("@")[1] if "@" in from_email else None,
                
                # Key entities from classification
                "key_entities": email.get("key_entities", {})
            }
            
            # Upgrade status for high-intent categories
            if category in ("meeting_request", "demo_request", "interested"):
                lead["status"] = "interested"
            elif category in ("pricing_inquiry", "rfq_request"):
                lead["status"] = "qualified"
            
            result = self.leads.insert_one(lead)
            
            return {
                "success": True,
                "action": "created_lead",
                "record_type": "lead",
                "record_id": str(result.inserted_id)
            }


class FinanceHandler:
    """Handles routing to Finance department"""
    
    def __init__(self, db: MongoClient):
        self.db = db
        self.invoices = db["invoices"]
        self.payments = db["payments"]
        self.finance_emails = db["finance_emails"]
    
    def handle(self, email: Dict) -> Dict[str, Any]:
        """Handle a finance-related email"""
        category = email.get("b2b_category") or email.get("category")
        
        # Create finance email record for review
        finance_email = {
            "email_id": str(email["_id"]),
            "category": category,
            "from_email": self._get_from_email(email),
            "subject": email.get("subject", ""),
            "received_at": email.get("timestamp"),
            "created_at": datetime.utcnow(),
            "status": "pending_review",
            "key_entities": email.get("key_entities", {}),
            "suggested_action": email.get("suggested_action"),
            "priority": email.get("category_priority", "medium")
        }
        
        # Try to extract invoice/payment info
        if category == "invoice":
            finance_email["type"] = "invoice_received"
            # Could add AI extraction of invoice number, amount, due date
            
        elif category == "payment_confirmation":
            finance_email["type"] = "payment_received"
            
        elif category == "payment_reminder":
            finance_email["type"] = "payment_due"
            finance_email["priority"] = "high"
            
        elif category == "billing_dispute":
            finance_email["type"] = "dispute"
            finance_email["priority"] = "high"
        
        result = self.finance_emails.insert_one(finance_email)
        
        return {
            "success": True,
            "action": "created_finance_email",
            "record_type": "finance_email",
            "record_id": str(result.inserted_id)
        }
    
    def _get_from_email(self, email: Dict) -> str:
        from_addr = email.get("from_address", {})
        if isinstance(from_addr, dict):
            return from_addr.get("email", "")
        return str(from_addr)


class OperationsHandler:
    """Handles routing to Operations department"""
    
    def __init__(self, db: MongoClient):
        self.db = db
        self.rfqs = db["rfqs"]
        self.orders = db["orders"]
        self.ops_emails = db["operations_emails"]
    
    def handle(self, email: Dict) -> Dict[str, Any]:
        """Handle an operations-related email"""
        category = email.get("b2b_category") or email.get("category")
        
        # Extract sender info
        from_addr = email.get("from_address", {})
        if isinstance(from_addr, dict):
            from_email = from_addr.get("email", "")
            from_name = from_addr.get("name", "")
        else:
            from_email = str(from_addr)
            from_name = ""
        
        if category in ("rfq_request", "pricing_inquiry"):
            return self._create_rfq(email, from_email, from_name)
        
        elif category == "purchase_order":
            return self._create_order(email, from_email, from_name)
        
        else:
            # Generic operations email
            ops_email = {
                "email_id": str(email["_id"]),
                "category": category,
                "from_email": from_email,
                "from_name": from_name,
                "subject": email.get("subject", ""),
                "received_at": email.get("timestamp"),
                "created_at": datetime.utcnow(),
                "status": "pending_review",
                "key_entities": email.get("key_entities", {}),
                "priority": email.get("category_priority", "medium")
            }
            
            result = self.ops_emails.insert_one(ops_email)
            
            return {
                "success": True,
                "action": "created_ops_email",
                "record_type": "operations_email",
                "record_id": str(result.inserted_id)
            }
    
    def _create_rfq(self, email: Dict, from_email: str, from_name: str) -> Dict[str, Any]:
        """Create an RFQ from email"""
        # Check for existing RFQ from same sender recently
        existing = self.rfqs.find_one({
            "contact_email": from_email,
            "created_at": {"$gte": datetime.utcnow() - __import__("datetime").timedelta(hours=24)},
            "status": {"$in": ["new", "pending"]}
        })
        
        if existing:
            # Add email to existing RFQ
            self.rfqs.update_one(
                {"_id": existing["_id"]},
                {
                    "$push": {"source_emails": str(email["_id"])},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            return {
                "success": True,
                "action": "updated_rfq",
                "record_type": "rfq",
                "record_id": str(existing["_id"])
            }
        
        # Create new RFQ
        rfq = {
            "contact_email": from_email,
            "contact_name": from_name,
            "company_domain": from_email.split("@")[1] if "@" in from_email else None,
            "subject": email.get("subject", ""),
            "source_emails": [str(email["_id"])],
            "status": "new",
            "priority": email.get("category_priority", "medium"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "key_entities": email.get("key_entities", {}),
            
            # To be filled by operations team
            "items": [],
            "quoted_value": None,
            "expected_close_date": None,
            "assigned_to": None
        }
        
        result = self.rfqs.insert_one(rfq)
        
        return {
            "success": True,
            "action": "created_rfq",
            "record_type": "rfq",
            "record_id": str(result.inserted_id)
        }
    
    def _create_order(self, email: Dict, from_email: str, from_name: str) -> Dict[str, Any]:
        """Create an order from email"""
        order = {
            "contact_email": from_email,
            "contact_name": from_name,
            "company_domain": from_email.split("@")[1] if "@" in from_email else None,
            "subject": email.get("subject", ""),
            "source_email_id": str(email["_id"]),
            "status": "pending_review",
            "created_at": datetime.utcnow(),
            "key_entities": email.get("key_entities", {}),
            
            # To be filled by operations team
            "items": [],
            "order_value": None,
            "po_number": None
        }
        
        result = self.orders.insert_one(order)
        
        return {
            "success": True,
            "action": "created_order",
            "record_type": "order",
            "record_id": str(result.inserted_id)
        }


class SupportHandler:
    """Handles routing to Support department"""
    
    def __init__(self, db: MongoClient):
        self.db = db
        self.tickets = db["support_tickets"]
    
    def handle(self, email: Dict) -> Dict[str, Any]:
        """Handle a support-related email"""
        category = email.get("b2b_category") or email.get("category")
        
        # Extract sender info
        from_addr = email.get("from_address", {})
        if isinstance(from_addr, dict):
            from_email = from_addr.get("email", "")
            from_name = from_addr.get("name", "")
        else:
            from_email = str(from_addr)
            from_name = ""
        
        # Check for existing open ticket
        existing = self.tickets.find_one({
            "contact_email": from_email,
            "status": {"$in": ["open", "in_progress", "waiting_customer"]}
        }, sort=[("created_at", -1)])
        
        if existing:
            # Add to existing ticket
            self.tickets.update_one(
                {"_id": existing["_id"]},
                {
                    "$push": {"email_thread": str(email["_id"])},
                    "$set": {
                        "updated_at": datetime.utcnow(),
                        "status": "open"  # Reopen if was waiting
                    }
                }
            )
            return {
                "success": True,
                "action": "updated_ticket",
                "record_type": "support_ticket",
                "record_id": str(existing["_id"])
            }
        
        # Create new ticket
        priority = "high" if category == "complaint" else email.get("category_priority", "medium")
        
        ticket = {
            "contact_email": from_email,
            "contact_name": from_name,
            "subject": email.get("subject", ""),
            "category": category,
            "email_thread": [str(email["_id"])],
            "status": "open",
            "priority": priority,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "key_entities": email.get("key_entities", {}),
            
            # To be filled by support team
            "assigned_to": None,
            "resolution": None,
            "resolved_at": None
        }
        
        result = self.tickets.insert_one(ticket)
        
        return {
            "success": True,
            "action": "created_ticket",
            "record_type": "support_ticket",
            "record_id": str(result.inserted_id)
        }


class DepartmentRoutingWorker:
    """
    Background worker that routes newly classified emails.
    """
    
    def __init__(
        self,
        db: MongoClient,
        poll_interval: int = 60
    ):
        """
        Initialize routing worker.
        
        Args:
            db: MongoDB database instance
            poll_interval: Seconds between poll cycles
        """
        self.db = db
        self.router = DepartmentRouter(db)
        self.poll_interval = poll_interval
        
        self._running = False
        self._thread = None
        self._stop_event = __import__("threading").Event()
    
    def start(self):
        """Start the worker thread"""
        if self._running:
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = __import__("threading").Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("DepartmentRoutingWorker started")
    
    def stop(self):
        """Stop the worker thread"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("DepartmentRoutingWorker stopped")
    
    def _run_loop(self):
        """Main processing loop"""
        while self._running and not self._stop_event.is_set():
            try:
                result = self.router.route_unrouted_emails(limit=50)
                if result["routed"] > 0:
                    logger.info(f"Routed {result['routed']} emails to departments")
                
                self._stop_event.wait(self.poll_interval)
                
            except Exception as e:
                logger.error(f"DepartmentRoutingWorker error: {e}", exc_info=True)
                __import__("time").sleep(30)
