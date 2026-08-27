"""
Gmail Router - Handles Gmail API integration with OAuth 2.0

Provides endpoints for:
- OAuth authentication flow
- Email fetching and analysis
- Email composition and sending
- Account/alias management
- Rate limiting
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

from fastapi import APIRouter, HTTPException, Request, Query, Body, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

# Add gmail_automation to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from gmail_automation.auth import GmailAuthenticator
    from gmail_automation.email_fetcher import EmailFetcher
    from gmail_automation.categorizer import EmailCategorizer, CategorizationRule, CategoryPriority
    from gmail_automation.sentiment_analyzer import SentimentAnalyzer
    from gmail_automation.email_composer import EmailComposer, EmailTemplate
    from gmail_automation.account_manager import AccountManager, EmailAccount, EmailAlias, RoutingRule
    GMAIL_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Gmail automation import error: {e}")
    GMAIL_AVAILABLE = False
    # Create dummy classes to prevent NameError
    GmailAuthenticator = None
    EmailFetcher = None
    EmailCategorizer = None
    CategorizationRule = None
    CategoryPriority = None
    SentimentAnalyzer = None
    EmailComposer = None
    EmailTemplate = None
    AccountManager = None
    EmailAccount = None
    EmailAlias = None
    RoutingRule = None

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/gmail",
    tags=["gmail"]
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=8000,
)
gmail_db = mongo_client["torpedo_gmail"]
accounts_collection = gmail_db["accounts"]
rate_limits_collection = gmail_db["rate_limits"]
email_cache_collection = gmail_db["email_cache"]
settings_collection = gmail_db["settings"]

# Email automation database for leads
email_automation_db = mongo_client["email_automation"]
email_leads_collection = email_automation_db["email_leads"]

# In-memory cache for authenticated services
_gmail_services: Dict[str, Any] = {}
_authenticators: Dict[str, Any] = {}  # Changed type hint to Any since GmailAuthenticator might be None


# ============================================
# Pydantic Models
# ============================================

class GmailAccountCreate(BaseModel):
    """Model for creating a new Gmail account"""
    account_id: str = Field(..., description="Unique identifier for the account")
    display_name: str = Field("", description="Display name for the account")
    is_default: bool = Field(False, description="Set as default account")


class GmailAliasCreate(BaseModel):
    """Model for adding an alias"""
    email: str = Field(..., description="Alias email address")
    display_name: str = Field("", description="Display name for alias")
    signature: str = Field("", description="Email signature")
    is_default: bool = Field(False, description="Set as default sending address")


class RateLimitSettings(BaseModel):
    """Model for rate limit settings"""
    daily_limit: int = Field(500, ge=1, le=2000, description="Maximum emails per day")
    hourly_limit: int = Field(50, ge=1, le=500, description="Maximum emails per hour")
    per_minute_limit: int = Field(10, ge=1, le=100, description="Maximum emails per minute")
    cooldown_seconds: int = Field(5, ge=1, le=60, description="Minimum seconds between emails")


class EmailComposeRequest(BaseModel):
    """Model for composing an email"""
    to: List[str] = Field(..., description="Recipient email addresses")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body")
    cc: List[str] = Field(default=[], description="CC recipients")
    bcc: List[str] = Field(default=[], description="BCC recipients")
    html_body: Optional[str] = Field(None, description="HTML body")
    template_name: Optional[str] = Field(None, description="Template to use")
    from_alias: Optional[str] = Field(None, description="Sender alias to use")
    account_id: Optional[str] = Field(None, description="Account to send from")


class EmailReplyRequest(BaseModel):
    """Model for replying to an email"""
    email_id: str = Field(..., description="ID of email to reply to")
    body: str = Field(..., description="Reply body")
    template_name: Optional[str] = Field(None, description="Template to use")
    use_ai: bool = Field(False, description="Generate content with AI")


class CategorizationRuleCreate(BaseModel):
    """Model for creating a categorization rule"""
    name: str
    category: str
    keywords: List[str] = []
    sender_patterns: List[str] = []
    subject_patterns: List[str] = []
    priority: str = "MEDIUM"


# ============================================
# Helper Functions
# ============================================

def get_account_from_db(account_id: str) -> Optional[Dict]:
    """Get account from MongoDB"""
    return accounts_collection.find_one({"account_id": account_id})


def save_account_to_db(account_data: Dict) -> bool:
    """Save account to MongoDB"""
    try:
        accounts_collection.update_one(
            {"account_id": account_data["account_id"]},
            {"$set": {**account_data, "updated_at": datetime.utcnow()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error saving account: {e}")
        return False


def get_rate_limit_settings() -> Dict:
    """Get rate limit settings from MongoDB"""
    try:
        settings = settings_collection.find_one({"_id": "rate_limits"}, max_time_ms=3000)
    except Exception:
        settings = None
    if settings:
        return {
            "daily_limit": settings.get("daily_limit", 500),
            "hourly_limit": settings.get("hourly_limit", 50),
            "per_minute_limit": settings.get("per_minute_limit", 10),
            "cooldown_seconds": settings.get("cooldown_seconds", 5)
        }
    return {
        "daily_limit": 500,
        "hourly_limit": 50,
        "per_minute_limit": 10,
        "cooldown_seconds": 5
    }


def check_rate_limit(account_id: str) -> Dict[str, Any]:
    """Check if account can send email based on rate limits"""
    settings = get_rate_limit_settings()
    now = datetime.utcnow()
    
    # Get or create rate limit record
    rate_record = rate_limits_collection.find_one({"account_id": account_id})
    
    if not rate_record:
        rate_record = {
            "account_id": account_id,
            "daily_count": 0,
            "hourly_count": 0,
            "minute_count": 0,
            "last_send": None,
            "day_start": now,
            "hour_start": now,
            "minute_start": now
        }
        rate_limits_collection.insert_one(rate_record)
    
    # Reset counters if needed
    updates = {}
    
    if rate_record.get("day_start"):
        if (now - rate_record["day_start"]).days >= 1:
            updates["daily_count"] = 0
            updates["day_start"] = now
    
    if rate_record.get("hour_start"):
        if (now - rate_record["hour_start"]).seconds >= 3600:
            updates["hourly_count"] = 0
            updates["hour_start"] = now
    
    if rate_record.get("minute_start"):
        if (now - rate_record["minute_start"]).seconds >= 60:
            updates["minute_count"] = 0
            updates["minute_start"] = now
    
    if updates:
        rate_limits_collection.update_one(
            {"account_id": account_id},
            {"$set": updates}
        )
        rate_record.update(updates)
    
    # Check limits
    daily_count = rate_record.get("daily_count", 0)
    hourly_count = rate_record.get("hourly_count", 0)
    minute_count = rate_record.get("minute_count", 0)
    last_send = rate_record.get("last_send")
    
    can_send = True
    reason = None
    wait_seconds = 0
    
    if daily_count >= settings["daily_limit"]:
        can_send = False
        reason = "Daily limit reached"
        # Calculate wait until midnight
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        wait_seconds = (tomorrow - now).seconds
    elif hourly_count >= settings["hourly_limit"]:
        can_send = False
        reason = "Hourly limit reached"
        wait_seconds = 3600 - (now - rate_record.get("hour_start", now)).seconds
    elif minute_count >= settings["per_minute_limit"]:
        can_send = False
        reason = "Per-minute limit reached"
        wait_seconds = 60 - (now - rate_record.get("minute_start", now)).seconds
    elif last_send:
        cooldown_remaining = settings["cooldown_seconds"] - (now - last_send).seconds
        if cooldown_remaining > 0:
            can_send = False
            reason = "Cooldown period"
            wait_seconds = cooldown_remaining
    
    return {
        "can_send": can_send,
        "reason": reason,
        "wait_seconds": wait_seconds,
        "daily_count": daily_count,
        "daily_limit": settings["daily_limit"],
        "hourly_count": hourly_count,
        "hourly_limit": settings["hourly_limit"],
        "minute_count": minute_count,
        "per_minute_limit": settings["per_minute_limit"]
    }


def record_email_sent(account_id: str):
    """Record that an email was sent"""
    now = datetime.utcnow()
    rate_limits_collection.update_one(
        {"account_id": account_id},
        {
            "$inc": {
                "daily_count": 1,
                "hourly_count": 1,
                "minute_count": 1
            },
            "$set": {
                "last_send": now
            }
        },
        upsert=True
    )


def get_authenticator(account_id: str):
    """Get or create authenticator for account"""
    if account_id not in _authenticators:
        config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'gmail_config', account_id)
        os.makedirs(config_dir, exist_ok=True)
        
        _authenticators[account_id] = GmailAuthenticator(
            credentials_path="credentials.json",
            token_path=f"token_{account_id}.pickle",
            config_dir=config_dir
        )
    
    return _authenticators[account_id]


# ============================================
# Authentication Endpoints
# ============================================

@router.get("/auth/status")
async def get_auth_status(request: Request):
    """Get authentication status for all accounts"""
    try:
        accounts = list(accounts_collection.find({}, {"_id": 0}))
        
        status_list = []
        for account in accounts:
            account_id = account.get("account_id")
            auth = get_authenticator(account_id)
            
            status_list.append({
                "account_id": account_id,
                "email": account.get("email", ""),
                "display_name": account.get("display_name", ""),
                "is_default": account.get("is_default", False),
                "authenticated": auth.is_authenticated(),
                "aliases": account.get("aliases", []),
                "created_at": account.get("created_at"),
                "updated_at": account.get("updated_at")
            })
        
        return {"accounts": status_list}
    
    except Exception as e:
        logger.error(f"Error getting auth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/add-account")
async def add_gmail_account(account: GmailAccountCreate, request: Request):
    """Add a new Gmail account for authentication"""
    try:
        # Check if account already exists
        existing = get_account_from_db(account.account_id)
        if existing:
            raise HTTPException(status_code=400, detail="Account already exists")
        
        # If setting as default, unset other defaults
        if account.is_default:
            accounts_collection.update_many({}, {"$set": {"is_default": False}})
        
        # Create account record
        account_data = {
            "account_id": account.account_id,
            "display_name": account.display_name or account.account_id,
            "email": "",
            "is_default": account.is_default,
            "aliases": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        save_account_to_db(account_data)
        
        # Initialize authenticator
        get_authenticator(account.account_id)
        
        return {
            "success": True,
            "message": f"Account {account.account_id} added. Please authenticate via OAuth.",
            "account": account_data
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Store pending OAuth states
_oauth_states: Dict[str, dict] = {}

@router.get("/auth/url")
async def get_auth_url_v2(request: Request, account_id: Optional[str] = None):
    """
    Get OAuth authorization URL for web-based authentication.
    Uses proper redirect URI for web OAuth flow.
    """
    try:
        from google_auth_oauthlib.flow import Flow
        import secrets
        
        aid = account_id or f"temp_{int(datetime.utcnow().timestamp())}"
        credentials_path = os.path.join(os.path.dirname(__file__), '..', '..', 'gmail_automation', 'credentials.json')
        
        if not os.path.exists(credentials_path):
            raise HTTPException(status_code=500, detail="OAuth credentials not configured")
        
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.settings.basic"
        ]
        
        # Use the backend callback URL
        redirect_uri = "http://localhost:8000/gmail/auth/callback"
        
        flow = Flow.from_client_secrets_file(
            credentials_path,
            scopes=scopes,
            redirect_uri=redirect_uri
        )
        
        # Generate state token for security
        state = secrets.token_urlsafe(32)
        
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=state
        )
        
        # Store state for callback verification
        _oauth_states[state] = {
            "account_id": aid,
            "flow": flow,
            "created_at": datetime.utcnow()
        }
        
        return {
            "auth_url": auth_url,
            "account_id": aid,
            "message": "Open this URL to authenticate with Google"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/callback")
async def oauth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """
    OAuth callback endpoint - Google redirects here after user consent.
    """
    try:
        if error:
            return RedirectResponse(
                url=f"http://localhost:5173/settings?error={error}",
                status_code=302
            )
        
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing code or state parameter")
        
        # Verify state
        if state not in _oauth_states:
            raise HTTPException(status_code=400, detail="Invalid state parameter")
        
        oauth_data = _oauth_states.pop(state)
        flow = oauth_data["flow"]
        account_id = oauth_data["account_id"]
        
        # Exchange code for credentials
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Save credentials
        config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'gmail_config', account_id)
        os.makedirs(config_dir, exist_ok=True)
        token_path = os.path.join(config_dir, 'token.json')
        
        with open(token_path, 'w') as f:
            f.write(credentials.to_json())
        
        # Get user email
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress', '')
        
        # Update or create account in database
        existing = accounts_collection.find_one({"account_id": account_id})
        if existing:
            accounts_collection.update_one(
                {"account_id": account_id},
                {"$set": {"email": email, "is_authenticated": True, "updated_at": datetime.utcnow()}}
            )
        else:
            accounts_collection.insert_one({
                "account_id": account_id,
                "email": email,
                "display_name": email.split("@")[0],
                "is_default": False,
                "is_authenticated": True,
                "aliases": [],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
        
        # Cache service
        _gmail_services[account_id] = service
        
        # Redirect back to frontend settings page with success
        return RedirectResponse(
            url=f"http://localhost:5173/settings?gmail_auth=success&email={email}",
            status_code=302
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return RedirectResponse(
            url=f"http://localhost:5173/settings?error={str(e)}",
            status_code=302
        )


@router.get("/auth/login/{account_id}")
async def initiate_oauth(account_id: str, request: Request):
    """
    Initiate OAuth flow for a Gmail account.
    This will redirect to Google's consent screen.
    """
    try:
        account = get_account_from_db(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        auth = get_authenticator(account_id)
        
        # Check if already authenticated
        if auth.is_authenticated():
            return {
                "success": True,
                "message": "Already authenticated",
                "email": auth.get_user_email()
            }
        
        # Authenticate (this will open browser)
        service = auth.authenticate()
        email = auth.get_user_email()
        
        # Update account with email
        accounts_collection.update_one(
            {"account_id": account_id},
            {"$set": {"email": email, "updated_at": datetime.utcnow()}}
        )
        
        # Cache service
        _gmail_services[account_id] = service
        
        return {
            "success": True,
            "message": "Authentication successful",
            "email": email
        }
    
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auth/logout/{account_id}")
async def logout_account(account_id: str, request: Request):
    """Logout and revoke credentials for an account"""
    try:
        if account_id in _authenticators:
            _authenticators[account_id].revoke_credentials()
            del _authenticators[account_id]
        
        if account_id in _gmail_services:
            del _gmail_services[account_id]
        
        accounts_collection.update_one(
            {"account_id": account_id},
            {"$set": {"email": "", "updated_at": datetime.utcnow()}}
        )
        
        return {"success": True, "message": "Logged out successfully"}
    
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/auth/account/{account_id}")
async def delete_account(account_id: str, request: Request):
    """Delete a Gmail account configuration"""
    try:
        # Logout first
        if account_id in _authenticators:
            try:
                _authenticators[account_id].revoke_credentials()
            except:
                pass
            del _authenticators[account_id]
        
        if account_id in _gmail_services:
            del _gmail_services[account_id]
        
        # Delete from database
        accounts_collection.delete_one({"account_id": account_id})
        rate_limits_collection.delete_one({"account_id": account_id})
        
        return {"success": True, "message": "Account deleted"}
    
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Account Management Endpoints
# ============================================

@router.get("/accounts")
async def get_accounts(request: Request):
    """Get all configured Gmail accounts"""
    try:
        accounts = list(accounts_collection.find({}, {"_id": 0}))
        
        # Enrich with authentication status
        for account in accounts:
            account_id = account.get("account_id")
            auth = get_authenticator(account_id)
            account["is_authenticated"] = auth.is_authenticated()
            # Rename for frontend compatibility
            account["id"] = account.get("account_id", "")
            account["email"] = account.get("email", account.get("account_id", ""))
            account["name"] = account.get("display_name", "")
        
        return {"accounts": accounts}
    
    except Exception as e:
        logger.error(f"Get accounts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts")
async def create_account(request: Request):
    """Create a new Gmail account configuration"""
    try:
        data = await request.json()
        email = data.get("email", "")
        name = data.get("name", "")
        is_default = data.get("is_default", False)
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Use email as account_id
        account_id = email.split("@")[0].replace(".", "_")
        
        # Check if account already exists
        existing = accounts_collection.find_one({"email": email})
        if existing:
            raise HTTPException(status_code=400, detail="Account already exists")
        
        # If setting as default, unset other defaults
        if is_default:
            accounts_collection.update_many({}, {"$set": {"is_default": False}})
        
        account_data = {
            "account_id": account_id,
            "email": email,
            "display_name": name,
            "is_default": is_default,
            "is_authenticated": False,
            "aliases": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        accounts_collection.insert_one(account_data)
        
        return {"success": True, "account_id": account_id, "message": "Account created"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create account error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/accounts/{account_id}")
async def delete_account_by_id(account_id: str, request: Request):
    """Delete a Gmail account by ID"""
    try:
        # Try to find by account_id first, then by email
        account = accounts_collection.find_one({"$or": [
            {"account_id": account_id},
            {"email": account_id}
        ]})
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        actual_id = account.get("account_id")
        
        # Logout first
        if actual_id in _authenticators:
            try:
                _authenticators[actual_id].revoke_credentials()
            except:
                pass
            del _authenticators[actual_id]
        
        if actual_id in _gmail_services:
            del _gmail_services[actual_id]
        
        # Delete from database
        accounts_collection.delete_one({"account_id": actual_id})
        rate_limits_collection.delete_one({"account_id": actual_id})
        
        return {"success": True, "message": "Account deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/set-default")
async def set_default_account(account_id: str, request: Request):
    """Set an account as the default"""
    try:
        account = accounts_collection.find_one({"$or": [
            {"account_id": account_id},
            {"email": account_id}
        ]})
        
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Unset all defaults
        accounts_collection.update_many({}, {"$set": {"is_default": False}})
        
        # Set this account as default
        accounts_collection.update_one(
            {"account_id": account.get("account_id")},
            {"$set": {"is_default": True, "updated_at": datetime.utcnow()}}
        )
        
        return {"success": True, "message": "Default account updated"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set default error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Alias Management Endpoints
# ============================================

@router.get("/accounts/{account_id}/aliases")
async def get_aliases(account_id: str, request: Request):
    """Get all aliases for an account"""
    account = get_account_from_db(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return {"aliases": account.get("aliases", [])}


@router.post("/accounts/{account_id}/aliases")
async def add_alias(account_id: str, alias: GmailAliasCreate, request: Request):
    """Add an alias to an account"""
    try:
        account = get_account_from_db(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        aliases = account.get("aliases", [])
        
        # Check if alias already exists
        if any(a["email"].lower() == alias.email.lower() for a in aliases):
            raise HTTPException(status_code=400, detail="Alias already exists")
        
        # If setting as default, unset other defaults
        if alias.is_default:
            for a in aliases:
                a["is_default"] = False
        
        new_alias = {
            "email": alias.email,
            "display_name": alias.display_name,
            "signature": alias.signature,
            "is_default": alias.is_default,
            "is_primary": False,
            "created_at": datetime.utcnow().isoformat()
        }
        
        aliases.append(new_alias)
        
        accounts_collection.update_one(
            {"account_id": account_id},
            {"$set": {"aliases": aliases, "updated_at": datetime.utcnow()}}
        )
        
        return {"success": True, "alias": new_alias}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding alias: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/accounts/{account_id}/aliases/{alias_email}")
async def delete_alias(account_id: str, alias_email: str, request: Request):
    """Delete an alias from an account"""
    try:
        account = get_account_from_db(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        aliases = account.get("aliases", [])
        
        # Find and remove alias
        alias_to_remove = None
        for a in aliases:
            if a["email"].lower() == alias_email.lower():
                if a.get("is_primary"):
                    raise HTTPException(status_code=400, detail="Cannot delete primary address")
                alias_to_remove = a
                break
        
        if not alias_to_remove:
            raise HTTPException(status_code=404, detail="Alias not found")
        
        aliases.remove(alias_to_remove)
        
        accounts_collection.update_one(
            {"account_id": account_id},
            {"$set": {"aliases": aliases, "updated_at": datetime.utcnow()}}
        )
        
        return {"success": True, "message": "Alias deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting alias: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/aliases/sync")
async def sync_aliases(account_id: str, request: Request):
    """Sync send-as aliases from Gmail (frontend-compatible endpoint)"""
    return await sync_aliases_from_gmail(account_id, request)


@router.post("/accounts/{account_id}/sync-aliases")
async def sync_aliases_from_gmail(account_id: str, request: Request):
    """Sync send-as aliases from Gmail"""
    try:
        auth = get_authenticator(account_id)
        if not auth.is_authenticated():
            raise HTTPException(status_code=401, detail="Account not authenticated")
        
        service = auth.get_service()
        
        # Get send-as addresses from Gmail
        response = service.users().settings().sendAs().list(userId='me').execute()
        
        aliases = []
        for send_as in response.get('sendAs', []):
            aliases.append({
                "email": send_as.get("sendAsEmail", ""),
                "display_name": send_as.get("displayName", ""),
                "signature": send_as.get("signature", ""),
                "is_default": send_as.get("isDefault", False),
                "is_primary": send_as.get("isPrimary", False),
                "reply_to": send_as.get("replyToAddress"),
                "verification_status": send_as.get("verificationStatus", "")
            })
        
        accounts_collection.update_one(
            {"account_id": account_id},
            {"$set": {"aliases": aliases, "updated_at": datetime.utcnow()}}
        )
        
        return {"success": True, "aliases": aliases}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing aliases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Rate Limit Endpoints
# ============================================

@router.get("/rate-limits")
async def get_rate_limits(request: Request):
    """Get rate limit settings (frontend-compatible format)"""
    try:
        settings = get_rate_limit_settings()
    except Exception:
        settings = {}
    return {
        "rate_limits": {
            "max_per_day": settings.get("daily_limit", 500),
            "max_per_hour": settings.get("hourly_limit", 50),
            "max_per_minute": settings.get("per_minute_limit", 10),
            "cooldown_seconds": settings.get("cooldown_seconds", 5),
            "enabled": settings.get("enabled", True)
        }
    }


@router.post("/rate-limits")
async def update_rate_limits(request: Request):
    """Update rate limit settings (frontend-compatible format)"""
    try:
        data = await request.json()
        
        settings_collection.update_one(
            {"_id": "rate_limits"},
            {"$set": {
                "daily_limit": data.get("max_per_day", 500),
                "hourly_limit": data.get("max_per_hour", 50),
                "per_minute_limit": data.get("max_per_minute", 10),
                "cooldown_seconds": data.get("cooldown_seconds", 5),
                "enabled": data.get("enabled", True),
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        
        return {"success": True, "message": "Rate limits saved"}
    
    except Exception as e:
        logger.error(f"Error updating rate limits: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limits/settings")
async def get_rate_limit_config(request: Request):
    """Get rate limit settings"""
    return get_rate_limit_settings()


@router.post("/rate-limits/settings")
async def update_rate_limit_config(settings: RateLimitSettings, request: Request):
    """Update rate limit settings"""
    try:
        settings_collection.update_one(
            {"_id": "rate_limits"},
            {"$set": {
                "daily_limit": settings.daily_limit,
                "hourly_limit": settings.hourly_limit,
                "per_minute_limit": settings.per_minute_limit,
                "cooldown_seconds": settings.cooldown_seconds,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )
        
        return {"success": True, "settings": settings.dict()}
    
    except Exception as e:
        logger.error(f"Error updating rate limits: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limits/status")
async def get_rate_limit_status(account_id: Optional[str] = None, request: Request = None):
    """Get current rate limit status for accounts"""
    try:
        if account_id:
            status = check_rate_limit(account_id)
            return {"accounts": {account_id: status}}
        
        # Get status for all accounts
        accounts = list(accounts_collection.find({}, {"account_id": 1}))
        status_map = {}
        
        for account in accounts:
            aid = account["account_id"]
            status_map[aid] = check_rate_limit(aid)
        
        return {"accounts": status_map}
    
    except Exception as e:
        logger.error(f"Error getting rate limit status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rate-limits/reset/{account_id}")
async def reset_rate_limits(account_id: str, request: Request):
    """Reset rate limits for an account"""
    try:
        rate_limits_collection.delete_one({"account_id": account_id})
        return {"success": True, "message": "Rate limits reset"}
    except Exception as e:
        logger.error(f"Error resetting rate limits: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Email Fetching Endpoints
# ============================================

@router.get("/emails")
async def fetch_emails(
    request: Request,
    account_id: Optional[str] = None,
    query: str = "is:inbox",
    max_results: int = Query(50, ge=1, le=500),
    include_analysis: bool = True
):
    """Fetch emails from Gmail with optional analysis"""
    try:
        # Get account
        if not account_id:
            default_account = accounts_collection.find_one({"is_default": True})
            if not default_account:
                accounts = list(accounts_collection.find().limit(1))
                if not accounts:
                    raise HTTPException(status_code=400, detail="No Gmail accounts configured")
                account_id = accounts[0]["account_id"]
            else:
                account_id = default_account["account_id"]
        
        auth = get_authenticator(account_id)
        if not auth.is_authenticated():
            raise HTTPException(status_code=401, detail="Account not authenticated")
        
        service = auth.get_service()
        
        # Fetch emails
        fetcher = EmailFetcher(service)
        emails = fetcher.fetch_emails(query=query, max_results=max_results)
        
        result = {
            "account_id": account_id,
            "count": len(emails),
            "emails": []
        }
        
        # Optionally analyze
        if include_analysis and emails:
            categorizer = EmailCategorizer()
            analyzer = SentimentAnalyzer()
            
            for email in emails:
                email_data = email.to_dict()
                
                # Categorize
                cat_result = categorizer.categorize(email)
                email_data["category"] = cat_result.primary_category
                email_data["category_confidence"] = cat_result.confidence
                email_data["priority"] = cat_result.priority.name
                
                # Analyze sentiment
                sent_result = analyzer.analyze(email)
                email_data["sentiment"] = sent_result.sentiment.value
                email_data["tone"] = sent_result.tone.value
                email_data["urgency"] = sent_result.urgency.value
                email_data["intent"] = sent_result.intent.value
                
                result["emails"].append(email_data)
        else:
            result["emails"] = [e.to_dict() for e in emails]
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emails/{message_id}")
async def get_email(
    message_id: str,
    request: Request,
    account_id: Optional[str] = None
):
    """Get a single email by ID"""
    try:
        if not account_id:
            default_account = accounts_collection.find_one({"is_default": True})
            if default_account:
                account_id = default_account["account_id"]
            else:
                raise HTTPException(status_code=400, detail="No account specified")
        
        auth = get_authenticator(account_id)
        if not auth.is_authenticated():
            raise HTTPException(status_code=401, detail="Account not authenticated")
        
        service = auth.get_service()
        fetcher = EmailFetcher(service)
        
        email = fetcher.fetch_email_by_id(message_id)
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        
        # Analyze
        categorizer = EmailCategorizer()
        analyzer = SentimentAnalyzer()
        
        email_data = email.to_dict()
        email_data["body_text"] = email.get_plain_body()
        email_data["body_html"] = email.body_html
        
        cat_result = categorizer.categorize(email)
        sent_result = analyzer.analyze(email)
        
        email_data["analysis"] = {
            "category": cat_result.to_dict(),
            "sentiment": sent_result.to_dict()
        }
        
        return email_data
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Email Composition & Sending Endpoints
# ============================================

@router.post("/emails/compose")
async def compose_email(email_request: EmailComposeRequest, request: Request):
    """Compose a new email (returns preview, doesn't send)"""
    try:
        account_id = email_request.account_id
        if not account_id:
            default_account = accounts_collection.find_one({"is_default": True})
            if default_account:
                account_id = default_account["account_id"]
            else:
                raise HTTPException(status_code=400, detail="No account specified")
        
        account = get_account_from_db(account_id)
        
        # Get sender info
        sender_email = email_request.from_alias or account.get("email", "")
        sender_name = account.get("display_name", "")
        
        # Find alias if specified
        if email_request.from_alias:
            for alias in account.get("aliases", []):
                if alias["email"].lower() == email_request.from_alias.lower():
                    sender_name = alias.get("display_name", sender_name)
                    break
        
        composer = EmailComposer(default_name=sender_name)
        
        composed = composer.compose_new(
            to=email_request.to,
            subject=email_request.subject,
            body=email_request.body,
            template_name=email_request.template_name,
            html_body=email_request.html_body,
            cc=email_request.cc,
            bcc=email_request.bcc
        )
        
        return {
            "preview": composed.to_dict(),
            "from": f"{sender_name} <{sender_email}>",
            "account_id": account_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error composing email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emails/send")
async def send_email(email_request: EmailComposeRequest, request: Request):
    """Send an email"""
    try:
        account_id = email_request.account_id
        if not account_id:
            default_account = accounts_collection.find_one({"is_default": True})
            if default_account:
                account_id = default_account["account_id"]
            else:
                raise HTTPException(status_code=400, detail="No account specified")
        
        # Check rate limits
        rate_status = check_rate_limit(account_id)
        if not rate_status["can_send"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": rate_status["reason"],
                    "wait_seconds": rate_status["wait_seconds"],
                    "limits": rate_status
                }
            )
        
        auth = get_authenticator(account_id)
        if not auth.is_authenticated():
            raise HTTPException(status_code=401, detail="Account not authenticated")
        
        service = auth.get_service()
        account = get_account_from_db(account_id)
        
        # Get sender info
        sender_email = email_request.from_alias or account.get("email", "")
        sender_name = account.get("display_name", "")
        
        if email_request.from_alias:
            for alias in account.get("aliases", []):
                if alias["email"].lower() == email_request.from_alias.lower():
                    sender_name = alias.get("display_name", sender_name)
                    break
        
        composer = EmailComposer(
            service=service,
            default_name=sender_name,
            default_from=f"{sender_name} <{sender_email}>"
        )
        
        composed = composer.compose_new(
            to=email_request.to,
            subject=email_request.subject,
            body=email_request.body,
            template_name=email_request.template_name,
            html_body=email_request.html_body,
            cc=email_request.cc,
            bcc=email_request.bcc
        )
        
        result = composer.send_email(composed)
        
        if result.success:
            record_email_sent(account_id)
            return {
                "success": True,
                "message_id": result.message_id,
                "thread_id": result.thread_id
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emails/reply")
async def reply_to_email(reply_request: EmailReplyRequest, request: Request):
    """Reply to an email"""
    try:
        # Get original email
        default_account = accounts_collection.find_one({"is_default": True})
        if not default_account:
            raise HTTPException(status_code=400, detail="No default account")
        
        account_id = default_account["account_id"]
        
        # Check rate limits
        rate_status = check_rate_limit(account_id)
        if not rate_status["can_send"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "message": rate_status["reason"],
                    "wait_seconds": rate_status["wait_seconds"]
                }
            )
        
        auth = get_authenticator(account_id)
        if not auth.is_authenticated():
            raise HTTPException(status_code=401, detail="Account not authenticated")
        
        service = auth.get_service()
        account = get_account_from_db(account_id)
        
        # Fetch original email
        fetcher = EmailFetcher(service)
        original_email = fetcher.fetch_email_by_id(reply_request.email_id)
        
        if not original_email:
            raise HTTPException(status_code=404, detail="Original email not found")
        
        # Analyze for context
        analyzer = SentimentAnalyzer()
        sentiment = analyzer.analyze(original_email)
        
        # Compose reply
        composer = EmailComposer(
            service=service,
            default_name=account.get("display_name", ""),
            default_from=account.get("email", ""),
            use_ai=reply_request.use_ai
        )
        
        composed = composer.compose_response(
            original_email=original_email,
            sentiment_result=sentiment,
            template_name=reply_request.template_name,
            custom_content=reply_request.body,
            use_ai_content=reply_request.use_ai
        )
        
        result = composer.send_email(composed)
        
        if result.success:
            record_email_sent(account_id)
            return {
                "success": True,
                "message_id": result.message_id,
                "thread_id": result.thread_id
            }
        else:
            raise HTTPException(status_code=500, detail=result.error)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error replying to email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Templates Endpoint
# ============================================

@router.get("/templates")
async def list_templates(request: Request):
    """List available email templates"""
    composer = EmailComposer()
    return {"templates": composer.list_templates()}


# ============================================
# Dashboard/Stats Endpoints
# ============================================

@router.get("/stats")
async def get_gmail_stats(request: Request):
    """Get Gmail usage statistics"""
    try:
        accounts = list(accounts_collection.find({}, {"_id": 0}))
        
        stats = {
            "total_accounts": len(accounts),
            "authenticated_accounts": 0,
            "total_aliases": 0,
            "rate_limits": get_rate_limit_settings(),
            "accounts": []
        }
        
        for account in accounts:
            account_id = account.get("account_id")
            auth = get_authenticator(account_id)
            rate_status = check_rate_limit(account_id)
            
            is_authenticated = auth.is_authenticated()
            if is_authenticated:
                stats["authenticated_accounts"] += 1
            
            aliases = account.get("aliases", [])
            stats["total_aliases"] += len(aliases)
            
            stats["accounts"].append({
                "account_id": account_id,
                "email": account.get("email", ""),
                "display_name": account.get("display_name", ""),
                "is_default": account.get("is_default", False),
                "authenticated": is_authenticated,
                "alias_count": len(aliases),
                "daily_sent": rate_status["daily_count"],
                "daily_limit": rate_status["daily_limit"],
                "can_send": rate_status["can_send"]
            })
        
        return stats
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# IMAP IDLE Control Endpoints
# ============================================

# Import IDLE services
try:
    from leads.imap_idle_service import get_idle_manager, set_email_processor
    from leads.imap_leads_service import (
        process_email_for_lead, 
        import_emails_enhanced,
        run_historical_import,
        get_import_progress,
        imap_accounts_collection
    )
    from leads.ai_classifier import update_lead_conversation_summary
    IDLE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"IDLE service import error: {e}")
    IDLE_AVAILABLE = False


def process_new_email_callback(inbox: str, email_data: Dict[str, Any]):
    """
    Callback function for IDLE manager when new email arrives.
    Processes the email and updates the lead.
    """
    try:
        logger.info(f"Processing new email from {inbox}: {email_data.get('subject', 'No subject')}")
        
        # Process email for lead
        result = process_email_for_lead(email_data, inbox)
        
        if result.get("new_lead") or result.get("updated_lead"):
            # Trigger conversation summary update
            contact_email = email_data.get("contact_email")
            if contact_email:
                update_lead_conversation_summary(contact_email)
        
        logger.info(f"Email processed: new_lead={result.get('new_lead')}, updated={result.get('updated_lead')}, rfq={result.get('rfq_created')}")
        
    except Exception as e:
        logger.error(f"Error in email callback: {e}")


# Initialize IDLE manager with callback
if IDLE_AVAILABLE:
    set_email_processor(process_new_email_callback)


@router.post("/idle/start")
async def start_idle_watchers(background_tasks: BackgroundTasks):
    """
    Start IMAP IDLE watchers for all active accounts.
    This enables real-time email notifications.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="IDLE service not available")
    
    try:
        idle_manager = get_idle_manager()
        result = idle_manager.start_all()
        
        return {
            "success": result.get("success", False),
            "message": f"Started {len(result.get('started', []))} IDLE watchers",
            "started": result.get("started", []),
            "errors": result.get("errors", [])
        }
    
    except Exception as e:
        logger.error(f"Error starting IDLE watchers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/idle/stop")
async def stop_idle_watchers():
    """
    Stop all IMAP IDLE watchers.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="IDLE service not available")
    
    try:
        idle_manager = get_idle_manager()
        result = idle_manager.stop_all()
        
        return {
            "success": True,
            "message": f"Stopped {len(result.get('stopped', []))} IDLE watchers",
            "stopped": result.get("stopped", [])
        }
    
    except Exception as e:
        logger.error(f"Error stopping IDLE watchers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/idle/status")
async def get_idle_status():
    """
    Get status of all IMAP IDLE watchers.
    """
    if not IDLE_AVAILABLE:
        return {
            "available": False,
            "message": "IDLE service not available"
        }
    
    try:
        idle_manager = get_idle_manager()
        status = idle_manager.get_status()
        
        return {
            "available": True,
            **status
        }
    
    except Exception as e:
        logger.error(f"Error getting IDLE status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/idle/start/{account_email}")
async def start_idle_for_account(account_email: str):
    """
    Start IMAP IDLE watcher for a specific account.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="IDLE service not available")
    
    try:
        idle_manager = get_idle_manager()
        result = idle_manager.start_account(account_email)
        
        return result
    
    except Exception as e:
        logger.error(f"Error starting IDLE for {account_email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/idle/stop/{account_email}")
async def stop_idle_for_account(account_email: str):
    """
    Stop IMAP IDLE watcher for a specific account.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="IDLE service not available")
    
    try:
        idle_manager = get_idle_manager()
        result = idle_manager.stop_account(account_email)
        
        return result
    
    except Exception as e:
        logger.error(f"Error stopping IDLE for {account_email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Historical Import Endpoints
# ============================================

class HistoricalImportRequest(BaseModel):
    """Request model for historical import"""
    days: int = Field(30, ge=0, le=3650, description="Number of days to import (0 = all)")


@router.post("/import/start")
async def start_email_import(
    background_tasks: BackgroundTasks,
    account_emails: Optional[List[str]] = None,
    days: int = Query(30, ge=0, le=3650),
    max_emails: int = Query(500, ge=1, le=5000)
):
    """
    Start email import for specified accounts (or all active accounts).
    This runs in the background.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Import service not available")
    
    try:
        # Run import in background
        background_tasks.add_task(
            import_emails_enhanced,
            account_emails=account_emails,
            max_emails_per_folder=max_emails,
            since_days=days if days > 0 else 3650,
            trigger_enrichment=True
        )
        
        return {
            "success": True,
            "message": f"Email import started for {len(account_emails) if account_emails else 'all'} accounts",
            "days": days,
            "max_emails_per_folder": max_emails
        }
    
    except Exception as e:
        logger.error(f"Error starting import: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/historical/{account_email}")
async def start_historical_import(
    account_email: str,
    background_tasks: BackgroundTasks,
    import_request: HistoricalImportRequest = None
):
    """
    Start historical import for a specific account.
    Updates progress in database for UI tracking.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Import service not available")
    
    days = import_request.days if import_request else 30
    
    try:
        # Verify account exists
        account = imap_accounts_collection.find_one({"email": account_email})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Run import in background
        background_tasks.add_task(run_historical_import, account_email, days)
        
        return {
            "success": True,
            "message": f"Historical import started for {account_email}",
            "days": days
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting historical import for {account_email}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/import/progress/{account_email}")
async def get_historical_import_progress(account_email: str):
    """
    Get the progress of historical import for a specific account.
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Import service not available")
    
    try:
        progress = get_import_progress(account_email)
        
        if not progress:
            return {
                "success": True,
                "status": "not_started",
                "message": "No import has been started for this account"
            }
        
        return {
            "success": True,
            **progress
        }
    
    except Exception as e:
        logger.error(f"Error getting import progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/imap-accounts/{account_email}/settings")
async def update_imap_account_settings(
    account_email: str,
    historical_import_days: Optional[int] = Body(None, embed=True)
):
    """
    Update IMAP account settings (e.g., historical import days).
    """
    if not IDLE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service not available")
    
    try:
        # Find account
        account = imap_accounts_collection.find_one({"email": account_email})
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Build update
        update_doc = {"updated_at": datetime.utcnow()}
        
        if historical_import_days is not None:
            update_doc["historical_import_days"] = historical_import_days
        
        imap_accounts_collection.update_one(
            {"email": account_email},
            {"$set": update_doc}
        )
        
        return {
            "success": True,
            "message": "Account settings updated"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating account settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# MAIL POOL - Consolidated Email Activity Tracking
# ============================================

# In-memory cache for Mail Pool stats (reduces database load during heavy background processing)
import time as _time
import threading as _threading

_STATS_CACHE_ID = "mail_pool_stats_v1"
_STATS_CACHE_TTL = 900  # 15 minutes TTL before triggering background refresh
_stats_refresh_lock = _threading.Lock()  # Prevent duplicate background refreshes

# Primary email collection - use torpedo_gmail (Gmail Workspace sync system)
# This contains all synced emails with full metadata
torpedo_gmail_db = mongo_client["torpedo_gmail"]
mail_pool_emails = torpedo_gmail_db["email_metadata"]  # Primary source - Gmail Workspace sync
mail_pool_workspace_mailboxes = torpedo_gmail_db["workspace_mailboxes"]  # Gmail Workspace mailboxes

# Legacy email_automation for backward compatibility
email_automation_db = mongo_client["email_automation"]
mail_pool_mailboxes = email_automation_db["mailboxes"]  # Old IMAP mailbox accounts

# Legacy gmail_archive for backward compatibility (if needed)
gmail_archive_db = mongo_client["gmail_archive"]
mail_pool_legacy_emails = gmail_archive_db["emails"]

# Additional collections for leads data
mail_pool_email_leads = email_automation_db["email_leads"]
mail_pool_conversations = email_automation_db["email_conversations"]
mail_pool_sync_log = gmail_db["email_sync_log"]

# Full per-sender AI analysis (contacts, rfq) — sales/mail_pool_ai.py writes the
# FULL analysis here, keyed by sender email (_id). The per-email ai_analysis on
# email_metadata is only a compact stub ({sender_level, summary, category, ...})
# for the (overwhelmingly common) sender-level processing path — it never
# carries contacts/rfq itself, so any UI field sourced from those must look
# here instead.
mail_sender_analysis = email_automation_db["mail_sender_analysis"]


def _sender_contacts_and_rfq(from_email: str) -> tuple:
    """(contacts, has_rfq) for one sender, from mail_sender_analysis."""
    doc = mail_sender_analysis.find_one(
        {"_id": (from_email or "").strip().lower()},
        {"analysis.contacts": 1, "analysis.rfq": 1, "rfq_scan.ledger": 1})
    if not doc:
        return [], False
    contacts = ((doc.get("analysis") or {}).get("contacts")) or []
    has_rfq = bool(((doc.get("analysis") or {}).get("rfq") or {}).get("is_rfq"))
    if not has_rfq:
        has_rfq = bool((doc.get("rfq_scan") or {}).get("ledger"))
    return contacts, has_rfq


def _batch_sender_contacts_and_rfq(from_emails: list) -> dict:
    """Batch version of _sender_contacts_and_rfq for a list view page —
    one query instead of one per row. Returns {email_lower: (contacts, has_rfq)}."""
    emails_lower = list({(e or "").strip().lower() for e in from_emails if e})
    if not emails_lower:
        return {}
    result = {}
    for doc in mail_sender_analysis.find(
            {"_id": {"$in": emails_lower}},
            {"analysis.contacts": 1, "analysis.rfq": 1, "rfq_scan.ledger": 1}):
        contacts = ((doc.get("analysis") or {}).get("contacts")) or []
        has_rfq = bool(((doc.get("analysis") or {}).get("rfq") or {}).get("is_rfq"))
        if not has_rfq:
            has_rfq = bool((doc.get("rfq_scan") or {}).get("ledger"))
        result[doc["_id"]] = (contacts, has_rfq)
    return result

# MongoDB-backed stats cache (persisted across restarts, shared across workers)
_stats_cache_col = torpedo_gmail_db["mail_pool_stats_cache"]


# Helper function to parse email address from "Name <email@domain.com>" format
def parse_email_address(from_string):
    """Extract email and name from 'Name <email>' format"""
    import re
    if not from_string:
        return "", ""
    
    # Decode MIME encoded strings
    from email.header import decode_header
    try:
        decoded_parts = decode_header(from_string)
        decoded_str = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                decoded_str += part.decode(encoding or 'utf-8', errors='ignore')
            else:
                decoded_str += part
        from_string = decoded_str
    except:
        pass
    
    # Match "Name <email>" pattern
    match = re.match(r'^([^<]*)<([^>]+)>$', from_string.strip())
    if match:
        name = match.group(1).strip().strip('"').strip("'")
        email = match.group(2).strip()
        return email, name
    
    # Just email address
    if '@' in from_string:
        return from_string.strip(), ""
    
    return from_string, ""


# Helper to determine direction from label
def get_direction_from_label(label):
    """Determine if email is inbox or outbox based on Gmail label"""
    if not label:
        return "inbox"
    label_lower = label.lower()
    if "sent" in label_lower:
        return "outbox"
    return "inbox"


# Helper to clean email body (remove headers that appear at start)
def clean_email_body(body):
    """Remove email headers from body content if they appear at the start"""
    if not body:
        return ""
    
    import re
    
    # Pattern to match email headers at the start of body
    # Matches lines like "From: xxx", "Subject: xxx", "To: xxx", "Date: xxx"
    header_pattern = r'^(From:|Subject:|To:|Date:|Cc:|Reply-To:|Content-Type:|MIME-Version:)[^\n]*\n'
    
    cleaned = body
    
    # Remove header lines from the beginning
    while True:
        match = re.match(header_pattern, cleaned, re.IGNORECASE | re.MULTILINE)
        if match:
            cleaned = cleaned[match.end():]
        else:
            break
    
    # Also try to remove the pattern: From: "Name" [email]\nSubject: xxx\n\n
    cleaned = re.sub(r'^From:\s*"[^"]*"\s*\[[^\]]*\]\s*\n', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^Subject:\s*[^\n]*\n', '', cleaned, flags=re.IGNORECASE)
    
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()
    
    return cleaned


@router.get("/mail-pool/stats")
async def get_mail_pool_stats(
    request: Request
):
    """
    Get consolidated statistics for the Mail Pool.
    Reads from MongoDB-backed cache (fast, shared across workers, persists restarts).
    Triggers background refresh if cache is stale (>5 min).
    Always returns immediately - never blocks on stats computation.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")

        # Read pre-computed stats from MongoDB (single fast find_one, max 2s)
        cached_doc = None
        try:
            cached_doc = _stats_cache_col.find_one({"_id": _STATS_CACHE_ID}, max_time_ms=2000)
        except Exception as e:
            logger.warning(f"Could not read stats cache from MongoDB: {e}")

        now = _time.time()

        if cached_doc:
            cached_at = cached_doc.get("cached_at", 0)
            age = now - cached_at
            # Remove internal MongoDB/cache fields from response
            stats = {k: v for k, v in cached_doc.items() if k not in ("_id", "cached_at")}

            # Trigger background refresh if stale (non-blocking)
            if age > _STATS_CACHE_TTL:
                if _stats_refresh_lock.acquire(blocking=False):
                    def _bg_refresh():
                        try:
                            _compute_and_persist_mail_pool_stats()
                        finally:
                            _stats_refresh_lock.release()
                    _threading.Thread(target=_bg_refresh, daemon=True).start()

            return {"success": True, "stats": stats}

        # No cache at all - trigger background computation, return empty immediately
        if _stats_refresh_lock.acquire(blocking=False):
            def _bg_cold():
                try:
                    _compute_and_persist_mail_pool_stats()
                finally:
                    _stats_refresh_lock.release()
            _threading.Thread(target=_bg_cold, daemon=True).start()

        return {"success": True, "stats": {
            "total_emails": 0, "gmail_total": 0, "inbox_count": 0,
            "sent_count": 0, "drafts_count": 0, "segments": {},
            "ai_categories": {}, "pending_review": 0, "accounts": [],
            "total_accounts": 0, "_computing": True
        }}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching mail pool stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _compute_and_persist_mail_pool_stats():
    """
    Compute mail pool stats and persist to MongoDB cache.
    Runs in background thread - does NOT block HTTP responses.
    Written to torpedo_gmail.mail_pool_stats_cache, shared across all workers.
    """
    try:
        logger.info("Computing mail pool stats (background)...")

        # Get all mailbox accounts from both collections
        imap_accounts = list(mail_pool_mailboxes.find({"is_active": True}, max_time_ms=3000))
        workspace_accounts = list(mail_pool_workspace_mailboxes.find({"is_active": True}, max_time_ms=3000))

        # Merge both lists, avoiding duplicates by email
        seen_emails = set()
        accounts = []
        for acc in workspace_accounts:  # Prefer workspace accounts
            email = acc.get("email", "").lower()
            if email and email not in seen_emails:
                seen_emails.add(email)
                accounts.append(acc)
        for acc in imap_accounts:
            email = acc.get("email", "").lower()
            if email and email not in seen_emails:
                seen_emails.add(email)
                accounts.append(acc)

        # Use estimated_document_count - reads collection metadata, not documents
        try:
            total_emails = mail_pool_emails.estimated_document_count()
        except Exception:
            total_emails = 0

        # Count by direction using indexes
        try:
            inbox_count = mail_pool_emails.count_documents({"direction": "inbound"}, maxTimeMS=8000)
        except Exception:
            inbox_count = 0
        try:
            sent_count = mail_pool_emails.count_documents({"direction": "outbound"}, maxTimeMS=8000)
        except Exception:
            sent_count = 0

        # Count drafts
        try:
            drafts_count = mail_pool_emails.count_documents({"labels": "DRAFT"}, maxTimeMS=5000)
            if drafts_count == 0:
                drafts_count = mail_pool_emails.count_documents(
                    {"labels": {"$regex": "DRAFT", "$options": "i"}}, maxTimeMS=5000)
        except Exception:
            drafts_count = 0

        # Segment breakdown — group by `segment` (the field mail_pool_ai.py's
        # derive_segment() actually writes on the flat schema; the legacy
        # `category` field this used to group by is unset on essentially
        # every doc in that schema, so it always produced an empty result).
        try:
            category_stats = list(mail_pool_emails.aggregate([
                {"$group": {"_id": "$segment", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20}
            ], maxTimeMS=8000))
        except Exception:
            category_stats = []

        # AI category breakdown (uses indexed ai_tier1_category)
        try:
            ai_category_stats = list(mail_pool_emails.aggregate([
                {"$match": {"ai_tier1_category": {"$exists": True, "$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$ai_tier1_category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20}
            ], maxTimeMS=8000))
        except Exception:
            ai_category_stats = []

        # Pending review count
        try:
            pending_review_count = mongo_client["email_automation"]["ai_review_queue"].count_documents(
                {"status": "pending"}, maxTimeMS=3000)
        except Exception:
            pending_review_count = 0

        # Per-mailbox email counts (single aggregation)
        try:
            account_ids = [str(a["_id"]) for a in accounts]
            counts_map = {doc["_id"]: doc["count"] for doc in mail_pool_emails.aggregate([
                {"$match": {"mailbox_id": {"$in": account_ids}}},
                {"$group": {"_id": "$mailbox_id", "count": {"$sum": 1}}}
            ], maxTimeMS=8000)}
        except Exception:
            counts_map = {}

        # Build per-account stats
        account_stats = []
        for acc in accounts:
            acc_id = str(acc["_id"])
            count = counts_map.get(acc_id, 0)
            if count == 0:
                count = acc.get("email_count", 0)

            raw_aliases = acc.get("aliases", acc.get("alias_emails", []))
            normalized_aliases = []
            for alias in raw_aliases:
                if isinstance(alias, str):
                    normalized_aliases.append({
                        "email": alias, "display_name": alias.split("@")[0],
                        "signature": acc.get("signature", ""), "is_default": False
                    })
                elif isinstance(alias, dict):
                    normalized_aliases.append({
                        "email": alias.get("email", alias.get("alias_email", "")),
                        "display_name": alias.get("display_name", alias.get("email", "").split("@")[0]),
                        "signature": alias.get("signature", acc.get("signature", "")),
                        "is_default": alias.get("is_default", alias.get("is_primary", False))
                    })

            account_stats.append({
                "id": acc_id,
                "email": acc["email"],
                "display_name": acc.get("display_name", acc["email"].split("@")[0]),
                "total_emails": count,
                "gmail_total": acc.get("gmail_total", 0),
                "today": 0,
                "last_sync": acc.get("last_sync_at"),
                "aliases": normalized_aliases,
                "signature": acc.get("signature", ""),
                "is_default": acc.get("is_default", False)
            })

        total_gmail_total = sum(acc.get("gmail_total", 0) for acc in accounts)

        stats_doc = {
            "_id": _STATS_CACHE_ID,
            "cached_at": _time.time(),
            "total_emails": total_emails,
            "gmail_total": total_gmail_total,
            "emails_today": inbox_count,
            "emails_this_week": total_emails,
            "total_accounts": len(accounts),
            "inbox_count": inbox_count,
            "sent_count": sent_count,
            "drafts_count": drafts_count,
            "segments": {s["_id"]: s["count"] for s in category_stats if s["_id"]},
            "ai_categories": {s["_id"]: s["count"] for s in ai_category_stats if s["_id"]},
            "pending_review": pending_review_count,
            "accounts": account_stats,
        }

        # Persist to MongoDB (replace_one with upsert = update or insert)
        _stats_cache_col.replace_one(
            {"_id": _STATS_CACHE_ID},
            stats_doc,
            upsert=True
        )
        logger.info(f"Mail pool stats cached: {total_emails} emails, {len(accounts)} accounts")

    except Exception as e:
        logger.error(f"Error computing mail pool stats: {e}")


@router.get("/mail-pool/emails")
def get_mail_pool_emails(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    segment: Optional[str] = Query(None, description="Filter by segment/category (legacy)"),
    ai_category: Optional[str] = Query(None, description="Filter by AI classification category"),
    account: Optional[str] = Query(None, description="Filter by inbox account"),
    direction: Optional[str] = Query(None, description="Filter by direction (inbox/outbox)"),
    is_draft: Optional[bool] = Query(None, description="Filter by draft status"),
    is_starred: Optional[bool] = Query(None, description="Filter by starred status"),
    search: Optional[str] = Query(None, description="Search in subject/sender"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)")
):
    """
    Get paginated list of all emails in the Mail Pool with filtering options
    Uses email_automation.emails collection (new sync system)
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")

        # Build query filter for email_automation.emails (new schema)
        query = {}
        
        # Direction filter (new schema uses 'direction' field: inbound/outbound)
        if direction == "inbox":
            query["direction"] = "inbound"
        elif direction == "outbox":
            query["direction"] = "outbound"
        
        # Draft filter - check labels for DRAFT
        if is_draft is True:
            query["labels"] = {"$regex": "DRAFT", "$options": "i"}
        
        # Starred filter - check labels for STARRED
        if is_starred is True:
            query["labels"] = {"$regex": "STARRED", "$options": "i"}
        
        # Segment filter (using category field in new schema) - legacy
        if segment:
            query["category"] = {"$regex": segment, "$options": "i"}
        
        # AI Category filter (new OpenAI-based classification)
        if ai_category:
            query["ai_tier1_category"] = ai_category.lower()
        
        # Account filter - match by mailbox_id or email in from/to fields
        if account:
            # First try to find the mailbox_id for this account email
            mailbox = mail_pool_workspace_mailboxes.find_one({"email": account.lower()})
            if mailbox:
                query["mailbox_id"] = str(mailbox["_id"])
            else:
                # Fallback to email matching
                query["$or"] = [
                    {"from_email": {"$regex": account, "$options": "i"}},
                    {"to_emails": {"$regex": account, "$options": "i"}}
                ]
        
        # Search in subject, from_email, snippet
        if search:
            search_query = [
                {"from_email": {"$regex": search, "$options": "i"}},
                {"from_name": {"$regex": search, "$options": "i"}},
                {"to_emails": {"$regex": search, "$options": "i"}},
                {"subject": {"$regex": search, "$options": "i"}},
                {"snippet": {"$regex": search, "$options": "i"}}
            ]
            if "$or" in query:
                query["$and"] = [{"$or": query["$or"]}, {"$or": search_query}]
                del query["$or"]
            else:
                query["$or"] = search_query
        
        # Date filters using timestamp field
        if date_from or date_to:
            from datetime import datetime
            date_query = {}
            if date_from:
                try:
                    date_query["$gte"] = datetime.strptime(date_from, "%Y-%m-%d")
                except:
                    pass
            if date_to:
                try:
                    date_query["$lte"] = datetime.strptime(date_to, "%Y-%m-%d")
                except:
                    pass
            if date_query:
                query["timestamp"] = date_query
        
        # Calculate skip
        skip = (page - 1) * limit

        # Projection: only fetch fields needed for list view (exclude large body fields)
        _PROJECTION = {
            "from_email": 1, "from_name": 1, "to_emails": 1, "direction": 1,
            "subject": 1, "snippet": 1, "category": 1, "labels": 1,
            "timestamp": 1, "has_attachments": 1, "attachment_count": 1,
            "mailbox_id": 1, "is_starred": 1, "is_read": 1,
            "gmail_thread_id": 1, "gmail_message_id": 1, "synced_at": 1,
            "ai_category": 1, "ai_confidence": 1, "ai_urgency": 1,
            "ai_intent": 1, "ai_tier1_category": 1,
            "ai_summary": 1, "segment": 1, "segment_source": 1,
            "ai_analysis.contacts": 1, "ai_analysis.rfq": 1,
        }

        # Use cached count for simple direction-only filters (avoids full count scan)
        _simple_direction = list(query.keys()) == ["direction"]
        if _simple_direction:
            try:
                cached_doc = _stats_cache_col.find_one({"_id": _STATS_CACHE_ID},
                    {"inbox_count": 1, "sent_count": 1, "total_emails": 1}, max_time_ms=1000)
                if cached_doc:
                    if query["direction"] == "inbound":
                        total = cached_doc.get("inbox_count", 0)
                    elif query["direction"] == "outbound":
                        total = cached_doc.get("sent_count", 0)
                    else:
                        total = cached_doc.get("total_emails", 0)
                else:
                    total = mail_pool_emails.estimated_document_count()
            except Exception:
                total = mail_pool_emails.estimated_document_count()
        else:
            # Non-simple query: count with timeout, fall back to estimate
            try:
                total = mail_pool_emails.count_documents(query, maxTimeMS=5000)
            except Exception:
                total = mail_pool_emails.estimated_document_count()

        # Fetch emails with projection (excludes body_html/body_text - huge fields)
        emails = list(mail_pool_emails.find(query, _PROJECTION)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
            .max_time_ms(8000))
        
        # Batch-fetch mailbox accounts to avoid N+1 queries
        mailbox_ids = list({e.get("mailbox_id") for e in emails if e.get("mailbox_id")})
        mailbox_map = {}
        if mailbox_ids:
            try:
                mailboxes = mail_pool_workspace_mailboxes.find(
                    {"_id": {"$in": [ObjectId(mid) for mid in mailbox_ids if mid]}},
                    {"email": 1},
                    max_time_ms=3000
                )
                mailbox_map = {str(m["_id"]): m.get("email", "") for m in mailboxes}
            except Exception:
                pass

        # Batch-fetch full per-sender contacts/RFQ (the per-email ai_analysis
        # is usually just a sender-level stub — see mail_sender_analysis above)
        try:
            sender_map = _batch_sender_contacts_and_rfq(
                [e.get("from_email") for e in emails])
        except Exception:
            sender_map = {}

        # Format for response (adapting email_metadata schema to existing frontend format)
        formatted_emails = []
        for email_doc in emails:
            # Get from email/name (email_metadata uses from_email/from_name fields)
            from_email = email_doc.get("from_email", "")
            from_name = email_doc.get("from_name", "")
            
            # Get to addresses (email_metadata uses to_emails as a list)
            to_emails = email_doc.get("to_emails", [])
            to_email = to_emails[0] if to_emails else ""
            
            # Get direction from field
            email_direction = email_doc.get("direction", "inbound")
            if email_direction == "inbound":
                email_direction = "inbox"
            elif email_direction == "outbound":
                email_direction = "outbox"
            
            # Get body/snippet
            snippet = email_doc.get("snippet", "")
            
            # Get category/segment (prefer the AI-derived segment from
            # mail_pool_ai.py's derive_segment() over the legacy `category`)
            category = email_doc.get("category", "") or ""
            segment = email_doc.get("segment") or category
            labels = email_doc.get("labels", [])

            # Format timestamp
            timestamp = email_doc.get("timestamp")
            date_str = timestamp.isoformat() if timestamp else ""

            # Check for attachments
            has_attachments = email_doc.get("has_attachments", False)
            attachment_count = email_doc.get("attachment_count", 0)

            # Get mailbox email for account_email field (from pre-fetched map)
            mailbox_id = email_doc.get("mailbox_id")
            account_email = mailbox_map.get(mailbox_id, "") if mailbox_id else ""

            # Pull contact/RFQ info: prefer the per-email ai_analysis (the
            # per-email processing path carries contacts/rfq directly), fall
            # back to the full per-sender analysis (the sender-level path —
            # what the vast majority of the pool was processed with — only
            # stamps a compact stub per email with no contacts/rfq of its own).
            ai_analysis = email_doc.get("ai_analysis") or {}
            ai_contacts = ai_analysis.get("contacts") or []
            has_rfq = bool(ai_analysis.get("rfq", {}).get("is_rfq"))
            if not ai_contacts and not has_rfq:
                ai_contacts, has_rfq = sender_map.get(from_email.strip().lower(), ([], False))
            sender_contact = next(
                (c for c in ai_contacts
                 if (c.get("email") or "").strip().lower() == from_email.strip().lower()),
                ai_contacts[0] if ai_contacts else {})
            company = sender_contact.get("company") or ""
            title = sender_contact.get("title") or ""

            formatted_emails.append({
                "id": str(email_doc["_id"]),
                "email": from_email,
                "name": from_name,
                "first_name": from_name.split()[0] if from_name else "",
                "last_name": from_name.split()[-1] if from_name and " " in from_name else "",
                "company": company,
                "title": title,
                "segment": segment,
                "snippet": snippet,
                "subject": email_doc.get("subject", "(no subject)"),
                "added_on": date_str,
                "date": date_str,
                "source": "gmail_workspace",
                "ai_summary": email_doc.get("ai_summary", ""),
                "has_rfq": has_rfq,
                "has_attachments": has_attachments,
                "attachment_count": attachment_count,
                "direction": email_direction,
                "is_internal": False,
                "is_starred": email_doc.get("is_starred", False) or "STARRED" in str(labels).upper(),
                "is_draft": "DRAFT" in str(labels).upper(),
                "is_read": email_doc.get("is_read", "UNREAD" not in str(labels).upper()),
                "account_email": account_email or to_email,
                "to_email": to_email,
                "thread_id": email_doc.get("gmail_thread_id", ""),
                "thread_count": 1,
                "message_id": email_doc.get("gmail_message_id", ""),
                "category": category,
                "synced_at": email_doc.get("synced_at", "").isoformat() if email_doc.get("synced_at") else "",
                # AI Classification fields
                "ai_category": email_doc.get("ai_category"),
                "ai_confidence": email_doc.get("ai_confidence"),
                "ai_urgency": email_doc.get("ai_urgency"),
                "ai_intent": email_doc.get("ai_intent")
            })
        
        return {
            "success": True,
            "emails": formatted_emails,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching mail pool emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/emails/{email_id}")
async def get_mail_pool_email_detail(
    request: Request,
    email_id: str
):
    """
    Get detailed information about a specific email in the Mail Pool
    Uses torpedo_gmail.email_metadata collection and fetches body from Gmail API
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from bson import ObjectId
        
        try:
            email_doc = mail_pool_emails.find_one({"_id": ObjectId(email_id)})
        except Exception:
            email_doc = None
        
        if not email_doc:
            raise HTTPException(status_code=404, detail="Email not found")
        
        # Handle both old nested schema and new flat schema
        # New flat schema: from_email, from_name, to_emails (direct fields)
        # Old nested schema: from_address.email, from_address.name, to_addresses
        if "from_email" in email_doc:
            # New flat schema (torpedo_gmail.email_metadata)
            from_email = email_doc.get("from_email", "")
            from_name = email_doc.get("from_name", "")
            to_emails = email_doc.get("to_emails", [])
            to_names = ", ".join(to_emails) if to_emails else ""
            cc_emails = email_doc.get("cc_emails", [])
            cc_str = ", ".join(cc_emails) if cc_emails else ""
        else:
            # Old nested schema (email_automation.emails)
            from_addr = email_doc.get("from_address", {})
            if isinstance(from_addr, dict):
                from_email = from_addr.get("email", "")
                from_name = from_addr.get("name", "")
            else:
                from_email, from_name = parse_email_address(str(from_addr))
            to_addresses = email_doc.get("to_addresses", [])
            to_names = ", ".join([addr.get("email", "") for addr in to_addresses]) if to_addresses else ""
            cc_addresses = email_doc.get("cc_addresses", [])
            cc_str = ", ".join([addr.get("email", "") for addr in cc_addresses]) if cc_addresses else ""
        
        # Get direction
        email_direction = email_doc.get("direction", "inbound")
        if email_direction == "inbound":
            email_direction = "inbox"
        elif email_direction == "outbound":
            email_direction = "outbox"
        
        # Get body content from stored data
        body_plain = email_doc.get("body_plain", "") or ""
        body_html = email_doc.get("body_html", "") or ""
        
        # If body is empty, try to fetch from Gmail API
        gmail_message_id = email_doc.get("gmail_message_id", "")
        mailbox_id = email_doc.get("mailbox_id", "")
        
        if not body_html and not body_plain and gmail_message_id and mailbox_id:
            try:
                from app.services.gmail_workspace_service import GmailWorkspaceService
                
                service = GmailWorkspaceService()
                if service.is_configured():
                    # Get the mailbox to find the email address for delegation
                    mailbox = mail_pool_workspace_mailboxes.find_one({"_id": ObjectId(mailbox_id)})
                    if mailbox:
                        user_email = mailbox.get("email", "")
                        if user_email:
                            # Fetch full email from Gmail API
                            gmail_service = service._get_gmail_service(user_email)
                            if gmail_service:
                                msg = gmail_service.users().messages().get(
                                    userId='me',
                                    id=gmail_message_id,
                                    format='full'
                                ).execute()
                                
                                # Extract body from message parts
                                def get_body_from_parts(parts):
                                    html_body = ""
                                    plain_body = ""
                                    for part in parts:
                                        mime_type = part.get("mimeType", "")
                                        if mime_type == "text/html":
                                            data = part.get("body", {}).get("data", "")
                                            if data:
                                                import base64
                                                html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                        elif mime_type == "text/plain":
                                            data = part.get("body", {}).get("data", "")
                                            if data:
                                                import base64
                                                plain_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                        elif "parts" in part:
                                            nested_html, nested_plain = get_body_from_parts(part["parts"])
                                            if nested_html:
                                                html_body = nested_html
                                            if nested_plain:
                                                plain_body = nested_plain
                                    return html_body, plain_body
                                
                                payload = msg.get("payload", {})
                                parts = payload.get("parts", [])
                                
                                if parts:
                                    body_html, body_plain = get_body_from_parts(parts)
                                else:
                                    # Single part message
                                    mime_type = payload.get("mimeType", "")
                                    data = payload.get("body", {}).get("data", "")
                                    if data:
                                        import base64
                                        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                        if mime_type == "text/html":
                                            body_html = decoded
                                        else:
                                            body_plain = decoded
                                
                                # Cache the body in the database for future requests
                                if body_html or body_plain:
                                    mail_pool_emails.update_one(
                                        {"_id": email_doc["_id"]},
                                        {"$set": {"body_html": body_html, "body_plain": body_plain}}
                                    )
                                    logger.info(f"Fetched and cached email body for {gmail_message_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch email body from Gmail API: {e}")
        
        cleaned_body = clean_email_body(body_plain) if body_plain else ""
        
        # Get category and labels
        category = email_doc.get("category", "") or ""
        labels = email_doc.get("labels", [])
        
        # Format timestamp
        timestamp = email_doc.get("timestamp")
        date_str = timestamp.isoformat() if timestamp else ""
        
        # Get attachments
        attachments = email_doc.get("attachments", [])
        has_attachments = email_doc.get("has_attachments", False) or len(attachments) > 0
        
        # Get or generate AI summary
        ai_summary = email_doc.get("ai_summary", "")
        if not ai_summary and cleaned_body and len(cleaned_body.strip()) > 50:
            try:
                from leads.ai_classifier import generate_single_email_summary
                subject = email_doc.get("subject", "")
                ai_summary = generate_single_email_summary(
                    subject=subject,
                    body=cleaned_body,
                    from_email=from_email,
                    date=date_str
                )
                if ai_summary:
                    mail_pool_emails.update_one(
                        {"_id": email_doc["_id"]},
                        {"$set": {"ai_summary": ai_summary}}
                    )
            except Exception as e:
                logger.warning(f"Failed to generate AI summary: {e}")
                ai_summary = ""

        # Pull contact/RFQ info: prefer the per-email ai_analysis, fall back to
        # the full per-sender analysis (see _sender_contacts_and_rfq above —
        # the sender-level processing path, which covers most of the pool,
        # only stamps a contacts/rfq-less stub on each individual email).
        ai_analysis = email_doc.get("ai_analysis") or {}
        ai_contacts = ai_analysis.get("contacts") or []
        ai_rfq = ai_analysis.get("rfq") or {}
        has_rfq_flag = bool(ai_rfq.get("is_rfq"))
        if not ai_contacts and not has_rfq_flag:
            ai_contacts, has_rfq_flag = _sender_contacts_and_rfq(from_email)
        sender_contact = next(
            (c for c in ai_contacts
             if (c.get("email") or "").strip().lower() == from_email.strip().lower()),
            ai_contacts[0] if ai_contacts else {})
        company = sender_contact.get("company") or ""
        title = sender_contact.get("title") or ""
        segment = email_doc.get("segment") or category

        return {
            "success": True,
            "email": {
                "id": str(email_doc["_id"]),
                "email": from_email,
                "name": from_name,
                "first_name": from_name.split()[0] if from_name else "",
                "last_name": from_name.split()[-1] if from_name and " " in from_name else "",
                "company": company,
                "title": title,
                "segment": segment,
                "category": category,
                "snippet": email_doc.get("snippet", cleaned_body[:200] if cleaned_body else ""),
                "subject": email_doc.get("subject", "(no subject)"),
                "body": cleaned_body or body_html,  # Fallback to HTML if no plain text
                "body_html": body_html,
                "ai_summary": ai_summary,
                "contacts": ai_contacts,
                "rfq": ai_rfq if ai_rfq.get("is_rfq") else None,
                "added_on": date_str,
                "date": date_str,
                "source": "email_sync",
                "has_rfq": has_rfq_flag or email_doc.get("crm_rfq_id") is not None,
                "has_attachments": has_attachments,
                "attachment_count": email_doc.get("attachment_count", len(attachments)),
                "attachments": attachments,
                "direction": email_direction,
                "is_internal": False,
                "account_email": to_names.split(",")[0] if to_names else "",
                "to_email": to_names,
                "cc": cc_str,
                "message_id": email_doc.get("gmail_message_id", email_doc.get("provider_message_id", "")),
                "thread_id": email_doc.get("gmail_thread_id", email_doc.get("provider_thread_id", "")),
                "is_starred": email_doc.get("is_starred", False) or "STARRED" in str(labels).upper(),
                "is_read": email_doc.get("is_read", True),
                "is_draft": "DRAFT" in str(labels).upper(),
                "synced_at": email_doc.get("synced_at", "").isoformat() if email_doc.get("synced_at") else "",
                # AI Classification fields
                "ai_category": email_doc.get("ai_category"),
                "ai_confidence": email_doc.get("ai_confidence"),
                "ai_method": email_doc.get("ai_method"),
                "ai_intent": email_doc.get("ai_intent"),
                "ai_urgency": email_doc.get("ai_urgency"),
                "ai_sentiment": email_doc.get("ai_sentiment"),
                "ai_key_points": email_doc.get("ai_key_points", []),
                "ai_action_items": email_doc.get("ai_action_items", []),
                "ai_reply_expected": email_doc.get("ai_reply_expected"),
                "ai_classified_at": email_doc.get("ai_classified_at", "").isoformat() if email_doc.get("ai_classified_at") else ""
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching email detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/thread/{thread_id}")
async def get_mail_pool_thread(
    request: Request,
    thread_id: str
):
    """
    Get all emails in a conversation thread.
    Fetches full body from Gmail API if not cached.
    Returns emails sorted by date (oldest first for proper conversation flow).
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Find all emails with this thread_id - check both field names
        thread_emails = list(mail_pool_emails.find({
            "$or": [
                {"gmail_thread_id": thread_id},
                {"provider_thread_id": thread_id}
            ]
        }).sort("timestamp", 1))  # Sort oldest first
        
        if not thread_emails:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        # Initialize Gmail service once if needed
        gmail_service = None
        service = None
        
        formatted_emails = []
        for email_doc in thread_emails:
            # Handle both flat and nested schema
            if "from_email" in email_doc:
                # Flat schema (torpedo_gmail.email_metadata)
                from_email = email_doc.get("from_email", "")
                from_name = email_doc.get("from_name", "")
                to_emails = email_doc.get("to_emails", [])
                to_email = ", ".join(to_emails) if to_emails else ""
                cc_emails = email_doc.get("cc_emails", [])
                cc_str = ", ".join(cc_emails) if cc_emails else ""
            else:
                # Nested schema
                from_addr = email_doc.get("from_address", {})
                if isinstance(from_addr, dict):
                    from_email = from_addr.get("email", "")
                    from_name = from_addr.get("name", "")
                else:
                    from_email, from_name = parse_email_address(str(from_addr))
                to_addresses = email_doc.get("to_addresses", [])
                to_email = ", ".join([addr.get("email", "") for addr in to_addresses]) if to_addresses else ""
            
            # Get direction
            email_direction = email_doc.get("direction", "inbound")
            if email_direction == "inbound":
                email_direction = "inbox"
            elif email_direction == "outbound":
                email_direction = "outbox"
            
            # Get body content
            body_plain = email_doc.get("body_plain", "") or ""
            body_html = email_doc.get("body_html", "") or ""
            
            # Fetch from Gmail API if body is empty
            gmail_message_id = email_doc.get("gmail_message_id", "")
            mailbox_id = email_doc.get("mailbox_id", "")
            
            if not body_html and not body_plain and gmail_message_id and mailbox_id:
                try:
                    if not service:
                        from app.services.gmail_workspace_service import GmailWorkspaceService
                        service = GmailWorkspaceService()
                    
                    if service and service.is_configured():
                        mailbox = mail_pool_workspace_mailboxes.find_one({"_id": ObjectId(mailbox_id)})
                        if mailbox:
                            user_email = mailbox.get("email", "")
                            if user_email:
                                gmail_service = service._get_gmail_service(user_email)
                                if gmail_service:
                                    msg = gmail_service.users().messages().get(
                                        userId='me',
                                        id=gmail_message_id,
                                        format='full'
                                    ).execute()
                                    
                                    # Extract body from message parts
                                    def get_body_from_parts(parts):
                                        html_body = ""
                                        plain_body = ""
                                        for part in parts:
                                            mime_type = part.get("mimeType", "")
                                            if mime_type == "text/html":
                                                data = part.get("body", {}).get("data", "")
                                                if data:
                                                    import base64
                                                    html_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                            elif mime_type == "text/plain":
                                                data = part.get("body", {}).get("data", "")
                                                if data:
                                                    import base64
                                                    plain_body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                            elif "parts" in part:
                                                nested_html, nested_plain = get_body_from_parts(part["parts"])
                                                if nested_html:
                                                    html_body = nested_html
                                                if nested_plain:
                                                    plain_body = nested_plain
                                        return html_body, plain_body
                                    
                                    payload = msg.get("payload", {})
                                    parts = payload.get("parts", [])
                                    
                                    if parts:
                                        body_html, body_plain = get_body_from_parts(parts)
                                    else:
                                        mime_type = payload.get("mimeType", "")
                                        data = payload.get("body", {}).get("data", "")
                                        if data:
                                            import base64
                                            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                            if mime_type == "text/html":
                                                body_html = decoded
                                            else:
                                                body_plain = decoded
                                    
                                    # Cache the body
                                    if body_html or body_plain:
                                        mail_pool_emails.update_one(
                                            {"_id": email_doc["_id"]},
                                            {"$set": {"body_html": body_html, "body_plain": body_plain}}
                                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch email body from Gmail API: {e}")
            
            cleaned_body = clean_email_body(body_plain) if body_plain else ""
            labels = email_doc.get("labels", [])
            timestamp = email_doc.get("timestamp")
            
            formatted_emails.append({
                "id": str(email_doc["_id"]),
                "email": from_email,
                "name": from_name,
                "to_email": to_email,
                "subject": email_doc.get("subject", "(no subject)"),
                "body": cleaned_body or body_html,
                "body_html": body_html,
                "snippet": email_doc.get("snippet", cleaned_body[:200] if cleaned_body else ""),
                "added_on": timestamp.isoformat() if timestamp else "",
                "date": timestamp.isoformat() if timestamp else "",
                "direction": email_direction,
                "message_id": email_doc.get("gmail_message_id", email_doc.get("provider_message_id", "")),
                "thread_id": email_doc.get("gmail_thread_id", email_doc.get("provider_thread_id", "")),
                "is_starred": email_doc.get("is_starred", False) or "STARRED" in str(labels).upper(),
                "is_read": email_doc.get("is_read", "UNREAD" not in str(labels).upper()),
                "attachments": email_doc.get("attachments", []),
                "has_attachments": email_doc.get("has_attachments", False)
            })
        
        return {
            "success": True,
            "thread_id": thread_id,
            "email_count": len(formatted_emails),
            "emails": formatted_emails
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching thread: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/contact")
async def get_mail_pool_contact(
    request: Request,
    email: str = Query(..., description="Contact email address")
):
    """
    Get contact information for a specific email address from Mail Pool
    Uses email_automation.emails collection (new sync system)
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Find the most recent email from this contact (flat schema:
        # from_email; fall back to the old nested schema for legacy docs)
        contact_doc = mail_pool_emails.find_one(
            {"from_email": {"$regex": email, "$options": "i"}},
            sort=[("timestamp", -1)]
        )
        if not contact_doc:
            contact_doc = mail_pool_emails.find_one(
                {"from_address.email": {"$regex": email, "$options": "i"}},
                sort=[("timestamp", -1)]
            )

        if not contact_doc:
            # Try to find in to_addresses
            contact_doc = mail_pool_emails.find_one(
                {"to_emails": {"$regex": email, "$options": "i"}},
                sort=[("timestamp", -1)]
            )
            if not contact_doc:
                contact_doc = mail_pool_emails.find_one(
                    {"to_addresses.email": {"$regex": email, "$options": "i"}},
                    sort=[("timestamp", -1)]
                )

        if not contact_doc:
            # Return basic info if no email found
            return {
                "success": True,
                "contact": {
                    "email": email,
                    "name": email.split("@")[0] if "@" in email else email,
                    "first_name": "",
                    "last_name": "",
                    "title": "",
                    "company": "",
                    "company_website": "",
                    "linkedin": "",
                    "location": "",
                    "phone": "",
                    "added_on": "",
                    "last_contacted": "",
                    "email_count": 0,
                    "source": "email_sync"
                }
            }
        
        # Get sender identity — flat schema (from_email/from_name) first,
        # fall back to the old nested schema for legacy docs
        if "from_email" in contact_doc:
            parsed_email = contact_doc.get("from_email", "")
            parsed_name = contact_doc.get("from_name", "")
        else:
            from_addr = contact_doc.get("from_address", {})
            if isinstance(from_addr, dict):
                parsed_email = from_addr.get("email", "")
                parsed_name = from_addr.get("name", "")
            else:
                parsed_email, parsed_name = parse_email_address(str(from_addr))

        # Count emails from this contact (flat schema)
        email_count = mail_pool_emails.count_documents(
            {"from_email": {"$regex": email, "$options": "i"}})
        if not email_count:
            email_count = mail_pool_emails.count_documents(
                {"from_address.email": {"$regex": email, "$options": "i"}})

        # Format timestamp
        timestamp = contact_doc.get("timestamp")
        date_str = timestamp.isoformat() if timestamp else ""

        # Pull company/title out of the mail_pool_ai.py contact extraction.
        # `email` is usually itself a sender, so mail_sender_analysis (keyed by
        # sender email) is checked first; that document's own `analysis.contacts`
        # also covers other people (e.g. co-signers) mentioned in that sender's
        # mail, and finally fall back to whatever this one email doc carries.
        matched_contact = None
        sender_doc = mail_sender_analysis.find_one(
            {"_id": email.strip().lower()},
            {"analysis.contacts": 1, "analysis.sender_type": 1})
        candidate_pools = []
        if sender_doc:
            candidate_pools.append((sender_doc.get("analysis") or {}).get("contacts") or [])
        candidate_pools.append((contact_doc.get("ai_analysis") or {}).get("contacts") or [])
        for pool in candidate_pools:
            for c in pool:
                if (c.get("email") or "").strip().lower() == email.strip().lower():
                    matched_contact = c
                    break
            if matched_contact:
                break
        if not matched_contact:
            enriched_doc = mail_pool_emails.find_one(
                {"ai_analysis.contacts.email": {"$regex": f"^{email}$", "$options": "i"}},
                sort=[("timestamp", -1)])
            if enriched_doc:
                for c in (enriched_doc.get("ai_analysis") or {}).get("contacts") or []:
                    if (c.get("email") or "").strip().lower() == email.strip().lower():
                        matched_contact = c
                        break
        matched_contact = matched_contact or {}

        return {
            "success": True,
            "contact": {
                "email": parsed_email or email,
                "name": parsed_name or matched_contact.get("name") or (email.split("@")[0] if "@" in email else email),
                "first_name": parsed_name.split()[0] if parsed_name else "",
                "last_name": parsed_name.split()[-1] if parsed_name and " " in parsed_name else "",
                "title": matched_contact.get("title") or "",
                "company": matched_contact.get("company") or "",
                "company_website": "",
                "linkedin": "",
                "location": "",
                "phone": matched_contact.get("phone") or "",
                "added_on": date_str,
                "last_contacted": date_str,
                "email_count": email_count,
                "source": "email_sync"
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching contact: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/activity")
async def get_mail_pool_activity(
    request: Request,
    days: int = Query(7, ge=1, le=30, description="Number of days to look back")
):
    """
    Get email activity timeline for the Mail Pool - shows daily email volume
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Aggregate by day
        pipeline = [
            {
                "$match": {
                    "processed_at": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": {
                        "year": {"$year": "$processed_at"},
                        "month": {"$month": "$processed_at"},
                        "day": {"$dayOfMonth": "$processed_at"}
                    },
                    "count": {"$sum": 1},
                    "inboxes": {"$addToSet": "$inbox"}
                }
            },
            {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1}}
        ]
        
        daily_stats = list(mail_pool_sync_log.aggregate(pipeline))
        
        # Format for chart
        activity = []
        for stat in daily_stats:
            date_str = f"{stat['_id']['year']}-{stat['_id']['month']:02d}-{stat['_id']['day']:02d}"
            activity.append({
                "date": date_str,
                "count": stat["count"],
                "inboxes": len(stat["inboxes"])
            })
        
        return {
            "success": True,
            "activity": activity,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": days
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching mail pool activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/conversations")
async def get_mail_pool_conversations(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    contact_email: Optional[str] = Query(None, description="Filter by contact email")
):
    """
    Get email conversation threads with AI summaries
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        query = {}
        if contact_email:
            query["contact_email"] = contact_email
        
        skip = (page - 1) * limit
        total = mail_pool_conversations.count_documents(query)
        
        conversations = list(mail_pool_conversations.find(query)
            .sort("last_updated", -1)
            .skip(skip)
            .limit(limit))
        
        formatted = []
        for conv in conversations:
            formatted.append({
                "id": str(conv["_id"]),
                "contact_email": conv.get("contact_email", ""),
                "contact_name": conv.get("contact_name", ""),
                "subject": conv.get("subject", ""),
                "message_count": conv.get("message_count", 0),
                "ai_summary": conv.get("ai_summary", ""),
                "last_updated": conv.get("last_updated", ""),
                "segment": conv.get("segment", "others"),
                "inboxes": conv.get("inboxes", [])
            })
        
        return {
            "success": True,
            "conversations": formatted,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# IMAP/SMTP Send Endpoint (DEPRECATED - Use /gmail-ws/send)
# ============================================

class ImapSendRequest(BaseModel):
    """Model for sending email via IMAP account's SMTP (DEPRECATED)"""
    to: List[str] = Field(..., description="Recipient email addresses")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body (plain text)")
    html_body: Optional[str] = Field(None, description="HTML body")
    cc: List[str] = Field(default=[], description="CC recipients")
    bcc: List[str] = Field(default=[], description="BCC recipients")
    from_email: Optional[str] = Field(None, description="Sender email (must be from mailbox)")
    signature_html: Optional[str] = Field(None, description="Email signature HTML")


@router.post("/imap/send")
async def send_email_imap(send_request: ImapSendRequest, request: Request):
    """
    DEPRECATED: Use /gmail-ws/send instead.
    
    This endpoint now redirects to the Gmail API send endpoint.
    IMAP/SMTP is no longer used for sending emails.
    """
    # Forward to Gmail API send endpoint
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Import Gmail Workspace service
        from app.services.gmail_workspace_service import GmailWorkspaceService
        
        service = GmailWorkspaceService()
        
        if not service.is_configured():
            raise HTTPException(
                status_code=400, 
                detail="Gmail Workspace service not configured. Please set up service account credentials."
            )
        
        # Use provided from_email or find the first active mailbox
        from_email = send_request.from_email
        if not from_email:
            mailboxes = service.list_mailboxes()
            if not mailboxes:
                raise HTTPException(status_code=400, detail="No mailboxes configured")
            from_email = mailboxes[0]["email"]
        
        # Build HTML body
        html_body = send_request.html_body or send_request.body.replace("\n", "<br>")
        
        # Send email via Gmail API
        result = service.send_email(
            from_email=from_email,
            to=send_request.to,
            subject=send_request.subject,
            body_html=html_body,
            body_plain=send_request.body,
            cc=send_request.cc,
            bcc=send_request.bcc,
            signature_html=send_request.signature_html
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to send email"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# MAIL POOL AI CLASSIFICATION ENDPOINTS
# ============================================

# Background task tracking for classification
_classification_tasks: Dict[str, Any] = {}


class ClassifyRequest(BaseModel):
    """Request model for email classification"""
    email_ids: Optional[List[str]] = None  # Specific emails to classify
    limit: int = Field(100, ge=1, le=1000, description="Max emails to process")
    run_tier2: bool = Field(True, description="Run deep analysis for client/vendor emails")
    category_filter: Optional[str] = Field(None, description="Only classify emails in this category")


@router.post("/mail-pool/classify")
async def classify_mail_pool_emails(
    request: Request,
    classify_request: ClassifyRequest,
    background_tasks: BackgroundTasks
):
    """
    Start AI classification of Mail Pool emails.
    
    Uses tiered approach:
    - Tier 1: Fast classification (keywords + GPT-4o-mini) for ALL emails
    - Tier 2: Deep analysis (Claude Sonnet) for client/vendor emails only
    
    Returns task_id to track progress.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        import uuid
        import threading
        from leads.email_classifier import (
            classify_email_batch,
            get_emails_needing_classification,
            get_internal_domains
        )
        
        # Get email IDs to classify
        if classify_request.email_ids:
            email_ids = classify_request.email_ids
        else:
            email_ids = get_emails_needing_classification(
                limit=classify_request.limit,
                category_filter=classify_request.category_filter
            )
        
        if not email_ids:
            return {
                "success": True,
                "message": "No emails need classification",
                "total": 0
            }
        
        # Get internal domains for classification
        internal_domains = get_internal_domains()
        
        # Create task
        task_id = str(uuid.uuid4())
        _classification_tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "total": len(email_ids),
            "processed": 0,
            "tier1_only": 0,
            "tier2_analyzed": 0,
            "errors": 0,
            "run_tier2": classify_request.run_tier2,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Run classification in background thread
        def run_classification():
            try:
                _classification_tasks[task_id]["status"] = "running"
                _classification_tasks[task_id]["started_at"] = datetime.utcnow().isoformat()
                
                result = classify_email_batch(
                    email_ids=email_ids,
                    run_tier2=classify_request.run_tier2,
                    internal_domains=internal_domains,
                    source="background"
                )
                
                _classification_tasks[task_id].update({
                    "status": "completed",
                    "completed_at": datetime.utcnow().isoformat(),
                    "processed": result["stats"]["processed"],
                    "tier1_only": result["stats"]["tier1_only"],
                    "tier2_analyzed": result["stats"]["tier2_analyzed"],
                    "errors": result["stats"]["errors"],
                    "by_category": result["stats"]["by_category"]
                })
                
            except Exception as e:
                logger.error(f"Classification task error: {e}")
                _classification_tasks[task_id]["status"] = "failed"
                _classification_tasks[task_id]["error"] = str(e)
        
        thread = threading.Thread(target=run_classification)
        thread.daemon = True
        thread.start()
        
        return {
            "success": True,
            "task_id": task_id,
            "total_emails": len(email_ids),
            "run_tier2": classify_request.run_tier2,
            "message": f"Started classification of {len(email_ids)} emails"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting classification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/classify/status/{task_id}")
async def get_classification_status(
    request: Request,
    task_id: str
):
    """Get status of a classification task"""
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    if task_id not in _classification_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return _classification_tasks[task_id]


@router.get("/mail-pool/classify/tasks")
async def list_classification_tasks(request: Request):
    """List all classification tasks"""
    session_id = request.headers.get("Authorization")
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing session token")
    
    return {
        "tasks": list(_classification_tasks.values())
    }


@router.post("/mail-pool/classify-single/{email_id}")
async def classify_single_email(
    request: Request,
    email_id: str,
    run_tier2: bool = Query(True, description="Run deep analysis")
):
    """
    Classify a single email on-demand.
    Returns classification result immediately (not background task).
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from bson import ObjectId
        from leads.email_classifier import classify_email_full, get_internal_domains
        
        # Fetch email
        try:
            email_doc = mail_pool_emails.find_one({"_id": ObjectId(email_id)})
        except Exception:
            email_doc = None
        
        if not email_doc:
            raise HTTPException(status_code=404, detail="Email not found")
        
        # Extract fields
        subject = email_doc.get("subject", "")
        body = email_doc.get("body_plain", "") or email_doc.get("snippet", "")
        from_email = email_doc.get("from_email", "")
        to_emails = email_doc.get("to_emails", [])
        to_email = to_emails[0] if to_emails else ""
        timestamp = email_doc.get("timestamp")
        date_str = timestamp.isoformat() if timestamp else ""
        
        # Get internal domains
        internal_domains = get_internal_domains()
        
        # Classify
        classification = classify_email_full(
            email_id=email_id,
            subject=subject,
            body=body,
            from_email=from_email,
            to_email=to_email,
            date=date_str,
            internal_domains=internal_domains,
            run_tier2=run_tier2,
            source="api"
        )
        
        # Update database
        update_fields = {
            "ai_category": classification.get("tier1_category"),
            "ai_confidence": classification.get("tier1_confidence"),
            "ai_method": classification.get("tier1_method"),
            "ai_classified_at": datetime.utcnow()
        }
        
        if classification.get("tier2_intent"):
            update_fields.update({
                "ai_intent": classification.get("tier2_intent"),
                "ai_urgency": classification.get("tier2_urgency"),
                "ai_sentiment": classification.get("tier2_sentiment"),
                "ai_summary": classification.get("tier2_summary"),
                "ai_key_points": classification.get("tier2_key_points"),
                "ai_action_items": classification.get("tier2_action_items"),
                "ai_reply_expected": classification.get("tier2_reply_expected"),
                "ai_tier2_at": datetime.utcnow()
            })
        
        mail_pool_emails.update_one(
            {"_id": ObjectId(email_id)},
            {"$set": update_fields}
        )
        
        return {
            "success": True,
            "classification": classification
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error classifying email: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mail-pool/classification-stats")
async def get_classification_stats(request: Request):
    """Get AI classification statistics for Mail Pool"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Count by AI category
        category_pipeline = [
            {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        category_stats = list(mail_pool_emails.aggregate(category_pipeline))
        
        # Count by AI intent (Tier 2)
        intent_pipeline = [
            {"$match": {"ai_intent": {"$exists": True}}},
            {"$group": {"_id": "$ai_intent", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        intent_stats = list(mail_pool_emails.aggregate(intent_pipeline))
        
        # Count by urgency
        urgency_pipeline = [
            {"$match": {"ai_urgency": {"$exists": True}}},
            {"$group": {"_id": "$ai_urgency", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        urgency_stats = list(mail_pool_emails.aggregate(urgency_pipeline))
        
        # Count totals
        total_emails = mail_pool_emails.count_documents({})
        classified = mail_pool_emails.count_documents({"ai_category": {"$exists": True}})
        tier2_analyzed = mail_pool_emails.count_documents({"ai_intent": {"$exists": True}})
        unclassified = total_emails - classified
        
        # Client/Vendor counts
        client_count = mail_pool_emails.count_documents({"ai_category": "client"})
        vendor_count = mail_pool_emails.count_documents({"ai_category": "vendor"})
        
        # Urgency breakdown
        urgent_count = mail_pool_emails.count_documents({"ai_urgency": {"$in": ["critical", "high"]}})
        
        return {
            "success": True,
            "stats": {
                "total_emails": total_emails,
                "classified": classified,
                "unclassified": unclassified,
                "tier2_analyzed": tier2_analyzed,
                "client_emails": client_count,
                "vendor_emails": vendor_count,
                "urgent_emails": urgent_count,
                "by_category": {s["_id"]: s["count"] for s in category_stats if s["_id"]},
                "by_intent": {s["_id"]: s["count"] for s in intent_stats if s["_id"]},
                "by_urgency": {s["_id"]: s["count"] for s in urgency_stats if s["_id"]}
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching classification stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PARALLEL EMAIL SYNC ENDPOINTS
# ============================================

try:
    from leads.parallel_email_sync import (
        parallel_sync_all_accounts,
        get_total_email_count,
        get_all_accounts_email_count,
        get_parallel_sync_status,
        start_background_parallel_sync,
        IMAPAccountConfig
    )
    PARALLEL_SYNC_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Parallel sync module not available: {e}")
    PARALLEL_SYNC_AVAILABLE = False


@router.get("/parallel-sync/email-counts")
async def get_email_counts(
    since_days: int = Query(0, ge=0, description="Only count emails from last N days (0 = all)")
):
    """
    Get total email count for all active accounts.
    Returns count per folder per account WITHOUT downloading.
    """
    if not PARALLEL_SYNC_AVAILABLE:
        raise HTTPException(status_code=503, detail="Parallel sync service not available")
    
    try:
        counts = get_all_accounts_email_count(since_days)
        
        # Calculate totals
        total_emails = 0
        for account_counts in counts.values():
            if isinstance(account_counts, dict) and "error" not in account_counts:
                total_emails += sum(account_counts.values())
        
        return {
            "success": True,
            "total_emails": total_emails,
            "since_days": since_days if since_days > 0 else "all",
            "accounts": counts
        }
    except Exception as e:
        logger.error(f"Error getting email counts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/parallel-sync/start")
async def start_parallel_sync(
    background_tasks: BackgroundTasks,
    account_emails: Optional[List[str]] = Body(None),
    since_days: int = Query(0, ge=0, description="Only fetch from last N days (0 = all)"),
    max_parallel: int = Query(5, ge=1, le=10)
):
    """
    Start parallel email download for all accounts using Celery background tasks.
    
    Downloads ALL emails (no 50,000 limit) across multiple accounts in parallel.
    Returns an operation_id for tracking progress via polling.
    Progress can be tracked via /operations/{operation_id}/status endpoint.
    """
    if not PARALLEL_SYNC_AVAILABLE:
        raise HTTPException(status_code=503, detail="Parallel sync service not available")
    
    try:
        # Try using Celery tasks first (preferred for non-blocking)
        try:
            from tasks.api_tasks import start_async_email_sync
            
            if account_emails and len(account_emails) == 1:
                # Single account sync
                result = start_async_email_sync(
                    account_email=account_emails[0],
                    since_days=since_days
                )
            else:
                # All accounts sync (or specific list)
                result = start_async_email_sync(
                    account_email=None,
                    since_days=since_days
                )
            
            return {
                "success": True,
                "message": "Parallel sync started via background workers",
                "operation_id": result['operation_id'],
                "poll_url": f"/operations/async/{result['operation_id']}/status",
                "async": True
            }
            
        except ImportError:
            # Celery not available, fall back to thread-based sync
            logger.warning("Celery not configured, falling back to thread-based sync")
            result = start_background_parallel_sync(
                account_emails=account_emails,
                since_days=since_days
            )
            return {
                **result,
                "async": False,
                "message": "Sync started (Celery not configured, using thread-based sync)"
            }
        
    except Exception as e:
        logger.error(f"Error starting parallel sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/parallel-sync/status")
async def get_sync_status():
    """
    Get status of all parallel sync operations.
    Shows progress per account including downloaded/total counts.
    """
    if not PARALLEL_SYNC_AVAILABLE:
        raise HTTPException(status_code=503, detail="Parallel sync service not available")
    
    try:
        status = get_parallel_sync_status()
        return status
    except Exception as e:
        logger.error(f"Error getting sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SYNC PROGRESS SSE, WEBSOCKET & CANCELLATION ENDPOINTS
# ============================================

from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import redis

# Import WebSocket connection manager
try:
    from websocket_manager import connection_manager, BroadcastPriority
    WEBSOCKET_AVAILABLE = True
except ImportError:
    try:
        from backend.websocket_manager import connection_manager, BroadcastPriority
        WEBSOCKET_AVAILABLE = True
    except ImportError:
        WEBSOCKET_AVAILABLE = False
        logger.warning("WebSocket manager not available")

# Redis connection for sync cancellation flags
try:
    _sync_redis = redis.Redis(host='localhost', port=6379, db=3, decode_responses=True)
    SYNC_REDIS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Redis not available for sync control: {e}")
    SYNC_REDIS_AVAILABLE = False
    _sync_redis = None


def get_sync_cancellation_key(mailbox_id: str) -> str:
    """Get Redis key for sync cancellation flag"""
    return f"sync:cancel:{mailbox_id}"


@router.websocket("/ws/sync")
async def websocket_sync_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time sync progress updates.
    
    This is the preferred method over SSE for sync progress as it:
    - Supports bidirectional communication
    - Has lower priority than survey updates (CPX/CINT)
    - Includes server-side throttling to prevent flooding
    
    Messages received:
    - {"type": "sync_progress", "mailboxes": [...]} - Progress updates
    - {"type": "heartbeat"} - Keep-alive ping
    - {"type": "connected", "channel": "sync_progress"} - Connection confirmation
    
    The client can send:
    - {"type": "ping"} - Heartbeat response
    """
    # Import parallel_sync_progress collection at module scope for static analysis
    from leads.parallel_email_sync import parallel_sync_progress as sync_progress_coll
    
    if not WEBSOCKET_AVAILABLE:
        await websocket.close(code=1011, reason="WebSocket manager not available")
        return
    
    connected = await connection_manager.connect(websocket, "sync_progress")
    if not connected:
        return
    
    try:
        # Start background task to poll progress and broadcast
        async def progress_broadcaster():
            """Background task to fetch and broadcast sync progress."""
            last_states = {}
            
            while True:
                try:
                    # Fetch current progress from MongoDB
                    progress_docs = list(sync_progress_coll.find({
                        "status": {"$in": ["pending", "connecting", "counting", "downloading", "processing"]}
                    }))
                    
                    # Also fetch recently completed (last 30 seconds)
                    recent_threshold = datetime.utcnow() - timedelta(seconds=30)
                    completed_docs = list(sync_progress_coll.find({
                        "status": {"$in": ["completed", "error", "cancelled"]},
                        "updated_at": {"$gte": recent_threshold}
                    }))
                    
                    all_docs = progress_docs + completed_docs
                    
                    if all_docs:
                        mailboxes = []
                        for doc in all_docs:
                            mailbox_id = doc.get("email", "")
                            downloaded = doc.get("downloaded", 0)
                            total = doc.get("total_emails", 0)
                            status = doc.get("status", "unknown")
                            
                            # Only send if state changed
                            state_key = f"{mailbox_id}:{downloaded}:{status}"
                            if state_key != last_states.get(mailbox_id):
                                last_states[mailbox_id] = state_key
                                
                                percentage = round((downloaded / total) * 100, 1) if total > 0 else 0
                                
                                mailboxes.append({
                                    "mailbox_id": mailbox_id,
                                    "status": status,
                                    "synced_count": downloaded,
                                    "total_count": total,
                                    "percentage": percentage,
                                    "current_folder": doc.get("current_folder", ""),
                                    "current_email_id": doc.get("current_email_id", ""),
                                    "current_subject": doc.get("current_subject", ""),
                                    "errors": doc.get("errors", 0),
                                })
                        
                        if mailboxes:
                            # Use priority broadcast - sync has lowest priority
                            await connection_manager.broadcast(
                                channel="sync_progress",
                                message={
                                    "type": "sync_progress",
                                    "mailboxes": mailboxes
                                },
                                priority=BroadcastPriority.SYNC_PROGRESS
                            )
                    
                    # Wait before next poll (throttled on WebSocket manager side too)
                    await asyncio.sleep(1.0)
                    
                except Exception as e:
                    logger.error(f"WebSocket progress broadcaster error: {e}")
                    await asyncio.sleep(2.0)
        
        # Start broadcaster in background
        broadcaster_task = asyncio.create_task(progress_broadcaster())
        
        # Handle incoming messages from client
        while True:
            try:
                data = await websocket.receive_json()
                
                if data.get("type") == "ping":
                    await connection_manager.send_personal(websocket, {
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.warning(f"WebSocket receive error: {e}")
                break
        
        # Cancel broadcaster on disconnect
        broadcaster_task.cancel()
        
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket sync endpoint error: {e}")
    finally:
        connection_manager.disconnect(websocket, "sync_progress")


@router.post("/sync/{mailbox_id}/cancel")
async def cancel_sync_operation(mailbox_id: str):
    """
    Cancel an active sync operation for a specific mailbox.
    
    Sets a cancellation flag that the sync process checks periodically.
    The sync will stop gracefully after completing the current batch.
    """
    if not SYNC_REDIS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Sync cancellation not available (Redis required)")
    
    try:
        # Set cancellation flag with 5 minute TTL
        cancel_key = get_sync_cancellation_key(mailbox_id)
        _sync_redis.setex(cancel_key, 300, "1")
        
        # Also update MongoDB progress
        from leads.parallel_email_sync import parallel_sync_progress
        result = parallel_sync_progress.update_one(
            {"email": mailbox_id},
            {"$set": {"status": "cancelling", "updated_at": datetime.utcnow()}}
        )
        
        return {
            "success": True,
            "message": f"Cancellation requested for {mailbox_id}",
            "mailbox_id": mailbox_id
        }
    except Exception as e:
        logger.error(f"Error cancelling sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def is_sync_cancelled(mailbox_id: str) -> bool:
    """Check if sync is cancelled for a mailbox"""
    if not SYNC_REDIS_AVAILABLE or not _sync_redis:
        return False
    try:
        cancel_key = get_sync_cancellation_key(mailbox_id)
        return _sync_redis.get(cancel_key) == "1"
    except:
        return False


def clear_sync_cancellation(mailbox_id: str):
    """Clear the cancellation flag after sync stops"""
    if SYNC_REDIS_AVAILABLE and _sync_redis:
        try:
            cancel_key = get_sync_cancellation_key(mailbox_id)
            _sync_redis.delete(cancel_key)
        except:
            pass


async def sync_progress_event_generator():
    """
    Generator for SSE sync progress events.
    
    Yields JSON events with sync progress for all active mailboxes:
    - mailbox_id: The mailbox email address
    - current_email_id: ID of email currently being synced
    - current_subject: Subject preview of current email
    - synced_count: Number of emails synced so far
    - total_count: Total emails to sync
    - status: Current status (connecting, counting, downloading, completed, error)
    - percentage: Progress percentage
    """
    from leads.parallel_email_sync import parallel_sync_progress
    
    last_states = {}
    
    while True:
        try:
            # Get all active sync operations
            progress_docs = list(parallel_sync_progress.find({
                "status": {"$in": ["pending", "connecting", "counting", "downloading", "processing"]}
            }))
            
            # Also include recently completed (within last 30 seconds)
            recent_threshold = datetime.utcnow() - timedelta(seconds=30)
            completed_docs = list(parallel_sync_progress.find({
                "status": {"$in": ["completed", "error", "cancelled"]},
                "updated_at": {"$gte": recent_threshold}
            }))
            
            all_docs = progress_docs + completed_docs
            
            if all_docs:
                events = []
                for doc in all_docs:
                    mailbox_id = doc.get("email", "unknown")
                    total = doc.get("total_emails", 0)
                    downloaded = doc.get("downloaded", 0)
                    percentage = round((downloaded / total * 100), 1) if total > 0 else 0
                    
                    event_data = {
                        "mailbox_id": mailbox_id,
                        "current_email_id": doc.get("current_email_id", ""),
                        "current_subject": doc.get("current_subject", "")[:50] if doc.get("current_subject") else "",
                        "synced_count": downloaded,
                        "total_count": total,
                        "status": doc.get("status", "unknown"),
                        "percentage": percentage,
                        "current_folder": doc.get("current_folder", ""),
                        "errors": doc.get("errors", [])[:3],  # Last 3 errors only
                    }
                    
                    # Only emit if state changed
                    state_key = f"{mailbox_id}:{downloaded}:{doc.get('status')}"
                    if state_key != last_states.get(mailbox_id):
                        last_states[mailbox_id] = state_key
                        events.append(event_data)
                
                if events:
                    data = json.dumps({"type": "sync_progress", "mailboxes": events, "timestamp": datetime.utcnow().isoformat()})
                    yield f"data: {data}\n\n"
            else:
                # No active syncs - send heartbeat
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Wait before next check (500ms for responsive updates)
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"SSE generator error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            await asyncio.sleep(2)


@router.get("/sync/stream")
async def sync_progress_stream():
    """
    Server-Sent Events (SSE) stream for real-time sync progress.
    
    Connect to this endpoint to receive live updates on email sync progress.
    Events include:
    - sync_progress: Progress update for one or more mailboxes
    - heartbeat: Keep-alive message when no syncs are active
    - error: Error notification
    
    Example usage (JavaScript):
    ```javascript
    const eventSource = new EventSource('/api/gmail/sync/stream');
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log(data);
    };
    ```
    
    **DEPRECATED**: This SSE endpoint is deprecated in favor of the WebSocket endpoint
    at `/gmail/ws/sync`. The WebSocket endpoint provides better performance with
    priority-based broadcasting that ensures survey updates (CPX/CINT) are not
    blocked by sync progress updates. This endpoint will be removed in a future release.
    """
    # Log deprecation usage for monitoring
    logger.info("DEPRECATED: SSE sync/stream endpoint accessed - migrate to WebSocket /ws/sync")
    
    return StreamingResponse(
        sync_progress_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "X-Deprecated": "true",  # Signal deprecation to clients
            "X-Deprecated-Message": "Use WebSocket endpoint /gmail/ws/sync instead",
        }
    )


# ============================================
# AI EMAIL AGENTS ENDPOINTS
# ============================================

try:
    from leads.ai_email_agents import (
        agent1_process_email_thread,
        agent1_batch_process,
        agent2_categorize_batch,
        run_batch_categorization,
        get_uncategorized_leads,
        get_category_statistics,
        get_agents_status,
        process_new_emails_pipeline
    )
    AI_AGENTS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI agents module not available: {e}")
    AI_AGENTS_AVAILABLE = False


@router.get("/ai-agents/status")
async def get_ai_agents_status():
    """
    Get status of AI email agents including:
    - Gemini API key status
    - Agent 1 (Summary & Contact) stats
    - Agent 2 (Categorization) stats
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        status = get_agents_status()
        return {"success": True, **status}
    except Exception as e:
        logger.error(f"Error getting agents status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-agents/agent1/process")
async def run_agent1_on_lead(
    contact_email: str = Body(..., description="Contact email to process"),
    background_tasks: BackgroundTasks = None
):
    """
    Run Agent 1 (Summary & Contact Extraction) on a specific lead.
    
    Agent 1 will:
    - Fetch all emails for this contact (full thread/trail)
    - Create a 500-word max AI summary
    - Extract: first name, last name, email, company domain
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        # Get emails for this contact
        lead = email_leads_collection.find_one({"email": contact_email})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        emails = lead.get("email_threads", [])
        if not emails:
            return {
                "success": False,
                "message": "No emails found for this contact"
            }
        
        result = agent1_process_email_thread(
            emails=emails,
            contact_email=contact_email,
            source="api"
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running Agent 1: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-agents/agent1/batch")
async def run_agent1_batch(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    skip_existing: bool = Query(True)
):
    """
    Run Agent 1 on a batch of leads (background task).
    
    Processes leads that haven't been summarized yet.
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        # Find leads needing summaries
        query = {"email_threads.0": {"$exists": True}}
        if skip_existing:
            query["conversation_summary"] = {"$exists": False}
        
        leads = list(email_leads_collection.find(query).limit(limit))
        
        if not leads:
            return {
                "success": True,
                "message": "No leads to process"
            }
        
        # Prepare for batch processing
        leads_to_process = [
            {"contact_email": lead["email"], "emails": lead.get("email_threads", [])}
            for lead in leads
        ]
        
        def process_batch():
            results = agent1_batch_process(leads_to_process)
            logger.info(f"Agent 1 batch complete: {len(results)} leads processed")
        
        background_tasks.add_task(process_batch)
        
        return {
            "success": True,
            "message": f"Agent 1 batch started for {len(leads_to_process)} leads",
            "leads_count": len(leads_to_process)
        }
    except Exception as e:
        logger.error(f"Error starting Agent 1 batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-agents/agent2/categorize")
async def run_agent2_categorization(
    background_tasks: BackgroundTasks,
    limit: int = Query(500, ge=50, le=1000)
):
    """
    Run Agent 2 (Bulk Categorization) on uncategorized leads.
    
    Agent 2 will:
    - Take up to 500 AI summaries
    - Dynamically determine categories based on the data
    - Assign each lead to a category
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        # Get uncategorized leads count first
        summaries = get_uncategorized_leads(limit)
        
        if not summaries:
            return {
                "success": True,
                "message": "No uncategorized leads found"
            }
        
        def run_categorization():
            result = agent2_categorize_batch(summaries)
            logger.info(f"Agent 2 complete: {len(result.get('categories', []))} categories, {len(result.get('categorized_leads', []))} leads")
        
        background_tasks.add_task(run_categorization)
        
        return {
            "success": True,
            "message": f"Agent 2 categorization started for {len(summaries)} leads",
            "leads_count": len(summaries)
        }
    except Exception as e:
        logger.error(f"Error starting Agent 2: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-agents/categories")
async def get_ai_categories():
    """
    Get all AI-generated categories and their statistics.
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        stats = get_category_statistics()
        return {"success": True, **stats}
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-agents/full-pipeline")
async def run_full_ai_pipeline(
    background_tasks: BackgroundTasks,
    run_sync: bool = Query(True, description="Run parallel sync first"),
    since_days: int = Query(30, ge=0),
    agent1_limit: int = Query(100, ge=1, le=500),
    agent2_limit: int = Query(500, ge=50, le=1000)
):
    """
    Run the complete AI pipeline:
    1. Parallel email sync (optional)
    2. Agent 1: Generate summaries for new leads
    3. Agent 2: Categorize leads with summaries
    """
    if not AI_AGENTS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI agents not available")
    
    try:
        def run_pipeline():
            import time
            
            # Step 1: Sync emails if requested
            if run_sync and PARALLEL_SYNC_AVAILABLE:
                logger.info("Pipeline: Starting parallel email sync...")
                from leads.parallel_email_sync import parallel_sync_all_accounts
                sync_result = parallel_sync_all_accounts(since_days=since_days)
                logger.info(f"Pipeline: Sync complete - {sync_result.get('total_emails', 0)} emails")
                time.sleep(2)
            
            # Step 2: Run Agent 1
            logger.info(f"Pipeline: Running Agent 1 on up to {agent1_limit} leads...")
            query = {
                "email_threads.0": {"$exists": True},
                "conversation_summary": {"$exists": False}
            }
            leads = list(email_leads_collection.find(query).limit(agent1_limit))
            
            if leads:
                leads_to_process = [
                    {"contact_email": lead["email"], "emails": lead.get("email_threads", [])}
                    for lead in leads
                ]
                results = agent1_batch_process(leads_to_process)
                logger.info(f"Pipeline: Agent 1 complete - {len(results)} leads processed")
                time.sleep(2)
            
            # Step 3: Run Agent 2
            logger.info(f"Pipeline: Running Agent 2 categorization...")
            summaries = get_uncategorized_leads(agent2_limit)
            if summaries:
                result = agent2_categorize_batch(summaries)
                logger.info(f"Pipeline: Agent 2 complete - {len(result.get('categories', []))} categories")
            
            logger.info("Pipeline: Complete!")
        
        background_tasks.add_task(run_pipeline)
        
        return {
            "success": True,
            "message": "Full AI pipeline started in background",
            "steps": ["parallel_sync", "agent1_summaries", "agent2_categorization"] if run_sync else ["agent1_summaries", "agent2_categorization"]
        }
    except Exception as e:
        logger.error(f"Error starting pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

