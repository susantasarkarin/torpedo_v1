"""
MULTI-CHANNEL SEQUENCE EXECUTOR
================================

Executes campaign sequences across multiple channels (Email + LinkedIn).

Features:
- Routes steps to appropriate channel handlers
- Manages channel-specific delays and constraints
- Tracks multi-channel engagement events
- Integrates with LinkedIn automation service
- Handles connection acceptance before messaging on LinkedIn
- Monitors channel-specific rate limits
- Maintains unified lead engagement history

Usage:
    executor = MultiChannelExecutor(db, linkedin_service)
    result = await executor.execute_step(step, recipient, campaign)
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, Callable
from enum import Enum
from pymongo import MongoClient
from bson import ObjectId

from .models import (
    CampaignManager,
    RecipientStatus,
    SendStatus
)

logger = logging.getLogger(__name__)


class ChannelType(str, Enum):
    """Channel types for multi-channel sequences"""
    EMAIL = "email"
    LINKEDIN = "linkedin"


class LinkedInActionType(str, Enum):
    """LinkedIn-specific action types"""
    CONNECTION_REQUEST = "connection_request"
    MESSAGE = "message"
    PROFILE_VIEW = "profile_view"


class ChannelStatus(str, Enum):
    """Status of channel-specific sends"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    WAITING_FOR_CONNECTION = "waiting_for_connection"
    CONNECTION_REJECTED = "connection_rejected"


class MultiChannelExecutor:
    """
    Executes campaign sequences across multiple channels.
    
    Responsibilities:
    1. Route steps to appropriate channel
    2. Apply channel-specific delays and constraints
    3. Track engagement events per channel
    4. Manage LinkedIn-specific flows (connection acceptance before message)
    5. Handle channel-specific errors and retries
    """
    
    def __init__(
        self,
        db: MongoClient,
        linkedin_service: Optional[Any] = None,
        email_send_function: Optional[Callable] = None
    ):
        """
        Initialize multi-channel executor.
        
        Args:
            db: MongoDB database instance
            linkedin_service: LinkedInAutomationService instance for automation
            email_send_function: Function to send emails
        """
        self.db = db
        self.manager = CampaignManager(db)
        self.linkedin_service = linkedin_service
        self.email_send_function = email_send_function
        
        # Channel-specific rate limits
        self._linkedin_activity: Dict[str, Dict] = {}
        self._email_hourly_sends: Dict[str, List[datetime]] = {}
    
    async def execute_step(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict,
        campaign_manager: Optional[CampaignManager] = None
    ) -> Dict[str, Any]:
        """
        Execute a campaign step across the specified channel.
        
        Args:
            step: Campaign step configuration
            recipient: Recipient/lead data
            campaign: Campaign configuration
            campaign_manager: Optional campaign manager instance
            
        Returns:
            Execution result with status, channel, message_id, etc.
        """
        if campaign_manager:
            self.manager = campaign_manager
        
        channel = step.get("channel", "email").lower()
        
        try:
            if channel == ChannelType.EMAIL.value:
                return await self._execute_email_step(step, recipient, campaign)
            elif channel == ChannelType.LINKEDIN.value:
                return await self._execute_linkedin_step(step, recipient, campaign)
            else:
                logger.warning(f"Unknown channel: {channel}")
                return {
                    "success": False,
                    "channel": channel,
                    "error": f"Unknown channel: {channel}"
                }
        
        except Exception as e:
            logger.error(f"Error executing {channel} step: {e}", exc_info=True)
            return {
                "success": False,
                "channel": channel,
                "error": str(e)
            }
    
    async def _execute_email_step(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict
    ) -> Dict[str, Any]:
        """
        Execute an email campaign step.
        
        Args:
            step: Email step configuration
            recipient: Recipient data
            campaign: Campaign configuration
            
        Returns:
            Execution result
        """
        step_id = str(step.get("_id", ""))
        recipient_id = str(recipient.get("_id", ""))
        
        try:
            # Render template
            variables = self._build_template_variables(recipient, campaign)
            rendered = self.manager.render_template(step["template_id"], variables)
            
            # Add unsubscribe link if configured
            settings = campaign.get("settings", {})
            if settings.get("include_unsubscribe_link", True):
                unsubscribe_link = self._generate_unsubscribe_link(
                    str(campaign["_id"]), recipient_id
                )
                rendered["body_html"] += (
                    f'\n<p style="font-size:11px;color:#666;">'
                    f'{settings.get("unsubscribe_text", "Unsubscribe")}: '
                    f'<a href="{unsubscribe_link}">Click here</a></p>'
                )
            
            # Send email
            message_id = await self._send_email(
                to=recipient["email"],
                subject=rendered["subject"],
                body_html=rendered["body_html"],
                body_plain=rendered["body_plain"],
                from_email=campaign["from_email"],
                from_name=campaign.get("from_name"),
                reply_to=campaign.get("reply_to")
            )
            
            # Record send
            send_record = {
                "campaign_id": str(campaign["_id"]),
                "step_id": step_id,
                "recipient_id": recipient_id,
                "channel": ChannelType.EMAIL.value,
                "to_email": recipient["email"],
                "subject": rendered["subject"],
                "status": SendStatus.SENT.value,
                "sent_at": datetime.utcnow(),
                "provider_message_id": message_id,
                "from_email": campaign["from_email"]
            }
            
            result = self.db["campaign_sends"].insert_one(send_record)
            
            logger.info(
                f"Email sent to {recipient['email']} "
                f"(campaign: {campaign['_id']}, step: {step_id})"
            )
            
            # Track for rate limiting
            mailbox_id = campaign.get("from_mailbox_id", "default")
            self._email_hourly_sends.setdefault(mailbox_id, []).append(datetime.utcnow())
            
            return {
                "success": True,
                "channel": ChannelType.EMAIL.value,
                "message_id": str(result.inserted_id),
                "provider_message_id": message_id,
                "timestamp": datetime.utcnow()
            }
        
        except Exception as e:
            logger.error(f"Email send failed for recipient {recipient_id}: {e}")
            return {
                "success": False,
                "channel": ChannelType.EMAIL.value,
                "error": str(e)
            }
    
    async def _execute_linkedin_step(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict
    ) -> Dict[str, Any]:
        """
        Execute a LinkedIn campaign step.
        
        Handles both connection requests and messages, with proper
        sequencing (connection must be accepted before messaging).
        
        Args:
            step: LinkedIn step configuration
            recipient: Recipient data (must include linkedin_url)
            campaign: Campaign configuration
            
        Returns:
            Execution result
        """
        if not self.linkedin_service:
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "LinkedIn service not configured"
            }
        
        step_id = str(step.get("_id", ""))
        recipient_id = str(recipient.get("_id", ""))
        linkedin_url = recipient.get("linkedin_url")
        
        if not linkedin_url:
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "Recipient missing linkedin_url"
            }
        
        action_type = step.get("linkedin_action_type", LinkedInActionType.CONNECTION_REQUEST.value)
        
        try:
            if action_type == LinkedInActionType.CONNECTION_REQUEST.value:
                return await self._send_connection_request(
                    step, recipient, campaign, linkedin_url, step_id, recipient_id
                )
            
            elif action_type == LinkedInActionType.MESSAGE.value:
                return await self._send_linkedin_message(
                    step, recipient, campaign, linkedin_url, step_id, recipient_id
                )
            
            elif action_type == LinkedInActionType.PROFILE_VIEW.value:
                return await self._view_linkedin_profile(
                    step, recipient, campaign, linkedin_url, step_id, recipient_id
                )
            
            else:
                return {
                    "success": False,
                    "channel": ChannelType.LINKEDIN.value,
                    "error": f"Unknown LinkedIn action: {action_type}"
                }
        
        except Exception as e:
            logger.error(
                f"LinkedIn {action_type} failed for recipient {recipient_id}: {e}",
                exc_info=True
            )
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": str(e)
            }
    
    async def _send_connection_request(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict,
        linkedin_url: str,
        step_id: str,
        recipient_id: str
    ) -> Dict[str, Any]:
        """Send a LinkedIn connection request."""
        
        # Check if already connected or request pending
        existing = self.db["linkedin_connections"].find_one({
            "recipient_id": recipient_id,
            "status": {"$in": ["pending", "accepted"]}
        })
        
        if existing:
            return {
                "success": True,
                "channel": ChannelType.LINKEDIN.value,
                "action": "connection_request",
                "status": "already_pending",
                "message": f"Connection already {existing['status']}"
            }
        
        # Prepare connection note from step
        connection_note = step.get("connection_note", "")
        if connection_note:
            # Render variables in note
            variables = self._build_template_variables(recipient, campaign)
            connection_note = self._render_text(connection_note, variables)
        
        # Check rate limits
        session_id = campaign.get("linkedin_session_id", "default")
        if not await self._check_linkedin_rate_limit(session_id, "connections"):
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "LinkedIn daily connection request limit reached"
            }
        
        try:
            # Send connection request via LinkedIn service
            result = await self.linkedin_service.send_connection_request(
                linkedin_url=linkedin_url,
                connection_note=connection_note
            )
            
            if result.get("success"):
                # Record connection attempt
                conn_record = {
                    "recipient_id": recipient_id,
                    "campaign_id": str(campaign["_id"]),
                    "step_id": step_id,
                    "linkedin_url": linkedin_url,
                    "status": "pending",
                    "connection_note": connection_note,
                    "sent_at": datetime.utcnow(),
                    "action_result": result
                }
                conn_result = self.db["linkedin_connections"].insert_one(conn_record)
                
                logger.info(
                    f"LinkedIn connection request sent to {linkedin_url} "
                    f"(recipient: {recipient_id})"
                )
                
                return {
                    "success": True,
                    "channel": ChannelType.LINKEDIN.value,
                    "action": "connection_request",
                    "message_id": str(conn_result.inserted_id),
                    "timestamp": datetime.utcnow()
                }
            else:
                return {
                    "success": False,
                    "channel": ChannelType.LINKEDIN.value,
                    "error": result.get("error", "Connection request failed")
                }
        
        except Exception as e:
            logger.error(f"Connection request failed: {e}")
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": str(e)
            }
    
    async def _send_linkedin_message(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict,
        linkedin_url: str,
        step_id: str,
        recipient_id: str
    ) -> Dict[str, Any]:
        """Send a LinkedIn message (only if connected)."""
        
        # Check if connected
        connection = self.db["linkedin_connections"].find_one({
            "recipient_id": recipient_id,
            "campaign_id": str(campaign["_id"])
        })
        
        if not connection:
            # No prior connection attempt
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "status": ChannelStatus.WAITING_FOR_CONNECTION.value,
                "error": "No connection found. Send connection request first."
            }
        
        if connection.get("status") == "rejected":
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "status": ChannelStatus.CONNECTION_REJECTED.value,
                "error": "Connection request was rejected"
            }
        
        if connection.get("status") != "accepted":
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "status": ChannelStatus.WAITING_FOR_CONNECTION.value,
                "error": f"Connection not yet accepted (status: {connection.get('status')})"
            }
        
        # Prepare message
        message_template = step.get("message_template", step.get("template_id"))
        if message_template and isinstance(message_template, str):
            # It's a template ID - render it
            try:
                variables = self._build_template_variables(recipient, campaign)
                rendered = self.manager.render_template(message_template, variables)
                message_content = rendered.get("body_plain", rendered.get("body_html", ""))
            except Exception as e:
                logger.warning(f"Failed to render message template: {e}")
                message_content = step.get("message_content", "")
        else:
            # Direct message content
            message_content = step.get("message_content", "")
        
        if not message_content:
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "No message content provided"
            }
        
        # Render variables in message
        variables = self._build_template_variables(recipient, campaign)
        message_content = self._render_text(message_content, variables)
        
        # Check rate limits
        session_id = campaign.get("linkedin_session_id", "default")
        if not await self._check_linkedin_rate_limit(session_id, "messages"):
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "LinkedIn daily message limit reached"
            }
        
        try:
            # Send message via LinkedIn service
            result = await self.linkedin_service.send_message(
                linkedin_url=linkedin_url,
                message_content=message_content
            )
            
            if result.get("success"):
                # Record message
                msg_record = {
                    "recipient_id": recipient_id,
                    "campaign_id": str(campaign["_id"]),
                    "step_id": step_id,
                    "connection_id": str(connection["_id"]),
                    "linkedin_url": linkedin_url,
                    "message_content": message_content,
                    "sent_at": datetime.utcnow(),
                    "action_result": result
                }
                msg_result = self.db["linkedin_messages"].insert_one(msg_record)
                
                logger.info(
                    f"LinkedIn message sent to {linkedin_url} "
                    f"(recipient: {recipient_id})"
                )
                
                return {
                    "success": True,
                    "channel": ChannelType.LINKEDIN.value,
                    "action": "message",
                    "message_id": str(msg_result.inserted_id),
                    "timestamp": datetime.utcnow()
                }
            else:
                return {
                    "success": False,
                    "channel": ChannelType.LINKEDIN.value,
                    "error": result.get("error", "Message send failed")
                }
        
        except Exception as e:
            logger.error(f"Message send failed: {e}")
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": str(e)
            }
    
    async def _view_linkedin_profile(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict,
        linkedin_url: str,
        step_id: str,
        recipient_id: str
    ) -> Dict[str, Any]:
        """View a LinkedIn profile (simple engagement action)."""
        
        if not self.linkedin_service:
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": "LinkedIn service not configured"
            }
        
        try:
            # View profile
            result = await self.linkedin_service.view_profile(linkedin_url)
            
            if result.get("success"):
                # Record view
                view_record = {
                    "recipient_id": recipient_id,
                    "campaign_id": str(campaign["_id"]),
                    "step_id": step_id,
                    "linkedin_url": linkedin_url,
                    "viewed_at": datetime.utcnow(),
                    "action_result": result
                }
                view_result = self.db["linkedin_profile_views"].insert_one(view_record)
                
                logger.info(
                    f"LinkedIn profile viewed: {linkedin_url} "
                    f"(recipient: {recipient_id})"
                )
                
                return {
                    "success": True,
                    "channel": ChannelType.LINKEDIN.value,
                    "action": "profile_view",
                    "message_id": str(view_result.inserted_id),
                    "timestamp": datetime.utcnow()
                }
            else:
                return {
                    "success": False,
                    "channel": ChannelType.LINKEDIN.value,
                    "error": result.get("error", "Profile view failed")
                }
        
        except Exception as e:
            logger.error(f"Profile view failed: {e}")
            return {
                "success": False,
                "channel": ChannelType.LINKEDIN.value,
                "error": str(e)
            }
    
    async def check_linkedin_connection_status(
        self,
        recipient_id: str,
        campaign_id: str
    ) -> str:
        """
        Check if a LinkedIn connection request has been accepted.
        
        Args:
            recipient_id: Recipient ID
            campaign_id: Campaign ID
            
        Returns:
            Status: 'pending', 'accepted', 'rejected', 'not_found'
        """
        connection = self.db["linkedin_connections"].find_one({
            "recipient_id": recipient_id,
            "campaign_id": campaign_id
        })
        
        if not connection:
            return "not_found"
        
        return connection.get("status", "unknown")
    
    async def _check_linkedin_rate_limit(
        self,
        session_id: str,
        action_type: str  # 'connections' or 'messages'
    ) -> bool:
        """
        Check if LinkedIn rate limit has been reached.
        
        Args:
            session_id: LinkedIn session ID
            action_type: Type of action
            
        Returns:
            True if action can be performed, False if limit reached
        """
        if not self.linkedin_service:
            return False
        
        try:
            # Get today's activity
            today = datetime.utcnow().date().isoformat()
            activity = self.db["linkedin_activity"].find_one({
                "session_id": session_id,
                "date": today
            })
            
            if not activity:
                return True  # No activity yet today, can proceed
            
            if action_type == "connections":
                count = activity.get("connections_sent", 0)
                limit = activity.get("daily_connection_limit", 100)
            elif action_type == "messages":
                count = activity.get("messages_sent", 0)
                limit = activity.get("daily_message_limit", 50)
            else:
                return False
            
            return count < limit
        
        except Exception as e:
            logger.warning(f"Error checking LinkedIn rate limit: {e}")
            return True  # Assume we can proceed on error
    
    def _build_template_variables(
        self,
        recipient: Dict,
        campaign: Dict
    ) -> Dict[str, str]:
        """Build template variables from recipient and campaign data."""
        return {
            "first_name": recipient.get("first_name", ""),
            "last_name": recipient.get("last_name", ""),
            "company": recipient.get("company", ""),
            "title": recipient.get("title", ""),
            "email": recipient.get("email", ""),
            "linkedin_url": recipient.get("linkedin_url", ""),
            **recipient.get("custom_variables", {})
        }
    
    def _render_text(self, text: str, variables: Dict[str, str]) -> str:
        """Render text with variable substitution using {{ }} syntax."""
        rendered = text
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value or ""))
        return rendered
    
    def _generate_unsubscribe_link(
        self,
        campaign_id: str,
        recipient_id: str
    ) -> str:
        """Generate unsubscribe link."""
        base_url = os.getenv("APP_BASE_URL", "http://localhost:8000")
        return f"{base_url}/api/campaigns/unsubscribe/{campaign_id}/{recipient_id}"
    
    async def _send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_plain: str,
        from_email: str,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> str:
        """Send email using configured send function or default."""
        if self.email_send_function:
            if asyncio.iscoroutinefunction(self.email_send_function):
                return await self.email_send_function(
                    to, subject, body_html, body_plain, from_email, from_name, reply_to
                )
            else:
                return self.email_send_function(
                    to, subject, body_html, body_plain, from_email, from_name, reply_to
                )
        else:
            # Default implementation
            logger.warning(f"[DRY RUN] Would send email to {to}: {subject}")
            return f"dry-run-{datetime.utcnow().timestamp()}"


class MultiChannelIntegration:
    """
    Integration helper to use MultiChannelExecutor with existing CampaignExecutor.
    
    This class provides methods to augment the existing executor with multi-channel
    capabilities without major refactoring.
    """
    
    def __init__(self, campaign_executor, multi_channel_executor):
        """Initialize integration."""
        self.campaign_executor = campaign_executor
        self.multi_channel_executor = multi_channel_executor
    
    async def execute_step_with_fallback(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict
    ) -> Dict[str, Any]:
        """
        Execute a step, automatically routing based on channel.
        Falls back to email if channel is not specified.
        
        Args:
            step: Campaign step
            recipient: Recipient data
            campaign: Campaign data
            
        Returns:
            Execution result
        """
        channel = step.get("channel", "email")
        
        if channel == "email":
            # Use existing email executor
            return await self._execute_email_via_executor(step, recipient, campaign)
        else:
            # Use multi-channel executor
            return await self.multi_channel_executor.execute_step(
                step, recipient, campaign, self.campaign_executor.manager
            )
    
    async def _execute_email_via_executor(
        self,
        step: Dict,
        recipient: Dict,
        campaign: Dict
    ) -> Dict[str, Any]:
        """Route to existing campaign executor for email sends."""
        # This would call the existing _execute_send logic
        try:
            # Prepare send record
            send_record = {
                "_id": ObjectId(),
                "campaign_id": str(campaign["_id"]),
                "recipient_id": str(recipient["_id"]),
                "template_id": step.get("template_id"),
                "status": "queued",
                "scheduled_at": datetime.utcnow()
            }
            
            # Execute via existing executor's _execute_send
            self.campaign_executor._execute_send(send_record, campaign)
            
            return {
                "success": True,
                "channel": "email",
                "message": "Sent via campaign executor"
            }
        except Exception as e:
            logger.error(f"Email execution failed: {e}")
            return {
                "success": False,
                "channel": "email",
                "error": str(e)
            }
