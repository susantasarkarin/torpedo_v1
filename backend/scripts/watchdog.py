#!/usr/bin/env python3
"""
UNIFIED WATCHDOG SCRIPT
=======================

This script runs as a cron job to ensure all background services are running:
1. Gmail sync - Syncs all mailboxes for new emails
2. CPX surveys - Verifies CPX refresh job is active
3. Cint subscription - Checks webhook is active and resubscribes if needed

Run via cron every 5-10 minutes:
    */5 * * * * cd /var/www/campaign_platform/backend && ./venv/bin/python scripts/watchdog.py >> /var/log/campaign_watchdog.log 2>&1
"""
import sys
import os
import asyncio
from datetime import datetime

# Set up path for imports - use venv
BACKEND_PATH = "/var/www/campaign_platform/backend"
sys.path.insert(0, BACKEND_PATH)
os.chdir(BACKEND_PATH)

# Load environment variables (try with dotenv if available, otherwise from .env file manually)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manually load .env if dotenv not available
    env_file = os.path.join(BACKEND_PATH, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
CINT_WEBHOOK_CALLBACK_URL = os.getenv("CINT_WEBHOOK_CALLBACK_URL", "https://torpedo.cogentixresearch.com/api/cint/webhooks/opportunities")


def log(level: str, component: str, message: str):
    """Structured logging"""
    timestamp = datetime.utcnow().isoformat()
    print(f"[{timestamp}] [{level}] [{component}] {message}")


def sync_gmail():
    """Sync all Gmail mailboxes for new emails"""
    log("INFO", "Gmail", "Starting sync for all mailboxes...")
    
    try:
        from app.services.gmail_workspace_service import GmailWorkspaceService
        
        service = GmailWorkspaceService(mongo_uri=MONGO_URI)
        service.load_service_account()
        
        mailboxes = service.list_mailboxes()
        log("INFO", "Gmail", f"Found {len(mailboxes)} mailboxes")
        
        total_synced = 0
        for mb in mailboxes:
            try:
                # Incremental sync, fetch up to 1000 new messages
                result = service.sync_mailbox(mb["id"], max_results=1000, full_sync=False)
                new_count = result.get("new_emails", 0)
                total_synced += new_count
                if new_count > 0:
                    log("INFO", "Gmail", f"  {mb['email']}: +{new_count} new emails")
            except Exception as e:
                log("ERROR", "Gmail", f"  {mb['email']}: {e}")
        
        log("INFO", "Gmail", f"Sync complete: {total_synced} new emails")
        return total_synced
        
    except ImportError:
        log("WARN", "Gmail", "Gmail Workspace Service not available")
        return 0
    except Exception as e:
        log("ERROR", "Gmail", f"Sync failed: {e}")
        return 0


def check_cpx():
    """Verify CPX surveys are being refreshed"""
    log("INFO", "CPX", "Checking CPX survey inventory...")
    
    try:
        from pymongo import MongoClient
        
        client = MongoClient(MONGO_URI)
        cpx_db = client["cpx_research"]
        surveys = cpx_db["cpx_surveys"]
        
        # Count recent surveys (updated in last 10 minutes)
        from datetime import timedelta
        ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
        
        total_count = surveys.count_documents({})
        recent_count = surveys.count_documents({"last_updated": {"$gte": ten_mins_ago}})
        
        log("INFO", "CPX", f"Total surveys: {total_count}, Updated in last 10min: {recent_count}")
        
        if recent_count == 0 and total_count > 0:
            log("WARN", "CPX", "No recent updates - CPX refresh may not be running!")
            # Could trigger a manual refresh here if needed
        
        return total_count
        
    except Exception as e:
        log("ERROR", "CPX", f"Check failed: {e}")
        return 0


async def check_cint():
    """Check Cint subscription and resubscribe if needed"""
    log("INFO", "Cint", "Checking Cint subscription status...")
    
    try:
        from app.integrations.cint_integration import CintIntegration
        from app.models.cint import OpportunitiesSubscriptionConfig
        
        cint = CintIntegration()
        await cint.initialize()
        
        if not cint.cint_service:
            log("WARN", "Cint", "Cint service not available")
            return False
        
        # Check subscription status
        status = await cint.cint_service.get_opportunities_subscription()
        
        if status.get("success"):
            log("INFO", "Cint", "Subscription is active")
            return True
        else:
            log("WARN", "Cint", f"Subscription inactive: {status.get('error', 'Unknown')}")
            
            # Attempt to resubscribe
            log("INFO", "Cint", "Attempting to resubscribe...")
            
            config = OpportunitiesSubscriptionConfig(
                callback_url=CINT_WEBHOOK_CALLBACK_URL,
                include_quotas=True,
                payload_max_size_mb=10,
                payload_max_survey_count=1000,
                send_interval_seconds=30,
                opportunities_filters=[],
            )
            
            result = await cint.cint_service.create_opportunities_subscription(config)
            
            if result.get("success"):
                log("INFO", "Cint", f"Resubscribed successfully: {CINT_WEBHOOK_CALLBACK_URL}")
                return True
            else:
                log("ERROR", "Cint", f"Resubscribe failed: {result.get('error')}")
                return False
                
    except ImportError as e:
        log("WARN", "Cint", f"Cint integration not available: {e}")
        return False
    except Exception as e:
        log("ERROR", "Cint", f"Check failed: {e}")
        return False


def check_cint_surveys():
    """Check Cint survey count in database"""
    log("INFO", "Cint", "Checking Cint survey inventory...")
    
    try:
        from pymongo import MongoClient
        
        client = MongoClient(MONGO_URI)
        cint_db = client["cint_db"]
        surveys = cint_db["cint_surveys"]
        
        total_count = surveys.count_documents({})
        
        log("INFO", "Cint", f"Total Cint surveys in database: {total_count}")
        
        if total_count == 0:
            log("WARN", "Cint", "No Cint surveys found - check webhook connectivity!")
        
        return total_count
        
    except Exception as e:
        log("ERROR", "Cint", f"Survey check failed: {e}")
        return 0


def main():
    """Run all watchdog checks"""
    log("INFO", "Watchdog", "=" * 50)
    log("INFO", "Watchdog", "Starting watchdog checks...")
    log("INFO", "Watchdog", "=" * 50)
    
    # 1. Gmail sync
    gmail_count = sync_gmail()
    
    # 2. CPX check
    cpx_count = check_cpx()
    
    # 3. Cint subscription check (async)
    try:
        asyncio.run(check_cint())
    except Exception as e:
        log("ERROR", "Cint", f"Async check failed: {e}")
    
    # 4. Cint survey count
    cint_count = check_cint_surveys()
    
    # Summary
    log("INFO", "Watchdog", "=" * 50)
    log("INFO", "Watchdog", f"SUMMARY: Gmail={gmail_count} new, CPX={cpx_count} total, Cint={cint_count} total")
    log("INFO", "Watchdog", "=" * 50)


if __name__ == "__main__":
    main()
