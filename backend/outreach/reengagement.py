"""
RE-ENGAGEMENT MODULE
===================

Manages drip and re-engagement campaigns for unresponsive leads:
- Week 3-4: Soft drip with educational content
- Month 2: Trigger-based outreach
- Month 3-4: Reset outreach with new angles

Automatically moves completed sequences into re-engagement pool.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from bson import ObjectId
from pymongo.database import Database

from .models import (
    OutreachLead,
    ReengagementLead,
    ReengagementStage,
    SequenceStage,
    EngagementStatus
)


class ReengagementEngine:
    """
    Engine for managing re-engagement campaigns and drip sequences.
    """
    
    def __init__(self, db: Database):
        """
        Initialize re-engagement engine.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.leads = db["outreach_leads"]
        self.reengagement_pool = db["reengagement_pool"]
        self.emails = db["outreach_emails"]
        self.events = db["outreach_events"]
        self.templates = db["outreach_templates"]
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary database indexes."""
        try:
            self.reengagement_pool.create_index([("lead_id", 1)], unique=True)
            self.reengagement_pool.create_index([("stage", 1), ("is_active", 1)])
            self.reengagement_pool.create_index([("next_action_at", 1)])
            self.reengagement_pool.create_index([("enrolled_at", 1)])
        except Exception as e:
            import logging
            logging.warning(f"Index creation failed: {e}")
    
    def enroll_eligible_leads(self) -> int:
        """
        Find and enroll leads eligible for re-engagement.
        
        Returns:
            Number of leads enrolled
        """
        # Find leads with completed sequences and no reply
        eligible_leads = self.leads.find({
            "sequence_stage": SequenceStage.SEQUENCE_COMPLETED.value,
            "reengagement_eligible": True,
            "emails_replied": 0,
            "engagement_status": {"$nin": [
                EngagementStatus.REPLIED_POSITIVE.value,
                EngagementStatus.REPLIED_NEUTRAL.value,
                EngagementStatus.REPLIED_NEGATIVE.value,
                EngagementStatus.UNSUBSCRIBED.value,
                EngagementStatus.BOUNCED.value
            ]}
        })
        
        enrolled = 0
        
        for lead in eligible_leads:
            # Check if already in pool
            existing = self.reengagement_pool.find_one({"lead_id": str(lead["_id"])})
            if existing:
                continue
            
            # Get completed sequence info
            last_email = self.emails.find_one(
                {"lead_id": str(lead["_id"])},
                sort=[("sent_at", -1)]
            )
            
            if not last_email:
                continue
            
            # Create re-engagement record
            reengagement = ReengagementLead(
                lead_id=str(lead["_id"]),
                original_sequence_id=lead.get("assigned_sequence_id", ""),
                completed_sequence_at=last_email.get("sent_at", datetime.utcnow()),
                original_opens=lead.get("emails_opened", 0),
                original_clicks=lead.get("emails_clicked", 0),
                last_activity_at=lead.get("last_opened_at") or lead.get("last_contacted_at"),
                stage=ReengagementStage.SOFT_DRIP_WEEK_3_4,
                next_action_at=datetime.utcnow() + timedelta(days=7)  # Start soft drip in 1 week
            )
            
            self.reengagement_pool.insert_one(reengagement.model_dump())
            
            # Update lead
            self.leads.update_one(
                {"_id": lead["_id"]},
                {
                    "$set": {
                        "reengagement_stage": ReengagementStage.SOFT_DRIP_WEEK_3_4.value,
                        "reengagement_enrolled_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            enrolled += 1
        
        return enrolled
    
    def process_soft_drip(self, lead_id: str) -> bool:
        """
        Send soft drip content (educational, no hard CTA).
        
        Args:
            lead_id: Lead ID
        
        Returns:
            Success status
        """
        # Get re-engagement record
        reeng = self.reengagement_pool.find_one({"lead_id": lead_id})
        if not reeng or reeng["stage"] != ReengagementStage.SOFT_DRIP_WEEK_3_4.value:
            return False
        
        # Get soft drip template
        template = self.templates.find_one({
            "category": "reengagement",
            "step_type": "soft_drip",
            "is_active": True
        })
        
        if not template:
            return False
        
        # Schedule drip email
        # (Implementation would schedule email similar to sequence engine)
        
        # Update re-engagement record
        drip_count = reeng.get("drip_emails_sent", 0) + 1
        
        update_data = {
            "$inc": {"drip_emails_sent": 1},
            "$set": {
                "last_drip_sent_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        }
        
        # After 2-3 soft drips, move to trigger-based stage
        if drip_count >= 3:
            update_data["$set"]["stage"] = ReengagementStage.TRIGGER_BASED_MONTH_2.value
            update_data["$set"]["next_action_at"] = datetime.utcnow() + timedelta(days=30)
        else:
            # Schedule next drip in 1 week
            update_data["$set"]["next_action_at"] = datetime.utcnow() + timedelta(days=7)
        
        self.reengagement_pool.update_one(
            {"_id": reeng["_id"]},
            update_data
        )
        
        return True
    
    def detect_triggers(self, lead_id: str) -> List[str]:
        """
        Detect re-engagement triggers for a lead.
        
        Args:
            lead_id: Lead ID
        
        Returns:
            List of detected triggers
        """
        triggers = []
        
        # Get lead
        lead = self.leads.find_one({"_id": ObjectId(lead_id)})
        if not lead:
            return triggers
        
        # Check for various triggers
        # (These would typically integrate with external data sources)
        
        # Example trigger checks:
        # 1. Job change (would need LinkedIn integration)
        # 2. Company funding (would need Crunchbase integration)
        # 3. Company growth (would need employee count tracking)
        # 4. Industry events (would need calendar integration)
        # 5. Product updates (internal trigger)
        
        # For now, return placeholder
        # In production, this would make API calls to enrichment services
        
        return triggers
    
    def send_trigger_based_email(
        self,
        lead_id: str,
        trigger: str
    ) -> bool:
        """
        Send trigger-based re-engagement email.
        
        Args:
            lead_id: Lead ID
            trigger: Trigger type (job_change, company_growth, etc.)
        
        Returns:
            Success status
        """
        # Get re-engagement record
        reeng = self.reengagement_pool.find_one({"lead_id": lead_id})
        if not reeng:
            return False
        
        # Get trigger-specific template
        template = self.templates.find_one({
            "category": "reengagement",
            "step_type": f"trigger_{trigger}",
            "is_active": True
        })
        
        if not template:
            # Fallback to generic trigger template
            template = self.templates.find_one({
                "category": "reengagement",
                "step_type": "trigger_based",
                "is_active": True
            })
        
        if not template:
            return False
        
        # Schedule trigger-based email
        # (Implementation would schedule email with trigger context)
        
        # Update re-engagement record
        self.reengagement_pool.update_one(
            {"_id": reeng["_id"]},
            {
                "$addToSet": {"detected_triggers": trigger},
                "$set": {
                    "trigger_detected_at": datetime.utcnow(),
                    "stage": ReengagementStage.TRIGGER_BASED_MONTH_2.value,
                    "next_action_at": datetime.utcnow() + timedelta(days=30),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return True
    
    def send_reset_outreach(self, lead_id: str) -> bool:
        """
        Send reset outreach with new angle.
        
        Args:
            lead_id: Lead ID
        
        Returns:
            Success status
        """
        # Get re-engagement record
        reeng = self.reengagement_pool.find_one({"lead_id": lead_id})
        if not reeng:
            return False
        
        # Get reset outreach template
        template = self.templates.find_one({
            "category": "reengagement",
            "step_type": "reset_outreach",
            "is_active": True
        })
        
        if not template:
            return False
        
        # Schedule reset email with new angle
        # (Implementation would use different template/sender)
        
        # Update stage
        self.reengagement_pool.update_one(
            {"_id": reeng["_id"]},
            {
                "$set": {
                    "stage": ReengagementStage.RESET_OUTREACH_MONTH_3_4.value,
                    "last_drip_sent_at": datetime.utcnow(),
                    "next_action_at": None,  # No more automated actions
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return True
    
    def remove_from_pool(
        self,
        lead_id: str,
        reason: str
    ) -> bool:
        """
        Remove a lead from re-engagement pool.
        
        Args:
            lead_id: Lead ID
            reason: Reason for removal (replied, unsubscribed, converted, etc.)
        
        Returns:
            Success status
        """
        result = self.reengagement_pool.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "is_active": False,
                    "removed_reason": reason,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # Update lead
        self.leads.update_one(
            {"_id": ObjectId(lead_id)},
            {
                "$set": {
                    "reengagement_stage": ReengagementStage.NOT_IN_POOL.value,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return result.modified_count > 0
    
    def mark_converted(self, lead_id: str) -> bool:
        """
        Mark a lead as converted from re-engagement.
        
        Args:
            lead_id: Lead ID
        
        Returns:
            Success status
        """
        result = self.reengagement_pool.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "converted_to_active": True,
                    "is_active": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return result.modified_count > 0
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get statistics for re-engagement pool.
        
        Returns:
            Pool statistics
        """
        # Count by stage
        pipeline = [
            {"$match": {"is_active": True}},
            {"$group": {
                "_id": "$stage",
                "count": {"$sum": 1}
            }}
        ]
        
        stage_counts = {r["_id"]: r["count"] for r in self.reengagement_pool.aggregate(pipeline)}
        
        # Count conversions
        total_enrolled = self.reengagement_pool.count_documents({})
        total_converted = self.reengagement_pool.count_documents({"converted_to_active": True})
        
        # Calculate conversion rate
        conversion_rate = (total_converted / total_enrolled * 100) if total_enrolled > 0 else 0
        
        return {
            "total_enrolled": total_enrolled,
            "active_leads": self.reengagement_pool.count_documents({"is_active": True}),
            "stage_breakdown": stage_counts,
            "total_converted": total_converted,
            "conversion_rate": round(conversion_rate, 2),
            "avg_drip_emails": self._get_avg_drip_emails()
        }
    
    def _get_avg_drip_emails(self) -> float:
        """Calculate average number of drip emails sent."""
        pipeline = [
            {"$match": {"is_active": True}},
            {"$group": {
                "_id": None,
                "avg_emails": {"$avg": "$drip_emails_sent"}
            }}
        ]
        
        result = list(self.reengagement_pool.aggregate(pipeline))
        
        if result:
            return round(result[0].get("avg_emails", 0), 1)
        
        return 0.0
    
    def process_due_actions(self, limit: int = 50) -> int:
        """
        Process re-engagement actions that are due.
        
        Args:
            limit: Maximum number of actions to process
        
        Returns:
            Number of actions processed
        """
        now = datetime.utcnow()
        
        # Find actions due for processing
        due_actions = self.reengagement_pool.find({
            "is_active": True,
            "next_action_at": {"$lte": now}
        }).limit(limit)
        
        processed = 0
        
        for reeng in due_actions:
            lead_id = reeng["lead_id"]
            stage = reeng["stage"]
            
            if stage == ReengagementStage.SOFT_DRIP_WEEK_3_4.value:
                self.process_soft_drip(lead_id)
                processed += 1
            
            elif stage == ReengagementStage.TRIGGER_BASED_MONTH_2.value:
                # Check for triggers
                triggers = self.detect_triggers(lead_id)
                if triggers:
                    self.send_trigger_based_email(lead_id, triggers[0])
                    processed += 1
                else:
                    # No triggers, move to reset stage
                    self.reengagement_pool.update_one(
                        {"_id": reeng["_id"]},
                        {
                            "$set": {
                                "stage": ReengagementStage.RESET_OUTREACH_MONTH_3_4.value,
                                "next_action_at": now + timedelta(days=30)
                            }
                        }
                    )
            
            elif stage == ReengagementStage.RESET_OUTREACH_MONTH_3_4.value:
                self.send_reset_outreach(lead_id)
                processed += 1
        
        return processed
