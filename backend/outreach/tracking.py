"""
EMAIL TRACKING & EVENT HANDLING
================================

Handles email behavior tracking events:
- Sent, Delivered, Bounced
- Opened, Clicked
- Replied, Unsubscribed

Updates lead engagement metrics and triggers automation rules.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from bson import ObjectId
from pymongo.database import Database

from .models import (
    OutreachLead,
    OutreachEmail,
    EmailEvent,
    EmailEventType,
    EngagementStatus
)
from .automation_rules import AutomationRulesEngine


class EmailTrackingService:
    """
    Service for tracking email events and updating engagement metrics.
    """
    
    def __init__(self, db: Database):
        """
        Initialize email tracking service.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.leads = db["outreach_leads"]
        self.emails = db["outreach_emails"]
        self.events = db["outreach_events"]
        
        # Initialize automation engine
        self.automation = AutomationRulesEngine(db)
    
    def track_sent(
        self,
        email_id: str,
        provider_message_id: Optional[str] = None
    ) -> bool:
        """
        Track that an email was sent.
        
        Args:
            email_id: Email ID
            provider_message_id: Message ID from email provider
        
        Returns:
            Success status
        """
        # Get email
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        # Update email status
        now = datetime.utcnow()
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "status": "sent",
                    "sent_at": now,
                    "provider_message_id": provider_message_id,
                    "updated_at": now
                }
            }
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.SENT
        )
        self.events.insert_one(event.model_dump())
        
        # Update lead metrics
        self.leads.update_one(
            {"_id": ObjectId(email["lead_id"])},
            {
                "$inc": {"emails_sent": 1},
                "$set": {
                    "last_contacted_at": now,
                    "updated_at": now
                }
            }
        )
        
        # Update sequence stage to SENT
        from .sequence_engine import SequenceEngine
        engine = SequenceEngine(self.db)
        engine._update_lead_stage(email["lead_id"], email["step_number"], sent=True)
        
        return True
    
    def track_delivered(self, email_id: str) -> bool:
        """Track that an email was delivered."""
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "status": "delivered",
                    "delivered_at": now,
                    "updated_at": now
                }
            }
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.DELIVERED
        )
        self.events.insert_one(event.model_dump())
        
        return True
    
    def track_bounced(
        self,
        email_id: str,
        bounce_reason: Optional[str] = None
    ) -> bool:
        """
        Track that an email bounced.
        
        Args:
            email_id: Email ID
            bounce_reason: Reason for bounce
        
        Returns:
            Success status
        """
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        
        # Update email status
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "status": "bounced",
                    "error_message": bounce_reason,
                    "updated_at": now
                }
            }
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.BOUNCED,
            bounce_reason=bounce_reason
        )
        
        event_doc = event.model_dump()
        self.events.insert_one(event_doc)
        
        # Process automation rules
        self.automation.process_event(event)
        
        return True
    
    def track_opened(
        self,
        email_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """
        Track that an email was opened.
        
        Args:
            email_id: Email ID
            ip_address: IP address of opener
            user_agent: User agent string
        
        Returns:
            Success status
        """
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        
        # Update email
        update_data = {
            "$inc": {"open_count": 1},
            "$set": {"updated_at": now}
        }
        
        # Set opened_at only on first open
        if not email.get("opened_at"):
            update_data["$set"]["opened_at"] = now
            update_data["$set"]["status"] = "opened"
        
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            update_data
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.OPENED,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        event_doc = event.model_dump()
        self.events.insert_one(event_doc)
        
        # Update lead metrics
        lead_update = {
            "$set": {
                "last_opened_at": now,
                "updated_at": now
            }
        }
        
        # Increment unique opens count only on first open of this email
        if not email.get("opened_at"):
            lead_update["$inc"] = {"emails_opened": 1}
            
            # Update engagement status if currently NEVER_OPENED
            lead = self.leads.find_one({"_id": ObjectId(email["lead_id"])})
            if lead and lead.get("engagement_status") == EngagementStatus.NEVER_OPENED.value:
                lead_update["$set"]["engagement_status"] = EngagementStatus.OPENED_NO_REPLY.value
        
        self.leads.update_one(
            {"_id": ObjectId(email["lead_id"])},
            lead_update
        )
        
        # Process automation rules (e.g., warm lead detection)
        self.automation.evaluate_lead(email["lead_id"])
        
        return True
    
    def track_clicked(
        self,
        email_id: str,
        clicked_url: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """
        Track that a link in an email was clicked.
        
        Args:
            email_id: Email ID
            clicked_url: URL that was clicked
            ip_address: IP address of clicker
            user_agent: User agent string
        
        Returns:
            Success status
        """
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        
        # Update email
        update_data = {
            "$inc": {"click_count": 1},
            "$addToSet": {"clicked_links": clicked_url},
            "$set": {"updated_at": now}
        }
        
        # Set clicked_at only on first click
        if not email.get("clicked_at"):
            update_data["$set"]["clicked_at"] = now
            update_data["$set"]["status"] = "clicked"
        
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            update_data
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.CLICKED,
            clicked_url=clicked_url,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        event_doc = event.model_dump()
        self.events.insert_one(event_doc)
        
        # Update lead metrics
        lead_update = {
            "$set": {
                "last_clicked_at": now,
                "engagement_status": EngagementStatus.ENGAGED.value,
                "updated_at": now
            }
        }
        
        # Increment unique clicks count only on first click of this email
        if not email.get("clicked_at"):
            lead_update["$inc"] = {"emails_clicked": 1}
        
        self.leads.update_one(
            {"_id": ObjectId(email["lead_id"])},
            lead_update
        )
        
        return True
    
    def track_replied(
        self,
        email_id: str,
        reply_message_id: Optional[str] = None
    ) -> bool:
        """
        Track that a lead replied to an email.
        
        Args:
            email_id: Email ID
            reply_message_id: Message ID of reply
        
        Returns:
            Success status
        """
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        
        # Update email status
        self.emails.update_one(
            {"_id": ObjectId(email_id)},
            {
                "$set": {
                    "status": "replied",
                    "replied_at": now,
                    "updated_at": now
                }
            }
        )
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.REPLIED,
            reply_message_id=reply_message_id
        )
        
        event_doc = event.model_dump()
        self.events.insert_one(event_doc)
        
        # Update lead metrics
        self.leads.update_one(
            {"_id": ObjectId(email["lead_id"])},
            {
                "$inc": {"emails_replied": 1},
                "$set": {
                    "last_replied_at": now,
                    "updated_at": now
                }
            }
        )
        
        # Process automation rules (will stop sequence)
        self.automation.process_event(event)
        
        return True
    
    def track_unsubscribed(self, email_id: str) -> bool:
        """Track that a lead unsubscribed."""
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return False
        
        now = datetime.utcnow()
        
        # Create event
        event = EmailEvent(
            email_id=email_id,
            lead_id=email["lead_id"],
            sequence_id=email["sequence_id"],
            event_type=EmailEventType.UNSUBSCRIBED
        )
        
        event_doc = event.model_dump()
        self.events.insert_one(event_doc)
        
        # Update lead
        self.leads.update_one(
            {"_id": ObjectId(email["lead_id"])},
            {
                "$set": {
                    "engagement_status": EngagementStatus.UNSUBSCRIBED.value,
                    "updated_at": now
                }
            }
        )
        
        # Stop sequence
        from .sequence_engine import SequenceEngine
        engine = SequenceEngine(self.db)
        engine.stop_sequence(email["lead_id"], reason="unsubscribed")
        
        return True
    
    def get_lead_events(
        self,
        lead_id: str,
        event_type: Optional[EmailEventType] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Get events for a lead.
        
        Args:
            lead_id: Lead ID
            event_type: Filter by event type (optional)
            limit: Maximum number of events
        
        Returns:
            List of event documents
        """
        query = {"lead_id": lead_id}
        
        if event_type:
            query["event_type"] = event_type.value
        
        events = self.events.find(query).sort("timestamp", -1).limit(limit)
        return list(events)
    
    def get_email_activity(self, email_id: str) -> Dict[str, Any]:
        """
        Get complete activity summary for an email.
        
        Args:
            email_id: Email ID
        
        Returns:
            Activity summary
        """
        email = self.emails.find_one({"_id": ObjectId(email_id)})
        if not email:
            return {}
        
        # Get all events for this email
        events = list(self.events.find({"email_id": email_id}).sort("timestamp", 1))
        
        return {
            "email_id": email_id,
            "to_email": email.get("to_email"),
            "subject": email.get("subject"),
            "status": email.get("status"),
            "sent_at": email.get("sent_at"),
            "delivered_at": email.get("delivered_at"),
            "opened_at": email.get("opened_at"),
            "open_count": email.get("open_count", 0),
            "clicked_at": email.get("clicked_at"),
            "click_count": email.get("click_count", 0),
            "clicked_links": email.get("clicked_links", []),
            "replied_at": email.get("replied_at"),
            "events": [
                {
                    "type": e.get("event_type"),
                    "timestamp": e.get("timestamp"),
                    "details": {
                        "ip_address": e.get("ip_address"),
                        "clicked_url": e.get("clicked_url"),
                        "bounce_reason": e.get("bounce_reason")
                    }
                }
                for e in events
            ]
        }
