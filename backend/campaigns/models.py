"""
CAMPAIGN & OUTREACH MODULE
===========================

Email campaign management system for cold outreach, follow-ups, and automated sequences.

Features:
- Campaign creation with multi-step sequences
- Email template management with personalization
- Scheduled sending with rate limiting
- Reply detection and sequence control
- A/B testing support
- Analytics and tracking

Collections:
- campaigns: Campaign definitions and settings
- campaign_sequences: Step-by-step email sequences
- campaign_recipients: Recipient list with status tracking
- campaign_sends: Send history and tracking
- email_templates: Reusable email templates

Usage:
    from campaigns import CampaignManager
    
    manager = CampaignManager(db)
    campaign_id = manager.create_campaign(
        name="Q1 Outreach",
        from_mailbox_id="...",
        sequence_steps=[
            {"day": 0, "template_id": "initial_outreach"},
            {"day": 3, "template_id": "follow_up_1", "condition": "no_reply"},
            {"day": 7, "template_id": "follow_up_2", "condition": "no_reply"}
        ]
    )
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from pydantic import BaseModel, Field
from bson import ObjectId


# ============== ENUMS ==============

class CampaignStatus(str, Enum):
    """Campaign lifecycle status"""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class RecipientStatus(str, Enum):
    """Individual recipient status within a campaign"""
    PENDING = "pending"
    IN_SEQUENCE = "in_sequence"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    COMPLETED = "completed"
    EXCLUDED = "excluded"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"


class SendStatus(str, Enum):
    """Individual send status"""
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"


class SequenceCondition(str, Enum):
    """Conditions for sequence step execution"""
    ALWAYS = "always"
    NO_REPLY = "no_reply"
    NO_OPEN = "no_open"
    NO_CLICK = "no_click"
    OPENED = "opened"
    CLICKED = "clicked"


class ReplyType(str, Enum):
    """Types of replies for sequence control"""
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    MEETING_BOOKED = "meeting_booked"
    REFERRED = "referred"
    UNSUBSCRIBE = "unsubscribe"
    BOUNCE = "bounce"
    AUTO_REPLY = "auto_reply"
    OTHER = "other"


# ============== PYDANTIC MODELS ==============

class EmailTemplate(BaseModel):
    """Email template with personalization support"""
    id: Optional[str] = Field(default_factory=lambda: str(ObjectId()))
    name: str
    subject: str  # Supports {{variables}}
    body_html: str  # Supports {{variables}}
    body_plain: Optional[str] = None
    category: str = "outreach"  # outreach, follow_up, nurture, transactional
    tags: List[str] = []
    variables: List[str] = []  # List of expected variables like ["first_name", "company"]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True
    
    # A/B testing
    variant: Optional[str] = None  # "A", "B", etc.
    parent_template_id: Optional[str] = None


class SequenceStep(BaseModel):
    """Single step in a campaign sequence"""
    step_number: int
    template_id: str
    template_variant: Optional[str] = None  # For A/B testing
    delay_days: int = 0  # Days after previous step (or campaign start for step 0)
    delay_hours: int = 0
    send_time: Optional[str] = None  # Preferred send time "09:00" in recipient timezone
    condition: SequenceCondition = SequenceCondition.ALWAYS
    
    # Stop conditions
    stop_on_reply: bool = True
    stop_on_bounce: bool = True
    stop_on_unsubscribe: bool = True


class CampaignSettings(BaseModel):
    """Campaign configuration settings"""
    # Sending limits
    daily_send_limit: int = 100
    hourly_send_limit: int = 20
    min_delay_between_sends_seconds: int = 60
    
    # Timing
    send_days: List[int] = [0, 1, 2, 3, 4]  # 0=Monday, 6=Sunday
    send_hours_start: int = 9  # 9 AM
    send_hours_end: int = 17  # 5 PM
    timezone: str = "UTC"
    
    # Reply handling
    stop_on_any_reply: bool = True
    auto_detect_reply_type: bool = True
    
    # Compliance
    include_unsubscribe_link: bool = True
    unsubscribe_text: str = "Click here to unsubscribe"
    
    # Tracking
    track_opens: bool = True
    track_clicks: bool = True


class Campaign(BaseModel):
    """Campaign definition"""
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    
    # Ownership
    from_mailbox_id: str
    from_email: str
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    
    # Status
    status: CampaignStatus = CampaignStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    scheduled_start: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Sequence
    sequence_steps: List[SequenceStep] = []
    
    # Settings
    settings: CampaignSettings = Field(default_factory=CampaignSettings)
    
    # Tags and organization
    tags: List[str] = []
    folder: Optional[str] = None
    
    # Statistics (denormalized for quick access)
    stats: Dict[str, int] = Field(default_factory=lambda: {
        "total_recipients": 0,
        "pending": 0,
        "in_sequence": 0,
        "completed": 0,
        "replied": 0,
        "interested": 0,
        "bounced": 0,
        "unsubscribed": 0
    })


class CampaignRecipient(BaseModel):
    """Individual recipient in a campaign"""
    id: Optional[str] = None
    campaign_id: str
    
    # Contact info
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    
    # Custom variables for personalization
    custom_variables: Dict[str, Any] = {}
    
    # Source tracking
    lead_id: Optional[str] = None
    source: str = "manual"  # manual, csv_import, lead_list, api
    
    # Status
    status: RecipientStatus = RecipientStatus.PENDING
    current_step: int = 0
    
    # Timing
    added_at: datetime = Field(default_factory=datetime.utcnow)
    sequence_started_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None
    next_send_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Engagement
    reply_detected_at: Optional[datetime] = None
    reply_type: Optional[ReplyType] = None
    reply_email_id: Optional[str] = None
    
    # A/B test assignment
    ab_variant: Optional[str] = None
    
    # Timezone for sending
    timezone: str = "UTC"


class CampaignSend(BaseModel):
    """Record of an individual email send"""
    id: Optional[str] = None
    campaign_id: str
    recipient_id: str
    step_number: int
    template_id: str
    
    # Email details
    to_email: str
    subject: str  # Rendered subject
    
    # Status
    status: SendStatus = SendStatus.QUEUED
    
    # Timing
    scheduled_at: datetime
    queued_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    # Tracking
    opened_at: Optional[datetime] = None
    open_count: int = 0
    clicked_at: Optional[datetime] = None
    click_count: int = 0
    clicked_links: List[str] = []
    
    # Reply tracking
    replied_at: Optional[datetime] = None
    reply_email_id: Optional[str] = None
    
    # Errors
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Provider info
    provider_message_id: Optional[str] = None


# ============== CAMPAIGN MANAGER ==============

class CampaignManager:
    """
    Main interface for campaign operations.
    """
    
    def __init__(self, db):
        """
        Initialize campaign manager.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.campaigns = db["campaigns"]
        self.recipients = db["campaign_recipients"]
        self.sends = db["campaign_sends"]
        self.templates = db["email_templates"]
        self.send_queue = db["campaign_send_queue"]
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            # Campaigns
            self.campaigns.create_index([("status", 1), ("scheduled_start", 1)])
            self.campaigns.create_index([("from_mailbox_id", 1)])
            
            # Recipients
            self.recipients.create_index([("campaign_id", 1), ("status", 1)])
            self.recipients.create_index([("campaign_id", 1), ("email", 1)], unique=True)
            self.recipients.create_index([("next_send_at", 1), ("status", 1)])
            self.recipients.create_index([("email", 1)])  # For duplicate checking
            
            # Sends
            self.sends.create_index([("campaign_id", 1), ("recipient_id", 1)])
            self.sends.create_index([("status", 1), ("scheduled_at", 1)])
            self.sends.create_index([("to_email", 1)])
            
            # Templates
            self.templates.create_index([("category", 1), ("is_active", 1)])
            self.templates.create_index([("name", 1)])
            
            # Send queue
            self.send_queue.create_index([("scheduled_at", 1), ("status", 1)])
            self.send_queue.create_index([("campaign_id", 1)])
            
        except Exception as e:
            import logging
            logging.warning(f"Index creation failed: {e}")
    
    # ============== TEMPLATE OPERATIONS ==============
    
    def create_template(
        self,
        name: str,
        subject: str,
        body_html: str,
        body_plain: Optional[str] = None,
        category: str = "outreach",
        tags: List[str] = []
    ) -> str:
        """Create a new email template"""
        # Extract variables from subject and body
        import re
        variables = list(set(re.findall(r'\{\{(\w+)\}\}', subject + body_html)))
        
        template = EmailTemplate(
            name=name,
            subject=subject,
            body_html=body_html,
            body_plain=body_plain or self._html_to_plain(body_html),
            category=category,
            tags=tags,
            variables=variables
        )
        
        result = self.templates.insert_one(template.model_dump())
        return str(result.inserted_id)
    
    def get_template(self, template_id: str) -> Optional[Dict]:
        """Get a template by ID"""
        return self.templates.find_one({"_id": ObjectId(template_id)})
    
    def render_template(
        self,
        template_id: str,
        variables: Dict[str, Any]
    ) -> Dict[str, str]:
        """Render a template with variables"""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        subject = template["subject"]
        body_html = template["body_html"]
        body_plain = template.get("body_plain", "")
        
        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            subject = subject.replace(placeholder, str(value))
            body_html = body_html.replace(placeholder, str(value))
            body_plain = body_plain.replace(placeholder, str(value))
        
        return {
            "subject": subject,
            "body_html": body_html,
            "body_plain": body_plain
        }
    
    def _html_to_plain(self, html: str) -> str:
        """Convert HTML to plain text"""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Decode common entities
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    # ============== CAMPAIGN OPERATIONS ==============
    
    def create_campaign(
        self,
        name: str,
        from_mailbox_id: str,
        from_email: str,
        sequence_steps: List[Dict],
        from_name: Optional[str] = None,
        description: Optional[str] = None,
        settings: Optional[Dict] = None
    ) -> str:
        """Create a new campaign"""
        # Convert sequence steps to model
        steps = []
        for i, step_data in enumerate(sequence_steps):
            step = SequenceStep(
                step_number=i,
                template_id=step_data["template_id"],
                delay_days=step_data.get("delay_days", step_data.get("day", 0)),
                delay_hours=step_data.get("delay_hours", 0),
                condition=SequenceCondition(step_data.get("condition", "always"))
            )
            steps.append(step)
        
        campaign = Campaign(
            name=name,
            from_mailbox_id=from_mailbox_id,
            from_email=from_email,
            from_name=from_name,
            description=description,
            sequence_steps=steps,
            settings=CampaignSettings(**(settings or {}))
        )
        
        doc = campaign.model_dump()
        result = self.campaigns.insert_one(doc)
        return str(result.inserted_id)
    
    def get_campaign(self, campaign_id: str) -> Optional[Dict]:
        """Get a campaign by ID"""
        return self.campaigns.find_one({"_id": ObjectId(campaign_id)})
    
    def update_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus
    ) -> bool:
        """Update campaign status"""
        update_fields = {
            "status": status.value,
            "updated_at": datetime.utcnow()
        }
        
        if status == CampaignStatus.ACTIVE:
            update_fields["started_at"] = datetime.utcnow()
        elif status == CampaignStatus.COMPLETED:
            update_fields["completed_at"] = datetime.utcnow()
        
        result = self.campaigns.update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": update_fields}
        )
        return result.modified_count > 0
    
    # ============== RECIPIENT OPERATIONS ==============
    
    def add_recipients(
        self,
        campaign_id: str,
        recipients: List[Dict],
        deduplicate: bool = True
    ) -> Dict[str, int]:
        """Add recipients to a campaign"""
        added = 0
        skipped = 0
        
        for recipient_data in recipients:
            email = recipient_data.get("email", "").lower().strip()
            if not email:
                skipped += 1
                continue
            
            # Check for duplicates
            if deduplicate:
                existing = self.recipients.find_one({
                    "campaign_id": campaign_id,
                    "email": email
                })
                if existing:
                    skipped += 1
                    continue
            
            recipient = CampaignRecipient(
                campaign_id=campaign_id,
                email=email,
                first_name=recipient_data.get("first_name"),
                last_name=recipient_data.get("last_name"),
                company=recipient_data.get("company"),
                title=recipient_data.get("title"),
                custom_variables=recipient_data.get("custom_variables", {}),
                lead_id=recipient_data.get("lead_id"),
                source=recipient_data.get("source", "manual"),
                timezone=recipient_data.get("timezone", "UTC")
            )
            
            try:
                self.recipients.insert_one(recipient.model_dump())
                added += 1
            except Exception:
                skipped += 1
        
        # Update campaign stats
        self._update_campaign_stats(campaign_id)
        
        return {"added": added, "skipped": skipped}
    
    def get_recipient(self, recipient_id: str) -> Optional[Dict]:
        """Get a recipient by ID"""
        return self.recipients.find_one({"_id": ObjectId(recipient_id)})
    
    def update_recipient_status(
        self,
        recipient_id: str,
        status: RecipientStatus,
        reply_type: Optional[ReplyType] = None,
        reply_email_id: Optional[str] = None
    ) -> bool:
        """Update recipient status"""
        update_fields = {
            "status": status.value,
        }
        
        if status == RecipientStatus.REPLIED:
            update_fields["reply_detected_at"] = datetime.utcnow()
            if reply_type:
                update_fields["reply_type"] = reply_type.value
            if reply_email_id:
                update_fields["reply_email_id"] = reply_email_id
        elif status == RecipientStatus.COMPLETED:
            update_fields["completed_at"] = datetime.utcnow()
        
        result = self.recipients.update_one(
            {"_id": ObjectId(recipient_id)},
            {"$set": update_fields}
        )
        
        if result.modified_count > 0:
            recipient = self.get_recipient(recipient_id)
            if recipient:
                self._update_campaign_stats(recipient["campaign_id"])
        
        return result.modified_count > 0
    
    def _update_campaign_stats(self, campaign_id: str):
        """Recalculate campaign statistics"""
        pipeline = [
            {"$match": {"campaign_id": campaign_id}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.recipients.aggregate(pipeline))
        stats = {
            "total_recipients": 0,
            "pending": 0,
            "in_sequence": 0,
            "completed": 0,
            "replied": 0,
            "interested": 0,
            "bounced": 0,
            "unsubscribed": 0
        }
        
        for r in results:
            status = r["_id"]
            count = r["count"]
            stats["total_recipients"] += count
            
            if status in stats:
                stats[status] = count
        
        self.campaigns.update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": {"stats": stats, "updated_at": datetime.utcnow()}}
        )
    
    # ============== SEND QUEUE OPERATIONS ==============
    
    def schedule_next_sends(self, campaign_id: str) -> int:
        """Schedule next sends for recipients in sequence"""
        campaign = self.get_campaign(campaign_id)
        if not campaign or campaign["status"] != CampaignStatus.ACTIVE.value:
            return 0
        
        settings = campaign.get("settings", {})
        sequence_steps = campaign.get("sequence_steps", [])
        
        # Find recipients needing next send
        now = datetime.utcnow()
        recipients = self.recipients.find({
            "campaign_id": campaign_id,
            "status": {"$in": [RecipientStatus.PENDING.value, RecipientStatus.IN_SEQUENCE.value]},
            "$or": [
                {"next_send_at": {"$lte": now}},
                {"next_send_at": {"$exists": False}}
            ]
        }).limit(settings.get("hourly_send_limit", 20))
        
        scheduled = 0
        for recipient in recipients:
            current_step = recipient.get("current_step", 0)
            
            if current_step >= len(sequence_steps):
                # Sequence complete
                self.update_recipient_status(
                    str(recipient["_id"]),
                    RecipientStatus.COMPLETED
                )
                continue
            
            step = sequence_steps[current_step]
            
            # Check step condition
            if not self._check_step_condition(recipient, step):
                continue
            
            # Create send record
            send = CampaignSend(
                campaign_id=campaign_id,
                recipient_id=str(recipient["_id"]),
                step_number=current_step,
                template_id=step["template_id"],
                to_email=recipient["email"],
                subject="",  # Will be rendered at send time
                scheduled_at=now
            )
            
            self.sends.insert_one(send.model_dump())
            
            # Update recipient
            next_step = current_step + 1
            next_send_at = None
            
            if next_step < len(sequence_steps):
                next_step_config = sequence_steps[next_step]
                next_send_at = now + timedelta(
                    days=next_step_config.get("delay_days", 0),
                    hours=next_step_config.get("delay_hours", 0)
                )
            
            self.recipients.update_one(
                {"_id": recipient["_id"]},
                {
                    "$set": {
                        "status": RecipientStatus.IN_SEQUENCE.value,
                        "current_step": next_step,
                        "last_sent_at": now,
                        "next_send_at": next_send_at,
                        "sequence_started_at": recipient.get("sequence_started_at") or now
                    }
                }
            )
            
            scheduled += 1
        
        return scheduled
    
    def _check_step_condition(self, recipient: Dict, step: Dict) -> bool:
        """Check if step condition is met"""
        condition = step.get("condition", "always")
        
        if condition == "always":
            return True
        elif condition == "no_reply":
            return recipient.get("status") != RecipientStatus.REPLIED.value
        elif condition == "no_open":
            # Check if previous email was opened
            last_send = self.sends.find_one(
                {"recipient_id": str(recipient["_id"])},
                sort=[("step_number", -1)]
            )
            return not last_send or not last_send.get("opened_at")
        
        return True
    
    # ============== ANALYTICS ==============
    
    def get_campaign_analytics(self, campaign_id: str) -> Dict[str, Any]:
        """Get detailed analytics for a campaign"""
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            return {}
        
        # Send statistics
        send_pipeline = [
            {"$match": {"campaign_id": campaign_id}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        send_stats = {r["_id"]: r["count"] for r in self.sends.aggregate(send_pipeline)}
        
        # Calculate rates
        total_sent = send_stats.get(SendStatus.SENT.value, 0) + send_stats.get(SendStatus.DELIVERED.value, 0)
        total_opened = send_stats.get(SendStatus.OPENED.value, 0)
        total_clicked = send_stats.get(SendStatus.CLICKED.value, 0)
        total_replied = send_stats.get(SendStatus.REPLIED.value, 0)
        
        return {
            "campaign_id": campaign_id,
            "name": campaign.get("name"),
            "status": campaign.get("status"),
            "recipient_stats": campaign.get("stats", {}),
            "send_stats": send_stats,
            "rates": {
                "open_rate": round(total_opened / total_sent * 100, 2) if total_sent > 0 else 0,
                "click_rate": round(total_clicked / total_sent * 100, 2) if total_sent > 0 else 0,
                "reply_rate": round(total_replied / total_sent * 100, 2) if total_sent > 0 else 0
            }
        }
