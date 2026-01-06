# backend/support/service.py
# Support/Tickets Service Layer

from datetime import datetime
from typing import Optional, List, Dict, Any
from bson import ObjectId
import uuid

from .models import (
    Ticket, TicketCreate, TicketUpdate, TicketResolve, TicketEscalate,
    TicketStatus, TicketPriority, TicketCategory, TicketSource,
    TicketComment, TicketActivity, TicketStats,
    EscalationLevel, TeamQueue
)
from .sla import SLAManager


class TicketService:
    """Service class for ticket operations"""
    
    def __init__(self, db):
        self.db = db
        # db is a DatabaseManager, get the torpedo_settings database
        settings_db = db.get_database("torpedo_settings")
        self.tickets = settings_db["tickets"]
        self.comments = settings_db["ticket_comments"]
        self.activities = settings_db["ticket_activities"]
        self.teams = settings_db["support_teams"]
        self.sla_manager = SLAManager(db)
    
    # ==================== TICKETS ====================
    
    def create_ticket(self, data: TicketCreate, created_by: str = None) -> Dict[str, Any]:
        """Create a new ticket"""
        # Generate ticket number
        count = self.tickets.count_documents({})
        ticket_number = f"TKT-{count + 1:06d}"
        
        ticket_doc = {
            **data.model_dump(),
            "ticket_number": ticket_number,
            "status": TicketStatus.OPEN.value,
            "escalation_level": EscalationLevel.LEVEL_1.value,
            "created_at": datetime.utcnow(),
            "created_by": created_by,
            "is_deleted": False,
            "related_tickets": []
        }
        
        # Calculate SLA
        policy = None
        if data.sla_policy_id:
            policy = self.sla_manager.get_policy(data.sla_policy_id)
        
        sla_status = self.sla_manager.calculate_sla_for_ticket(
            priority=data.priority,
            created_at=ticket_doc["created_at"],
            policy=policy
        )
        ticket_doc["sla_status"] = sla_status.model_dump()
        
        result = self.tickets.insert_one(ticket_doc)
        ticket_doc["_id"] = result.inserted_id
        
        # Log activity
        self._log_activity(
            ticket_id=str(result.inserted_id),
            action="created",
            description=f"Ticket {ticket_number} created",
            actor_id=created_by,
            actor_type="agent"
        )
        
        return self._serialize_ticket(ticket_doc)
    
    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get a ticket by ID"""
        ticket = self.tickets.find_one({"_id": ObjectId(ticket_id), "is_deleted": False})
        return self._serialize_ticket(ticket) if ticket else None
    
    def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict[str, Any]]:
        """Get a ticket by ticket number"""
        ticket = self.tickets.find_one({"ticket_number": ticket_number, "is_deleted": False})
        return self._serialize_ticket(ticket) if ticket else None
    
    def list_tickets(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        assigned_to: Optional[str] = None,
        team_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        account_id: Optional[str] = None,
        sla_breached: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_order: int = -1
    ) -> Dict[str, Any]:
        """List tickets with filters"""
        query = {"is_deleted": False}
        
        if status:
            query["status"] = status
        if priority:
            query["priority"] = priority
        if category:
            query["category"] = category
        if assigned_to:
            query["assigned_to"] = assigned_to
        if team_id:
            query["team_id"] = team_id
        if contact_id:
            query["contact_id"] = contact_id
        if account_id:
            query["account_id"] = account_id
        if sla_breached is not None:
            if sla_breached:
                query["$or"] = [
                    {"sla_status.response_breached": True},
                    {"sla_status.resolution_breached": True}
                ]
            else:
                query["sla_status.response_breached"] = {"$ne": True}
                query["sla_status.resolution_breached"] = {"$ne": True}
        
        total = self.tickets.count_documents(query)
        tickets = list(
            self.tickets.find(query)
            .sort(sort_by, sort_order)
            .skip(skip)
            .limit(limit)
        )
        
        return {
            "items": [self._serialize_ticket(t) for t in tickets],
            "total": total,
            "skip": skip,
            "limit": limit
        }
    
    def update_ticket(
        self,
        ticket_id: str,
        data: TicketUpdate,
        updated_by: str = None
    ) -> Optional[Dict[str, Any]]:
        """Update a ticket"""
        old_ticket = self.tickets.find_one({"_id": ObjectId(ticket_id)})
        if not old_ticket:
            return None
        
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        update_data["updated_at"] = datetime.utcnow()
        
        # Track status changes
        if data.status and data.status.value != old_ticket.get("status"):
            self._log_activity(
                ticket_id=ticket_id,
                action="status_change",
                description=f"Status changed from {old_ticket.get('status')} to {data.status.value}",
                actor_id=updated_by,
                old_value=old_ticket.get("status"),
                new_value=data.status.value
            )
        
        # Track assignment changes
        if data.assigned_to and data.assigned_to != old_ticket.get("assigned_to"):
            update_data["assigned_at"] = datetime.utcnow()
            self._log_activity(
                ticket_id=ticket_id,
                action="assignment",
                description=f"Ticket assigned to {data.assigned_to}",
                actor_id=updated_by,
                old_value=old_ticket.get("assigned_to"),
                new_value=data.assigned_to
            )
        
        # Track priority changes
        if data.priority and data.priority.value != old_ticket.get("priority"):
            self._log_activity(
                ticket_id=ticket_id,
                action="priority_change",
                description=f"Priority changed from {old_ticket.get('priority')} to {data.priority.value}",
                actor_id=updated_by,
                old_value=old_ticket.get("priority"),
                new_value=data.priority.value
            )
            
            # Recalculate SLA with new priority
            sla_status = self.sla_manager.calculate_sla_for_ticket(
                priority=data.priority,
                created_at=old_ticket.get("created_at", datetime.utcnow())
            )
            update_data["sla_status"] = sla_status.model_dump()
        
        result = self.tickets.find_one_and_update(
            {"_id": ObjectId(ticket_id), "is_deleted": False},
            {"$set": update_data},
            return_document=True
        )
        
        return self._serialize_ticket(result) if result else None
    
    def resolve_ticket(
        self,
        ticket_id: str,
        resolution: str,
        close_ticket: bool = False,
        resolved_by: str = None
    ) -> Optional[Dict[str, Any]]:
        """Resolve a ticket"""
        now = datetime.utcnow()
        update_data = {
            "resolution": resolution,
            "resolved_at": now,
            "resolved_by": resolved_by,
            "status": TicketStatus.CLOSED.value if close_ticket else TicketStatus.RESOLVED.value,
            "updated_at": now
        }
        
        if close_ticket:
            update_data["closed_at"] = now
        
        result = self.tickets.find_one_and_update(
            {"_id": ObjectId(ticket_id), "is_deleted": False},
            {"$set": update_data},
            return_document=True
        )
        
        if result:
            # Update SLA status
            self.sla_manager.update_sla_status(ticket_id, resolved_at=now)
            
            # Log activity
            self._log_activity(
                ticket_id=ticket_id,
                action="resolved",
                description=f"Ticket resolved: {resolution[:100]}...",
                actor_id=resolved_by
            )
        
        return self._serialize_ticket(result) if result else None
    
    def close_ticket(self, ticket_id: str, closed_by: str = None) -> Optional[Dict[str, Any]]:
        """Close a ticket"""
        now = datetime.utcnow()
        result = self.tickets.find_one_and_update(
            {"_id": ObjectId(ticket_id), "is_deleted": False},
            {"$set": {
                "status": TicketStatus.CLOSED.value,
                "closed_at": now,
                "updated_at": now
            }},
            return_document=True
        )
        
        if result:
            self._log_activity(
                ticket_id=ticket_id,
                action="closed",
                description="Ticket closed",
                actor_id=closed_by
            )
        
        return self._serialize_ticket(result) if result else None
    
    def reopen_ticket(self, ticket_id: str, reason: str = None, reopened_by: str = None) -> Optional[Dict[str, Any]]:
        """Reopen a closed ticket"""
        result = self.tickets.find_one_and_update(
            {"_id": ObjectId(ticket_id), "is_deleted": False},
            {"$set": {
                "status": TicketStatus.REOPENED.value,
                "closed_at": None,
                "resolved_at": None,
                "resolution": None,
                "updated_at": datetime.utcnow()
            }},
            return_document=True
        )
        
        if result:
            self._log_activity(
                ticket_id=ticket_id,
                action="reopened",
                description=f"Ticket reopened: {reason or 'No reason provided'}",
                actor_id=reopened_by
            )
        
        return self._serialize_ticket(result) if result else None
    
    def delete_ticket(self, ticket_id: str) -> bool:
        """Soft delete a ticket"""
        result = self.tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    # ==================== ESCALATION ====================
    
    def escalate_ticket(
        self,
        ticket_id: str,
        level: EscalationLevel,
        reason: str,
        assign_to: str = None,
        escalated_by: str = None
    ) -> Optional[Dict[str, Any]]:
        """Escalate a ticket"""
        now = datetime.utcnow()
        update_data = {
            "escalation_level": level.value,
            "escalated_at": now,
            "escalated_by": escalated_by,
            "updated_at": now
        }
        
        if assign_to:
            update_data["assigned_to"] = assign_to
            update_data["assigned_at"] = now
        
        result = self.tickets.find_one_and_update(
            {"_id": ObjectId(ticket_id), "is_deleted": False},
            {"$set": update_data},
            return_document=True
        )
        
        if result:
            self._log_activity(
                ticket_id=ticket_id,
                action="escalated",
                description=f"Ticket escalated to {level.value}: {reason}",
                actor_id=escalated_by,
                new_value=level.value,
                metadata={"reason": reason, "assign_to": assign_to}
            )
        
        return self._serialize_ticket(result) if result else None
    
    # ==================== COMMENTS ====================
    
    def add_comment(
        self,
        ticket_id: str,
        content: str,
        author_id: str,
        author_name: str = None,
        author_type: str = "agent",
        is_internal: bool = False,
        attachments: List[Dict] = None
    ) -> Dict[str, Any]:
        """Add a comment to a ticket"""
        # Check if this is the first response
        ticket = self.tickets.find_one({"_id": ObjectId(ticket_id)})
        is_first_response = ticket and not ticket.get("first_response_at") and author_type == "agent"
        
        comment_doc = {
            "ticket_id": ticket_id,
            "content": content,
            "author_id": author_id,
            "author_name": author_name,
            "author_type": author_type,
            "is_internal": is_internal,
            "attachments": attachments or [],
            "created_at": datetime.utcnow()
        }
        
        result = self.comments.insert_one(comment_doc)
        comment_doc["_id"] = result.inserted_id
        
        # Update ticket
        update = {"updated_at": datetime.utcnow()}
        if is_first_response:
            update["first_response_at"] = datetime.utcnow()
            self.sla_manager.update_sla_status(ticket_id, first_response_at=update["first_response_at"])
        
        # Update status if customer is waiting
        if author_type == "agent" and not is_internal and ticket.get("status") == TicketStatus.WAITING_ON_CUSTOMER.value:
            update["status"] = TicketStatus.IN_PROGRESS.value
        elif author_type == "customer":
            update["status"] = TicketStatus.OPEN.value if ticket.get("status") == TicketStatus.WAITING_ON_CUSTOMER.value else ticket.get("status")
        
        self.tickets.update_one({"_id": ObjectId(ticket_id)}, {"$set": update})
        
        # Log activity
        self._log_activity(
            ticket_id=ticket_id,
            action="comment_added",
            description=f"{'Internal note' if is_internal else 'Comment'} added by {author_name or author_id}",
            actor_id=author_id,
            actor_type=author_type
        )
        
        return self._serialize_comment(comment_doc)
    
    def get_comments(self, ticket_id: str, include_internal: bool = True) -> List[Dict[str, Any]]:
        """Get comments for a ticket"""
        query = {"ticket_id": ticket_id}
        if not include_internal:
            query["is_internal"] = False
        
        comments = list(self.comments.find(query).sort("created_at", 1))
        return [self._serialize_comment(c) for c in comments]
    
    # ==================== ACTIVITIES ====================
    
    def get_activities(self, ticket_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get activity log for a ticket"""
        activities = list(
            self.activities.find({"ticket_id": ticket_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        return [self._serialize_activity(a) for a in activities]
    
    def _log_activity(
        self,
        ticket_id: str,
        action: str,
        description: str,
        actor_id: str = None,
        actor_name: str = None,
        actor_type: str = "agent",
        old_value: str = None,
        new_value: str = None,
        metadata: Dict = None
    ):
        """Log an activity for a ticket"""
        activity = {
            "ticket_id": ticket_id,
            "action": action,
            "description": description,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "actor_type": actor_type,
            "old_value": old_value,
            "new_value": new_value,
            "metadata": metadata or {},
            "created_at": datetime.utcnow()
        }
        self.activities.insert_one(activity)
    
    # ==================== STATISTICS ====================
    
    def get_stats(
        self,
        assigned_to: str = None,
        team_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> TicketStats:
        """Get ticket statistics"""
        query = {"is_deleted": False}
        
        if assigned_to:
            query["assigned_to"] = assigned_to
        if team_id:
            query["team_id"] = team_id
        if start_date or end_date:
            query["created_at"] = {}
            if start_date:
                query["created_at"]["$gte"] = start_date
            if end_date:
                query["created_at"]["$lte"] = end_date
        
        tickets = list(self.tickets.find(query))
        
        stats = TicketStats()
        stats.total_tickets = len(tickets)
        
        response_times = []
        resolution_times = []
        satisfaction_ratings = []
        
        for t in tickets:
            status = t.get("status")
            
            # Count by status
            stats.by_status[status] = stats.by_status.get(status, 0) + 1
            
            if status == TicketStatus.OPEN.value:
                stats.open_tickets += 1
            elif status == TicketStatus.IN_PROGRESS.value:
                stats.in_progress_tickets += 1
            elif status == TicketStatus.RESOLVED.value:
                stats.resolved_tickets += 1
            elif status == TicketStatus.CLOSED.value:
                stats.closed_tickets += 1
            
            # Count by priority
            priority = t.get("priority")
            stats.by_priority[priority] = stats.by_priority.get(priority, 0) + 1
            
            # Count by category
            category = t.get("category")
            stats.by_category[category] = stats.by_category.get(category, 0) + 1
            
            # SLA breaches
            sla_status = t.get("sla_status", {})
            if sla_status.get("response_breached") or sla_status.get("resolution_breached"):
                stats.sla_breached_count += 1
            
            # Check overdue
            resolution_due = sla_status.get("resolution_due")
            if resolution_due and status not in [TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]:
                if isinstance(resolution_due, str):
                    resolution_due = datetime.fromisoformat(resolution_due.replace('Z', '+00:00'))
                if resolution_due < datetime.utcnow():
                    stats.overdue_tickets += 1
            
            # Response times
            first_response = t.get("first_response_at")
            created = t.get("created_at")
            if first_response and created:
                delta = (first_response - created).total_seconds() / 3600
                response_times.append(delta)
            
            # Resolution times
            resolved = t.get("resolved_at")
            if resolved and created:
                delta = (resolved - created).total_seconds() / 3600
                resolution_times.append(delta)
            
            # Satisfaction
            rating = t.get("satisfaction_rating")
            if rating:
                satisfaction_ratings.append(rating)
        
        # Calculate averages
        if response_times:
            stats.avg_response_time_hours = round(sum(response_times) / len(response_times), 2)
        if resolution_times:
            stats.avg_resolution_time_hours = round(sum(resolution_times) / len(resolution_times), 2)
        if satisfaction_ratings:
            stats.satisfaction_avg = round(sum(satisfaction_ratings) / len(satisfaction_ratings), 2)
        
        return stats
    
    def get_my_tickets(self, user_id: str, include_closed: bool = False) -> List[Dict[str, Any]]:
        """Get tickets assigned to a user"""
        query = {"assigned_to": user_id, "is_deleted": False}
        if not include_closed:
            query["status"] = {"$nin": [TicketStatus.CLOSED.value]}
        
        tickets = list(self.tickets.find(query).sort([("priority", -1), ("created_at", 1)]))
        return [self._serialize_ticket(t) for t in tickets]
    
    # ==================== TEAMS ====================
    
    def create_team(
        self,
        name: str,
        description: str = None,
        member_ids: List[str] = None,
        manager_ids: List[str] = None,
        default_sla_policy_id: str = None,
        categories: List[str] = None
    ) -> Dict[str, Any]:
        """Create a support team"""
        team_doc = {
            "name": name,
            "description": description,
            "member_ids": member_ids or [],
            "manager_ids": manager_ids or [],
            "default_sla_policy_id": default_sla_policy_id,
            "categories": categories or [],
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        
        result = self.teams.insert_one(team_doc)
        team_doc["_id"] = result.inserted_id
        team_doc["id"] = str(result.inserted_id)
        
        return team_doc
    
    def list_teams(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """List support teams"""
        query = {"is_active": True} if active_only else {}
        teams = list(self.teams.find(query))
        for t in teams:
            t["id"] = str(t.pop("_id"))
        return teams
    
    # ==================== HELPERS ====================
    
    def _serialize_ticket(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a ticket document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
    
    def _serialize_comment(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a comment document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
    
    def _serialize_activity(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize an activity document"""
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
