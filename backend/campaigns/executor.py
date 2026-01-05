"""
CAMPAIGN SEQUENCE EXECUTOR
==========================

Background worker that executes campaign email sequences.

Features:
- Processes scheduled sends from the queue
- Handles rate limiting per mailbox
- Detects and classifies replies
- Updates recipient status based on engagement
- Integrates with Gmail/IMAP for sending

Usage:
    executor = CampaignExecutor(db)
    executor.start()  # Starts background processing
"""

import os
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from pymongo import MongoClient
from bson import ObjectId

from .models import (
    CampaignManager,
    CampaignStatus,
    RecipientStatus,
    SendStatus,
    ReplyType
)
from .email_safety import (
    check_kill_switch,
    EmailKillSwitchActiveError,
    is_dry_run_mode,
    DISABLE_EMAIL_SENDING
)

logger = logging.getLogger(__name__)


class CampaignExecutor:
    """
    Background worker for executing campaign sequences.
    
    Responsibilities:
    1. Process scheduled sends
    2. Render email templates
    3. Send via Gmail API or SMTP
    4. Track delivery and engagement
    5. Detect and classify replies
    6. Update recipient status
    """
    
    def __init__(
        self,
        db: MongoClient,
        send_function: Optional[Callable] = None,
        poll_interval: int = 30
    ):
        """
        Initialize executor.
        
        Args:
            db: MongoDB database instance
            send_function: Function to actually send emails. 
                          Signature: (to, subject, body_html, body_plain, from_email, reply_to) -> message_id
            poll_interval: Seconds between poll cycles
        """
        self.db = db
        self.manager = CampaignManager(db)
        self.send_function = send_function or self._default_send
        self.poll_interval = poll_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Rate limiting
        self._mailbox_last_send: Dict[str, datetime] = {}
        self._hourly_sends: Dict[str, List[datetime]] = {}
    
    def start(self):
        """Start the executor thread"""
        if self._running:
            logger.warning("CampaignExecutor already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("CampaignExecutor started")
    
    def stop(self):
        """Stop the executor thread"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("CampaignExecutor stopped")
    
    def _run_loop(self):
        """Main processing loop"""
        while self._running and not self._stop_event.is_set():
            try:
                # Process active campaigns
                self._process_campaigns()
                
                # Process reply detection
                self._detect_replies()
                
                # Wait for next cycle
                self._stop_event.wait(self.poll_interval)
                
            except Exception as e:
                logger.error(f"CampaignExecutor error: {e}", exc_info=True)
                time.sleep(5)  # Brief pause on error
    
    def _process_campaigns(self):
        """Process all active campaigns"""
        active_campaigns = self.db["campaigns"].find({
            "status": CampaignStatus.ACTIVE.value
        })
        
        for campaign in active_campaigns:
            campaign_id = str(campaign["_id"])
            try:
                # Schedule next sends
                self.manager.schedule_next_sends(campaign_id)
                
                # Process send queue
                self._process_send_queue(campaign)
                
            except Exception as e:
                logger.error(f"Error processing campaign {campaign_id}: {e}")
    
    def _process_send_queue(self, campaign: Dict):
        """Process sends for a campaign"""
        campaign_id = str(campaign["_id"])
        mailbox_id = campaign["from_mailbox_id"]
        settings = campaign.get("settings", {})
        
        # Check rate limits
        if not self._can_send(mailbox_id, settings):
            return
        
        # Get pending sends
        pending_sends = list(self.db["campaign_sends"].find({
            "campaign_id": campaign_id,
            "status": SendStatus.QUEUED.value,
            "scheduled_at": {"$lte": datetime.utcnow()}
        }).limit(settings.get("hourly_send_limit", 20)))
        
        for send in pending_sends:
            if not self._can_send(mailbox_id, settings):
                break
            
            self._execute_send(send, campaign)
            
            # Delay between sends
            min_delay = settings.get("min_delay_between_sends_seconds", 60)
            time.sleep(min_delay)
    
    def _can_send(self, mailbox_id: str, settings: Dict) -> bool:
        """Check if we can send from this mailbox"""
        now = datetime.utcnow()
        
        # Check hourly limit
        if mailbox_id not in self._hourly_sends:
            self._hourly_sends[mailbox_id] = []
        
        # Clean old entries
        hour_ago = now - timedelta(hours=1)
        self._hourly_sends[mailbox_id] = [
            t for t in self._hourly_sends[mailbox_id] if t > hour_ago
        ]
        
        hourly_limit = settings.get("hourly_send_limit", 20)
        if len(self._hourly_sends[mailbox_id]) >= hourly_limit:
            return False
        
        # Check send hours
        send_hours_start = settings.get("send_hours_start", 9)
        send_hours_end = settings.get("send_hours_end", 17)
        current_hour = now.hour
        
        if current_hour < send_hours_start or current_hour >= send_hours_end:
            return False
        
        # Check send days
        send_days = settings.get("send_days", [0, 1, 2, 3, 4])
        if now.weekday() not in send_days:
            return False
        
        return True
    
    def _execute_send(self, send: Dict, campaign: Dict):
        """Execute a single send"""
        send_id = str(send["_id"])
        recipient_id = send["recipient_id"]
        
        try:
            # SAFETY: Check kill switch first
            if DISABLE_EMAIL_SENDING:
                logger.warning(f"[KILL SWITCH] Email sending blocked for send {send_id}")
                self.db["campaign_sends"].update_one(
                    {"_id": send["_id"]},
                    {"$set": {"status": SendStatus.QUEUED.value, "error_message": "Email sending disabled via kill switch"}}
                )
                return
            
            # SAFETY: Check dry-run mode
            if is_dry_run_mode():
                recipient = self.manager.get_recipient(recipient_id)
                email = recipient.get("email", "unknown") if recipient else "unknown"
                logger.info(f"[DRY RUN] Would send to {email} (send_id: {send_id})")
                self.db["campaign_sends"].update_one(
                    {"_id": send["_id"]},
                    {"$set": {"status": SendStatus.SENT.value, "sent_at": datetime.utcnow(), "dry_run": True}}
                )
                return
            
            # Mark as sending
            self.db["campaign_sends"].update_one(
                {"_id": send["_id"]},
                {"$set": {"status": SendStatus.SENDING.value, "queued_at": datetime.utcnow()}}
            )
            
            # Get recipient
            recipient = self.manager.get_recipient(recipient_id)
            if not recipient:
                raise ValueError(f"Recipient {recipient_id} not found")
            
            # Build variables for template
            variables = {
                "first_name": recipient.get("first_name", ""),
                "last_name": recipient.get("last_name", ""),
                "company": recipient.get("company", ""),
                "title": recipient.get("title", ""),
                "email": recipient.get("email", ""),
                **recipient.get("custom_variables", {})
            }
            
            # Render template
            rendered = self.manager.render_template(send["template_id"], variables)
            
            # Add unsubscribe link if configured
            settings = campaign.get("settings", {})
            if settings.get("include_unsubscribe_link", True):
                unsubscribe_link = self._generate_unsubscribe_link(
                    campaign["_id"], recipient_id
                )
                rendered["body_html"] += f'\n<p style="font-size:11px;color:#666;">{settings.get("unsubscribe_text", "Unsubscribe")}: <a href="{unsubscribe_link}">Click here</a></p>'
            
            # Send email
            message_id = self.send_function(
                to=recipient["email"],
                subject=rendered["subject"],
                body_html=rendered["body_html"],
                body_plain=rendered["body_plain"],
                from_email=campaign["from_email"],
                from_name=campaign.get("from_name"),
                reply_to=campaign.get("reply_to")
            )
            
            # Update send record
            self.db["campaign_sends"].update_one(
                {"_id": send["_id"]},
                {
                    "$set": {
                        "status": SendStatus.SENT.value,
                        "sent_at": datetime.utcnow(),
                        "subject": rendered["subject"],
                        "provider_message_id": message_id
                    }
                }
            )
            
            # Track for rate limiting
            mailbox_id = campaign["from_mailbox_id"]
            self._mailbox_last_send[mailbox_id] = datetime.utcnow()
            self._hourly_sends.setdefault(mailbox_id, []).append(datetime.utcnow())
            
            logger.info(f"Sent campaign email to {recipient['email']}")
            
        except Exception as e:
            logger.error(f"Failed to send {send_id}: {e}")
            
            # Update with error
            retry_count = send.get("retry_count", 0) + 1
            new_status = SendStatus.QUEUED.value if retry_count < 3 else SendStatus.FAILED.value
            
            self.db["campaign_sends"].update_one(
                {"_id": send["_id"]},
                {
                    "$set": {
                        "status": new_status,
                        "error_message": str(e),
                        "retry_count": retry_count
                    }
                }
            )
    
    def _detect_replies(self):
        """Detect replies to campaign emails"""
        # Get recently sent emails that haven't been checked for replies
        recent_sends = self.db["campaign_sends"].find({
            "status": {"$in": [SendStatus.SENT.value, SendStatus.DELIVERED.value, SendStatus.OPENED.value]},
            "sent_at": {"$gte": datetime.utcnow() - timedelta(days=7)},
            "replied_at": {"$exists": False}
        }).limit(100)
        
        for send in recent_sends:
            self._check_for_reply(send)
    
    def _check_for_reply(self, send: Dict):
        """Check if there's a reply to a specific send"""
        to_email = send["to_email"]
        sent_at = send["sent_at"]
        campaign_id = send["campaign_id"]
        
        # Get campaign to know the from_email
        campaign = self.manager.get_campaign(campaign_id)
        if not campaign:
            return
        
        from_email = campaign["from_email"]
        
        # Look for inbound emails from recipient to our mailbox after send time
        reply = self.db["emails"].find_one({
            "from_address.email": to_email,
            "to_addresses.email": from_email,
            "timestamp": {"$gt": sent_at},
            "direction": "inbound"
        }, sort=[("timestamp", 1)])
        
        if reply:
            # Classify the reply
            reply_type = self._classify_reply(reply)
            
            # Update send record
            self.db["campaign_sends"].update_one(
                {"_id": send["_id"]},
                {
                    "$set": {
                        "status": SendStatus.REPLIED.value,
                        "replied_at": reply["timestamp"],
                        "reply_email_id": str(reply["_id"])
                    }
                }
            )
            
            # Update recipient status
            self.manager.update_recipient_status(
                send["recipient_id"],
                RecipientStatus.REPLIED,
                reply_type=reply_type,
                reply_email_id=str(reply["_id"])
            )
            
            # If interested, update to interested status
            if reply_type == ReplyType.INTERESTED:
                self.manager.update_recipient_status(
                    send["recipient_id"],
                    RecipientStatus.INTERESTED
                )
            
            logger.info(f"Detected reply from {to_email}, type: {reply_type}")
    
    def _classify_reply(self, email: Dict) -> ReplyType:
        """Classify a reply email"""
        subject = (email.get("subject") or "").lower()
        body = (email.get("body_plain") or email.get("snippet") or "")[:500].lower()
        content = f"{subject} {body}"
        
        # Out of Office
        ooo_indicators = [
            "out of office", "away from office", "automatic reply",
            "on vacation", "currently unavailable", "autoresponder"
        ]
        if any(ind in content for ind in ooo_indicators):
            return ReplyType.OUT_OF_OFFICE
        
        # Bounce
        bounce_indicators = [
            "delivery failed", "undeliverable", "mail delivery failed",
            "returned mail", "550 ", "recipient rejected"
        ]
        if any(ind in content for ind in bounce_indicators):
            return ReplyType.BOUNCE
        
        # Unsubscribe
        unsub_indicators = [
            "unsubscribe", "remove me", "stop emailing", "opt out",
            "do not contact", "take me off"
        ]
        if any(ind in content for ind in unsub_indicators):
            return ReplyType.UNSUBSCRIBE
        
        # Not Interested
        not_interested_indicators = [
            "not interested", "no thanks", "no thank you", "not looking",
            "not a good fit", "pass on this", "not for us", "already have"
        ]
        if any(ind in content for ind in not_interested_indicators):
            return ReplyType.NOT_INTERESTED
        
        # Interested indicators
        interested_indicators = [
            "interested", "tell me more", "learn more", "schedule a call",
            "set up a meeting", "demo", "pricing", "quote", "sounds good",
            "let's talk", "available", "free time", "calendar"
        ]
        if any(ind in content for ind in interested_indicators):
            return ReplyType.INTERESTED
        
        # Meeting booked
        meeting_indicators = [
            "calendar invite", "meeting confirmed", "see you", "looking forward",
            "booked", "scheduled for"
        ]
        if any(ind in content for ind in meeting_indicators):
            return ReplyType.MEETING_BOOKED
        
        # Default - needs manual review
        return ReplyType.OTHER
    
    def _generate_unsubscribe_link(self, campaign_id: str, recipient_id: str) -> str:
        """Generate unsubscribe link"""
        # In production, this would be a proper tracking URL
        base_url = os.getenv("APP_BASE_URL", "http://localhost:8000")
        return f"{base_url}/api/campaigns/unsubscribe/{campaign_id}/{recipient_id}"
    
    def _default_send(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_plain: str,
        from_email: str,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> str:
        """Default send function - logs but doesn't actually send"""
        logger.warning(f"[DRY RUN] Would send email to {to}: {subject}")
        return f"dry-run-{datetime.utcnow().timestamp()}"


class ReplyClassifierWorker:
    """
    Worker that uses AI to classify replies more accurately.
    
    Runs periodically to re-classify replies that were marked as "OTHER"
    using the AI classifier for better accuracy.
    """
    
    def __init__(
        self,
        db: MongoClient,
        poll_interval: int = 300  # 5 minutes
    ):
        """
        Initialize reply classifier worker.
        
        Args:
            db: MongoDB database instance
            poll_interval: Seconds between poll cycles
        """
        self.db = db
        self.poll_interval = poll_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def start(self):
        """Start the worker thread"""
        if self._running:
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("ReplyClassifierWorker started")
    
    def stop(self):
        """Stop the worker thread"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("ReplyClassifierWorker stopped")
    
    def _run_loop(self):
        """Main processing loop"""
        while self._running and not self._stop_event.is_set():
            try:
                self._classify_pending_replies()
                self._stop_event.wait(self.poll_interval)
            except Exception as e:
                logger.error(f"ReplyClassifierWorker error: {e}", exc_info=True)
                time.sleep(30)
    
    def _classify_pending_replies(self):
        """Find and classify replies marked as OTHER"""
        # Find recipients with unclassified replies
        recipients = self.db["campaign_recipients"].find({
            "reply_type": ReplyType.OTHER.value,
            "ai_classification_attempted": {"$ne": True}
        }).limit(20)
        
        for recipient in recipients:
            reply_email_id = recipient.get("reply_email_id")
            if not reply_email_id:
                continue
            
            # Get the reply email
            email = self.db["emails"].find_one({"_id": ObjectId(reply_email_id)})
            if not email:
                continue
            
            # Classify using AI
            reply_type = self._classify_with_ai(email)
            
            # Update recipient
            self.db["campaign_recipients"].update_one(
                {"_id": recipient["_id"]},
                {
                    "$set": {
                        "reply_type": reply_type.value,
                        "ai_classification_attempted": True,
                        "ai_classified_at": datetime.utcnow()
                    }
                }
            )
            
            # Update status if interested
            if reply_type == ReplyType.INTERESTED:
                self.db["campaign_recipients"].update_one(
                    {"_id": recipient["_id"]},
                    {"$set": {"status": RecipientStatus.INTERESTED.value}}
                )
    
    def _classify_with_ai(self, email: Dict) -> ReplyType:
        """Classify a reply using AI"""
        try:
            from ..leads.openai_wrapper import chat_completion
            
            subject = email.get("subject", "")
            body = (email.get("body_plain") or email.get("snippet") or "")[:1000]
            
            prompt = f"""Classify this email reply to a sales outreach.

Subject: {subject}
Body: {body}

Categories:
- interested: Wants to learn more, schedule a call, get pricing
- not_interested: Politely declining, not a fit, already has solution
- out_of_office: Auto-reply about being away
- bounce: Delivery failure
- unsubscribe: Wants to stop receiving emails
- meeting_booked: Confirming a meeting
- referred: Referring to someone else
- other: Doesn't fit other categories

Respond with JSON only:
{{"reply_type": "<category>", "confidence": 0.0-1.0, "reason": "brief explanation"}}"""

            result = chat_completion(
                messages=[
                    {"role": "system", "content": "You are an expert at classifying sales email replies."},
                    {"role": "user", "content": prompt}
                ],
                source="background",
                endpoint="reply_classification",
                max_output_tokens=100,
                response_format={"type": "json_object"}
            )
            
            if result["success"]:
                import json
                parsed = json.loads(result["content"])
                reply_type_str = parsed.get("reply_type", "other")
                
                # Map to enum
                type_map = {
                    "interested": ReplyType.INTERESTED,
                    "not_interested": ReplyType.NOT_INTERESTED,
                    "out_of_office": ReplyType.OUT_OF_OFFICE,
                    "bounce": ReplyType.BOUNCE,
                    "unsubscribe": ReplyType.UNSUBSCRIBE,
                    "meeting_booked": ReplyType.MEETING_BOOKED,
                    "referred": ReplyType.REFERRED,
                    "auto_reply": ReplyType.AUTO_REPLY
                }
                
                return type_map.get(reply_type_str, ReplyType.OTHER)
            
        except Exception as e:
            logger.warning(f"AI reply classification failed: {e}")
        
        return ReplyType.OTHER


class CampaignWorkerManager:
    """
    Manages all campaign-related workers.
    """
    
    def __init__(self, db: MongoClient, send_function: Optional[Callable] = None):
        """
        Initialize worker manager.
        
        Args:
            db: MongoDB database instance
            send_function: Function to send emails
        """
        self.db = db
        self.executor = CampaignExecutor(db, send_function)
        self.reply_classifier = ReplyClassifierWorker(db)
    
    def start_all(self):
        """Start all workers"""
        logger.info("Starting campaign workers")
        self.executor.start()
        self.reply_classifier.start()
    
    def stop_all(self):
        """Stop all workers"""
        logger.info("Stopping campaign workers")
        self.executor.stop()
        self.reply_classifier.stop()
    
    def get_status(self) -> Dict[str, bool]:
        """Get status of all workers"""
        return {
            "executor": self.executor._running,
            "reply_classifier": self.reply_classifier._running
        }
