"""
WORKFLOW ENGINE
===============

State machine for email sequence progression.

State Machine:
    NOT_STARTED -> IN_PROGRESS (on first send)
    IN_PROGRESS -> Step N (wait delay) -> Step N+1
    IN_PROGRESS -> STOPPED_REPLY (if reply detected)
    IN_PROGRESS -> STOPPED_BOUNCE (if bounce detected)
    IN_PROGRESS -> STOPPED_UNSUBSCRIBE (if unsubscribe detected)
    IN_PROGRESS -> STOPPED_MANUAL (if manually paused)
    IN_PROGRESS -> COMPLETED (after all steps)

Rules:
- No parallel conflicting workflows per lead
- Reply -> STOP workflow immediately
- Bounce -> STOP workflow immediately
- Manual pause -> STOP workflow
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pymongo.database import Database
from bson import ObjectId

from .models import (
    Lead,
    Campaign,
    WorkflowStep,
    WorkflowStatus,
    PersonalizationLevel,
    SendStatus,
    EmailSend,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Core workflow engine implementing state machine for email sequences.
    
    Responsibilities:
    - Start workflow for leads
    - Progress leads through workflow steps
    - Handle stop conditions (reply, bounce, unsubscribe)
    - Calculate next send times
    - Prevent parallel workflows per lead
    """
    
    def __init__(self, db: Database):
        """
        Initialize workflow engine.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.leads_collection = db["outreach_leads_v2"]
        self.campaigns_collection = db["outreach_campaigns_v2"]
        self.sends_collection = db["outreach_sends_v2"]
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            # Leads indexes
            self.leads_collection.create_index([("lead_id", 1)], unique=True)
            self.leads_collection.create_index([("email", 1)], unique=True)
            self.leads_collection.create_index([
                ("workflow_id", 1),
                ("workflow_status", 1),
                ("next_send_at", 1)
            ])
            self.leads_collection.create_index([("assigned_mailbox_id", 1)])
            
            # Sends indexes
            self.sends_collection.create_index([("message_id", 1)], unique=True)
            self.sends_collection.create_index([("campaign_id", 1), ("lead_id", 1)])
            self.sends_collection.create_index([("status", 1), ("scheduled_at", 1)])
            
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    # ============== WORKFLOW LIFECYCLE ==============
    
    def start_workflow(
        self,
        lead_id: str,
        campaign_id: str,
        personalization_level: PersonalizationLevel = PersonalizationLevel.LIGHT
    ) -> Tuple[bool, str]:
        """
        Start workflow for a lead.
        
        Args:
            lead_id: Lead ID to start workflow for
            campaign_id: Campaign ID to use
            personalization_level: Level of personalization
            
        Returns:
            Tuple of (success, message)
        """
        # Get lead
        lead_doc = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead_doc:
            return False, f"Lead {lead_id} not found"
        
        # Check for existing active workflow
        current_status = lead_doc.get("workflow_status")
        if current_status == WorkflowStatus.IN_PROGRESS.value:
            return False, f"Lead {lead_id} already has active workflow"
        
        # Get campaign
        campaign_doc = self.campaigns_collection.find_one({"campaign_id": campaign_id})
        if not campaign_doc:
            return False, f"Campaign {campaign_id} not found"
        
        if not campaign_doc.get("is_active", False):
            return False, f"Campaign {campaign_id} is not active"
        
        # Initialize workflow
        now = datetime.utcnow()
        first_send_at = self._calculate_next_send_time(
            campaign_doc,
            step_number=0,
            from_time=now
        )
        
        update_data = {
            "workflow_id": campaign_id,
            "campaign_id": campaign_id,
            "current_step": 0,
            "workflow_status": WorkflowStatus.IN_PROGRESS.value,
            "personalization_level": personalization_level.value,
            "workflow_started_at": now,
            "next_send_at": first_send_at,
            "updated_at": now,
            # Reset engagement fields
            "reply_status": None,
            "reply_detected_at": None,
            "bounce_status": None,
            "bounce_detected_at": None,
            "unsubscribe_detected_at": None,
        }
        
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": update_data}
        )
        
        logger.info(f"Started workflow for lead {lead_id} in campaign {campaign_id}")
        return True, f"Workflow started, first send scheduled at {first_send_at}"
    
    def advance_workflow(self, lead_id: str) -> Tuple[bool, str, Optional[int]]:
        """
        Advance lead to next workflow step.
        
        Args:
            lead_id: Lead ID to advance
            
        Returns:
            Tuple of (success, message, next_step_number)
        """
        # Get lead
        lead_doc = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead_doc:
            return False, f"Lead {lead_id} not found", None
        
        # Check status
        current_status = lead_doc.get("workflow_status")
        if current_status != WorkflowStatus.IN_PROGRESS.value:
            return False, f"Workflow not in progress (status: {current_status})", None
        
        # Get campaign
        campaign_id = lead_doc.get("campaign_id")
        campaign_doc = self.campaigns_collection.find_one({"campaign_id": campaign_id})
        if not campaign_doc:
            return False, f"Campaign {campaign_id} not found", None
        
        # Get current and next step
        current_step = lead_doc.get("current_step", 0)
        workflow_steps = campaign_doc.get("workflow_steps", [])
        
        next_step = current_step + 1
        
        # Check if workflow is complete
        if next_step >= len(workflow_steps):
            # Mark workflow as completed
            now = datetime.utcnow()
            self.leads_collection.update_one(
                {"lead_id": lead_id},
                {"$set": {
                    "workflow_status": WorkflowStatus.COMPLETED.value,
                    "workflow_completed_at": now,
                    "next_send_at": None,
                    "updated_at": now,
                }}
            )
            logger.info(f"Workflow completed for lead {lead_id}")
            return True, "Workflow completed", None
        
        # Calculate next send time
        now = datetime.utcnow()
        next_send_at = self._calculate_next_send_time(
            campaign_doc,
            step_number=next_step,
            from_time=now
        )
        
        # Update lead to next step
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "current_step": next_step,
                "next_send_at": next_send_at,
                "updated_at": now,
            }}
        )
        
        logger.info(f"Advanced lead {lead_id} to step {next_step}, next send at {next_send_at}")
        return True, f"Advanced to step {next_step}", next_step
    
    def stop_workflow(
        self,
        lead_id: str,
        reason: WorkflowStatus,
        details: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Stop workflow for a lead.
        
        Args:
            lead_id: Lead ID to stop
            reason: Reason for stopping (STOPPED_REPLY, STOPPED_BOUNCE, etc.)
            details: Optional additional details
            
        Returns:
            Tuple of (success, message)
        """
        valid_stop_reasons = {
            WorkflowStatus.STOPPED_REPLY,
            WorkflowStatus.STOPPED_BOUNCE,
            WorkflowStatus.STOPPED_UNSUBSCRIBE,
            WorkflowStatus.STOPPED_MANUAL,
        }
        
        if reason not in valid_stop_reasons:
            return False, f"Invalid stop reason: {reason}"
        
        now = datetime.utcnow()
        update_data = {
            "workflow_status": reason.value,
            "workflow_completed_at": now,
            "next_send_at": None,
            "updated_at": now,
        }
        
        # Add specific tracking fields based on reason
        if reason == WorkflowStatus.STOPPED_REPLY:
            update_data["reply_detected_at"] = now
        elif reason == WorkflowStatus.STOPPED_BOUNCE:
            update_data["bounce_detected_at"] = now
        elif reason == WorkflowStatus.STOPPED_UNSUBSCRIBE:
            update_data["unsubscribe_detected_at"] = now
        
        result = self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            return False, f"Lead {lead_id} not found or not modified"
        
        logger.info(f"Stopped workflow for lead {lead_id}: {reason.value} ({details})")
        return True, f"Workflow stopped: {reason.value}"
    
    # ============== QUERY METHODS ==============
    
    def get_leads_ready_to_send(
        self,
        campaign_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get leads that are ready for their next email.
        
        Args:
            campaign_id: Optional campaign filter
            limit: Maximum leads to return
            
        Returns:
            List of lead documents ready to send
        """
        now = datetime.utcnow()
        
        query = {
            "workflow_status": WorkflowStatus.IN_PROGRESS.value,
            "next_send_at": {"$lte": now},
        }
        
        if campaign_id:
            query["campaign_id"] = campaign_id
        
        leads = list(
            self.leads_collection.find(query)
            .sort("next_send_at", 1)
            .limit(limit)
        )
        
        return leads
    
    def get_workflow_state(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current workflow state for a lead.
        
        Args:
            lead_id: Lead ID to get state for
            
        Returns:
            Workflow state dictionary or None
        """
        lead_doc = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead_doc:
            return None
        
        return {
            "lead_id": lead_id,
            "workflow_id": lead_doc.get("workflow_id"),
            "campaign_id": lead_doc.get("campaign_id"),
            "current_step": lead_doc.get("current_step", 0),
            "workflow_status": lead_doc.get("workflow_status"),
            "personalization_level": lead_doc.get("personalization_level"),
            "assigned_mailbox_id": lead_doc.get("assigned_mailbox_id"),
            "thread_id": lead_doc.get("thread_id"),
            "message_id_last_sent": lead_doc.get("message_id_last_sent"),
            "ai_context_block": lead_doc.get("ai_context_block"),
            "next_send_at": lead_doc.get("next_send_at"),
            "last_sent_at": lead_doc.get("last_sent_at"),
            "emails_sent": lead_doc.get("emails_sent", 0),
            "reply_status": lead_doc.get("reply_status"),
            "bounce_status": lead_doc.get("bounce_status"),
        }
    
    def get_campaign_workflow_stats(self, campaign_id: str) -> Dict[str, int]:
        """
        Get workflow statistics for a campaign.
        
        Returns:
            Dictionary with counts by status
        """
        pipeline = [
            {"$match": {"campaign_id": campaign_id}},
            {"$group": {
                "_id": "$workflow_status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.leads_collection.aggregate(pipeline))
        
        stats = {
            "total": 0,
            "not_started": 0,
            "in_progress": 0,
            "completed": 0,
            "stopped_reply": 0,
            "stopped_bounce": 0,
            "stopped_unsubscribe": 0,
            "stopped_manual": 0,
        }
        
        for result in results:
            status = result["_id"]
            count = result["count"]
            stats["total"] += count
            if status:
                stats[status] = count
        
        return stats
    
    # ============== INTERNAL HELPERS ==============
    
    def _calculate_next_send_time(
        self,
        campaign_doc: Dict[str, Any],
        step_number: int,
        from_time: datetime
    ) -> datetime:
        """
        Calculate next send time based on campaign settings and step delay.
        """
        settings = campaign_doc.get("settings", {})
        workflow_steps = campaign_doc.get("workflow_steps", [])
        
        # Get step delay
        delay_days = 0
        delay_hours = 0
        
        if step_number < len(workflow_steps):
            step = workflow_steps[step_number]
            delay_days = step.get("delay_days", 0)
            delay_hours = step.get("delay_hours", 0)
        
        # Calculate base time with delay
        next_time = from_time + timedelta(days=delay_days, hours=delay_hours)
        
        # Adjust to sending window
        send_hours_start = settings.get("send_hours_start", 9)
        send_hours_end = settings.get("send_hours_end", 17)
        send_days = settings.get("send_days", [0, 1, 2, 3, 4])  # Mon-Fri
        
        # Adjust hour if outside window
        if next_time.hour < send_hours_start:
            next_time = next_time.replace(
                hour=send_hours_start,
                minute=0,
                second=0,
                microsecond=0
            )
        elif next_time.hour >= send_hours_end:
            # Move to next day
            next_time = next_time + timedelta(days=1)
            next_time = next_time.replace(
                hour=send_hours_start,
                minute=0,
                second=0,
                microsecond=0
            )
        
        # Adjust for valid send days (skip weekends if not in send_days)
        while next_time.weekday() not in send_days:
            next_time = next_time + timedelta(days=1)
            next_time = next_time.replace(
                hour=send_hours_start,
                minute=0,
                second=0,
                microsecond=0
            )
        
        return next_time
    
    # ============== EVENT HANDLERS ==============
    
    def handle_reply_detected(
        self,
        lead_id: str,
        reply_type: str = "neutral",
        reply_email_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Handle reply detection - stops workflow.
        
        Args:
            lead_id: Lead that replied
            reply_type: Type of reply (positive, negative, neutral)
            reply_email_id: ID of the reply email
            
        Returns:
            Tuple of (success, message)
        """
        now = datetime.utcnow()
        
        # Update lead with reply info
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "reply_status": reply_type,
                "reply_detected_at": now,
                "reply_email_id": reply_email_id,
                "updated_at": now,
            }}
        )
        
        # Stop workflow
        return self.stop_workflow(
            lead_id,
            WorkflowStatus.STOPPED_REPLY,
            f"Reply detected: {reply_type}"
        )
    
    def handle_bounce_detected(
        self,
        lead_id: str,
        bounce_type: str = "unknown",
        bounce_reason: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Handle bounce detection - stops workflow.
        
        Args:
            lead_id: Lead that bounced
            bounce_type: Type of bounce (hard, soft, unknown)
            bounce_reason: Reason for bounce
            
        Returns:
            Tuple of (success, message)
        """
        now = datetime.utcnow()
        
        # Update lead with bounce info
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "bounce_status": bounce_type,
                "bounce_detected_at": now,
                "updated_at": now,
            }}
        )
        
        # Stop workflow
        return self.stop_workflow(
            lead_id,
            WorkflowStatus.STOPPED_BOUNCE,
            f"Bounce detected: {bounce_type} - {bounce_reason}"
        )
    
    def handle_unsubscribe_detected(self, lead_id: str) -> Tuple[bool, str]:
        """
        Handle unsubscribe detection - stops workflow.
        
        Args:
            lead_id: Lead that unsubscribed
            
        Returns:
            Tuple of (success, message)
        """
        now = datetime.utcnow()
        
        # Update lead
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "unsubscribe_detected_at": now,
                "updated_at": now,
            }}
        )
        
        # Stop workflow
        return self.stop_workflow(
            lead_id,
            WorkflowStatus.STOPPED_UNSUBSCRIBE,
            "User unsubscribed"
        )
