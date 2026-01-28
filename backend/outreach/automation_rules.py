"""
AUTOMATION RULES ENGINE
=======================

Deterministic automation rules for email behavior handling:
- Bounce handling and email invalidation
- Reply detection and sequence stopping
- Warm lead flagging
- Cadence downgrade for unresponsive leads
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from bson import ObjectId
from pymongo.database import Database

from .models import (
    OutreachLead,
    EmailEvent,
    AutomationRule,
    AutomationRuleType,
    EmailStatus,
    EngagementStatus,
    SequenceStage,
    EmailEventType
)


class AutomationRulesEngine:
    """
    Engine for executing automation rules based on email behavior.
    """
    
    def __init__(self, db: Database):
        """
        Initialize automation rules engine.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.leads = db["outreach_leads"]
        self.events = db["outreach_events"]
        self.emails = db["outreach_emails"]
        self.rules = db["automation_rules"]
        
        # Initialize default rules
        self._ensure_default_rules()
    
    def _ensure_default_rules(self):
        """Create default automation rules if they don't exist."""
        default_rules = [
            {
                "name": "Mark Email Invalid on Bounce",
                "description": "Mark email as invalid and stop sequence when email bounces",
                "rule_type": AutomationRuleType.EMAIL_BOUNCED.value,
                "conditions": {"event_type": EmailEventType.BOUNCED.value},
                "actions": [
                    {"action": "update_field", "field": "email_status", "value": EmailStatus.INVALID.value},
                    {"action": "update_field", "field": "engagement_status", "value": EngagementStatus.BOUNCED.value},
                    {"action": "stop_sequence"}
                ],
                "priority": 1,
                "is_active": True
            },
            {
                "name": "Stop Sequence on Reply",
                "description": "Stop sequence when lead replies to any email",
                "rule_type": AutomationRuleType.REPLY_RECEIVED.value,
                "conditions": {"event_type": EmailEventType.REPLIED.value},
                "actions": [
                    {"action": "stop_sequence"},
                    {"action": "update_field", "field": "engagement_status", "value": EngagementStatus.ENGAGED.value}
                ],
                "priority": 2,
                "is_active": True
            },
            {
                "name": "Flag Warm Lead (2+ Opens, No Reply)",
                "description": "Flag lead as warm if they've opened 2+ times without replying",
                "rule_type": AutomationRuleType.WARM_LEAD_DETECTION.value,
                "conditions": {
                    "emails_opened": {"$gte": 2},
                    "emails_replied": 0
                },
                "actions": [
                    {"action": "update_field", "field": "engagement_status", "value": EngagementStatus.WARM_LEAD.value},
                    {"action": "add_tag", "tag": "warm_lead"}
                ],
                "priority": 5,
                "is_active": True
            },
            {
                "name": "Downgrade Cadence (No Opens After 3 Emails)",
                "description": "Slow down sending if lead hasn't opened after 3 emails",
                "rule_type": AutomationRuleType.CADENCE_DOWNGRADE.value,
                "conditions": {
                    "emails_sent": {"$gte": 3},
                    "emails_opened": 0
                },
                "actions": [
                    {"action": "add_tag", "tag": "unresponsive"},
                    {"action": "update_field", "field": "engagement_status", "value": EngagementStatus.NEVER_OPENED.value}
                ],
                "priority": 8,
                "is_active": True
            }
        ]
        
        for rule_data in default_rules:
            # Check if rule exists
            existing = self.rules.find_one({"name": rule_data["name"]})
            if not existing:
                rule_data["created_at"] = datetime.utcnow()
                rule_data["updated_at"] = datetime.utcnow()
                rule_data["execution_count"] = 0
                self.rules.insert_one(rule_data)
    
    def process_event(self, event: EmailEvent) -> List[str]:
        """
        Process an email event and execute matching rules.
        
        Args:
            event: Email event to process
        
        Returns:
            List of executed rule names
        """
        executed_rules = []
        
        # Get lead
        lead = self.leads.find_one({"_id": ObjectId(event.lead_id)})
        if not lead:
            return executed_rules
        
        # Find matching rules
        active_rules = self.rules.find({"is_active": True}).sort("priority", 1)
        
        for rule_doc in active_rules:
            if self._check_rule_conditions(rule_doc, event, lead):
                # Execute rule actions
                self._execute_rule_actions(rule_doc, event, lead)
                executed_rules.append(rule_doc["name"])
                
                # Update rule execution tracking
                self.rules.update_one(
                    {"_id": rule_doc["_id"]},
                    {
                        "$inc": {"execution_count": 1},
                        "$set": {"last_executed_at": datetime.utcnow()}
                    }
                )
        
        return executed_rules
    
    def _check_rule_conditions(
        self,
        rule: Dict,
        event: EmailEvent,
        lead: Dict
    ) -> bool:
        """
        Check if rule conditions are met.
        
        Args:
            rule: Rule document
            event: Email event
            lead: Lead document
        
        Returns:
            True if conditions met, False otherwise
        """
        conditions = rule.get("conditions", {})
        
        # Check event type condition
        if "event_type" in conditions:
            if conditions["event_type"] != event.event_type.value:
                return False
        
        # Check lead field conditions
        for field, condition in conditions.items():
            if field == "event_type":
                continue
            
            lead_value = lead.get(field)
            
            if isinstance(condition, dict):
                # Handle MongoDB-style operators
                if "$gte" in condition:
                    if not (lead_value is not None and lead_value >= condition["$gte"]):
                        return False
                if "$lte" in condition:
                    if not (lead_value is not None and lead_value <= condition["$lte"]):
                        return False
                if "$gt" in condition:
                    if not (lead_value is not None and lead_value > condition["$gt"]):
                        return False
                if "$lt" in condition:
                    if not (lead_value is not None and lead_value < condition["$lt"]):
                        return False
            else:
                # Direct equality check
                if lead_value != condition:
                    return False
        
        return True
    
    def _execute_rule_actions(
        self,
        rule: Dict,
        event: EmailEvent,
        lead: Dict
    ):
        """
        Execute rule actions.
        
        Args:
            rule: Rule document
            event: Email event
            lead: Lead document
        """
        actions = rule.get("actions", [])
        lead_id = str(lead["_id"])
        
        for action in actions:
            action_type = action.get("action")
            
            if action_type == "update_field":
                # Update a lead field
                field = action.get("field")
                value = action.get("value")
                
                self.leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {field: value, "updated_at": datetime.utcnow()}}
                )
            
            elif action_type == "stop_sequence":
                # Stop the lead's sequence
                self.leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": {
                        "sequence_stage": SequenceStage.SEQUENCE_STOPPED.value,
                        "updated_at": datetime.utcnow()
                    }}
                )
                
                # Cancel scheduled emails
                self.emails.update_many(
                    {"lead_id": lead_id, "status": "scheduled"},
                    {"$set": {"status": "cancelled", "updated_at": datetime.utcnow()}}
                )
            
            elif action_type == "add_tag":
                # Add a tag to the lead
                tag = action.get("tag")
                self.leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$addToSet": {"tags": tag}, "$set": {"updated_at": datetime.utcnow()}}
                )
            
            elif action_type == "remove_tag":
                # Remove a tag from the lead
                tag = action.get("tag")
                self.leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$pull": {"tags": tag}, "$set": {"updated_at": datetime.utcnow()}}
                )
            
            elif action_type == "increment_field":
                # Increment a numeric field
                field = action.get("field")
                amount = action.get("amount", 1)
                self.leads.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$inc": {field: amount}, "$set": {"updated_at": datetime.utcnow()}}
                )
    
    def create_custom_rule(
        self,
        name: str,
        description: str,
        rule_type: AutomationRuleType,
        conditions: Dict[str, Any],
        actions: List[Dict[str, Any]],
        priority: int = 10
    ) -> str:
        """
        Create a custom automation rule.
        
        Args:
            name: Rule name
            description: Rule description
            rule_type: Type of rule
            conditions: Conditions for triggering
            actions: Actions to execute
            priority: Priority (lower = higher priority)
        
        Returns:
            Rule ID
        """
        rule = AutomationRule(
            name=name,
            description=description,
            rule_type=rule_type,
            conditions=conditions,
            actions=actions,
            priority=priority
        )
        
        doc = rule.model_dump()
        result = self.rules.insert_one(doc)
        return str(result.inserted_id)
    
    def evaluate_lead(self, lead_id: str) -> List[str]:
        """
        Evaluate all rules against a lead's current state.
        
        Args:
            lead_id: Lead ID
        
        Returns:
            List of executed rule names
        """
        executed_rules = []
        
        # Get lead
        lead = self.leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return executed_rules
        
        # Find matching rules (excluding event-based rules)
        active_rules = self.rules.find({
            "is_active": True,
            "rule_type": {"$in": [
                AutomationRuleType.WARM_LEAD_DETECTION.value,
                AutomationRuleType.CADENCE_DOWNGRADE.value
            ]}
        }).sort("priority", 1)
        
        # Create a dummy event for non-event rules
        from .models import EmailEvent as EmailEventModel
        dummy_event = EmailEventModel(
            email_id="",
            lead_id=lead_id,
            sequence_id=lead.get("assigned_sequence_id", ""),
            event_type=EmailEventType.SENT
        )
        
        for rule_doc in active_rules:
            # Check only lead-based conditions
            conditions_met = True
            for field, condition in rule_doc.get("conditions", {}).items():
                lead_value = lead.get(field)
                
                if isinstance(condition, dict):
                    if "$gte" in condition and not (lead_value is not None and lead_value >= condition["$gte"]):
                        conditions_met = False
                        break
                    if "$lte" in condition and not (lead_value is not None and lead_value <= condition["$lte"]):
                        conditions_met = False
                        break
                else:
                    if lead_value != condition:
                        conditions_met = False
                        break
            
            if conditions_met:
                # Execute rule actions
                self._execute_rule_actions(rule_doc, dummy_event, lead)
                executed_rules.append(rule_doc["name"])
                
                # Update rule execution tracking
                self.rules.update_one(
                    {"_id": rule_doc["_id"]},
                    {
                        "$inc": {"execution_count": 1},
                        "$set": {"last_executed_at": datetime.utcnow()}
                    }
                )
        
        return executed_rules
    
    def get_rule_stats(self) -> List[Dict[str, Any]]:
        """
        Get execution statistics for all rules.
        
        Returns:
            List of rule statistics
        """
        rules = self.rules.find({"is_active": True})
        
        stats = []
        for rule in rules:
            stats.append({
                "name": rule.get("name"),
                "type": rule.get("rule_type"),
                "execution_count": rule.get("execution_count", 0),
                "last_executed_at": rule.get("last_executed_at"),
                "priority": rule.get("priority")
            })
        
        return sorted(stats, key=lambda x: x["execution_count"], reverse=True)
