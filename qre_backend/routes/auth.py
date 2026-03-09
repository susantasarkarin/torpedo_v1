"""
Simple bearer-token authentication for Admin and Client dashboard access.
Credentials are read from environment variables (see config.py).
Tokens are kept in an in-process dict; they expire after TOKEN_TTL_HOURS.
"""
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from config import ADMIN_PASSWORD, CLIENT_PASSWORD

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_TTL_HOURS = 8

# {token: {role, expires_at}}
_TOKENS: dict[str, dict] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    """Validate credentials and return a bearer token."""
    username = payload.username.strip().lower()
    password = payload.password

    if username == "admin" and password == ADMIN_PASSWORD:
        role = "admin"
    elif username == "viewer" and password == CLIENT_PASSWORD:
        role = "viewer"
    else:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = secrets.token_urlsafe(32)
    _TOKENS[token] = {
        "role": role,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return LoginResponse(token=token, role=role)


@router.post("/logout")
async def logout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    _TOKENS.pop(token, None)
    return {"ok": True}


def verify_token(authorization: str = Header(default="")) -> dict:
    """
    FastAPI dependency — reads Authorization: Bearer <token>,
    verifies it, and returns the token claims dict.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    token = authorization.removeprefix("Bearer ").strip()
    info = _TOKENS.get(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please log in again.")
    if datetime.now(timezone.utc) > info["expires_at"]:
        _TOKENS.pop(token, None)
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return info
