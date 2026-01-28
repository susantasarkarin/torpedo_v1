"""
RE-ENGAGEMENT SERVICE
=====================

Detects dormant leads and creates multi-phase re-engagement campaigns.

Features:
- Dormant lead detection based on activity and sequence completion
- Three-phase re-engagement strategy:
  * Soft-drip (Week 3-4): Educational content, no CTA
  * Trigger-based (Month 2): Job change, funding, industry events
  * Reset outreach (Month 3-4): Fresh angle, new copy with sender rotation
- Intelligent strategy selection based on lead behavior
- Sender rotation for reset campaigns

Collections:
- campaign_recipients: Lead activity tracking
- campaign_sends: Email engagement history
- reengagement_campaigns: Re-engagement campaign tracking

Usage:
    service = ReengagementService(db)
    
    # Detect dormant leads
    dormant = service.detect_dormant_leads(days_since_last_contact=21)
    
    # Create re-engagement campaign
    campaign = service.create_reengagement_campaign(
        lead_ids=[lead['_id'] for lead in dormant],
        strategy="soft_drip"
    )
    
    # Auto-select strategy for a lead
    strategy = service.select_reengagement_strategy(lead)
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Literal
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


class ReengagementService:
    """
    Service for detecting dormant leads and creating re-engagement campaigns.
    
    Attributes:
        db: MongoDB database instance
    """
    
    def __init__(self, db):
        """
        Initialize the re-engagement service.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.campaigns_col = db.campaigns
        self.recipients_col = db.campaign_recipients
        self.sends_col = db.campaign_sends
        self.reengagement_col = db.reengagement_campaigns
    
    def detect_dormant_leads(
        self, 
        days_since_last_contact: int = 21,
        sequence_completed_only: bool = True
    ) -> List[Dict]:
        """
        Detect leads that have gone dormant after campaign completion.
        
        A lead is considered dormant if:
        - They completed a campaign sequence (or optionally, any lead)
        - No email activity (open, click, reply) for X days
        - Not currently in an active re-engagement campaign
        - Not marked as unsubscribed or bounced
        
        Args:
            days_since_last_contact: Days of inactivity to consider dormant (default: 21)
            sequence_completed_only: Only consider leads who completed sequences (default: True)
        
        Returns:
            List of dormant lead dictionaries with metadata
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_since_last_contact)
        
        # Build query for dormant leads
        query = {
            "status": {"$in": ["completed", "in_sequence"]},
            "last_activity_at": {"$lt": cutoff_date},
            "$or": [
                {"unsubscribed": {"$exists": False}},
                {"unsubscribed": False}
            ]
        }
        
        if sequence_completed_only:
            query["status"] = "completed"
        
        # Find potentially dormant leads
        potential_dormant = list(self.recipients_col.find(query))
        
        dormant_leads = []
        for recipient in potential_dormant:
            # Check if already in a re-engagement campaign
            active_reengagement = self.reengagement_col.find_one({
                "lead_id": recipient["_id"],
                "status": {"$in": ["active", "scheduled"]}
            })
            
            if active_reengagement:
                continue
            
            # Get last send activity
            last_send = self.sends_col.find_one(
                {"recipient_id": recipient["_id"]},
                sort=[("sent_at", -1)]
            )
            
            if last_send:
                days_since_contact = (datetime.utcnow() - last_send["sent_at"]).days
            else:
                days_since_contact = 999  # No contact found
            
            # Calculate engagement metrics
            total_sends = self.sends_col.count_documents({"recipient_id": recipient["_id"]})
            opened_count = self.sends_col.count_documents({
                "recipient_id": recipient["_id"],
                "status": {"$in": ["opened", "clicked", "replied"]}
            })
            clicked_count = self.sends_col.count_documents({
                "recipient_id": recipient["_id"],
                "status": {"$in": ["clicked", "replied"]}
            })
            
            engagement_rate = opened_count / total_sends if total_sends > 0 else 0
            click_rate = clicked_count / total_sends if total_sends > 0 else 0
            
            dormant_leads.append({
                "_id": recipient["_id"],
                "lead_id": recipient.get("lead_id"),
                "email": recipient.get("email"),
                "campaign_id": recipient.get("campaign_id"),
                "days_since_contact": days_since_contact,
                "total_sends": total_sends,
                "engagement_rate": engagement_rate,
                "click_rate": click_rate,
                "last_activity_at": recipient.get("last_activity_at"),
                "completed_at": recipient.get("completed_at")
            })
        
        logger.info(f"Detected {len(dormant_leads)} dormant leads")
        return dormant_leads
    
    def select_reengagement_strategy(self, lead: Dict) -> Literal["soft_drip", "trigger_based", "reset_outreach"]:
        """
        Select the best re-engagement strategy based on lead behavior.
        
        Strategy selection logic:
        - Soft-drip (Week 3-4): For engaged leads (opened >50% of emails) who went quiet
        - Trigger-based (Month 2): For moderately engaged leads (20-50% open rate)
        - Reset outreach (Month 3-4): For low engagement (<20%) or very dormant (>60 days)
        
        Args:
            lead: Lead dictionary with engagement metrics
        
        Returns:
            Strategy name: "soft_drip" | "trigger_based" | "reset_outreach"
        """
        days_dormant = lead.get("days_since_contact", 0)
        engagement_rate = lead.get("engagement_rate", 0)
        click_rate = lead.get("click_rate", 0)
        
        # Reset outreach for very dormant or low engagement
        if days_dormant >= 60 or engagement_rate < 0.2:
            return "reset_outreach"
        
        # Soft-drip for recently dormant, high engagement leads
        if days_dormant <= 30 and engagement_rate >= 0.5:
            return "soft_drip"
        
        # Trigger-based for moderate engagement
        return "trigger_based"
    
    def create_reengagement_campaign(
        self,
        lead_ids: List[str],
        strategy: Literal["soft_drip", "trigger_based", "reset_outreach"],
        mailbox_id: Optional[str] = None,
        custom_templates: Optional[Dict[str, str]] = None
    ) -> Dict:
        """
        Create a re-engagement campaign for dormant leads.
        
        Args:
            lead_ids: List of lead IDs to re-engage
            strategy: Re-engagement strategy to use
            mailbox_id: Email mailbox to send from (optional)
            custom_templates: Custom email template IDs (optional)
        
        Returns:
            Created campaign dictionary with sequence steps
        """
        if not lead_ids:
            raise ValueError("At least one lead_id required")
        
        # Get default templates for strategy
        templates = custom_templates or self._get_default_templates(strategy)
        
        # Build sequence based on strategy
        sequence_steps = self._build_reengagement_sequence(strategy, templates)
        
        # Create campaign record
        campaign_data = {
            "name": f"Re-engagement - {strategy.replace('_', ' ').title()}",
            "type": "reengagement",
            "strategy": strategy,
            "status": "scheduled",
            "mailbox_id": mailbox_id,
            "sequence_steps": sequence_steps,
            "lead_ids": [ObjectId(lid) if isinstance(lid, str) else lid for lid in lead_ids],
            "created_at": datetime.utcnow(),
            "starts_at": datetime.utcnow() + timedelta(hours=1),
            "metrics": {
                "total_leads": len(lead_ids),
                "sent": 0,
                "opened": 0,
                "clicked": 0,
                "replied": 0,
                "reengaged": 0
            }
        }
        
        result = self.reengagement_col.insert_one(campaign_data)
        campaign_data["_id"] = result.inserted_id
        
        # Update recipients to track re-engagement
        self.recipients_col.update_many(
            {"_id": {"$in": campaign_data["lead_ids"]}},
            {
                "$set": {
                    "reengagement_campaign_id": result.inserted_id,
                    "reengagement_status": "scheduled",
                    "reengagement_started_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Created re-engagement campaign {result.inserted_id} with {len(lead_ids)} leads using {strategy} strategy")
        return campaign_data
    
    def _get_default_templates(self, strategy: str) -> Dict[str, str]:
        """
        Get default email template IDs for a re-engagement strategy.
        
        Args:
            strategy: Re-engagement strategy name
        
        Returns:
            Dictionary mapping step names to template IDs
        """
        # In production, these would be real template IDs from the database
        templates = {
            "soft_drip": {
                "step_1": "soft_drip_educational_1",
                "step_2": "soft_drip_educational_2",
                "step_3": "soft_drip_case_study"
            },
            "trigger_based": {
                "step_1": "trigger_job_change",
                "step_2": "trigger_funding_news",
                "step_3": "trigger_industry_event"
            },
            "reset_outreach": {
                "step_1": "reset_fresh_angle",
                "step_2": "reset_different_value_prop",
                "step_3": "reset_breakup_email"
            }
        }
        
        return templates.get(strategy, templates["soft_drip"])
    
    def _build_reengagement_sequence(self, strategy: str, templates: Dict[str, str]) -> List[Dict]:
        """
        Build email sequence steps for a re-engagement campaign.
        
        Args:
            strategy: Re-engagement strategy name
            templates: Template IDs for each step
        
        Returns:
            List of sequence step dictionaries
        """
        sequences = {
            "soft_drip": [
                {
                    "step": 1,
                    "day": 0,
                    "template_id": templates.get("step_1"),
                    "subject": "Thought you might find this useful",
                    "content_type": "educational",
                    "has_cta": False,
                    "condition": "always"
                },
                {
                    "step": 2,
                    "day": 4,
                    "template_id": templates.get("step_2"),
                    "subject": "Quick insight on [topic]",
                    "content_type": "educational",
                    "has_cta": False,
                    "condition": "no_reply"
                },
                {
                    "step": 3,
                    "day": 7,
                    "template_id": templates.get("step_3"),
                    "subject": "How [Company] solved [problem]",
                    "content_type": "case_study",
                    "has_cta": True,
                    "condition": "opened"
                }
            ],
            "trigger_based": [
                {
                    "step": 1,
                    "day": 0,
                    "template_id": templates.get("step_1"),
                    "subject": "Congrats on the new role!",
                    "trigger_type": "job_change",
                    "condition": "always"
                },
                {
                    "step": 2,
                    "day": 5,
                    "template_id": templates.get("step_2"),
                    "subject": "Saw the funding announcement",
                    "trigger_type": "funding",
                    "condition": "no_reply"
                },
                {
                    "step": 3,
                    "day": 10,
                    "template_id": templates.get("step_3"),
                    "subject": "Are you attending [Event]?",
                    "trigger_type": "industry_event",
                    "condition": "no_reply"
                }
            ],
            "reset_outreach": [
                {
                    "step": 1,
                    "day": 0,
                    "template_id": templates.get("step_1"),
                    "subject": "Different approach: [Fresh angle]",
                    "sender_rotation": True,
                    "condition": "always"
                },
                {
                    "step": 2,
                    "day": 5,
                    "template_id": templates.get("step_2"),
                    "subject": "One more thing about [value prop]",
                    "sender_rotation": True,
                    "condition": "no_reply"
                },
                {
                    "step": 3,
                    "day": 9,
                    "template_id": templates.get("step_3"),
                    "subject": "Breaking up is hard to do",
                    "breakup_email": True,
                    "condition": "no_reply"
                }
            ]
        }
        
        return sequences.get(strategy, sequences["soft_drip"])
    
    def rotate_sender_for_reset(self, campaign_id: str, current_mailbox_id: str) -> Optional[str]:
        """
        Select a different sender mailbox for reset outreach phase.
        
        Args:
            campaign_id: Re-engagement campaign ID
            current_mailbox_id: Current mailbox being used
        
        Returns:
            New mailbox ID to use, or None if no alternative available
        """
        # Get all available mailboxes except current
        available_mailboxes = list(self.db.mailboxes.find({
            "_id": {"$ne": ObjectId(current_mailbox_id)},
            "status": "active",
            "daily_limit": {"$gt": 0}
        }))
        
        if not available_mailboxes:
            logger.warning("No alternative mailboxes available for sender rotation")
            return None
        
        # Select mailbox with lowest send count today
        best_mailbox = min(
            available_mailboxes,
            key=lambda m: m.get("sends_today", 0)
        )
        
        logger.info(f"Rotated sender from {current_mailbox_id} to {best_mailbox['_id']}")
        return str(best_mailbox["_id"])
    
    def mark_reengaged(self, recipient_id: str, campaign_id: str):
        """
        Mark a lead as successfully re-engaged (replied or booked meeting).
        
        Args:
            recipient_id: Recipient ID
            campaign_id: Re-engagement campaign ID
        """
        self.recipients_col.update_one(
            {"_id": ObjectId(recipient_id)},
            {
                "$set": {
                    "reengagement_status": "reengaged",
                    "reengaged_at": datetime.utcnow()
                }
            }
        )
        
        self.reengagement_col.update_one(
            {"_id": ObjectId(campaign_id)},
            {
                "$inc": {"metrics.reengaged": 1}
            }
        )
        
        logger.info(f"Marked recipient {recipient_id} as re-engaged")
    
    def get_reengagement_metrics(self, campaign_id: str) -> Dict:
        """
        Get performance metrics for a re-engagement campaign.
        
        Args:
            campaign_id: Re-engagement campaign ID
        
        Returns:
            Dictionary with campaign metrics
        """
        campaign = self.reengagement_col.find_one({"_id": ObjectId(campaign_id)})
        
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        # Calculate rates
        metrics = campaign.get("metrics", {})
        total = metrics.get("total_leads", 0)
        
        if total > 0:
            metrics["open_rate"] = metrics.get("opened", 0) / total
            metrics["click_rate"] = metrics.get("clicked", 0) / total
            metrics["reply_rate"] = metrics.get("replied", 0) / total
            metrics["reengagement_rate"] = metrics.get("reengaged", 0) / total
        else:
            metrics["open_rate"] = 0
            metrics["click_rate"] = 0
            metrics["reply_rate"] = 0
            metrics["reengagement_rate"] = 0
        
        return metrics


def example_usage():
    """Example demonstrating re-engagement service usage."""
    from pymongo import MongoClient
    
    # Connect to database
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform
    
    # Initialize service
    service = ReengagementService(db)
    
    print("=" * 80)
    print("RE-ENGAGEMENT SERVICE EXAMPLE")
    print("=" * 80)
    
    # 1. Detect dormant leads
    print("\n1. Detecting dormant leads...")
    dormant_leads = service.detect_dormant_leads(days_since_last_contact=21)
    print(f"Found {len(dormant_leads)} dormant leads")
    
    if dormant_leads:
        # Show first dormant lead details
        lead = dormant_leads[0]
        print(f"\nExample dormant lead:")
        print(f"  - Email: {lead['email']}")
        print(f"  - Days dormant: {lead['days_since_contact']}")
        print(f"  - Engagement rate: {lead['engagement_rate']:.1%}")
        print(f"  - Click rate: {lead['click_rate']:.1%}")
        
        # 2. Select strategy
        print("\n2. Selecting re-engagement strategy...")
        strategy = service.select_reengagement_strategy(lead)
        print(f"Selected strategy: {strategy}")
        
        # 3. Create re-engagement campaign
        print("\n3. Creating re-engagement campaign...")
        campaign = service.create_reengagement_campaign(
            lead_ids=[str(lead["_id"])],
            strategy=strategy
        )
        print(f"Created campaign: {campaign['name']}")
        print(f"  - Campaign ID: {campaign['_id']}")
        print(f"  - Total leads: {campaign['metrics']['total_leads']}")
        print(f"  - Sequence steps: {len(campaign['sequence_steps'])}")
        
        # Show sequence details
        print("\n  Sequence steps:")
        for step in campaign["sequence_steps"]:
            print(f"    Day {step['day']}: {step.get('subject', 'No subject')}")
        
        # 4. Get metrics
        print("\n4. Campaign metrics...")
        metrics = service.get_reengagement_metrics(str(campaign["_id"]))
        print(f"  - Total leads: {metrics['total_leads']}")
        print(f"  - Reengagement rate: {metrics['reengagement_rate']:.1%}")


if __name__ == "__main__":
    example_usage()
