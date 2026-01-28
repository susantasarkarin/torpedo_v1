"""
SEQUENCE ENGINE
==============

Manages cold outreach email sequences with intelligent timing,
behavior-based follow-ups, and automatic sequence progression.

Features:
- 4-step default sequence (Day 1, 4, 7, 12)
- Behavior-based logic (opened/not opened/clicked)
- Automatic scheduling and progression
- Sequence stopping conditions
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from bson import ObjectId
from pymongo.database import Database

from .models import (
    OutreachLead,
    OutreachSequence,
    OutreachEmail,
    EmailEvent,
    SequenceStep,
    SequenceStage,
    EngagementStatus,
    EmailEventType,
    PersonalizationLevel
)
from .personalization import PersonalizationEngine


class SequenceEngine:
    """
    Engine for managing email sequences and automatic progression.
    """
    
    def __init__(self, db: Database):
        """
        Initialize sequence engine.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.leads = db["outreach_leads"]
        self.sequences = db["outreach_sequences"]
        self.emails = db["outreach_emails"]
        self.events = db["outreach_events"]
        self.templates = db["outreach_templates"]
        self.personalization = PersonalizationEngine()
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary database indexes."""
        try:
            # Leads indexes
            self.leads.create_index([("email", 1)], unique=True)
            self.leads.create_index([("assigned_sequence_id", 1), ("sequence_stage", 1)])
            self.leads.create_index([("engagement_status", 1)])
            self.leads.create_index([("last_contacted_at", 1)])
            
            # Emails indexes
            self.emails.create_index([("lead_id", 1), ("step_number", 1)])
            self.emails.create_index([("status", 1), ("scheduled_send_at", 1)])
            self.emails.create_index([("sequence_id", 1)])
            
            # Events indexes
            self.events.create_index([("email_id", 1), ("event_type", 1)])
            self.events.create_index([("lead_id", 1), ("timestamp", 1)])
            
        except Exception as e:
            import logging
            logging.warning(f"Index creation failed: {e}")
    
    def create_sequence(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        description: Optional[str] = None,
        personalization_level: PersonalizationLevel = PersonalizationLevel.ROLE_BASED,
        duration_days: int = 14,
        **kwargs
    ) -> str:
        """
        Create a new outreach sequence.
        
        Args:
            name: Sequence name
            steps: List of step configurations
            description: Sequence description
            personalization_level: Default personalization level
            duration_days: Total sequence duration
            **kwargs: Additional sequence settings
        
        Returns:
            Sequence ID
        """
        # Build sequence steps
        sequence_steps = []
        for step_data in steps:
            step = SequenceStep(
                step_number=step_data["step_number"],
                day_offset=step_data["day_offset"],
                name=step_data["name"],
                description=step_data.get("description", ""),
                template_id=step_data["template_id"],
                send_if_not_replied=step_data.get("send_if_not_replied", True),
                send_if_not_opened=step_data.get("send_if_not_opened", False),
                send_if_not_clicked=step_data.get("send_if_not_clicked", False),
                subject_variants=step_data.get("subject_variants", []),
                cta_variants=step_data.get("cta_variants", [])
            )
            sequence_steps.append(step)
        
        # Create sequence
        sequence = OutreachSequence(
            name=name,
            description=description,
            duration_days=duration_days,
            steps=sequence_steps,
            personalization_level=personalization_level,
            **kwargs
        )
        
        doc = sequence.model_dump()
        result = self.sequences.insert_one(doc)
        return str(result.inserted_id)
    
    def enroll_lead(
        self,
        lead_id: str,
        sequence_id: str,
        start_immediately: bool = True
    ) -> bool:
        """
        Enroll a lead in an outreach sequence.
        
        Args:
            lead_id: Lead ID
            sequence_id: Sequence ID
            start_immediately: Whether to start sequence immediately
        
        Returns:
            Success status
        """
        # Verify sequence exists
        sequence = self.sequences.find_one({"_id": ObjectId(sequence_id)})
        if not sequence or not sequence.get("is_active"):
            raise ValueError(f"Sequence {sequence_id} not found or not active")
        
        # Update lead
        update_data = {
            "assigned_sequence_id": sequence_id,
            "sequence_stage": SequenceStage.NOT_STARTED,
            "updated_at": datetime.utcnow()
        }
        
        result = self.leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            return False
        
        # Schedule first email if starting immediately
        if start_immediately:
            self._schedule_next_email(lead_id, sequence_id)
        
        return True
    
    def _schedule_next_email(
        self,
        lead_id: str,
        sequence_id: str
    ) -> Optional[str]:
        """
        Schedule the next email in the sequence for a lead.
        
        Args:
            lead_id: Lead ID
            sequence_id: Sequence ID
        
        Returns:
            Email ID if scheduled, None otherwise
        """
        # Get lead and sequence
        lead = self.leads.find_one({"_id": ObjectId(lead_id)})
        sequence = self.sequences.find_one({"_id": ObjectId(sequence_id)})
        
        if not lead or not sequence:
            return None
        
        # Determine next step
        current_stage = lead.get("sequence_stage", SequenceStage.NOT_STARTED.value)
        next_step_number = self._get_next_step_number(current_stage)
        
        if next_step_number is None:
            # Sequence completed
            self._mark_sequence_completed(lead_id)
            return None
        
        # Get step configuration
        steps = sequence.get("steps", [])
        if next_step_number >= len(steps):
            self._mark_sequence_completed(lead_id)
            return None
        
        step = steps[next_step_number]
        
        # Check step conditions
        if not self._check_step_conditions(lead, step):
            # Skip this step and try next
            self._update_lead_stage(lead_id, next_step_number)
            return self._schedule_next_email(lead_id, sequence_id)
        
        # Get template
        template = self.templates.find_one({"_id": ObjectId(step["template_id"])})
        if not template:
            raise ValueError(f"Template {step['template_id']} not found")
        
        # Build lead object for personalization
        lead_obj = OutreachLead(**lead)
        
        # Select subject variant based on behavior
        subject_to_use = template["subject"]
        if step.get("subject_variants") and lead.get("emails_sent", 0) > 0:
            # Use variant if lead hasn't opened previous emails
            if lead.get("emails_opened", 0) == 0:
                subject_to_use = step["subject_variants"][0] if step["subject_variants"] else template["subject"]
        
        # Create personalized content
        from .models import EmailTemplate as EmailTemplateModel
        template_obj = EmailTemplateModel(**template)
        template_obj.subject = subject_to_use
        
        try:
            personalized = self.personalization.render_template(
                template_obj,
                lead_obj
            )
        except ValueError as e:
            # Missing personalization data, log and skip
            import logging
            logging.error(f"Personalization failed for lead {lead_id}: {e}")
            return None
        
        # Calculate send time
        sequence_start = lead.get("last_contacted_at") or lead.get("created_at") or datetime.utcnow()
        scheduled_send_at = sequence_start + timedelta(days=step["day_offset"])
        
        # Don't schedule in the past
        if scheduled_send_at < datetime.utcnow():
            scheduled_send_at = datetime.utcnow() + timedelta(minutes=5)
        
        # Create email record
        email = OutreachEmail(
            lead_id=lead_id,
            sequence_id=sequence_id,
            step_number=next_step_number,
            to_email=lead["email"],
            subject=personalized["subject"],
            body_html=personalized["body_html"],
            body_plain=personalized.get("body_plain", ""),
            scheduled_send_at=scheduled_send_at,
            personalization_data=personalized.get("tokens_used", {})
        )
        
        doc = email.model_dump()
        result = self.emails.insert_one(doc)
        email_id = str(result.inserted_id)
        
        # Update lead stage
        self._update_lead_stage(lead_id, next_step_number, scheduled=True)
        
        return email_id
    
    def _check_step_conditions(
        self,
        lead: Dict,
        step: Dict
    ) -> bool:
        """
        Check if step conditions are met for sending.
        
        Args:
            lead: Lead document
            step: Step configuration
        
        Returns:
            True if conditions met, False otherwise
        """
        # Check if lead has replied
        if step.get("send_if_not_replied", True):
            if lead.get("emails_replied", 0) > 0:
                return False
        
        # Check if previous email was opened
        if step.get("send_if_not_opened", False):
            if lead.get("emails_opened", 0) > 0:
                return False
        
        # Check if previous email was clicked
        if step.get("send_if_not_clicked", False):
            if lead.get("emails_clicked", 0) > 0:
                return False
        
        return True
    
    def _get_next_step_number(self, current_stage: str) -> Optional[int]:
        """
        Determine next step number based on current stage.
        
        Args:
            current_stage: Current sequence stage
        
        Returns:
            Next step number or None if sequence complete
        """
        stage_to_step = {
            SequenceStage.NOT_STARTED.value: 0,
            SequenceStage.EMAIL_1_SCHEDULED.value: 0,
            SequenceStage.EMAIL_1_SENT.value: 1,
            SequenceStage.EMAIL_2_SCHEDULED.value: 1,
            SequenceStage.EMAIL_2_SENT.value: 2,
            SequenceStage.EMAIL_3_SCHEDULED.value: 2,
            SequenceStage.EMAIL_3_SENT.value: 3,
            SequenceStage.EMAIL_4_SCHEDULED.value: 3,
            SequenceStage.EMAIL_4_SENT.value: None,
            SequenceStage.SEQUENCE_COMPLETED.value: None,
            SequenceStage.SEQUENCE_STOPPED.value: None
        }
        
        return stage_to_step.get(current_stage, None)
    
    def _update_lead_stage(
        self,
        lead_id: str,
        step_number: int,
        scheduled: bool = False,
        sent: bool = False
    ):
        """Update lead's sequence stage."""
        step_to_stage = {
            0: SequenceStage.EMAIL_1_SCHEDULED if scheduled else SequenceStage.EMAIL_1_SENT,
            1: SequenceStage.EMAIL_2_SCHEDULED if scheduled else SequenceStage.EMAIL_2_SENT,
            2: SequenceStage.EMAIL_3_SCHEDULED if scheduled else SequenceStage.EMAIL_3_SENT,
            3: SequenceStage.EMAIL_4_SCHEDULED if scheduled else SequenceStage.EMAIL_4_SENT
        }
        
        if sent:
            step_to_stage = {
                0: SequenceStage.EMAIL_1_SENT,
                1: SequenceStage.EMAIL_2_SENT,
                2: SequenceStage.EMAIL_3_SENT,
                3: SequenceStage.EMAIL_4_SENT
            }
        
        new_stage = step_to_stage.get(step_number, SequenceStage.NOT_STARTED)
        
        self.leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "sequence_stage": new_stage.value,
                "updated_at": datetime.utcnow()
            }}
        )
    
    def _mark_sequence_completed(self, lead_id: str):
        """Mark a lead's sequence as completed."""
        self.leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "sequence_stage": SequenceStage.SEQUENCE_COMPLETED.value,
                "reengagement_eligible": True,
                "updated_at": datetime.utcnow()
            }}
        )
    
    def stop_sequence(
        self,
        lead_id: str,
        reason: str = "manual"
    ) -> bool:
        """
        Stop a sequence for a lead.
        
        Args:
            lead_id: Lead ID
            reason: Reason for stopping (manual, replied, bounced, etc.)
        
        Returns:
            Success status
        """
        result = self.leads.update_one(
            {"_id": ObjectId(lead_id)},
            {"$set": {
                "sequence_stage": SequenceStage.SEQUENCE_STOPPED.value,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Cancel any scheduled emails
        self.emails.update_many(
            {
                "lead_id": lead_id,
                "status": "scheduled"
            },
            {"$set": {"status": "cancelled"}}
        )
        
        return result.modified_count > 0
    
    def process_scheduled_emails(self, limit: int = 100) -> int:
        """
        Process scheduled emails that are due to be sent.
        
        Args:
            limit: Maximum number of emails to process
        
        Returns:
            Number of emails processed
        """
        now = datetime.utcnow()
        
        # Find emails due for sending
        scheduled_emails = self.emails.find({
            "status": "scheduled",
            "scheduled_send_at": {"$lte": now}
        }).limit(limit)
        
        processed = 0
        
        for email_doc in scheduled_emails:
            # Mark as ready to send (actual sending handled by email sender service)
            self.emails.update_one(
                {"_id": email_doc["_id"]},
                {"$set": {
                    "status": "queued",
                    "updated_at": now
                }}
            )
            
            processed += 1
        
        return processed


def create_default_sequence(db: Database) -> str:
    """
    Create the default 4-step cold outreach sequence.
    
    Args:
        db: MongoDB database
    
    Returns:
        Sequence ID
    """
    engine = SequenceEngine(db)
    
    # Note: Template IDs should be created separately
    # This is a placeholder structure
    steps = [
        {
            "step_number": 0,
            "day_offset": 0,
            "name": "Introduction",
            "description": "Soft introduction with one clear pain point",
            "template_id": "template_id_1",  # Replace with actual template ID
            "send_if_not_replied": True,
            "subject_variants": []
        },
        {
            "step_number": 1,
            "day_offset": 4,
            "name": "Value Follow-Up",
            "description": "Different angle with use case and social proof",
            "template_id": "template_id_2",
            "send_if_not_replied": True,
            "send_if_not_opened": False,
            "subject_variants": ["Quick follow-up for {{company}}"]
        },
        {
            "step_number": 2,
            "day_offset": 7,
            "name": "Direct / Break-Up",
            "description": "Concise with simple yes/no CTA",
            "template_id": "template_id_3",
            "send_if_not_replied": True,
            "subject_variants": ["Last check-in, {{first_name}}"]
        },
        {
            "step_number": 3,
            "day_offset": 12,
            "name": "Final Touch",
            "description": "Polite close-the-loop message",
            "template_id": "template_id_4",
            "send_if_not_replied": True,
            "subject_variants": ["Closing the loop"]
        }
    ]
    
    return engine.create_sequence(
        name="Default Cold Outreach (14 days)",
        steps=steps,
        description="Standard 4-step B2B cold outreach sequence",
        duration_days=14,
        personalization_level=PersonalizationLevel.ROLE_BASED
    )
