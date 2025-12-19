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
except ImportError as e:
    logging.warning(f"Gmail automation import error: {e}")

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
mongo_client = MongoClient(MONGO_URI)
gmail_db = mongo_client["torpedo_gmail"]
accounts_collection = gmail_db["accounts"]
rate_limits_collection = gmail_db["rate_limits"]
email_cache_collection = gmail_db["email_cache"]
settings_collection = gmail_db["settings"]

# In-memory cache for authenticated services
_gmail_services: Dict[str, Any] = {}
_authenticators: Dict[str, GmailAuthenticator] = {}


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
    settings = settings_collection.find_one({"_id": "rate_limits"})
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


def get_authenticator(account_id: str) -> GmailAuthenticator:
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
    settings = get_rate_limit_settings()
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
