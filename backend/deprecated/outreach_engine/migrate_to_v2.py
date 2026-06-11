"""
MIGRATION SCRIPT
================

Migrate from legacy email system to new Enterprise Outbound Engine.

This script:
1. Creates new collections with proper indexes
2. Migrates leads from old collections to outreach_leads_v2
3. Migrates mailboxes to outreach_mailboxes
4. Creates default templates in outreach_templates_v2
5. Backs up old data
6. Validates migration

IMPORTANT: Run this script ONCE after deploying the new engine.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any, List
from pymongo import MongoClient
from bson import ObjectId

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OutreachMigration:
    """
    Migration handler for outreach engine upgrade.
    """
    
    # Collection mappings
    OLD_COLLECTIONS = {
        "leads": ["leads_enriched", "outreach_leads", "campaign_recipients"],
        "campaigns": ["campaigns", "email_campaigns"],
        "templates": ["email_templates", "templates"],
        "mailboxes": ["mailboxes", "gmail_credentials"],
        "sends": ["campaign_sends", "outreach_emails", "email_sends"]
    }
    
    NEW_COLLECTIONS = {
        "leads": "outreach_leads_v2",
        "campaigns": "outreach_campaigns_v2",
        "templates": "outreach_templates_v2",
        "mailboxes": "outreach_mailboxes",
        "sends": "outreach_sends_v2",
        "send_queue": "outreach_send_queue",
        "send_logs": "outreach_send_logs",
        "error_logs": "outreach_error_logs",
        "metrics": "outreach_metrics",
        "ai_logs": "ai_usage_logs"
    }
    
    def __init__(self, mongo_uri: str = None):
        """
        Initialize migration handler.
        
        Args:
            mongo_uri: MongoDB connection URI
        """
        mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(mongo_uri)
        self.db = self.client["email_automation"]
        self.backup_db = self.client["email_automation_backup"]
        
        self.stats = {
            "leads_migrated": 0,
            "campaigns_migrated": 0,
            "templates_created": 0,
            "mailboxes_migrated": 0,
            "errors": []
        }
    
    def run_full_migration(self, skip_disable_check: bool = False):
        """
        Run complete migration to new system.
        
        CRITICAL SEQUENCE:
        0. STOP OLD SYSTEM (prevent double-sends)
        1. Confirm stopped
        2. Backup
        3. Create new collections
        4. Migrate data
        5. Validate
        
        Args:
            skip_disable_check: Skip confirmation (for automated runs)
        """
        logger.info("=" * 60)
        logger.info("STARTING MIGRATION TO ENTERPRISE OUTBOUND ENGINE")
        logger.info("=" * 60)
        
        try:
            # ==========================================
            # STEP 0: DISABLE OLD AUTOMATION (CRITICAL)
            # ==========================================
            logger.info("\n[0/7] DISABLING LEGACY AUTOMATION...")
            logger.info("=" * 60)
            logger.warning("⚠️  THIS WILL STOP ALL OLD EMAIL AUTOMATION")
            logger.info("=" * 60)
            
            disabled = self.disable_old_automation()
            if not disabled:
                raise RuntimeError("Failed to disable old automation - ABORTING")
            
            # Step 1: Confirm disabled
            logger.info("\n[1/7] Confirming legacy system is disabled...")
            if not self.confirm_legacy_disabled():
                raise RuntimeError("Legacy system still active - ABORTING")
            logger.info("  ✓ Legacy automation confirmed DISABLED")
            
            # Step 2: Backup old data
            logger.info("\n[2/7] Backing up existing data...")
            self.backup_old_data()
            
            # Step 3: Create new collections with indexes
            logger.info("\n[3/7] Creating new collections and indexes...")
            self.create_new_collections()
            
            # Step 4: Migrate leads
            logger.info("\n[4/7] Migrating leads...")
            self.migrate_leads()
            
            # Step 5: Migrate/create mailboxes
            logger.info("\n[5/7] Setting up mailboxes...")
            self.setup_mailboxes()
            
            # Step 6: Create default templates
            logger.info("\n[6/7] Creating default templates...")
            self.create_default_templates()
            
            # Step 7: Validate migration
            logger.info("\n[7/7] Validating migration...")
            self.validate_migration()
            
            # Print summary
            self.print_summary()
            
        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            raise
    
    def backup_old_data(self):
        """
        Backup old collections before migration.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        for category, collection_names in self.OLD_COLLECTIONS.items():
            for coll_name in collection_names:
                if coll_name in self.db.list_collection_names():
                    # Copy to backup database
                    backup_name = f"{coll_name}_backup_{timestamp}"
                    
                    docs = list(self.db[coll_name].find())
                    if docs:
                        self.backup_db[backup_name].insert_many(docs)
                        logger.info(f"  Backed up {len(docs)} docs from {coll_name} -> {backup_name}")
    
    def create_new_collections(self):
        """
        Create new collections with proper indexes.
        """
        # Create indexes for each new collection
        
        # Leads
        leads = self.db[self.NEW_COLLECTIONS["leads"]]
        leads.create_index([("lead_id", 1)], unique=True)
        leads.create_index([("email", 1)], unique=True)
        leads.create_index([("workflow_id", 1), ("workflow_status", 1)])
        leads.create_index([("campaign_id", 1), ("workflow_status", 1)])
        leads.create_index([("assigned_mailbox_id", 1)])
        leads.create_index([("next_send_at", 1), ("workflow_status", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['leads']} with indexes")
        
        # Campaigns
        campaigns = self.db[self.NEW_COLLECTIONS["campaigns"]]
        campaigns.create_index([("campaign_id", 1)], unique=True)
        campaigns.create_index([("status", 1), ("is_active", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['campaigns']} with indexes")
        
        # Templates
        templates = self.db[self.NEW_COLLECTIONS["templates"]]
        templates.create_index([("template_id", 1)], unique=True)
        templates.create_index([("company_brand", 1), ("step_type", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['templates']} with indexes")
        
        # Mailboxes
        mailboxes = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        mailboxes.create_index([("mailbox_id", 1)], unique=True)
        mailboxes.create_index([("email_address", 1)], unique=True)
        mailboxes.create_index([("health_status", 1), ("is_active", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['mailboxes']} with indexes")
        
        # Sends
        sends = self.db[self.NEW_COLLECTIONS["sends"]]
        sends.create_index([("send_id", 1)], unique=True)
        sends.create_index([("message_id", 1)], unique=True)
        sends.create_index([("campaign_id", 1), ("lead_id", 1)])
        sends.create_index([("status", 1), ("scheduled_at", 1)])
        sends.create_index([("mailbox_id", 1), ("sent_at", -1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['sends']} with indexes")
        
        # Send Queue
        queue = self.db[self.NEW_COLLECTIONS["send_queue"]]
        queue.create_index([("scheduled_at", 1), ("status", 1)])
        queue.create_index([("campaign_id", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['send_queue']} with indexes")
        
        # Logs
        send_logs = self.db[self.NEW_COLLECTIONS["send_logs"]]
        send_logs.create_index([("logged_at", -1)])
        send_logs.create_index([("campaign_id", 1), ("logged_at", -1)])
        send_logs.create_index([("mailbox_used", 1), ("logged_at", -1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['send_logs']} with indexes")
        
        error_logs = self.db[self.NEW_COLLECTIONS["error_logs"]]
        error_logs.create_index([("logged_at", -1)])
        error_logs.create_index([("error_type", 1)])
        logger.info(f"  Created {self.NEW_COLLECTIONS['error_logs']} with indexes")
    
    def migrate_leads(self):
        """
        Migrate leads from old collections to new format.
        """
        new_leads = self.db[self.NEW_COLLECTIONS["leads"]]
        
        # Try each old lead collection
        for old_collection in self.OLD_COLLECTIONS["leads"]:
            if old_collection not in self.db.list_collection_names():
                continue
            
            old_leads = list(self.db[old_collection].find())
            logger.info(f"  Found {len(old_leads)} leads in {old_collection}")
            
            for old_lead in old_leads:
                try:
                    # Check if already migrated
                    email = old_lead.get("email")
                    if not email:
                        continue
                    
                    existing = new_leads.find_one({"email": email})
                    if existing:
                        continue
                    
                    # Transform to new format
                    new_lead = self._transform_lead(old_lead)
                    
                    # Insert
                    new_leads.insert_one(new_lead)
                    self.stats["leads_migrated"] += 1
                    
                except Exception as e:
                    self.stats["errors"].append(f"Lead migration error: {e}")
        
        logger.info(f"  Migrated {self.stats['leads_migrated']} leads")
    
    def _transform_lead(self, old: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform old lead format to new format.
        """
        now = datetime.utcnow()
        
        return {
            "lead_id": old.get("lead_id", str(ObjectId())),
            "email": old.get("email"),
            "first_name": old.get("first_name", old.get("name", "").split()[0] if old.get("name") else ""),
            "last_name": old.get("last_name", old.get("name", "").split()[-1] if old.get("name") and len(old.get("name", "").split()) > 1 else ""),
            "company": old.get("company", old.get("company_name", "")),
            "industry": old.get("industry", old.get("company_industry", "")),
            "title": old.get("title", old.get("job_title", "")),
            
            # Workflow state - start fresh
            "workflow_id": None,
            "campaign_id": None,
            "current_step": 0,
            "workflow_status": "not_started",
            
            # Mailbox - not assigned yet
            "assigned_mailbox_id": None,
            
            # Thread continuity - will be set on first send
            "thread_id": None,
            "message_id_last_sent": None,
            "in_reply_to": None,
            "references": [],
            
            # AI context - will be generated on demand
            "ai_context_block": None,
            "ai_context_generated_at": None,
            "ai_tokens_used": 0,
            
            # Personalization
            "personalization_level": old.get("personalization_level", "light"),
            "custom_fields": old.get("custom_fields", {}),
            
            # Engagement - preserve if exists
            "last_sent_at": old.get("last_sent_at", old.get("last_contacted_at")),
            "next_send_at": None,
            "reply_status": old.get("reply_status"),
            "reply_detected_at": old.get("reply_detected_at"),
            "bounce_status": None,
            "bounce_detected_at": None,
            "unsubscribe_detected_at": None,
            
            # Metrics
            "emails_sent": old.get("emails_sent", 0),
            "emails_opened": old.get("emails_opened", 0),
            "emails_clicked": old.get("emails_clicked", 0),
            "last_opened_at": old.get("last_opened_at"),
            "last_clicked_at": old.get("last_clicked_at"),
            
            # Timestamps
            "created_at": old.get("created_at", now),
            "updated_at": now,
            "workflow_started_at": None,
            "workflow_completed_at": None,
            
            # Tags
            "tags": old.get("tags", []),
            "source": old.get("source", "migrated")
        }
    
    def setup_mailboxes(self):
        """
        Setup mailboxes from old config or create defaults.
        """
        new_mailboxes = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        
        # Try to migrate from old collections
        migrated = False
        for old_collection in self.OLD_COLLECTIONS["mailboxes"]:
            if old_collection not in self.db.list_collection_names():
                continue
            
            old_boxes = list(self.db[old_collection].find())
            for old_box in old_boxes:
                try:
                    email = old_box.get("email", old_box.get("email_address"))
                    if not email:
                        continue
                    
                    existing = new_mailboxes.find_one({"email_address": email})
                    if existing:
                        continue
                    
                    new_box = self._transform_mailbox(old_box)
                    new_mailboxes.insert_one(new_box)
                    self.stats["mailboxes_migrated"] += 1
                    migrated = True
                    
                except Exception as e:
                    self.stats["errors"].append(f"Mailbox migration error: {e}")
        
        # Create default mailboxes if none exist
        if not migrated and new_mailboxes.count_documents({}) == 0:
            logger.info("  Creating default mailbox placeholders...")
            self._create_default_mailboxes()
        
        logger.info(f"  Setup {self.stats['mailboxes_migrated']} mailboxes")
    
    def _transform_mailbox(self, old: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform old mailbox format to new format.
        """
        now = datetime.utcnow()
        email = old.get("email", old.get("email_address", ""))
        
        return {
            "mailbox_id": old.get("mailbox_id", str(ObjectId())),
            "email_address": email,
            "display_name": old.get("display_name", old.get("name", email.split("@")[0] if email else "")),
            "reply_to": old.get("reply_to"),
            
            "provider": old.get("provider", "gmail"),
            "credentials_id": old.get("credentials_id"),
            
            "signature_html": old.get("signature_html", old.get("email_signature", "")),
            "signature_plain": old.get("signature_plain", ""),
            
            "daily_send_count": 0,
            "hourly_send_count": 0,
            "daily_send_limit": old.get("daily_send_limit", 400),
            "hourly_send_limit": old.get("hourly_send_limit", 60),
            "last_send_at": None,
            "daily_reset_at": None,
            "hourly_reset_at": None,
            
            "health_status": "healthy",
            "warmup_status": old.get("warmup_status", "complete"),
            "warmup_day": old.get("warmup_day", 0),
            "bounce_rate_24h": 0.0,
            "complaint_rate_24h": 0.0,
            
            "paused_until": None,
            "pause_reason": None,
            
            "is_active": old.get("is_active", True),
            "created_at": old.get("created_at", now),
            "updated_at": now
        }
    
    def _create_default_mailboxes(self):
        """
        Create default mailbox entries (placeholder - need real config).
        """
        # These are placeholders - actual email credentials need to be configured
        defaults = [
            {
                "mailbox_id": str(ObjectId()),
                "email_address": "outreach1@surveyfieldwork.com",
                "display_name": "Survey Fieldwork",
                "provider": "gmail",
                "daily_send_limit": 400,
                "hourly_send_limit": 60,
                "signature_html": "<p>Best regards,<br>Survey Fieldwork Team</p>",
                "health_status": "healthy",
                "warmup_status": "complete",
                "is_active": False,  # Disabled until configured
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        ]
        
        new_mailboxes = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        for mb in defaults:
            new_mailboxes.insert_one(mb)
            logger.info(f"    Created placeholder mailbox: {mb['email_address']}")
    
    def create_default_templates(self):
        """
        Create default email templates.
        """
        try:
            # Import here to avoid circular dependency
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from outreach_engine.template_renderer import create_default_templates
            
            # Create for both brands
            for brand in ["surveyfieldwork", "cogentixresearch"]:
                try:
                    created = create_default_templates(self.db, brand)
                    self.stats["templates_created"] += len(created)
                    logger.info(f"  Created {len(created)} templates for {brand}")
                except Exception as e:
                    logger.warning(f"  Could not create templates for {brand}: {e}")
        except ImportError:
            logger.warning("  Could not import template_renderer, skipping template creation")
    
    def validate_migration(self):
        """
        Validate migration was successful.
        """
        # Check collections exist
        expected = list(self.NEW_COLLECTIONS.values())
        existing = self.db.list_collection_names()
        
        missing = [c for c in expected if c not in existing]
        if missing:
            logger.warning(f"  Missing collections: {missing}")
        
        # Check lead count
        leads = self.db[self.NEW_COLLECTIONS["leads"]]
        lead_count = leads.count_documents({})
        logger.info(f"  Total leads in new collection: {lead_count}")
        
        # Check mailbox count
        mailboxes = self.db[self.NEW_COLLECTIONS["mailboxes"]]
        mailbox_count = mailboxes.count_documents({})
        logger.info(f"  Total mailboxes: {mailbox_count}")
        
        # Check templates
        templates = self.db[self.NEW_COLLECTIONS["templates"]]
        template_count = templates.count_documents({})
        logger.info(f"  Total templates: {template_count}")
        
        # Check indexes
        for coll_name in expected[:5]:  # Check first 5
            coll = self.db[coll_name]
            indexes = coll.index_information()
            logger.info(f"  {coll_name}: {len(indexes)} indexes")
    
    def print_summary(self):
        """
        Print migration summary.
        """
        logger.info("\n" + "=" * 60)
        logger.info("MIGRATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Leads migrated: {self.stats['leads_migrated']}")
        logger.info(f"  Mailboxes setup: {self.stats['mailboxes_migrated']}")
        logger.info(f"  Templates created: {self.stats['templates_created']}")
        
        if self.stats["errors"]:
            logger.warning(f"\n  Errors ({len(self.stats['errors'])}):")
            for err in self.stats["errors"][:10]:
                logger.warning(f"    - {err}")
        
        logger.info("\nNEXT STEPS:")
        logger.info("  1. Configure mailbox credentials in outreach_mailboxes")
        logger.info("  2. Update mailbox signatures")
        logger.info("  3. Activate mailboxes (set is_active=True)")
        logger.info("  4. Create campaigns using the new engine")
        logger.info("  5. Test with dry_run=True before sending")


def cleanup_old_components():
    """
    Identify old components that can be removed after migration.
    """
    logger.info("\n" + "=" * 60)
    logger.info("OLD COMPONENTS TO REMOVE")
    logger.info("=" * 60)
    
    components = [
        # Agents to remove
        ("agents/outreach_composer_agent.py", "OutreachComposerAgent - Full AI email generation"),
        ("agents/reengagement_agent.py", "ReengagementAgent - Parallel AI automation"),
        
        # Old campaign modules
        ("campaigns/automation.py", "CampaignAutomation - Legacy automation"),
        ("campaigns/executor.py", "CampaignExecutor - Old executor"),
        ("campaigns/personalization_engine.py", "PersonalizationEngine - Duplicate engine"),
        
        # Old outreach modules  
        ("outreach/templates.py", "Old templates - Replaced by outreach_engine/template_renderer.py"),
        
        # Old routers
        ("routers/email_campaigns.py", "Old email campaigns router - Replace with new API"),
        
        # Gmail automation
        ("gmail_automation/email_composer.py", "EmailComposer - Old composer"),
    ]
    
    for path, description in components:
        logger.info(f"  REMOVE: {path}")
        logger.info(f"          {description}")
    
    logger.info("\nAfter confirming new system works:")
    logger.info("  1. Remove the files listed above")
    logger.info("  2. Update imports in main.py and other modules")
    logger.info("  3. Update Celery tasks to use new engine")
    logger.info("  4. Archive old collections (already backed up)")


if __name__ == "__main__":
    # Run migration
    migration = OutreachMigration()
    migration.run_full_migration()
    
    # Show cleanup recommendations
    cleanup_old_components()
