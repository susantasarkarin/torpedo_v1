"""
Central configuration and validation for environment variables.
"""
import os
from dotenv import load_dotenv
from typing import List

load_dotenv()

# Required
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI must be set in environment")

# Session secret
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET or SESSION_SECRET == "supersecretkey_change_this_in_production":
    raise RuntimeError("SESSION_SECRET must be set to a strong secret in production environment")

# CORS origins handling
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
if CORS_ORIGINS_RAW.strip() == "*":
    # Do not allow wildcard in production
    raise RuntimeError("CORS_ORIGINS must not be '*' in production. Provide explicit origins or use env-based overrides.")

CORS_ORIGINS: List[str] = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]

# API base
API_BASE = os.getenv("API_BASE", "http://localhost:9944")

# AI provider
AI_DEFAULT_PROVIDER = os.getenv("AI_DEFAULT_PROVIDER", "anthropic")  # Claude is the only provider

# Additional optional settings with safe defaults
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", 86400))

# Gmail OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", f"{API_BASE}/gmail/auth/callback")
