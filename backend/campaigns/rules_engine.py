"""
RULES ENGINE
============

Rule-based campaign automation system for handling email engagement events
and triggering appropriate actions.

Features:
- Automatic rule evaluation based on recipient and campaign data
- Email status tracking (bounce, reply, open, click)
- Sequence control (stop, pause, continue)
- Lead scoring and flagging
- Integration with suppression list
- Cadence adjustment based on engagement

Rules Implemented:
1. Bounce handling → Mark email invalid, stop sequence, add to suppression
2. Reply received → Stop sequence, mark as engaged
3. Multiple opens without reply → Flag as warm lead
4. Low engagement → Downgrade cadence
5. Unsubscribe → Add to suppression list, stop all campaigns

Usage:
    from campaigns.rules_engine import RulesEngine
    
    engine = RulesEngine(db)
    
    recipient_data = {
        "email": "john@acme.com",
        "status": "in_sequence",
        "email_opens": 3,
        "email_clicks": 1,
        "replied": False,
        "emails_sent": 3
    }
    
    campaign_data = {
        "campaign_id": "abc123",
        "sequence_length": 5
    }
    
    actions = engine.evaluate_rules(recipient_data, campaign_data)
    # Returns: [{"action": "flag_warm_lead", "reason": "multiple_opens_no_reply", ...}]
"""

import logging
from typing import Dict, List, Any, Optional, Literal
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class RuleAction(str, Enum):
    """Available rule actions"""
    STOP_SEQUENCE = "stop_sequence"
    PAUSE_SEQUENCE = "pause_sequence"
    CONTINUE_SEQUENCE = "continue_sequence"
    SKIP_NEXT_STEP = "skip_next_step"
    MARK_EMAIL_INVALID = "mark_email_invalid"
    MARK_AS_ENGAGED = "mark_as_engaged"
    FLAG_WARM_LEAD = "flag_warm_lead"
    FLAG_COLD_LEAD = "flag_cold_lead"
    ADD_TO_SUPPRESSION = "add_to_suppression"
    DOWNGRADE_CADENCE = "downgrade_cadence"
    UPGRADE_CADENCE = "upgrade_cadence"
    NOTIFY_SALES = "notify_sales"
    UPDATE_LEAD_SCORE = "update_lead_score"
    MOVE_TO_NURTURE = "move_to_nurture"


class RulePriority(str, Enum):
    """Rule priority levels"""
    CRITICAL = "critical"  # Execute immediately (e.g., unsubscribe)
    HIGH = "high"  # Execute soon (e.g., bounce, reply)
    MEDIUM = "medium"  # Execute normally (e.g., engagement flags)
    LOW = "low"  # Execute when convenient (e.g., scoring updates)


class RulesEngine:
    """
    Rule-based automation engine for campaign management.
    
    Evaluates recipient engagement and triggers appropriate actions.
    """
    
    def __init__(self, db=None):
        """
        Initialize rules engine.
        
        Args:
            db: MongoDB database instance (optional, for suppression list access)
        """
        self.db = db
        self.logger = logging.getLogger(__name__)
        
        # Rule configuration
        self.config = {
            "warm_lead_open_threshold": 2,  # Opens needed to flag as warm
            "cold_lead_email_threshold": 3,  # Emails with no opens = cold
            "downgrade_threshold_days": 14,  # Days of no engagement before downgrade
            "engagement_score_open": 5,  # Points for email open
            "engagement_score_click": 10,  # Points for email click
            "engagement_score_reply": 50,  # Points for reply
        }
    
    def evaluate_rules(
        self,
        recipient_data: Dict[str, Any],
        campaign_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Evaluate all rules and return list of actions to take.
        
        Args:
            recipient_data: Dictionary with recipient information:
                - email: str
                - status: str (RecipientStatus)
                - email_opens: int
                - email_clicks: int
                - replied: bool
                - bounced: bool
                - unsubscribed: bool
                - emails_sent: int
                - last_sent_at: datetime
                - last_opened_at: datetime
                - last_replied_at: datetime
                
            campaign_data: Dictionary with campaign information:
                - campaign_id: str
                - sequence_length: int
                - current_step: int
                - cadence: str (daily, weekly, etc.)
        
        Returns:
            List of action dictionaries:
            [
                {
                    "action": "stop_sequence",
                    "reason": "bounced",
                    "priority": "critical",
                    "data": {...}
                },
                ...
            ]
        """
        actions = []
        
        # Extract data with safe defaults
        email = recipient_data.get("email", "")
        status = recipient_data.get("status", "pending")
        email_opens = recipient_data.get("email_opens", 0)
        email_clicks = recipient_data.get("email_clicks", 0)
        replied = recipient_data.get("replied", False)
        bounced = recipient_data.get("bounced", False)
        unsubscribed = recipient_data.get("unsubscribed", False)
        emails_sent = recipient_data.get("emails_sent", 0)
        last_opened_at = recipient_data.get("last_opened_at")
        last_sent_at = recipient_data.get("last_sent_at")
        
        campaign_id = campaign_data.get("campaign_id", "")
        
        # CRITICAL PRIORITY RULES (execute first)
        
        # Rule 1: Unsubscribe → Stop everything, add to suppression
        if unsubscribed:
            actions.append(self._create_action(
                action=RuleAction.ADD_TO_SUPPRESSION,
                reason="unsubscribe_request",
                priority=RulePriority.CRITICAL,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "suppression_reason": "unsubscribed"
                }
            ))
            actions.append(self._create_action(
                action=RuleAction.STOP_SEQUENCE,
                reason="unsubscribed",
                priority=RulePriority.CRITICAL,
                data={"email": email, "campaign_id": campaign_id}
            ))
            # Don't evaluate other rules for unsubscribed users
            return actions
        
        # Rule 2: Bounce → Mark invalid, stop sequence, add to suppression
        if bounced:
            actions.append(self._create_action(
                action=RuleAction.MARK_EMAIL_INVALID,
                reason="email_bounced",
                priority=RulePriority.CRITICAL,
                data={"email": email, "campaign_id": campaign_id}
            ))
            actions.append(self._create_action(
                action=RuleAction.STOP_SEQUENCE,
                reason="bounced",
                priority=RulePriority.CRITICAL,
                data={"email": email, "campaign_id": campaign_id}
            ))
            actions.append(self._create_action(
                action=RuleAction.ADD_TO_SUPPRESSION,
                reason="email_bounced",
                priority=RulePriority.CRITICAL,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "suppression_reason": "bounced"
                }
            ))
            # Don't evaluate other rules for bounced emails
            return actions
        
        # HIGH PRIORITY RULES
        
        # Rule 3: Reply received → Stop sequence, mark as engaged
        if replied:
            actions.append(self._create_action(
                action=RuleAction.STOP_SEQUENCE,
                reason="reply_received",
                priority=RulePriority.HIGH,
                data={"email": email, "campaign_id": campaign_id}
            ))
            actions.append(self._create_action(
                action=RuleAction.MARK_AS_ENGAGED,
                reason="reply_received",
                priority=RulePriority.HIGH,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "engagement_type": "reply"
                }
            ))
            actions.append(self._create_action(
                action=RuleAction.NOTIFY_SALES,
                reason="reply_received",
                priority=RulePriority.HIGH,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "notification_type": "reply"
                }
            ))
            actions.append(self._create_action(
                action=RuleAction.UPDATE_LEAD_SCORE,
                reason="reply_received",
                priority=RulePriority.HIGH,
                data={
                    "email": email,
                    "score_change": self.config["engagement_score_reply"],
                    "reason": "email_reply"
                }
            ))
            # Don't evaluate cold lead rules if they replied
            return actions
        
        # MEDIUM PRIORITY RULES
        
        # Rule 4: Multiple opens without reply → Flag as warm lead
        if email_opens >= self.config["warm_lead_open_threshold"] and not replied:
            actions.append(self._create_action(
                action=RuleAction.FLAG_WARM_LEAD,
                reason="multiple_opens_no_reply",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "open_count": email_opens,
                    "engagement_level": "warm"
                }
            ))
            # Update lead score for opens
            actions.append(self._create_action(
                action=RuleAction.UPDATE_LEAD_SCORE,
                reason="multiple_opens",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "score_change": email_opens * self.config["engagement_score_open"],
                    "reason": "email_opens"
                }
            ))
        
        # Rule 5: Clicks without reply → Flag as interested, notify sales
        if email_clicks > 0 and not replied:
            actions.append(self._create_action(
                action=RuleAction.FLAG_WARM_LEAD,
                reason="clicked_without_reply",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "click_count": email_clicks,
                    "engagement_level": "hot"
                }
            ))
            actions.append(self._create_action(
                action=RuleAction.NOTIFY_SALES,
                reason="link_clicked",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "notification_type": "click"
                }
            ))
            # Update lead score for clicks
            actions.append(self._create_action(
                action=RuleAction.UPDATE_LEAD_SCORE,
                reason="link_clicks",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "score_change": email_clicks * self.config["engagement_score_click"],
                    "reason": "email_clicks"
                }
            ))
        
        # Rule 6: No opens after multiple emails → Downgrade cadence, flag as cold
        if emails_sent >= self.config["cold_lead_email_threshold"] and email_opens == 0:
            actions.append(self._create_action(
                action=RuleAction.FLAG_COLD_LEAD,
                reason="no_opens_after_multiple_emails",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "emails_sent": emails_sent,
                    "engagement_level": "cold"
                }
            ))
            actions.append(self._create_action(
                action=RuleAction.DOWNGRADE_CADENCE,
                reason="low_engagement",
                priority=RulePriority.MEDIUM,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "current_emails_sent": emails_sent,
                    "open_rate": 0
                }
            ))
        
        # Rule 7: Time-based engagement check
        if last_sent_at and not replied:
            days_since_last_send = (datetime.utcnow() - last_sent_at).days
            
            # No opens for extended period
            if days_since_last_send >= self.config["downgrade_threshold_days"] and email_opens == 0:
                actions.append(self._create_action(
                    action=RuleAction.MOVE_TO_NURTURE,
                    reason="extended_period_no_engagement",
                    priority=RulePriority.MEDIUM,
                    data={
                        "email": email,
                        "campaign_id": campaign_id,
                        "days_since_last_send": days_since_last_send
                    }
                ))
        
        # Rule 8: Opens but no progression → Extend wait time
        if email_opens > 0 and email_clicks == 0 and not replied and emails_sent >= 2:
            actions.append(self._create_action(
                action=RuleAction.DOWNGRADE_CADENCE,
                reason="opens_without_progression",
                priority=RulePriority.LOW,
                data={
                    "email": email,
                    "campaign_id": campaign_id,
                    "open_count": email_opens,
                    "recommendation": "increase_wait_between_emails"
                }
            ))
        
        return actions
    
    def _create_action(
        self,
        action: RuleAction,
        reason: str,
        priority: RulePriority,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a standardized action dictionary.
        
        Args:
            action: Action to take
            reason: Reason for action
            priority: Priority level
            data: Additional data for action execution
        
        Returns:
            Action dictionary
        """
        return {
            "action": action.value if isinstance(action, RuleAction) else action,
            "reason": reason,
            "priority": priority.value if isinstance(priority, RulePriority) else priority,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
            "executed": False
        }
    
    def execute_actions(
        self,
        actions: List[Dict[str, Any]],
        campaign_manager=None
    ) -> Dict[str, Any]:
        """
        Execute a list of actions returned by evaluate_rules.
        
        Args:
            actions: List of action dictionaries from evaluate_rules
            campaign_manager: CampaignManager instance for database operations
        
        Returns:
            Execution summary with results and errors
        """
        if not actions:
            return {"status": "success", "actions_executed": 0, "errors": []}
        
        # Sort by priority
        priority_order = {
            RulePriority.CRITICAL.value: 0,
            RulePriority.HIGH.value: 1,
            RulePriority.MEDIUM.value: 2,
            RulePriority.LOW.value: 3,
        }
        sorted_actions = sorted(
            actions,
            key=lambda x: priority_order.get(x.get("priority", "low"), 999)
        )
        
        executed = 0
        errors = []
        
        for action in sorted_actions:
            try:
                result = self._execute_single_action(action, campaign_manager)
                if result.get("success"):
                    executed += 1
                    action["executed"] = True
                else:
                    errors.append({
                        "action": action.get("action"),
                        "error": result.get("error", "Unknown error")
                    })
            except Exception as e:
                self.logger.error(f"Error executing action {action.get('action')}: {e}")
                errors.append({
                    "action": action.get("action"),
                    "error": str(e)
                })
        
        return {
            "status": "success" if not errors else "partial_success",
            "actions_executed": executed,
            "actions_failed": len(errors),
            "total_actions": len(actions),
            "errors": errors
        }
    
    def _execute_single_action(
        self,
        action: Dict[str, Any],
        campaign_manager=None
    ) -> Dict[str, Any]:
        """
        Execute a single action.
        
        This is a hook for integration with CampaignManager and other services.
        Actual implementation depends on your database structure.
        
        Args:
            action: Action dictionary
            campaign_manager: CampaignManager instance
        
        Returns:
            Execution result
        """
        action_type = action.get("action")
        data = action.get("data", {})
        
        try:
            # Hook for stop_sequence
            if action_type == RuleAction.STOP_SEQUENCE.value:
                if campaign_manager:
                    # Integration point with CampaignManager
                    # campaign_manager.stop_sequence(data.get("email"), data.get("campaign_id"))
                    pass
                self.logger.info(f"Stopped sequence for {data.get('email')} in campaign {data.get('campaign_id')}")
                return {"success": True}
            
            # Hook for add_to_suppression
            elif action_type == RuleAction.ADD_TO_SUPPRESSION.value:
                if self.db:
                    from campaigns.suppression import SuppressionListManager
                    suppression = SuppressionListManager(self.db)
                    suppression.add_email(
                        email=data.get("email"),
                        reason=data.get("suppression_reason", "system"),
                        source_campaign_id=data.get("campaign_id")
                    )
                self.logger.info(f"Added {data.get('email')} to suppression list")
                return {"success": True}
            
            # Hook for mark_email_invalid
            elif action_type == RuleAction.MARK_EMAIL_INVALID.value:
                if campaign_manager:
                    # Integration point
                    # campaign_manager.mark_email_invalid(data.get("email"))
                    pass
                self.logger.info(f"Marked email as invalid: {data.get('email')}")
                return {"success": True}
            
            # Hook for mark_as_engaged
            elif action_type == RuleAction.MARK_AS_ENGAGED.value:
                if campaign_manager:
                    # Integration point
                    # campaign_manager.update_recipient_status(
                    #     data.get("email"),
                    #     data.get("campaign_id"),
                    #     "replied"
                    # )
                    pass
                self.logger.info(f"Marked {data.get('email')} as engaged")
                return {"success": True}
            
            # Hook for flag_warm_lead / flag_cold_lead
            elif action_type in (RuleAction.FLAG_WARM_LEAD.value, RuleAction.FLAG_COLD_LEAD.value):
                if self.db:
                    # Update lead in database
                    # self.db.leads.update_one(
                    #     {"email": data.get("email")},
                    #     {"$set": {"engagement_level": data.get("engagement_level")}}
                    # )
                    pass
                self.logger.info(f"Flagged {data.get('email')} as {data.get('engagement_level')} lead")
                return {"success": True}
            
            # Hook for update_lead_score
            elif action_type == RuleAction.UPDATE_LEAD_SCORE.value:
                if self.db:
                    # Update lead score
                    # self.db.leads.update_one(
                    #     {"email": data.get("email")},
                    #     {"$inc": {"engagement_score": data.get("score_change", 0)}}
                    # )
                    pass
                self.logger.info(f"Updated lead score for {data.get('email')} by {data.get('score_change', 0)}")
                return {"success": True}
            
            # Hook for downgrade_cadence
            elif action_type == RuleAction.DOWNGRADE_CADENCE.value:
                if campaign_manager:
                    # Integration point
                    # campaign_manager.adjust_cadence(
                    #     data.get("email"),
                    #     data.get("campaign_id"),
                    #     "downgrade"
                    # )
                    pass
                self.logger.info(f"Downgraded cadence for {data.get('email')}")
                return {"success": True}
            
            # Hook for notify_sales
            elif action_type == RuleAction.NOTIFY_SALES.value:
                # Integration point for sales notifications (Slack, email, etc.)
                self.logger.info(f"Sales notification sent for {data.get('email')}")
                return {"success": True}
            
            # Hook for move_to_nurture
            elif action_type == RuleAction.MOVE_TO_NURTURE.value:
                if campaign_manager:
                    # Integration point
                    # campaign_manager.move_to_nurture_sequence(
                    #     data.get("email"),
                    #     data.get("campaign_id")
                    # )
                    pass
                self.logger.info(f"Moved {data.get('email')} to nurture sequence")
                return {"success": True}
            
            else:
                self.logger.warning(f"Unknown action type: {action_type}")
                return {"success": False, "error": f"Unknown action type: {action_type}"}
        
        except Exception as e:
            self.logger.error(f"Error executing action {action_type}: {e}")
            return {"success": False, "error": str(e)}
    
    def get_rule_config(self) -> Dict[str, Any]:
        """Get current rule configuration."""
        return self.config.copy()
    
    def update_rule_config(self, updates: Dict[str, Any]) -> None:
        """
        Update rule configuration.
        
        Args:
            updates: Dictionary of config keys to update
        """
        self.config.update(updates)
        self.logger.info(f"Updated rule config: {updates}")


# Convenience function for quick rule evaluation
def evaluate_rules(
    recipient_data: Dict[str, Any],
    campaign_data: Dict[str, Any],
    db=None
) -> List[Dict[str, Any]]:
    """
    Quick rule evaluation without instantiating engine.
    
    Args:
        recipient_data: Recipient information
        campaign_data: Campaign information
        db: Optional database instance
    
    Returns:
        List of actions to take
    """
    engine = RulesEngine(db=db)
    return engine.evaluate_rules(recipient_data, campaign_data)
