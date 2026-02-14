"""
MIGRATION SCRIPT: Legacy System to Enterprise Outbound Engine
=============================================================

This script migrates data from the legacy email system to the new 
consolidated enterprise outbound engine.

Migration Steps:
1. Backup existing collections
2. Migrate leads to new schema (outreach_leads_v2)
3. Migrate mailboxes to new schema (outreach_mailboxes)
4. Migrate campaigns to new schema (outreach_campaigns_v2)
5. Migrate templates to new schema (outreach_templates_v2)
6. Create indexes on new collections
7. Verify migration integrity

Components Being Removed:
- OutreachComposerAgent triggers
- Automatic AI email generation (full rewrites)
- Duplicate template engines
- Background AI email drafting processes
- campaigns/personalization_engine.py (replaced by template_renderer)
- outreach/models.py (consolidated into outreach_engine/models.py)

Usage:
    python -m backend.outreach_engine.migration --dry-run
    python -m backend.outreach_engine.migration --execute
"""

import os
import sys
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from pymongo import MongoClient
from bson import ObjectId

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")


class MigrationEngine:
    """
    Engine for migrating legacy email system to enterprise outbound engine.
    """
    
    # Collection mappings
    LEGACY_COLLECTIONS = {
        "leads": ["leads_enriched", "outreach_leads"],
        "campaigns": ["campaigns", "email_campaigns"],
        "templates": ["email_templates", "templates"],
        "sends": ["campaign_sends", "outreach_emails"],
        "mailboxes": ["mailboxes", "connected_accounts"],
    }
    
    NEW_COLLECTIONS = {
        "leads": "outreach_leads_v2",
        "campaigns": "outreach_campaigns_v2",
        "templates": "outreach_templates_v2",
        "sends": "outreach_sends_v2",
        "mailboxes": "outreach_mailboxes",
        "send_logs": "outreach_send_logs",
        "send_queue": "outreach_send_queue",
    }
    
    def __init__(self, mongo_uri: str = None, dry_run: bool = True):
        """
        Initialize migration engine.
        
        Args:
            mongo_uri: MongoDB connection string
            dry_run: If True, don't actually modify data
        """
        self.mongo_uri = mongo_uri or MONGO_URI
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client["email_automation"]
        self.dry_run = dry_run
        
        # Migration stats
        self.stats = {
            "leads_migrated": 0,
            "campaigns_migrated": 0,
            "templates_migrated": 0,
            "mailboxes_migrated": 0,
            "errors": [],
        }
    
    def run_migration(self) -> Dict[str, Any]:
        """
        Run the full migration.
        
        Returns:
            Migration results
        """
        logger.info(f"Starting migration (dry_run={self.dry_run})")
        start_time = datetime.utcnow()
        
        try:
            # Step 1: Backup
            if not self.dry_run:
                self._backup_collections()
            
            # Step 2: Migrate mailboxes first (needed for lead references)
            self._migrate_mailboxes()
            
            # Step 3: Migrate templates
            self._migrate_templates()
            
            # Step 4: Migrate campaigns
            self._migrate_campaigns()
            
            # Step 5: Migrate leads
            self._migrate_leads()
            
            # Step 6: Create indexes
            self._create_indexes()
            
            # Step 7: Verify
            self._verify_migration()
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "success": True,
                "dry_run": self.dry_run,
                "duration_seconds": duration,
                "stats": self.stats,
            }
            
        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stats": self.stats,
            }
    
    def _backup_collections(self):
        """Backup existing collections before migration"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        for collection_type, names in self.LEGACY_COLLECTIONS.items():
            for name in names:
                if name in self.db.list_collection_names():
                    backup_name = f"{name}_backup_{timestamp}"
                    
                    # Copy collection
                    docs = list(self.db[name].find())
                    if docs:
                        self.db[backup_name].insert_many(docs)
                        logger.info(f"Backed up {len(docs)} documents from {name} to {backup_name}")
    
    def _migrate_mailboxes(self):
        """Migrate mailboxes to new schema"""
        logger.info("Migrating mailboxes...")
        
        new_collection = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        
        # Check for existing mailboxes
        for source_name in self.LEGACY_COLLECTIONS["mailboxes"]:
            if source_name not in self.db.list_collection_names():
                continue
            
            source = self.db[source_name]
            
            for doc in source.find():
                try:
                    mailbox_id = str(doc.get("_id", ObjectId()))
                    
                    new_mailbox = {
                        "mailbox_id": mailbox_id,
                        "email_address": doc.get("email", doc.get("email_address", "")),
                        "display_name": doc.get("name", doc.get("display_name", "")),
                        "reply_to": doc.get("reply_to"),
                        "provider": doc.get("provider", "gmail"),
                        "credentials_id": doc.get("credentials_id"),
                        "signature_html": doc.get("signature", doc.get("signature_html", "")),
                        "signature_plain": doc.get("signature_plain", ""),
                        "daily_send_count": 0,
                        "hourly_send_count": 0,
                        "daily_send_limit": doc.get("daily_limit", 400),
                        "hourly_send_limit": doc.get("hourly_limit", 60),
                        "health_status": "healthy",
                        "warmup_status": doc.get("warmup_status", "complete"),
                        "is_active": doc.get("is_active", True),
                        "created_at": doc.get("created_at", datetime.utcnow()),
                        "updated_at": datetime.utcnow(),
                    }
                    
                    if not self.dry_run:
                        new_collection.update_one(
                            {"mailbox_id": mailbox_id},
                            {"$set": new_mailbox},
                            upsert=True
                        )
                    
                    self.stats["mailboxes_migrated"] += 1
                    
                except Exception as e:
                    self.stats["errors"].append(f"Mailbox migration error: {e}")
                    logger.warning(f"Failed to migrate mailbox: {e}")
        
        logger.info(f"Migrated {self.stats['mailboxes_migrated']} mailboxes")
    
    def _migrate_templates(self):
        """Migrate email templates to new schema"""
        logger.info("Migrating templates...")
        
        new_collection = self.db[self.NEW_COLLECTIONS["templates"]]
        
        for source_name in self.LEGACY_COLLECTIONS["templates"]:
            if source_name not in self.db.list_collection_names():
                continue
            
            source = self.db[source_name]
            
            for doc in source.find():
                try:
                    template_id = str(doc.get("_id", ObjectId()))
                    
                    # Determine step type from name/category
                    step_type = self._infer_step_type(
                        doc.get("name", ""),
                        doc.get("category", ""),
                        doc.get("step_type", "")
                    )
                    
                    new_template = {
                        "template_id": template_id,
                        "name": doc.get("name", "Unnamed Template"),
                        "description": doc.get("description"),
                        "subject": doc.get("subject", ""),
                        "body_html": doc.get("body_html", doc.get("body", "")),
                        "body_plain": doc.get("body_plain", ""),
                        "step_type": step_type,
                        "tokens": doc.get("variables", doc.get("tokens", [])),
                        "company_brand": doc.get("company_brand", "surveyfieldwork"),
                        "category": doc.get("category", "outreach"),
                        "is_active": doc.get("is_active", True),
                        "created_at": doc.get("created_at", datetime.utcnow()),
                        "updated_at": datetime.utcnow(),
                    }
                    
                    if not self.dry_run:
                        new_collection.update_one(
                            {"template_id": template_id},
                            {"$set": new_template},
                            upsert=True
                        )
                    
                    self.stats["templates_migrated"] += 1
                    
                except Exception as e:
                    self.stats["errors"].append(f"Template migration error: {e}")
                    logger.warning(f"Failed to migrate template: {e}")
        
        logger.info(f"Migrated {self.stats['templates_migrated']} templates")
    
    def _migrate_campaigns(self):
        """Migrate campaigns to new schema"""
        logger.info("Migrating campaigns...")
        
        new_collection = self.db[self.NEW_COLLECTIONS["campaigns"]]
        
        for source_name in self.LEGACY_COLLECTIONS["campaigns"]:
            if source_name not in self.db.list_collection_names():
                continue
            
            source = self.db[source_name]
            
            for doc in source.find():
                try:
                    campaign_id = str(doc.get("_id", ObjectId()))
                    
                    # Build workflow steps from sequence_steps
                    workflow_steps = []
                    for step in doc.get("sequence_steps", []):
                        workflow_steps.append({
                            "step_number": step.get("step_number", len(workflow_steps)),
                            "template_id": str(step.get("template_id", "")),
                            "delay_days": step.get("delay_days", 0),
                            "delay_hours": step.get("delay_hours", 0),
                            "subject_line": step.get("subject_line", ""),
                            "stop_on_reply": step.get("stop_on_reply", True),
                            "stop_on_bounce": step.get("stop_on_bounce", True),
                        })
                    
                    # Get mailbox IDs
                    mailbox_ids = []
                    if doc.get("from_mailbox_id"):
                        mailbox_ids.append(str(doc["from_mailbox_id"]))
                    
                    # Build settings
                    old_settings = doc.get("settings", {})
                    settings = {
                        "max_emails_per_day_per_inbox": old_settings.get("daily_send_limit", 400),
                        "max_emails_per_hour_per_inbox": old_settings.get("hourly_send_limit", 60),
                        "min_send_interval_seconds": old_settings.get("min_delay_between_sends_seconds", 60),
                        "max_send_interval_seconds": 180,
                        "send_days": old_settings.get("send_days", [0, 1, 2, 3, 4]),
                        "send_hours_start": old_settings.get("send_hours_start", 9),
                        "send_hours_end": old_settings.get("send_hours_end", 17),
                        "use_recipient_timezone": True,
                        "default_timezone": old_settings.get("timezone", "America/New_York"),
                        "bounce_rate_threshold": 0.05,
                        "stop_on_reply": old_settings.get("stop_on_any_reply", True),
                        "stop_on_unsubscribe": True,
                        "default_personalization_level": "light",
                        "ai_token_limit_per_lead": 150,
                    }
                    
                    new_campaign = {
                        "campaign_id": campaign_id,
                        "name": doc.get("name", "Unnamed Campaign"),
                        "description": doc.get("description"),
                        "company_brand": "surveyfieldwork",
                        "value_proposition": "Market research, consumer insights, ad testing, brand lift studies.",
                        "workflow_steps": workflow_steps,
                        "mailbox_ids": mailbox_ids,
                        "settings": settings,
                        "status": doc.get("status", "draft"),
                        "is_active": doc.get("status") == "active",
                        "total_leads": doc.get("stats", {}).get("total_recipients", 0),
                        "leads_in_progress": doc.get("stats", {}).get("in_sequence", 0),
                        "leads_completed": doc.get("stats", {}).get("completed", 0),
                        "leads_replied": doc.get("stats", {}).get("replied", 0),
                        "leads_bounced": doc.get("stats", {}).get("bounced", 0),
                        "total_emails_sent": 0,
                        "created_at": doc.get("created_at", datetime.utcnow()),
                        "updated_at": datetime.utcnow(),
                        "created_by": doc.get("created_by", "migration"),
                    }
                    
                    if not self.dry_run:
                        new_collection.update_one(
                            {"campaign_id": campaign_id},
                            {"$set": new_campaign},
                            upsert=True
                        )
                    
                    self.stats["campaigns_migrated"] += 1
                    
                except Exception as e:
                    self.stats["errors"].append(f"Campaign migration error: {e}")
                    logger.warning(f"Failed to migrate campaign: {e}")
        
        logger.info(f"Migrated {self.stats['campaigns_migrated']} campaigns")
    
    def _migrate_leads(self):
        """Migrate leads to new schema"""
        logger.info("Migrating leads...")
        
        new_collection = self.db[self.NEW_COLLECTIONS["leads"]]
        
        for source_name in self.LEGACY_COLLECTIONS["leads"]:
            if source_name not in self.db.list_collection_names():
                continue
            
            source = self.db[source_name]
            
            for doc in source.find():
                try:
                    lead_id = str(doc.get("_id", ObjectId()))
                    
                    # Map workflow status
                    old_status = doc.get("sequence_stage", doc.get("status", ""))
                    workflow_status = self._map_workflow_status(old_status)
                    
                    new_lead = {
                        "lead_id": lead_id,
                        "email": doc.get("email", ""),
                        "first_name": doc.get("first_name", doc.get("name", "").split()[0] if doc.get("name") else ""),
                        "last_name": doc.get("last_name", " ".join(doc.get("name", "").split()[1:]) if doc.get("name") else ""),
                        "company": doc.get("company", doc.get("company_name", "")),
                        "industry": doc.get("industry", doc.get("company_industry", "")),
                        "title": doc.get("title", ""),
                        "workflow_id": str(doc.get("campaign_id", doc.get("assigned_sequence_id", ""))) or None,
                        "campaign_id": str(doc.get("campaign_id", "")) or None,
                        "current_step": doc.get("current_step", 0),
                        "workflow_status": workflow_status,
                        "assigned_mailbox_id": None,  # Will be assigned on first send
                        "thread_id": doc.get("thread_id"),
                        "message_id_last_sent": None,
                        "in_reply_to": None,
                        "references": [],
                        "ai_context_block": None,
                        "ai_context_generated_at": None,
                        "ai_tokens_used": 0,
                        "personalization_level": doc.get("personalization_level", "light"),
                        "custom_fields": doc.get("custom_fields", doc.get("custom_variables", {})),
                        "last_sent_at": doc.get("last_sent_at", doc.get("last_contacted_at")),
                        "next_send_at": doc.get("next_send_at"),
                        "reply_status": self._map_reply_status(doc),
                        "reply_detected_at": doc.get("last_replied_at"),
                        "bounce_status": "hard" if doc.get("engagement_status") == "Bounced" else None,
                        "emails_sent": doc.get("emails_sent", 0),
                        "emails_opened": doc.get("emails_opened", 0),
                        "emails_clicked": doc.get("emails_clicked", 0),
                        "created_at": doc.get("created_at", datetime.utcnow()),
                        "updated_at": datetime.utcnow(),
                        "tags": doc.get("tags", []),
                        "source": doc.get("source", "migration"),
                    }
                    
                    if not self.dry_run:
                        # Use upsert to avoid duplicates
                        new_collection.update_one(
                            {"email": new_lead["email"]},
                            {"$set": new_lead},
                            upsert=True
                        )
                    
                    self.stats["leads_migrated"] += 1
                    
                except Exception as e:
                    self.stats["errors"].append(f"Lead migration error: {e}")
                    logger.warning(f"Failed to migrate lead: {e}")
        
        logger.info(f"Migrated {self.stats['leads_migrated']} leads")
    
    def _create_indexes(self):
        """Create indexes on new collections"""
        logger.info("Creating indexes...")
        
        if self.dry_run:
            return
        
        # Leads indexes
        leads = self.db[self.NEW_COLLECTIONS["leads"]]
        leads.create_index([("lead_id", 1)], unique=True)
        leads.create_index([("email", 1)], unique=True)
        leads.create_index([("workflow_id", 1), ("workflow_status", 1)])
        leads.create_index([("assigned_mailbox_id", 1)])
        leads.create_index([("next_send_at", 1)])
        
        # Campaigns indexes
        campaigns = self.db[self.NEW_COLLECTIONS["campaigns"]]
        campaigns.create_index([("campaign_id", 1)], unique=True)
        campaigns.create_index([("status", 1)])
        
        # Templates indexes
        templates = self.db[self.NEW_COLLECTIONS["templates"]]
        templates.create_index([("template_id", 1)], unique=True)
        templates.create_index([("company_brand", 1), ("step_type", 1)])
        
        # Mailboxes indexes
        mailboxes = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        mailboxes.create_index([("mailbox_id", 1)], unique=True)
        mailboxes.create_index([("email_address", 1)], unique=True)
        mailboxes.create_index([("health_status", 1), ("is_active", 1)])
        
        # Sends indexes
        sends = self.db[self.NEW_COLLECTIONS["sends"]]
        sends.create_index([("message_id", 1)], unique=True)
        sends.create_index([("campaign_id", 1), ("lead_id", 1)])
        sends.create_index([("status", 1), ("scheduled_at", 1)])
        
        # Send queue indexes
        queue = self.db[self.NEW_COLLECTIONS["send_queue"]]
        queue.create_index([("scheduled_at", 1), ("status", 1)])
        queue.create_index([("campaign_id", 1)])
        
        # Send logs indexes
        logs = self.db[self.NEW_COLLECTIONS["send_logs"]]
        logs.create_index([("logged_at", -1)])
        logs.create_index([("campaign_id", 1), ("logged_at", -1)])
        
        logger.info("Indexes created successfully")
    
    def _verify_migration(self):
        """Verify migration integrity"""
        logger.info("Verifying migration...")
        
        verifications = []
        
        # Check counts
        for coll_type, new_name in self.NEW_COLLECTIONS.items():
            if new_name in self.db.list_collection_names():
                count = self.db[new_name].count_documents({})
                verifications.append(f"{new_name}: {count} documents")
        
        for v in verifications:
            logger.info(f"  {v}")
        
        # Check for leads without email
        if not self.dry_run:
            leads = self.db[self.NEW_COLLECTIONS["leads"]]
            no_email = leads.count_documents({"email": {"$in": ["", None]}})
            if no_email > 0:
                logger.warning(f"Found {no_email} leads without email - these need attention")
    
    # ============== HELPER METHODS ==============
    
    def _infer_step_type(self, name: str, category: str, step_type: str) -> str:
        """Infer step type from template metadata"""
        if step_type:
            return step_type
        
        name_lower = name.lower()
        
        if any(x in name_lower for x in ["initial", "intro", "first", "email 1"]):
            return "initial"
        elif any(x in name_lower for x in ["follow-up 1", "followup_1", "week1", "email 2"]):
            return "follow_up_1"
        elif any(x in name_lower for x in ["follow-up 2", "followup_2", "week2", "email 3"]):
            return "follow_up_2"
        elif any(x in name_lower for x in ["follow-up 3", "followup_3", "week3", "breakup", "final", "email 4"]):
            return "follow_up_3"
        else:
            return "initial"
    
    def _map_workflow_status(self, old_status: str) -> str:
        """Map legacy status to new WorkflowStatus"""
        status_map = {
            "Not Started": "not_started",
            "pending": "not_started",
            "in_sequence": "in_progress",
            "Email 1 - Sent": "in_progress",
            "Email 2 - Sent": "in_progress",
            "Email 3 - Sent": "in_progress",
            "Email 4 - Sent": "in_progress",
            "Sequence Completed": "completed",
            "completed": "completed",
            "replied": "stopped_reply",
            "Replied - Positive": "stopped_reply",
            "Replied - Negative": "stopped_reply",
            "bounced": "stopped_bounce",
            "Bounced": "stopped_bounce",
            "Unsubscribed": "stopped_unsubscribe",
            "excluded": "stopped_manual",
            "Sequence Stopped": "stopped_manual",
        }
        
        return status_map.get(old_status, "not_started")
    
    def _map_reply_status(self, doc: Dict[str, Any]) -> Optional[str]:
        """Extract reply status from lead document"""
        engagement = doc.get("engagement_status", "")
        reply_type = doc.get("reply_type", "")
        
        if "Positive" in engagement or "interested" in str(reply_type).lower():
            return "positive"
        elif "Negative" in engagement or "not_interested" in str(reply_type).lower():
            return "negative"
        elif "Replied" in engagement or reply_type:
            return "neutral"
        
        return None


# ============== CLEANUP FUNCTIONS ==============

def list_legacy_components() -> List[str]:
    """
    List all legacy components that should be removed.
    """
    components = [
        # Agent files with AI email generation
        "backend/agents/outreach_composer_agent.py",  # FULL EMAIL AI GENERATION - REMOVE
        "backend/agents/reengagement_agent.py",       # DUPLICATE - CONSOLIDATE
        
        # Duplicate template/personalization engines
        "backend/campaigns/personalization_engine.py", # REPLACED BY template_renderer.py
        "backend/outreach/templates.py",               # DUPLICATE - CONSOLIDATE
        "backend/campaigns/email_templates.py",        # KEEP - but update to use new system
        
        # Duplicate automation logic
        "backend/campaigns/automation.py",             # REPLACED BY workflow_engine.py
        "backend/campaigns/executor.py",               # REPLACED BY sending_engine.py + scheduler.py
        
        # Old outreach models (consolidated)
        "backend/outreach/models.py",                  # CONSOLIDATED into outreach_engine/models.py
        
        # Legacy routers that need updating
        "backend/routers/email_campaigns.py",          # UPDATE to use new engine
    ]
    
    return components


def cleanup_legacy_code():
    """
    Instructions for cleaning up legacy code.
    
    This function prints the cleanup steps.
    In production, this would be handled by:
    1. Git commits removing files
    2. Feature flags deprecating old endpoints
    3. Gradual migration with monitoring
    """
    logger.info("=" * 60)
    logger.info("CLEANUP INSTRUCTIONS")
    logger.info("=" * 60)
    
    steps = """
    1. REMOVE OutreachComposerAgent triggers:
       - Delete: backend/agents/outreach_composer_agent.py
       - Remove imports from: backend/agents/__init__.py
       - Update: backend/tasks/lead_agent_tasks.py to remove outreach_composer references
    
    2. REMOVE duplicate template engines:
       - DELETE: backend/campaigns/personalization_engine.py
       - DELETE: backend/outreach/templates.py
       - UPDATE: Any code importing from these to use outreach_engine/template_renderer.py
    
    3. REMOVE old automation/executor:
       - DELETE: backend/campaigns/automation.py
       - DELETE: backend/campaigns/executor.py
       - These are replaced by:
         - outreach_engine/workflow_engine.py
         - outreach_engine/sending_engine.py
         - outreach_engine/scheduler.py
    
    4. CONSOLIDATE models:
       - backend/outreach/models.py is now DEPRECATED
       - All models are in: outreach_engine/models.py
    
    5. UPDATE routers:
       - backend/routers/email_campaigns.py
       - Should import from outreach_engine instead of multiple sources
    
    6. DISABLE old background processes:
       - OutreachComposerAgent scheduled tasks
       - CampaignExecutor background thread
       - Any cron-based email automation
    
    7. RUN migration:
       python -m backend.outreach_engine.migration --execute
    
    8. VERIFY:
       - Test send flows using new engine
       - Verify thread continuity
       - Check AI token logging
       - Monitor mailbox rate limits
    """
    
    print(steps)
    
    return steps


# ============== CLI ==============

def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate legacy email system to Enterprise Outbound Engine"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run migration without making changes"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the migration"
    )
    parser.add_argument(
        "--list-legacy",
        action="store_true",
        help="List legacy components to remove"
    )
    parser.add_argument(
        "--cleanup-instructions",
        action="store_true",
        help="Print cleanup instructions"
    )
    
    args = parser.parse_args()
    
    if args.list_legacy:
        print("\nLegacy components to remove:")
        for component in list_legacy_components():
            print(f"  - {component}")
        return
    
    if args.cleanup_instructions:
        cleanup_legacy_code()
        return
    
    if args.dry_run:
        engine = MigrationEngine(dry_run=True)
        result = engine.run_migration()
        print("\n" + "=" * 60)
        print("DRY RUN RESULTS")
        print("=" * 60)
        print(f"Would migrate:")
        print(f"  - {result['stats']['leads_migrated']} leads")
        print(f"  - {result['stats']['campaigns_migrated']} campaigns")
        print(f"  - {result['stats']['templates_migrated']} templates")
        print(f"  - {result['stats']['mailboxes_migrated']} mailboxes")
        if result['stats']['errors']:
            print(f"  - {len(result['stats']['errors'])} errors")
        return
    
    if args.execute:
        confirm = input("This will modify the database. Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Migration cancelled")
            return
        
        engine = MigrationEngine(dry_run=False)
        result = engine.run_migration()
        print("\n" + "=" * 60)
        print("MIGRATION RESULTS")
        print("=" * 60)
        print(f"Success: {result['success']}")
        print(f"Duration: {result['duration_seconds']:.2f} seconds")
        print(f"Migrated:")
        print(f"  - {result['stats']['leads_migrated']} leads")
        print(f"  - {result['stats']['campaigns_migrated']} campaigns")
        print(f"  - {result['stats']['templates_migrated']} templates")
        print(f"  - {result['stats']['mailboxes_migrated']} mailboxes")
        if result['stats']['errors']:
            print(f"Errors: {len(result['stats']['errors'])}")
            for err in result['stats']['errors'][:10]:
                print(f"  - {err}")
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
