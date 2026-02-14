"""
MAILBOX MANAGER
===============

Handles mailbox assignment, health tracking, and signature management.

Key Features:
- STICKY mailbox assignment (once assigned, never changes for follow-ups)
- Even distribution across mailbox pool for new leads
- Health tracking (bounce rates, complaints)
- Daily/hourly rate limit tracking
- Warmup status handling
- Dynamic signature retrieval

Rules:
- When first outreach is sent, assign mailbox_id to lead
- Store assigned_mailbox_id in lead record
- All future follow-ups MUST use same mailbox
- Do NOT rotate mailbox for follow-ups
- Do NOT allow reassignment mid-thread
- Mailbox selection distributes evenly for new leads only
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pymongo.database import Database
from bson import ObjectId

from .models import Mailbox, MailboxHealth, Lead

logger = logging.getLogger(__name__)


class MailboxManager:
    """
    Manages mailbox assignment, health, and signatures.
    
    Responsibilities:
    - Sticky mailbox assignment per lead
    - Even distribution for new lead assignments
    - Health monitoring and automatic pausing
    - Rate limit tracking (daily/hourly)
    - Dynamic signature retrieval
    """
    
    def __init__(self, db: Database):
        """
        Initialize mailbox manager.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.mailboxes_collection = db["outreach_mailboxes"]
        self.leads_collection = db["outreach_leads_v2"]
        self.profiles_collection = db["user_profiles"]  # For signature retrieval
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            self.mailboxes_collection.create_index([("mailbox_id", 1)], unique=True)
            self.mailboxes_collection.create_index([("email_address", 1)], unique=True)
            self.mailboxes_collection.create_index([
                ("health_status", 1),
                ("is_active", 1)
            ])
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    # ============== MAILBOX ASSIGNMENT ==============
    
    def get_assigned_mailbox(self, lead_id: str) -> Optional[str]:
        """
        Get the assigned mailbox for a lead (sticky assignment).
        
        Args:
            lead_id: Lead ID to get mailbox for
            
        Returns:
            Mailbox ID or None if not assigned
        """
        lead = self.leads_collection.find_one(
            {"lead_id": lead_id},
            {"assigned_mailbox_id": 1}
        )
        
        if lead:
            return lead.get("assigned_mailbox_id")
        return None
    
    def assign_mailbox_to_lead(
        self,
        lead_id: str,
        campaign_mailbox_ids: List[str],
        force: bool = False
    ) -> Tuple[Optional[str], str]:
        """
        Assign a mailbox to a lead using sticky assignment.
        
        Rules:
        - If lead already has assigned_mailbox_id, return that (sticky)
        - If no assignment, select from pool with lowest assignment count
        - Never reassign mid-thread unless force=True
        
        Args:
            lead_id: Lead ID to assign mailbox to
            campaign_mailbox_ids: Pool of mailbox IDs for this campaign
            force: Force reassignment (should almost never be True)
            
        Returns:
            Tuple of (mailbox_id, message)
        """
        # Get lead
        lead = self.leads_collection.find_one({"lead_id": lead_id})
        if not lead:
            return None, f"Lead {lead_id} not found"
        
        # Check existing assignment (STICKY)
        existing_mailbox = lead.get("assigned_mailbox_id")
        if existing_mailbox and not force:
            # Verify mailbox is still valid
            mailbox = self.mailboxes_collection.find_one({
                "mailbox_id": existing_mailbox,
                "is_active": True
            })
            if mailbox:
                return existing_mailbox, "Using existing sticky assignment"
            else:
                logger.warning(f"Lead {lead_id} has invalid mailbox {existing_mailbox}")
                # Fall through to reassign
        
        # Get available mailboxes from pool
        available_mailboxes = list(self.mailboxes_collection.find({
            "mailbox_id": {"$in": campaign_mailbox_ids},
            "is_active": True,
            "health_status": {"$in": [
                MailboxHealth.HEALTHY.value,
                MailboxHealth.WARMING.value
            ]},
            "$or": [
                {"paused_until": {"$exists": False}},
                {"paused_until": None},
                {"paused_until": {"$lte": datetime.utcnow()}}
            ]
        }))
        
        if not available_mailboxes:
            return None, "No available mailboxes in pool"
        
        # Select mailbox with lowest assignment count (even distribution)
        selected_mailbox = self._select_mailbox_for_distribution(
            available_mailboxes,
            campaign_mailbox_ids
        )
        
        if not selected_mailbox:
            return None, "Could not select mailbox"
        
        mailbox_id = selected_mailbox["mailbox_id"]
        
        # Assign to lead (STICKY)
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": {
                "assigned_mailbox_id": mailbox_id,
                "updated_at": datetime.utcnow()
            }}
        )
        
        logger.info(f"Assigned mailbox {mailbox_id} to lead {lead_id}")
        return mailbox_id, f"Assigned mailbox {mailbox_id}"
    
    def _select_mailbox_for_distribution(
        self,
        available_mailboxes: List[Dict[str, Any]],
        campaign_mailbox_ids: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Select mailbox with lowest assignment count for even distribution.
        """
        # Count current assignments per mailbox
        pipeline = [
            {"$match": {
                "assigned_mailbox_id": {"$in": campaign_mailbox_ids},
                "workflow_status": "in_progress"
            }},
            {"$group": {
                "_id": "$assigned_mailbox_id",
                "count": {"$sum": 1}
            }}
        ]
        
        counts = {r["_id"]: r["count"] for r in self.leads_collection.aggregate(pipeline)}
        
        # Find mailbox with lowest count
        selected = None
        min_count = float("inf")
        
        for mailbox in available_mailboxes:
            mailbox_id = mailbox["mailbox_id"]
            count = counts.get(mailbox_id, 0)
            
            # Also check rate limits
            if not self._can_send_from_mailbox(mailbox):
                continue
            
            if count < min_count:
                min_count = count
                selected = mailbox
        
        return selected
    
    # ============== RATE LIMITING ==============
    
    def can_send_from_mailbox(self, mailbox_id: str) -> Tuple[bool, str]:
        """
        Check if mailbox can send (rate limits, health).
        
        Args:
            mailbox_id: Mailbox to check
            
        Returns:
            Tuple of (can_send, reason)
        """
        mailbox = self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
        if not mailbox:
            return False, "Mailbox not found"
        
        can_send, reason = self._can_send_from_mailbox(mailbox)
        return can_send, reason
    
    def _can_send_from_mailbox(self, mailbox: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Internal check if mailbox can send.
        """
        # Check active status
        if not mailbox.get("is_active", False):
            return False, "Mailbox is not active"
        
        # Check health status
        health = mailbox.get("health_status")
        if health == MailboxHealth.SUSPENDED.value:
            return False, "Mailbox is suspended"
        if health == MailboxHealth.PAUSED.value:
            return False, "Mailbox is paused"
        
        # Check pause until
        paused_until = mailbox.get("paused_until")
        if paused_until and paused_until > datetime.utcnow():
            return False, f"Mailbox paused until {paused_until}"
        
        # Check daily limit
        daily_count = mailbox.get("daily_send_count", 0)
        daily_limit = mailbox.get("daily_send_limit", 400)
        daily_reset_at = mailbox.get("daily_reset_at")
        
        # Reset daily count if needed
        if daily_reset_at and daily_reset_at < datetime.utcnow():
            daily_count = 0
        
        if daily_count >= daily_limit:
            return False, f"Daily limit reached ({daily_count}/{daily_limit})"
        
        # Check hourly limit
        hourly_count = mailbox.get("hourly_send_count", 0)
        hourly_limit = mailbox.get("hourly_send_limit", 60)
        hourly_reset_at = mailbox.get("hourly_reset_at")
        
        # Reset hourly count if needed
        if hourly_reset_at and hourly_reset_at < datetime.utcnow():
            hourly_count = 0
        
        if hourly_count >= hourly_limit:
            return False, f"Hourly limit reached ({hourly_count}/{hourly_limit})"
        
        # Check warmup status
        warmup_status = mailbox.get("warmup_status", "complete")
        if warmup_status == "warmup":
            warmup_day = mailbox.get("warmup_day", 0)
            warmup_limit = self._get_warmup_limit(warmup_day)
            if daily_count >= warmup_limit:
                return False, f"Warmup daily limit reached ({warmup_limit})"
        
        return True, "OK"
    
    def _get_warmup_limit(self, warmup_day: int) -> int:
        """Get daily send limit based on warmup day"""
        # Gradual warmup schedule
        warmup_schedule = {
            0: 10, 1: 15, 2: 20, 3: 30, 4: 40,
            5: 50, 6: 60, 7: 80, 8: 100, 9: 120,
            10: 150, 11: 180, 12: 210, 13: 250, 14: 300
        }
        return warmup_schedule.get(warmup_day, 400)
    
    def increment_send_count(self, mailbox_id: str) -> bool:
        """
        Increment send counters for mailbox.
        
        Args:
            mailbox_id: Mailbox ID
            
        Returns:
            True if successful
        """
        now = datetime.utcnow()
        
        # Get mailbox to check reset times
        mailbox = self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
        if not mailbox:
            return False
        
        update = {"$set": {"last_send_at": now}}
        
        # Check if we need to reset daily count
        daily_reset_at = mailbox.get("daily_reset_at")
        if not daily_reset_at or daily_reset_at < now:
            # Reset daily count and set new reset time
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            update["$set"]["daily_send_count"] = 1
            update["$set"]["daily_reset_at"] = tomorrow
        else:
            update["$inc"] = {"daily_send_count": 1}
        
        # Check if we need to reset hourly count
        hourly_reset_at = mailbox.get("hourly_reset_at")
        if not hourly_reset_at or hourly_reset_at < now:
            # Reset hourly count and set new reset time
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            update["$set"]["hourly_send_count"] = 1
            update["$set"]["hourly_reset_at"] = next_hour
        else:
            if "$inc" not in update:
                update["$inc"] = {}
            update["$inc"]["hourly_send_count"] = 1
        
        self.mailboxes_collection.update_one(
            {"mailbox_id": mailbox_id},
            update
        )
        
        return True
    
    # ============== HEALTH MANAGEMENT ==============
    
    def update_bounce_rate(
        self,
        mailbox_id: str,
        bounce_threshold: float = 0.05
    ) -> Tuple[bool, Optional[str]]:
        """
        Update bounce rate and potentially pause mailbox.
        
        Args:
            mailbox_id: Mailbox to update
            bounce_threshold: Rate at which to pause (default 5%)
            
        Returns:
            Tuple of (is_paused, pause_reason)
        """
        # Calculate bounce rate from last 24 hours
        yesterday = datetime.utcnow() - timedelta(hours=24)
        
        sends_collection = self.db["outreach_sends_v2"]
        
        # Count total and bounced
        total_sends = sends_collection.count_documents({
            "mailbox_id": mailbox_id,
            "sent_at": {"$gte": yesterday}
        })
        
        bounced_sends = sends_collection.count_documents({
            "mailbox_id": mailbox_id,
            "sent_at": {"$gte": yesterday},
            "status": "bounced"
        })
        
        if total_sends == 0:
            rate = 0.0
        else:
            rate = bounced_sends / total_sends
        
        # Update rate
        updates: Dict[str, Any] = {
            "bounce_rate_24h": rate,
            "updated_at": datetime.utcnow()
        }
        
        # Check if we need to pause
        is_paused = False
        pause_reason = None
        
        if rate > bounce_threshold:
            is_paused = True
            pause_reason = f"Bounce rate {rate:.1%} exceeded threshold {bounce_threshold:.1%}"
            updates["health_status"] = MailboxHealth.THROTTLED.value
            updates["paused_until"] = datetime.utcnow() + timedelta(hours=4)
            updates["pause_reason"] = pause_reason
            logger.warning(f"Mailbox {mailbox_id} paused: {pause_reason}")
        
        self.mailboxes_collection.update_one(
            {"mailbox_id": mailbox_id},
            {"$set": updates}
        )
        
        return is_paused, pause_reason
    
    def pause_mailbox(
        self,
        mailbox_id: str,
        reason: str,
        duration_hours: int = 4
    ) -> bool:
        """
        Manually pause a mailbox.
        
        Args:
            mailbox_id: Mailbox to pause
            reason: Reason for pausing
            duration_hours: Hours to pause
            
        Returns:
            True if successful
        """
        result = self.mailboxes_collection.update_one(
            {"mailbox_id": mailbox_id},
            {"$set": {
                "health_status": MailboxHealth.PAUSED.value,
                "paused_until": datetime.utcnow() + timedelta(hours=duration_hours),
                "pause_reason": reason,
                "updated_at": datetime.utcnow()
            }}
        )
        
        logger.info(f"Paused mailbox {mailbox_id} for {duration_hours}h: {reason}")
        return result.modified_count > 0
    
    def resume_mailbox(self, mailbox_id: str) -> bool:
        """
        Resume a paused mailbox.
        
        Args:
            mailbox_id: Mailbox to resume
            
        Returns:
            True if successful
        """
        result = self.mailboxes_collection.update_one(
            {"mailbox_id": mailbox_id},
            {"$set": {
                "health_status": MailboxHealth.HEALTHY.value,
                "paused_until": None,
                "pause_reason": None,
                "updated_at": datetime.utcnow()
            }}
        )
        
        logger.info(f"Resumed mailbox {mailbox_id}")
        return result.modified_count > 0
    
    # ============== SIGNATURE MANAGEMENT ==============
    
    def get_mailbox_signature(
        self,
        mailbox_id: str,
        format: str = "html"
    ) -> str:
        """
        Get dynamic signature for mailbox.
        
        Signature is pulled from profile settings, NOT hardcoded in template.
        
        Args:
            mailbox_id: Mailbox to get signature for
            format: "html" or "plain"
            
        Returns:
            Signature string
        """
        mailbox = self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
        if not mailbox:
            return ""
        
        # First try mailbox-specific signature
        if format == "html":
            sig = mailbox.get("signature_html", "")
        else:
            sig = mailbox.get("signature_plain", "")
        
        if sig:
            return sig
        
        # Fall back to profile signature if linked
        email_address = mailbox.get("email_address")
        if email_address:
            profile = self.profiles_collection.find_one({"email": email_address})
            if profile:
                if format == "html":
                    return profile.get("email_signature_html", profile.get("email_signature", ""))
                else:
                    return profile.get("email_signature_plain", profile.get("email_signature", ""))
        
        return ""
    
    def update_mailbox_signature(
        self,
        mailbox_id: str,
        signature_html: str,
        signature_plain: Optional[str] = None
    ) -> bool:
        """
        Update signature for a mailbox.
        
        Args:
            mailbox_id: Mailbox to update
            signature_html: HTML signature
            signature_plain: Plain text signature (auto-generated if not provided)
            
        Returns:
            True if successful
        """
        if not signature_plain:
            # Generate plain text from HTML
            import re
            signature_plain = re.sub(r'<[^>]+>', '', signature_html)
            signature_plain = signature_plain.replace('&nbsp;', ' ')
        
        result = self.mailboxes_collection.update_one(
            {"mailbox_id": mailbox_id},
            {"$set": {
                "signature_html": signature_html,
                "signature_plain": signature_plain,
                "updated_at": datetime.utcnow()
            }}
        )
        
        return result.modified_count > 0
    
    # ============== MAILBOX CRUD ==============
    
    def create_mailbox(self, mailbox: Mailbox) -> str:
        """
        Create a new mailbox.
        
        Args:
            mailbox: Mailbox model
            
        Returns:
            Created mailbox ID
        """
        data = mailbox.model_dump()
        data["created_at"] = datetime.utcnow()
        data["updated_at"] = datetime.utcnow()
        
        self.mailboxes_collection.insert_one(data)
        logger.info(f"Created mailbox {mailbox.mailbox_id}")
        
        return mailbox.mailbox_id
    
    def get_mailbox(self, mailbox_id: str) -> Optional[Dict[str, Any]]:
        """Get mailbox by ID"""
        return self.mailboxes_collection.find_one({"mailbox_id": mailbox_id})
    
    def list_mailboxes(
        self,
        active_only: bool = True,
        healthy_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List mailboxes with filters.
        
        Args:
            active_only: Only return active mailboxes
            healthy_only: Only return healthy mailboxes
            
        Returns:
            List of mailbox documents
        """
        query: Dict[str, Any] = {}
        
        if active_only:
            query["is_active"] = True
        
        if healthy_only:
            query["health_status"] = MailboxHealth.HEALTHY.value
        
        return list(self.mailboxes_collection.find(query))
    
    def get_mailbox_stats(self, mailbox_id: str) -> Dict[str, Any]:
        """
        Get statistics for a mailbox.
        
        Returns:
            Dictionary with mailbox stats
        """
        mailbox = self.get_mailbox(mailbox_id)
        if not mailbox:
            return {}
        
        # Count active assignments
        active_leads = self.leads_collection.count_documents({
            "assigned_mailbox_id": mailbox_id,
            "workflow_status": "in_progress"
        })
        
        # Get send counts from today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        sends_collection = self.db["outreach_sends_v2"]
        
        today_sends = sends_collection.count_documents({
            "mailbox_id": mailbox_id,
            "sent_at": {"$gte": today_start}
        })
        
        return {
            "mailbox_id": mailbox_id,
            "email_address": mailbox.get("email_address"),
            "health_status": mailbox.get("health_status"),
            "daily_send_count": mailbox.get("daily_send_count", 0),
            "daily_send_limit": mailbox.get("daily_send_limit", 400),
            "hourly_send_count": mailbox.get("hourly_send_count", 0),
            "hourly_send_limit": mailbox.get("hourly_send_limit", 60),
            "active_leads_assigned": active_leads,
            "sends_today": today_sends,
            "bounce_rate_24h": mailbox.get("bounce_rate_24h", 0),
            "warmup_status": mailbox.get("warmup_status"),
            "is_paused": mailbox.get("paused_until") is not None and mailbox.get("paused_until") > datetime.utcnow(),
        }
