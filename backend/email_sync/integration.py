"""
EMAIL SYNC INTEGRATION
======================

Example integration of email sync module with FastAPI application.

Usage:
    from email_sync.integration import setup_email_sync
    
    app = FastAPI()
    setup_email_sync(app)
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from pymongo import MongoClient

from .orchestrator import EmailSyncOrchestrator
from .router import router, _orchestrator

logger = logging.getLogger(__name__)


def setup_email_sync(
    app: FastAPI,
    mongo_uri: Optional[str] = None,
    db_name: str = "campaign_platform",
    auto_start: bool = True,
    route_prefix: str = "/api/v1"
):
    """
    Set up email sync integration with FastAPI app.
    
    Args:
        app: FastAPI application instance
        mongo_uri: MongoDB connection URI (defaults to MONGO_URI env var)
        db_name: Database name
        auto_start: Whether to start workers on app startup
        route_prefix: API route prefix
        
    Example:
        app = FastAPI()
        setup_email_sync(app, mongo_uri="mongodb://localhost:27017")
    """
    global _orchestrator
    
    mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage email sync lifecycle"""
        global _orchestrator
        
        # Startup
        logger.info("Initializing email sync system...")
        _orchestrator = EmailSyncOrchestrator(
            mongo_uri=mongo_uri,
            db_name=db_name
        )
        
        if auto_start:
            _orchestrator.start()
            logger.info("Email sync workers started")
        
        yield
        
        # Shutdown
        if _orchestrator:
            _orchestrator.stop()
            logger.info("Email sync workers stopped")
    
    # Set lifespan if not already set
    if not hasattr(app, 'router') or app.router.lifespan_context is None:
        app.router.lifespan_context = lifespan
    
    # Include router
    app.include_router(router, prefix=route_prefix)
    
    logger.info(f"Email sync routes registered at {route_prefix}/email-sync")


def get_orchestrator_instance() -> Optional[EmailSyncOrchestrator]:
    """Get the current orchestrator instance"""
    global _orchestrator
    return _orchestrator


# =========================================================================
# EXAMPLE MAIN.PY INTEGRATION
# =========================================================================

EXAMPLE_MAIN = '''
"""
Example FastAPI Application with Email Sync
"""

from fastapi import FastAPI
from email_sync.integration import setup_email_sync

app = FastAPI(title="CRM API", version="1.0.0")

# Set up email sync
setup_email_sync(
    app,
    mongo_uri="mongodb://localhost:27017",
    db_name="email_automation",
    auto_start=True
)

# Your other routes...
@app.get("/")
async def root():
    return {"message": "CRM API"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''


# =========================================================================
# ENVIRONMENT VARIABLES REFERENCE
# =========================================================================

ENV_VARS = """
# Email Sync Configuration
MONGO_URI=mongodb://localhost:27017
MONGODB_DB=email_automation

# Gmail OAuth (for Gmail provider)
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Rate Limits (optional, defaults shown)
EMAIL_SYNC_RATE_PER_MINUTE=50
EMAIL_SYNC_RATE_PER_HOUR=500
EMAIL_SYNC_RATE_PER_DAY=5000
EMAIL_SYNC_MAX_CONCURRENT_BACKFILLS=5
EMAIL_SYNC_MAX_CONCURRENT_SYNCS=20
"""


# =========================================================================
# API DOCUMENTATION
# =========================================================================

API_DOCS = """
# Email Sync API

## Mailbox Management

### Register Mailbox
POST /api/v1/email-sync/mailboxes
{
    "email": "sales@company.com",
    "provider": "gmail",  // or "imap"
    "display_name": "Sales Team",
    "credentials": {
        "access_token": "ya29...",
        "refresh_token": "1//..."
    },
    "auto_start_backfill": true
}

### List Mailboxes
GET /api/v1/email-sync/mailboxes?skip=0&limit=50&active_only=true

### Get Mailbox Status
GET /api/v1/email-sync/mailboxes/{mailbox_id}

### Update Mailbox
PATCH /api/v1/email-sync/mailboxes/{mailbox_id}
{
    "sync_enabled": false
}

### Delete Mailbox
DELETE /api/v1/email-sync/mailboxes/{mailbox_id}?delete_emails=false

## Alias Management

### Add Alias
POST /api/v1/email-sync/mailboxes/{mailbox_id}/aliases
{
    "alias_email": "support@company.com",
    "display_name": "Support Team"
}

### List Aliases
GET /api/v1/email-sync/mailboxes/{mailbox_id}/aliases

### Delete Alias
DELETE /api/v1/email-sync/mailboxes/{mailbox_id}/aliases/{alias_id}

## Sync Controls

### Trigger Backfill
POST /api/v1/email-sync/mailboxes/{mailbox_id}/backfill

### Trigger Incremental Sync
POST /api/v1/email-sync/mailboxes/{mailbox_id}/sync

### Pause Sync
POST /api/v1/email-sync/mailboxes/{mailbox_id}/pause

### Resume Sync
POST /api/v1/email-sync/mailboxes/{mailbox_id}/resume

## Email Operations

### List Emails
GET /api/v1/email-sync/mailboxes/{mailbox_id}/emails?page=1&page_size=50&category=invoice

### Get Email
GET /api/v1/email-sync/mailboxes/{mailbox_id}/emails/{email_id}

### Update Email Category
PATCH /api/v1/email-sync/mailboxes/{mailbox_id}/emails/{email_id}/category?category=invoice

## System

### Health Check
GET /api/v1/email-sync/health

### Get Errors
GET /api/v1/email-sync/errors

### Start Workers
POST /api/v1/email-sync/start

### Stop Workers
POST /api/v1/email-sync/stop

### List Categories
GET /api/v1/email-sync/categories
"""

