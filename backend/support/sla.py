# backend/support/sla.py
# SLA Management and Calculation

from datetime import datetime, timedelta
from typing import Optional, Dict, List
from bson import ObjectId

from .models import (
    SLAPolicy, SLAStatus, TicketPriority, TicketStatus
)


class SLAManager:
    """Manages SLA calculations and enforcement"""
    
    def __init__(self, db):
        self.db = db
        # db is a DatabaseManager, get the torpedo_settings database
        settings_db = db.get_database("torpedo_settings")
        self.sla_policies = settings_db["sla_policies"]
        self.tickets = settings_db["tickets"]
    
    # ==================== SLA POLICIES ====================
    
    def create_policy(
        self,
        name: str,
        description: str = None,
        response_time: Dict[str, float] = None,
        resolution_time: Dict[str, float] = None,
        business_hours_only: bool = True,
        business_hours_start: int = 9,
        business_hours_end: int = 17,
        business_days: List[int] = None
    ) -> Dict:
        """Create a new SLA policy"""
        policy = SLAPolicy(
            name=name,
            description=description,
            response_time=response_time or SLAPolicy().response_time,
            resolution_time=resolution_time or SLAPolicy().resolution_time,
            business_hours_only=business_hours_only,
            business_hours_start=business_hours_start,
            business_hours_end=business_hours_end,
            business_days=business_days or [0, 1, 2, 3, 4]
        )
        
        policy_doc = policy.model_dump()
        result = self.sla_policies.insert_one(policy_doc)
        policy_doc["_id"] = result.inserted_id
        policy_doc["id"] = str(result.inserted_id)
        
        return policy_doc
    
    def get_policy(self, policy_id: str) -> Optional[SLAPolicy]:
        """Get an SLA policy by ID"""
        doc = self.sla_policies.find_one({"_id": ObjectId(policy_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return SLAPolicy(**doc)
        return None
    
    def get_default_policy(self) -> Optional[SLAPolicy]:
        """Get the default SLA policy"""
        doc = self.sla_policies.find_one({"is_active": True})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return SLAPolicy(**doc)
        # Return default policy if none exists
        return SLAPolicy(id="default", name="Default SLA")
    
    def list_policies(self, active_only: bool = True) -> List[Dict]:
        """List all SLA policies"""
        query = {"is_active": True} if active_only else {}
        policies = list(self.sla_policies.find(query))
        for p in policies:
            p["id"] = str(p.pop("_id"))
        return policies
    
    def update_policy(self, policy_id: str, **updates) -> Optional[Dict]:
        """Update an SLA policy"""
        updates["updated_at"] = datetime.utcnow()
        result = self.sla_policies.find_one_and_update(
            {"_id": ObjectId(policy_id)},
            {"$set": updates},
            return_document=True
        )
        if result:
            result["id"] = str(result.pop("_id"))
        return result
    
    def delete_policy(self, policy_id: str) -> bool:
        """Soft delete an SLA policy"""
        result = self.sla_policies.update_one(
            {"_id": ObjectId(policy_id)},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    # ==================== SLA CALCULATION ====================
    
    def calculate_sla_for_ticket(
        self,
        priority: TicketPriority,
        created_at: datetime,
        policy: SLAPolicy = None
    ) -> SLAStatus:
        """Calculate SLA deadlines for a ticket"""
        if not policy:
            policy = self.get_default_policy()
        
        priority_key = priority.value if isinstance(priority, TicketPriority) else priority
        
        response_hours = policy.response_time.get(priority_key, 8)
        resolution_hours = policy.resolution_time.get(priority_key, 24)
        
        if policy.business_hours_only:
            response_due = self._add_business_hours(
                created_at,
                response_hours,
                policy.business_hours_start,
                policy.business_hours_end,
                policy.business_days
            )
            resolution_due = self._add_business_hours(
                created_at,
                resolution_hours,
                policy.business_hours_start,
                policy.business_hours_end,
                policy.business_days
            )
        else:
            response_due = created_at + timedelta(hours=response_hours)
            resolution_due = created_at + timedelta(hours=resolution_hours)
        
        return SLAStatus(
            response_due=response_due,
            resolution_due=resolution_due,
            response_time_remaining=self._calculate_remaining(response_due),
            resolution_time_remaining=self._calculate_remaining(resolution_due)
        )
    
    def update_sla_status(
        self,
        ticket_id: str,
        first_response_at: datetime = None,
        resolved_at: datetime = None
    ) -> SLAStatus:
        """Update SLA status after response or resolution"""
        ticket = self.tickets.find_one({"_id": ObjectId(ticket_id)})
        if not ticket:
            return None
        
        sla_status = ticket.get("sla_status", {})
        
        if first_response_at:
            sla_status["first_response_at"] = first_response_at
            response_due = sla_status.get("response_due")
            if response_due and first_response_at > response_due:
                sla_status["response_breached"] = True
        
        if resolved_at:
            sla_status["resolved_at"] = resolved_at
            resolution_due = sla_status.get("resolution_due")
            if resolution_due and resolved_at > resolution_due:
                sla_status["resolution_breached"] = True
        
        # Update remaining times
        sla_status["response_time_remaining"] = self._calculate_remaining(
            sla_status.get("response_due")
        )
        sla_status["resolution_time_remaining"] = self._calculate_remaining(
            sla_status.get("resolution_due")
        )
        
        self.tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": {"sla_status": sla_status}}
        )
        
        return SLAStatus(**sla_status)
    
    def check_sla_breaches(self) -> List[Dict]:
        """Check for SLA breaches and return breached tickets"""
        now = datetime.utcnow()
        
        # Find tickets where SLA is about to breach or has breached
        breached_tickets = []
        
        # Response time breach check
        response_breached = list(self.tickets.find({
            "status": {"$in": [TicketStatus.OPEN.value]},
            "sla_status.first_response_at": None,
            "sla_status.response_due": {"$lt": now},
            "sla_status.response_breached": {"$ne": True},
            "is_deleted": False
        }))
        
        for ticket in response_breached:
            self.tickets.update_one(
                {"_id": ticket["_id"]},
                {"$set": {"sla_status.response_breached": True}}
            )
            ticket["breach_type"] = "response"
            breached_tickets.append(ticket)
        
        # Resolution time breach check
        resolution_breached = list(self.tickets.find({
            "status": {"$nin": [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]},
            "sla_status.resolution_due": {"$lt": now},
            "sla_status.resolution_breached": {"$ne": True},
            "is_deleted": False
        }))
        
        for ticket in resolution_breached:
            self.tickets.update_one(
                {"_id": ticket["_id"]},
                {"$set": {"sla_status.resolution_breached": True}}
            )
            ticket["breach_type"] = "resolution"
            breached_tickets.append(ticket)
        
        return breached_tickets
    
    def get_sla_at_risk_tickets(self, threshold_hours: float = 2) -> List[Dict]:
        """Get tickets at risk of SLA breach"""
        now = datetime.utcnow()
        threshold = now + timedelta(hours=threshold_hours)
        
        at_risk = list(self.tickets.find({
            "status": {"$nin": [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]},
            "is_deleted": False,
            "$or": [
                {
                    "sla_status.first_response_at": None,
                    "sla_status.response_due": {"$lte": threshold, "$gt": now},
                    "sla_status.response_breached": {"$ne": True}
                },
                {
                    "sla_status.resolution_due": {"$lte": threshold, "$gt": now},
                    "sla_status.resolution_breached": {"$ne": True}
                }
            ]
        }))
        
        for ticket in at_risk:
            ticket["id"] = str(ticket.pop("_id"))
        
        return at_risk
    
    # ==================== HELPERS ====================
    
    def _add_business_hours(
        self,
        start: datetime,
        hours: float,
        business_start: int,
        business_end: int,
        business_days: List[int]
    ) -> datetime:
        """Add business hours to a datetime"""
        hours_per_day = business_end - business_start
        current = start
        remaining_hours = hours
        
        # Limit iterations to prevent infinite loops
        max_iterations = 365 * 24  # 1 year
        iterations = 0
        
        while remaining_hours > 0 and iterations < max_iterations:
            iterations += 1
            
            # Check if current day is a business day
            if current.weekday() not in business_days:
                current = current.replace(hour=business_start, minute=0, second=0, microsecond=0)
                current += timedelta(days=1)
                continue
            
            # If before business hours, move to start of business hours
            if current.hour < business_start:
                current = current.replace(hour=business_start, minute=0, second=0, microsecond=0)
            
            # If after business hours, move to next day
            if current.hour >= business_end:
                current = current.replace(hour=business_start, minute=0, second=0, microsecond=0)
                current += timedelta(days=1)
                continue
            
            # Calculate hours remaining in current day
            hours_left_today = business_end - current.hour - (current.minute / 60)
            
            if remaining_hours <= hours_left_today:
                current += timedelta(hours=remaining_hours)
                remaining_hours = 0
            else:
                remaining_hours -= hours_left_today
                current = current.replace(hour=business_start, minute=0, second=0, microsecond=0)
                current += timedelta(days=1)
        
        return current
    
    def _calculate_remaining(self, due_date: datetime) -> Optional[float]:
        """Calculate remaining hours until due date"""
        if not due_date:
            return None
        
        now = datetime.utcnow()
        if isinstance(due_date, str):
            due_date = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
        
        delta = due_date - now
        return round(delta.total_seconds() / 3600, 2)
