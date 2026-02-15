"""
Campaign Integration Module
Connects Clay-like functionality to existing campaign entities
Preserves all existing campaign data while adding Clay capabilities
"""

from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from pymongo import MongoClient
import os
from dotenv import load_dotenv

from .clay_models import CampaignClayConfig, CostControl, DeduplicationRule

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')


class CampaignClayIntegration:
    """
    Integration layer between existing Campaign entities and Clay features
    Preserves existing campaign data while extending with Clay capabilities
    """
    
    def __init__(self):
        self.client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client['campaign_platform']
        self.campaigns_collection = self.db['campaigns']
        self.clay_configs_collection = self.db['campaign_clay_configs']
    
    async def get_or_create_clay_config(
        self,
        campaign_id: str,
        created_by: str = "system"
    ) -> CampaignClayConfig:
        """
        Get existing Clay config or create new one for campaign
        Always preserves existing campaign data
        """
        
        # Check if config exists
        existing = self.clay_configs_collection.find_one({"campaign_id": campaign_id})
        
        if existing:
            return CampaignClayConfig(**existing)
        
        # Create new config with defaults
        config = CampaignClayConfig(
            campaign_id=campaign_id,
            created_by=created_by,
            cost_control=CostControl(
                daily_hard_cap=1000.0,
                monthly_hard_cap=10000.0,
                cost_estimation_enabled=True
            ),
            deduplication_rules=[
                DeduplicationRule(
                    name="email_exact",
                    strategy="exact",
                    fields=["email"]
                ),
                DeduplicationRule(
                    name="name_company",
                    strategy="composite",
                    fields=["first_name", "last_name", "company_name"]
                )
            ]
        )
        
        # Store in MongoDB
        self.clay_configs_collection.insert_one(config.dict())
        
        return config
    
    async def attach_clay_to_campaign(
        self,
        campaign_id: str,
        cost_control: Optional[CostControl] = None,
        dedup_rules: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Attach Clay configuration to an existing campaign
        
        Returns:
            Campaign with Clay enabled
        """
        
        # Get existing campaign
        campaign = self.campaigns_collection.find_one({"_id": campaign_id})
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        # Create/update Clay config
        config = await self.get_or_create_clay_config(campaign_id)
        
        if cost_control:
            config.cost_control = cost_control
        if dedup_rules:
            config.deduplication_rules = dedup_rules
        
        # Update config in DB
        self.clay_configs_collection.update_one(
            {"campaign_id": campaign_id},
            {
                "$set": {
                    "cost_control": config.cost_control.dict(),
                    "deduplication_rules": [r.dict() for r in config.deduplication_rules],
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        # Add reference to campaign (non-destructive)
        self.campaigns_collection.update_one(
            {"_id": campaign_id},
            {
                "$set": {
                    "clay_config_id": campaign_id,
                    "clay_enabled": True,
                    "clay_enabled_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "campaign_id": campaign_id,
            "clay_enabled": True,
            "config": config.dict()
        }
    
    async def get_campaign_with_clay(self, campaign_id: str) -> Dict[str, Any]:
        """
        Get campaign with Clay configuration
        Preserves all existing campaign fields
        """
        
        campaign = self.campaigns_collection.find_one({"_id": campaign_id})
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        config = None
        if campaign.get("clay_enabled"):
            config = self.clay_configs_collection.find_one({"campaign_id": campaign_id})
        
        return {
            "campaign": campaign,
            "clay_config": config,
            "clay_enabled": campaign.get("clay_enabled", False)
        }
    
    async def sync_leads_to_campaign(
        self,
        campaign_id: str,
        workbook_id: str,
        row_ids: list,
        action: str = "attach"
    ) -> Dict[str, Any]:
        """
        Sync completed workbook rows back to campaign leads

        Actions:
        - "attach": Add new leads to campaign
        - "update": Update existing leads
        - "replace": Replace all campaign leads
        """

        from .import_gating import ImportGatingManager
        from .workbook_engine import WorkbookExecutionEngine

        # Get campaign
        campaign = self.campaigns_collection.find_one({"_id": campaign_id})
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Get workbook rows
        workbooks_db = self.db['workbook_rows']
        rows = list(workbooks_db.find({
            "workbook_id": workbook_id,
            "row_index": {"$in": row_ids}
        }))

        if not rows:
            return {"status": "error", "message": "No rows found"}

        # Extract lead data from rows
        leads = []
        for row in rows:
            lead = {
                "email": row.get("entity_data", {}).get("email"),
                "first_name": row.get("entity_data", {}).get("first_name"),
                "last_name": row.get("entity_data", {}).get("last_name"),
                "company_name": row.get("entity_data", {}).get("company_name"),
                "title": row.get("entity_data", {}).get("title"),
                "phone": row.get("entity_data", {}).get("phone"),
                "source": "clay_workbook",
                "workbook_id": workbook_id,
                "row_id": row.get("_id")
            }
            leads.append(lead)

        # Apply deduplication
        config = await self.get_or_create_clay_config(campaign_id)
        gating = ImportGatingManager()

        dedup_rules = [
            DeduplicationRule(
                name=rule.get("name"),
                strategy=rule.get("strategy"),
                fields=rule.get("fields")
            )
            for rule in config.deduplication_rules
        ]

        # Check for duplicates
        unique_leads, duplicate_groups = gating.deduplication_engine.detect_duplicates_in_batch(
            leads,
            dedup_rules
        )

        # Sync to campaign
        leads_collection = self.db.get_collection(f"campaign_{campaign_id}_leads")

        if action == "attach":
            # Add new leads
            if unique_leads:
                leads_collection.insert_many(unique_leads)
        elif action == "update":
            # Update existing
            for lead in unique_leads:
                leads_collection.update_one(
                    {"email": lead.get("email")},
                    {"$set": lead},
                    upsert=True
                )
        elif action == "replace":
            # Clear and replace
            leads_collection.delete_many({})
            if unique_leads:
                leads_collection.insert_many(unique_leads)

        # Update campaign stats
        self.campaigns_collection.update_one(
            {"_id": campaign_id},
            {
                "$set": {
                    "total_leads": leads_collection.count_documents({}),
                    "last_clay_sync": datetime.utcnow(),
                    "last_sync_workbook_id": workbook_id
                }
            }
        )

        return {
            "status": "success",
            "campaign_id": campaign_id,
            "leads_synced": len(unique_leads),
            "duplicates_found": len(duplicate_groups),
            "action": action
        }

    async def auto_route_qualified_leads(
        self,
        campaign_id: str,
        enable_decision_logging: bool = True
    ) -> Dict[str, Any]:
        """
        Autonomously route qualified leads to campaign based on ICP matching.
        Uses strict 0.85+ confidence threshold.

        Full audit trail logged for GDPR/CAN-SPAM compliance.

        Args:
            campaign_id: Campaign to route leads to
            enable_decision_logging: If True, log routing decisions for compliance

        Returns:
            Routing results with counts and decision audit trail
        """
        from ..automation.lead_router import LeadRouter
        from ..automation.decision_logger import DecisionLogger

        # Initialize router with decision logging
        decision_logger = None
        if enable_decision_logging:
            decision_logger = DecisionLogger(self.db)

        router = LeadRouter(self.db, decision_logger=decision_logger)

        # Route qualified leads with 0.85+ confidence threshold
        return router.route_qualified_leads(campaign_id, auto_route=True)
    
    async def get_campaign_clay_stats(self, campaign_id: str) -> Dict[str, Any]:
        """
        Get Clay-specific stats for campaign
        """
        
        costs = self.db['cost_ledgers']
        workbooks = self.db['workbooks']
        exec_logs = self.db['execution_logs']
        
        # Cost stats
        total_cost = costs.aggregate([
            {"$match": {"campaign_id": campaign_id}},
            {"$group": {"_id": None, "total": {"$sum": "$cost"}}}
        ])
        
        total_cost_amount = 0
        for doc in total_cost:
            total_cost_amount = doc.get("total", 0)
        
        # Workbook stats
        workbook_count = workbooks.count_documents({"campaign_id": campaign_id})
        
        # Execution stats
        execution_count = exec_logs.count_documents({"campaign_id": campaign_id})
        
        config = await self.get_or_create_clay_config(campaign_id)
        
        return {
            "campaign_id": campaign_id,
            "total_cost": total_cost_amount,
            "cost_control": config.cost_control.dict(),
            "workbooks_created": workbook_count,
            "total_executions": execution_count,
            "deduplication_rules": len(config.deduplication_rules)
        }


# ============== FACTORY ==============

_integration_instance = None


def get_campaign_integration() -> CampaignClayIntegration:
    """Get singleton integration instance"""
    global _integration_instance
    if _integration_instance is None:
        _integration_instance = CampaignClayIntegration()
    return _integration_instance
