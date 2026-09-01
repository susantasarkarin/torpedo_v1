"""
PANEL ROUTER
Survey Panel user authentication and management endpoints.

Endpoints:
- POST /panel/signup - Register new panelist
- POST /panel/login - Authenticate panelist
- POST /panel/logout - Invalidate session
- GET  /panel/verify-email - Complete double opt-in from the emailed link
- POST /panel/resend-verification - Re-send the double opt-in email
- POST /panel/forgot-password - Request password reset (sends the email)
- POST /panel/reset-password - Reset password with token
- GET /panel/profile - Get panelist profile
- PUT /panel/profile - Update panelist profile
- GET /panel/profile/completion - Get profile completion percentage
- GET /panel/surveys - Get available surveys for panelist
- GET /panel/rewards/balance - Get current reward points
- GET /panel/rewards/history - Get rewards transaction history
"""

import os
import secrets
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, validator
from bson import ObjectId
from pymongo import MongoClient

# Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


# Auth utilities
from auth import hash_password, verify_password
from session_store import get_session_store

# ============== LOGGING ==============
logger = logging.getLogger(__name__)

# ============== RATE LIMITING ==============
# Create limiter instance - uses client IP for rate limiting
limiter = Limiter(key_func=get_remote_address)

# ============== CONFIGURATION ==============

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
db = client["campaign_platform"]

# Collections
panelists_collection = db["panelists"]
panel_sessions_collection = db["panel_sessions"]
surveys_collection = db["surveys"]
rewards_collection = db["panel_rewards"]

# Token lookups happen on every verification / reset click; without these the
# lookup is a full scan of the ~190K panelists collection.
try:
    panelists_collection.create_index("verification_token", sparse=True)
    panelists_collection.create_index("reset_token", sparse=True)
except Exception as _idx_err:  # pragma: no cover
    logger.warning(f"panel token index creation failed: {_idx_err}")

# Session settings
PANEL_SESSION_TTL = 60 * 60 * 24 * 7  # 7 days

# Where to land the user after they click a verification link. Kept on the
# public SPA host, not the API host.
PANEL_PUBLIC_BASE_URL = os.getenv(
    "PANEL_PUBLIC_BASE_URL", "https://torpedo.cogentixresearch.com"
).rstrip("/")


def _send_verification(panelist_id: str, email: str, first_name: str) -> bool:
    """Issue a fresh verification token and email it. Never raises.

    Signup must still succeed if SES is down — the user can request a resend
    from the login screen — so failures are logged, not surfaced as a 500.
    """
    try:
        from services.panel_transactional_email import new_token, verification_expiry, send_verification_email

        token = new_token()
        panelists_collection.update_one(
            {"_id": ObjectId(panelist_id)},
            {"$set": {
                "verification_token": token,
                "verification_token_expires": verification_expiry(),
                "verification_sent_at": datetime.utcnow(),
            }},
        )
        ok, details = send_verification_email(email, first_name, token)
        if not ok:
            logger.error(f"Verification email failed for {email[:3]}***: {details}")
        return ok
    except Exception as e:
        logger.error(f"Verification email error for {email[:3]}***: {e}")
        return False

# ============== SCHEMAS ==============

class PanelistSignupRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    country: str = Field(..., min_length=2, max_length=100)
    language: str = Field(default="English", max_length=50)
    password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)
    
    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v
    
    @validator('password')
    def password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        return v


class PanelistLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PanelistLoginResponse(BaseModel):
    message: str
    panelist_id: str
    email: str
    first_name: str
    last_name: str
    panel_session_id: str
    rewards_balance: float = 0.0


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def password_strength(cls, v):
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', v):
            raise ValueError('Password must contain at least one digit')
        return v


class PanelistProfile(BaseModel):
    first_name: str
    last_name: str
    email: str
    country: str
    language: str
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    occupation: Optional[str] = None
    education: Optional[str] = None
    income_range: Optional[str] = None
    created_at: Optional[str] = None
    profile_completion: int = 0


class ProfileUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    occupation: Optional[str] = None
    education: Optional[str] = None
    income_range: Optional[str] = None


class SurveyItem(BaseModel):
    id: str
    title: str
    description: str
    estimated_time: int  # minutes
    reward_points: float
    category: Optional[str] = None
    status: str = "available"


class RewardsBalance(BaseModel):
    balance: float
    currency: str = "INR"
    pending: float = 0.0


class RewardsTransaction(BaseModel):
    id: str
    type: str  # "earned" or "redeemed"
    amount: float
    description: str
    date: str
    status: str = "completed"


# ============== ROUTER ==============

router = APIRouter(prefix="/panel", tags=["Panel"])


# ============== HELPER FUNCTIONS ==============

def generate_session_id() -> str:
    """Generate a secure session ID for panelists"""
    return f"panel_{secrets.token_urlsafe(32)}"


def get_panelist_from_session(session_id: str) -> Optional[dict]:
    """Retrieve panelist from session ID"""
    if not session_id or not session_id.startswith("panel_"):
        return None
    
    session = panel_sessions_collection.find_one({
        "session_id": session_id,
        "expires_at": {"$gt": datetime.utcnow()}
    })
    
    if not session:
        return None
    
    panelist = panelists_collection.find_one({"_id": ObjectId(session["panelist_id"])})
    return panelist


# Fields that are impossible to leave blank: PanelistSignupRequest requires
# first_name/last_name/email/country, and language defaults to "English" when
# omitted. Every account has all five the instant it exists.
_PROFILE_COMPLETION_OPTIONAL_FIELDS = [
    "phone", "date_of_birth", "gender", "address", "city",
    "postal_code", "occupation", "education", "income_range",
]


def calculate_profile_completion(panelist: dict) -> int:
    """Percentage of the OPTIONAL profile fields a panelist has filled in.

    Previously averaged across all 14 fields including the five that are
    mandatory at signup, so a brand-new account with nothing else filled in
    always reported ~36% — the dashboard's "profile completion" number, and
    the progress ring shown to the panelist, could never read below that
    floor regardless of actual engagement. Restricting the denominator to
    fields the user actually chooses to fill in makes 0% mean what it says.
    """
    fields = _PROFILE_COMPLETION_OPTIONAL_FIELDS
    filled = sum(1 for f in fields if panelist.get(f))
    return int((filled / len(fields)) * 100)


async def get_current_panelist(request: Request) -> dict:
    """Dependency to get current authenticated panelist"""
    session_id = request.headers.get("X-Panel-Session-Id") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    panelist = get_panelist_from_session(session_id)
    if not panelist:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    return panelist


# ============== AUTH ENDPOINTS ==============

@router.post("/signup", response_model=dict)
@limiter.limit("3/hour")  # Rate limit: 3 signups per hour per IP
async def signup(request: Request, data: PanelistSignupRequest):
    """Register a new panelist account
    
    Rate limited to 3 requests per hour per IP to prevent abuse.
    """
    
    # Check if email already exists
    existing = panelists_collection.find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create panelist document
    panelist = {
        "first_name": data.first_name,
        "last_name": data.last_name,
        "email": data.email.lower(),
        "country": data.country,
        "language": data.language,
        "password_hash": hash_password(data.password),
        "rewards_balance": 0.0,
        "email_verified": False,
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    result = panelists_collection.insert_one(panelist)
    panelist_id = str(result.inserted_id)

    # Create session
    session_id = generate_session_id()
    panel_sessions_collection.insert_one({
        "session_id": session_id,
        "panelist_id": panelist_id,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(seconds=PANEL_SESSION_TTL)
    })

    # Double opt-in: signup previously created a fully usable account and never
    # asked the user to confirm the address, so email_verified stayed False
    # forever and nobody ever received a confirmation mail.
    verification_sent = _send_verification(panelist_id, panelist["email"], data.first_name)

    return {
        "message": "Account created successfully. Check your inbox to confirm your email address.",
        "panelist_id": panelist_id,
        "email": data.email,
        "first_name": data.first_name,
        "last_name": data.last_name,
        "panel_session_id": session_id,
        "rewards_balance": 0.0,
        "email_verified": False,
        "verification_email_sent": verification_sent,
    }


@router.get("/verify-email")
async def verify_email(token: str = Query("", min_length=1)):
    """Complete double opt-in from the emailed link, then bounce to the panel.

    A GET that redirects (rather than a JSON POST) so the link works straight
    from any mail client. The token is single-use: it is cleared on success,
    so a second click lands on already_verified rather than an error.
    """
    landing = f"{PANEL_PUBLIC_BASE_URL}/panel/login"

    panelist = panelists_collection.find_one({"verification_token": token})
    if not panelist:
        # Either never valid, or already consumed by an earlier click.
        return RedirectResponse(url=f"{landing}?verified=invalid", status_code=302)

    expires = panelist.get("verification_token_expires")
    if expires and expires < datetime.utcnow():
        return RedirectResponse(url=f"{landing}?verified=expired", status_code=302)

    now = datetime.utcnow()
    panelists_collection.update_one(
        {"_id": panelist["_id"]},
        {
            "$set": {
                "email_verified": True,
                "double_opt_in_completed": True,
                "double_opt_in_completed_at": now,
                "status": "confirmed",
                "updated_at": now,
            },
            "$unset": {"verification_token": "", "verification_token_expires": ""},
        },
    )

    # Stop the invite cron chasing someone who has now confirmed, and let the
    # funnel report the conversion.
    try:
        from services.panel_bounce_handler import mark_double_opt_in_completed
        mark_double_opt_in_completed(
            email=panelist.get("email", ""),
            invite_token="",
            metadata={"source": "panel_verify_email"},
        )
    except Exception as e:
        logger.warning(f"Post-verification bookkeeping failed: {e}")

    return RedirectResponse(url=f"{landing}?verified=1", status_code=302)


@router.post("/resend-verification")
@limiter.limit("3/hour")
async def resend_verification(request: Request, data: ForgotPasswordRequest):
    """Re-send the double opt-in email. Rate limited to 3/hour per IP."""
    panelist = panelists_collection.find_one({"email": data.email.lower()})

    # Same non-committal response either way — this must not reveal whether an
    # address is registered.
    generic = {"message": "If the account exists and is unconfirmed, a new confirmation email has been sent"}

    if not panelist or panelist.get("email_verified"):
        return generic

    _send_verification(str(panelist["_id"]), panelist["email"], panelist.get("first_name", ""))
    return generic


@router.post("/login", response_model=PanelistLoginResponse)
@limiter.limit("5/minute")  # Rate limit: 5 login attempts per minute per IP
async def login(request: Request, data: PanelistLoginRequest):
    """Authenticate panelist and create session
    
    Rate limited to 5 requests per minute per IP to prevent brute force attacks.
    """
    
    panelist = panelists_collection.find_one({"email": data.email.lower()})
    
    if not panelist:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # verify_password raises ValueError on a hash it refuses to interpret (a
    # genuine legacy plaintext value). Admin login catches that and migrates;
    # this one did not, so it escaped as a 500. A failed credential check is a
    # 401 whatever the stored hash looks like — never a server error, and never
    # a distinguishable response that tells an attacker the account exists.
    try:
        password_ok = verify_password(data.password, panelist.get("password_hash", ""))
    except ValueError:
        logger.warning("panelist %s has an uninterpretable password hash", data.email.lower())
        password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # "confirmed" is what verify-email / mark_double_opt_in_completed /
    # the SFW registration sync all set on a fully opted-in panelist, so it
    # has to count as active here — checking `!= "active"` alone locked out
    # exactly the users who had completed double opt-in.
    if str(panelist.get("status") or "").lower() not in {"active", "confirmed", "double_opted_in"}:
        raise HTTPException(status_code=403, detail="Account is not active")
    
    # Create new session
    session_id = generate_session_id()
    panel_sessions_collection.insert_one({
        "session_id": session_id,
        "panelist_id": str(panelist["_id"]),
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(seconds=PANEL_SESSION_TTL)
    })
    
    # Update last login
    panelists_collection.update_one(
        {"_id": panelist["_id"]},
        {"$set": {"last_login": datetime.utcnow()}}
    )
    
    return PanelistLoginResponse(
        message="Login successful",
        panelist_id=str(panelist["_id"]),
        email=panelist["email"],
        first_name=panelist["first_name"],
        last_name=panelist["last_name"],
        panel_session_id=session_id,
        rewards_balance=panelist.get("rewards_balance", 0.0)
    )


@router.post("/logout")
async def logout(request: Request):
    """Invalidate current session"""
    session_id = request.headers.get("X-Panel-Session-Id") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    if session_id:
        panel_sessions_collection.delete_one({"session_id": session_id})
    
    return {"message": "Logged out successfully"}


async def _resolve_unsubscribe_email(request: Request) -> Optional[str]:
    """Find the address to opt out, from a signed token, body, query or session."""
    from services.panel_unsubscribe import read_token

    token = request.query_params.get("token")
    email = request.query_params.get("email")

    if not (token or email):
        try:
            payload = await request.json()
            token = payload.get("token")
            email = payload.get("email")
        except Exception:
            pass

    if token:
        resolved = read_token(token)
        if resolved:
            return resolved

    if email:
        return email.strip().lower()

    session_id = (
        request.headers.get("X-Panel-Session-Id")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
    )
    if session_id:
        panelist = get_panelist_from_session(session_id)
        if panelist:
            return (panelist.get("email") or "").lower()

    return None


@router.post("/unsubscribe")
async def unsubscribe(request: Request):
    """Record an opt-out.

    Previously this only flipped the panelist's status to "dnd" and never
    touched `panel_email_suppression`, which is the list the bulk senders
    actually consult — and no email ever linked here anyway, so in practice it
    had never run. It now writes the suppression entry too.
    """
    from services.panel_unsubscribe import unsubscribe_email

    email = await _resolve_unsubscribe_email(request)
    if email:
        unsubscribe_email(email, source="unsubscribe_page")

    # Deliberately identical whether or not the address was found — this
    # endpoint is public and must not confirm who is on the list.
    return {"message": "Your unsubscribe request has been recorded."}


@router.post("/unsubscribe/one-click")
async def unsubscribe_one_click(request: Request):
    """RFC 8058 one-click target named by the List-Unsubscribe-Post header.

    Gmail and Yahoo POST here directly when the user hits their native
    unsubscribe button; there is no browser session and no confirmation step,
    so this must opt the address out on the first request and always answer
    200 — a non-200 makes the mailbox provider treat the unsubscribe as broken.
    """
    from services.panel_unsubscribe import unsubscribe_email

    try:
        email = await _resolve_unsubscribe_email(request)
        if email:
            unsubscribe_email(email, source="one_click")
        else:
            logger.warning("[panel-unsub] one-click request carried no resolvable address")
    except Exception as e:
        logger.error(f"[panel-unsub] one-click failed: {e}")

    return {"status": "unsubscribed"}


@router.post("/forgot-password")
@limiter.limit("3/hour")  # Rate limit: 3 password reset requests per hour per IP
async def forgot_password(request: Request, data: ForgotPasswordRequest):
    """Request password reset email
    
    Rate limited to 3 requests per hour per IP to prevent abuse.
    """
    panelist = panelists_collection.find_one({"email": data.email.lower()})
    
    # Always return success to prevent email enumeration
    if not panelist:
        return {"message": "If the email exists, a password reset link will be sent"}
    
    from services.panel_transactional_email import new_token, reset_expiry, send_password_reset_email

    reset_token = new_token()

    panelists_collection.update_one(
        {"_id": panelist["_id"]},
        {"$set": {
            "reset_token": reset_token,
            "reset_token_expires": reset_expiry(),
            "reset_requested_at": datetime.utcnow(),
        }}
    )

    # This used to stop at a `# TODO: Send email` comment — the token was
    # stored and the user was told a link was on its way that never existed.
    # SECURITY: never log the token itself.
    ok, details = send_password_reset_email(
        panelist["email"], panelist.get("first_name", ""), reset_token
    )
    if ok:
        logger.info(f"Password reset link sent for email: {data.email[:3]}***")
    else:
        logger.error(f"Password reset email FAILED for {data.email[:3]}***: {details}")

    return {"message": "If the email exists, a password reset link will be sent"}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Reset password using token"""
    panelist = panelists_collection.find_one({
        "reset_token": data.token,
        "reset_token_expires": {"$gt": datetime.utcnow()}
    })
    
    if not panelist:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Update password and clear token
    panelists_collection.update_one(
        {"_id": panelist["_id"]},
        {
            "$set": {
                "password_hash": hash_password(data.new_password),
                "updated_at": datetime.utcnow()
            },
            "$unset": {"reset_token": "", "reset_token_expires": ""}
        }
    )
    
    # Invalidate all sessions for security
    panel_sessions_collection.delete_many({"panelist_id": str(panelist["_id"])})
    
    return {"message": "Password reset successful. Please login with your new password."}


# ============== PROFILE ENDPOINTS ==============

@router.get("/profile", response_model=PanelistProfile)
async def get_profile(panelist: dict = Depends(get_current_panelist)):
    """Get current panelist's profile"""
    
    return PanelistProfile(
        first_name=panelist.get("first_name", ""),
        last_name=panelist.get("last_name", ""),
        email=panelist.get("email", ""),
        country=panelist.get("country", ""),
        language=panelist.get("language", "English"),
        phone=panelist.get("phone"),
        date_of_birth=panelist.get("date_of_birth"),
        gender=panelist.get("gender"),
        address=panelist.get("address"),
        city=panelist.get("city"),
        postal_code=panelist.get("postal_code"),
        occupation=panelist.get("occupation"),
        education=panelist.get("education"),
        income_range=panelist.get("income_range"),
        created_at=str(panelist.get("created_at", "")),
        profile_completion=calculate_profile_completion(panelist)
    )


@router.put("/profile")
async def update_profile(
    data: ProfileUpdateRequest,
    panelist: dict = Depends(get_current_panelist)
):
    """Update panelist profile"""
    
    # Build update dict, excluding None values
    update_data = {k: v for k, v in data.dict().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    
    panelists_collection.update_one(
        {"_id": panelist["_id"]},
        {"$set": update_data}
    )
    
    # Get updated panelist
    updated = panelists_collection.find_one({"_id": panelist["_id"]})
    
    return {
        "message": "Profile updated successfully",
        "profile_completion": calculate_profile_completion(updated)
    }


@router.get("/profile/completion")
async def get_profile_completion(panelist: dict = Depends(get_current_panelist)):
    """Get profile completion percentage"""
    return {
        "completion": calculate_profile_completion(panelist),
        "rewards_balance": panelist.get("rewards_balance", 0.0)
    }


# ============== SURVEY ENDPOINTS ==============

@router.get("/surveys", response_model=List[SurveyItem])
async def get_available_surveys(panelist: dict = Depends(get_current_panelist)):
    """Get list of available surveys for the panelist"""
    
    # TODO: Implement actual survey matching logic based on panelist profile
    # For now, return surveys that match panelist's country
    surveys = surveys_collection.find({
        "status": "active",
        "$or": [
            {"target_countries": {"$in": [panelist.get("country")]}},
            {"target_countries": {"$exists": False}},
            {"target_countries": []}
        ]
    }).limit(20)
    
    result = []
    for survey in surveys:
        result.append(SurveyItem(
            id=str(survey["_id"]),
            title=survey.get("title", "Survey"),
            description=survey.get("description", ""),
            estimated_time=survey.get("estimated_time", 10),
            reward_points=survey.get("reward_points", 0),
            category=survey.get("category"),
            status="available"
        ))
    
    return result


# ============== REWARDS ENDPOINTS ==============

@router.get("/rewards/balance", response_model=RewardsBalance)
async def get_rewards_balance(panelist: dict = Depends(get_current_panelist)):
    """Get current rewards balance"""
    
    # Calculate pending rewards
    pending = rewards_collection.aggregate([
        {"$match": {
            "panelist_id": str(panelist["_id"]),
            "status": "pending",
            "type": "earned"
        }},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ])
    pending_amount = 0.0
    for p in pending:
        pending_amount = p.get("total", 0.0)
    
    return RewardsBalance(
        balance=panelist.get("rewards_balance", 0.0),
        currency="INR",
        pending=pending_amount
    )


@router.get("/rewards/history", response_model=List[RewardsTransaction])
async def get_rewards_history(
    skip: int = 0,
    limit: int = 20,
    panelist: dict = Depends(get_current_panelist)
):
    """Get rewards transaction history"""
    
    transactions = rewards_collection.find({
        "panelist_id": str(panelist["_id"])
    }).sort("created_at", -1).skip(skip).limit(limit)
    
    result = []
    for tx in transactions:
        result.append(RewardsTransaction(
            id=str(tx["_id"]),
            type=tx.get("type", "earned"),
            amount=tx.get("amount", 0),
            description=tx.get("description", ""),
            date=str(tx.get("created_at", "")),
            status=tx.get("status", "completed")
        ))
    
    return result
