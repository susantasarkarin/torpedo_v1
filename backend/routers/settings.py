"""
Settings Router - Handles application settings management
"""
from fastapi import APIRouter, Body, HTTPException, Request
from typing import Dict, Any
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv
# Import email safety module for kill switch status
from campaigns.email_safety import get_email_status
# Load env
load_dotenv()

router = APIRouter(
    prefix="/settings",
    tags=["settings"]
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)
settings_db = mongo_client["torpedo_settings"]
app_settings_collection = settings_db["app_settings"]
survey_filter_collection = settings_db["survey_filters"]
ai_prompts_collection = settings_db["ai_prompts"]

# Create indexes for ai_prompts
try:
    ai_prompts_collection.create_index("prompt_key", unique=True)
    ai_prompts_collection.create_index("is_active")
except Exception:
    pass


def get_settings_by_key(key: str) -> Dict[str, Any]:
    """Get settings by key from MongoDB"""
    try:
        settings = app_settings_collection.find_one({"_id": key})
        if settings:
            settings.pop("_id", None)
            return settings
        return {}
    except Exception as e:
        print(f"Error fetching settings for {key}: {e}")
        return {}


def save_settings_by_key(key: str, data: Dict[str, Any]) -> bool:
    """Save settings by key to MongoDB"""
    try:
        app_settings_collection.update_one(
            {"_id": key},
            {"$set": {**data, "last_updated": datetime.utcnow()}},
            upsert=True
        )
        return True
    except Exception as e:
        print(f"Error saving settings for {key}: {e}")
        return False


# ============================================
# Application Settings (Env-like variables)
# ============================================

@router.get("/app")
async def get_app_settings(request: Request = None) -> Dict[str, Any]:
    """
    Get all application settings (equivalent to env variables)
    Returns configured values from database, with fallback to env vars
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Get stored settings
        stored = get_settings_by_key("app_config")
        
        # Define all configurable settings with their defaults from env
        # Note: SESSION_SECRET is server-side only for signing session tokens.
        # It is loaded from environment variables and not user-editable.
        settings = {
            "mongo_uri": stored.get("mongo_uri", os.getenv("MONGO_URI", "mongodb://localhost:27017/")),
            "cpx_app_id": stored.get("cpx_app_id", os.getenv("CPX_APP_ID", "")),
            "cpx_ext_user_id": stored.get("cpx_ext_user_id", os.getenv("CPX_EXT_USER_ID", "")),
            "cpx_secure_hash_key": stored.get("cpx_secure_hash_key", os.getenv("CPX_SECURE_HASH_KEY", "")),
            "cpx_api_timeout": stored.get("cpx_api_timeout", int(os.getenv("CPX_API_TIMEOUT", "30"))),
            # AI Providers - Gemini (email ops) + OpenAI (web search only)
            # NOTE: DeepSeek removed per AI Governance spec
            "openai_api_key": stored.get("openai_api_key", os.getenv("OPENAI_API_KEY", "")),
            # Gemini API Keys (7 individual keys for 7,000 req/day total cap)
            "gemini_api_key_1": stored.get("gemini_api_key_1", os.getenv("GEMINI_API_KEY_1", "")),
            "gemini_api_key_2": stored.get("gemini_api_key_2", os.getenv("GEMINI_API_KEY_2", "")),
            "gemini_api_key_3": stored.get("gemini_api_key_3", os.getenv("GEMINI_API_KEY_3", "")),
            "gemini_api_key_4": stored.get("gemini_api_key_4", os.getenv("GEMINI_API_KEY_4", "")),
            "gemini_api_key_5": stored.get("gemini_api_key_5", os.getenv("GEMINI_API_KEY_5", "")),
            "gemini_api_key_6": stored.get("gemini_api_key_6", os.getenv("GEMINI_API_KEY_6", "")),
            "gemini_api_key_7": stored.get("gemini_api_key_7", os.getenv("GEMINI_API_KEY_7", "")),
            "google_sheets_service_account": stored.get("google_sheets_service_account", os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT", "")),
            # Skrapp.io API keys (3 accounts, 150 searches/month each)
            "skrapp_api_key_1": stored.get("skrapp_api_key_1", os.getenv("SKRAPP_API_KEY_1", "")),
            "skrapp_api_key_2": stored.get("skrapp_api_key_2", os.getenv("SKRAPP_API_KEY_2", "")),
            "skrapp_api_key_3": stored.get("skrapp_api_key_3", os.getenv("SKRAPP_API_KEY_3", "")),
        }
        
        # Mask sensitive fields for display
        masked_settings = {**settings}
        sensitive_fields = [
            "cpx_secure_hash_key",
            "openai_api_key",
            "gemini_api_key_1", "gemini_api_key_2", "gemini_api_key_3", "gemini_api_key_4",
            "gemini_api_key_5", "gemini_api_key_6", "gemini_api_key_7",
            "google_sheets_service_account",
            "skrapp_api_key_1", "skrapp_api_key_2", "skrapp_api_key_3"
        ]
        for field in sensitive_fields:
            if masked_settings.get(field):
                value = str(masked_settings[field])
                if len(value) > 8:
                    masked_settings[field + "_masked"] = value[:4] + "*" * (len(value) - 8) + value[-4:]
                else:
                    masked_settings[field + "_masked"] = "*" * len(value)
        
        return {
            "settings": masked_settings,
            "last_updated": stored.get("last_updated")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching app settings: {str(e)}")


@router.post("/app")
async def save_app_settings(
    settings: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """
    Save application settings to database
    
    Body:
    {
        "mongo_uri": "...",
        "cpx_app_id": "...",
        ...
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Validate and sanitize settings
        # Note: session_secret is intentionally excluded - it's server-side only
        allowed_keys = [
            "mongo_uri",
            "cpx_app_id", "cpx_ext_user_id", "cpx_secure_hash_key", "cpx_api_timeout",
            # AI Providers - Gemini (email) + OpenAI (web search) - DeepSeek removed per governance
            "openai_api_key",
            "gemini_api_key_1", "gemini_api_key_2", "gemini_api_key_3", "gemini_api_key_4",
            "gemini_api_key_5", "gemini_api_key_6", "gemini_api_key_7",
            "google_sheets_service_account",
            "skrapp_api_key_1", "skrapp_api_key_2", "skrapp_api_key_3"
        ]
        
        filtered_settings = {k: v for k, v in settings.items() if k in allowed_keys and v is not None}
        
        if not filtered_settings:
            raise HTTPException(status_code=400, detail="No valid settings provided")
        
        # Get existing settings and merge
        existing = get_settings_by_key("app_config")
        merged = {**existing, **filtered_settings}
        
        success = save_settings_by_key("app_config", merged)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save settings")
        
        return {"message": "Settings saved successfully", "updated_keys": list(filtered_settings.keys())}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving app settings: {str(e)}")


# ============================================
# Survey Filter Settings
# ============================================

@router.get("/survey-filters")
async def get_survey_filter_settings(request: Request = None) -> Dict[str, Any]:
    """
    Get survey filter settings (Min CPI, Deletion Period)
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        stored = get_settings_by_key("survey_filters")
        
        # Default filter values
        filters = {
            "min_cpi": stored.get("min_cpi", 1.0),  # Minimum Cost Per Interview in dollars
            "deletion_period_days": stored.get("deletion_period_days", 7),  # Days before surveys are deleted
            "auto_refresh_enabled": stored.get("auto_refresh_enabled", True),
            "refresh_interval_seconds": stored.get("refresh_interval_seconds", 60),
        }
        
        return {
            "filters": filters,
            "last_updated": stored.get("last_updated")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching survey filters: {str(e)}")


@router.post("/survey-filters")
async def save_survey_filter_settings(
    filters: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """
    Save survey filter settings
    
    Body:
    {
        "min_cpi": 1.0,
        "deletion_period_days": 7,
        "auto_refresh_enabled": true,
        "refresh_interval_seconds": 60
    }
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        allowed_keys = ["min_cpi", "deletion_period_days", "auto_refresh_enabled", "refresh_interval_seconds"]
        filtered = {k: v for k, v in filters.items() if k in allowed_keys and v is not None}
        
        # Validation
        if "min_cpi" in filtered:
            filtered["min_cpi"] = max(0.01, min(100, float(filtered["min_cpi"])))
        if "deletion_period_days" in filtered:
            filtered["deletion_period_days"] = max(1, min(30, int(filtered["deletion_period_days"])))
        if "refresh_interval_seconds" in filtered:
            filtered["refresh_interval_seconds"] = max(30, min(3600, int(filtered["refresh_interval_seconds"])))
        
        if not filtered:
            raise HTTPException(status_code=400, detail="No valid filter settings provided")
        
        # Merge with existing
        existing = get_settings_by_key("survey_filters")
        merged = {**existing, **filtered}
        
        success = save_settings_by_key("survey_filters", merged)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save filter settings")
        
        return {"message": "Filter settings saved successfully", "filters": merged}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving survey filters: {str(e)}")


# ============================================
# Test Connection Endpoints
# ============================================

@router.post("/test-mongo")
async def test_mongo_connection(
    data: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """Test MongoDB connection with given URI"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        uri = data.get("mongo_uri", "")
        if not uri:
            raise HTTPException(status_code=400, detail="MongoDB URI is required")
        
        # Try to connect
        test_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        test_client.admin.command('ping')
        test_client.close()
        
        return {"success": True, "message": "Successfully connected to MongoDB"}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}


@router.post("/test-cpx")
async def test_cpx_credentials(
    data: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """Test CPX API credentials"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        import requests
        import hashlib
        
        app_id = data.get("cpx_app_id", "")
        ext_user_id = data.get("cpx_ext_user_id", "")
        secure_hash_key = data.get("cpx_secure_hash_key", "")
        
        if not all([app_id, ext_user_id, secure_hash_key]):
            raise HTTPException(status_code=400, detail="All CPX credentials are required")
        
        # Generate request hash
        request_id = f"test_{datetime.utcnow().timestamp()}"
        secure_hash = hashlib.md5(f"{ext_user_id}-{secure_hash_key}".encode()).hexdigest()
        
        # Test API call - Using live-api per CPX documentation
        url = "https://live-api.cpx-research.com/api/get-surveys.php"
        params = {
            "app_id": app_id,
            "ext_user_id": ext_user_id,
            "secure_hash": secure_hash,
            "request_id": request_id,
            "output_method": "api"
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "message": "CPX credentials are valid"}
        else:
            return {"success": False, "message": f"CPX API returned status {response.status_code}"}
    
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "message": f"Test failed: {str(e)}"}


# ============================================
# Logs Endpoint
# ============================================

@router.get("/logs")
async def get_deployment_logs(
    request: Request = None,
    lines: int = 1000
) -> Dict[str, Any]:
    """
    Get deployment logs from cron-deploy.log file
    
    Query params:
    - lines: Number of lines to return (default: 1000, max: 10000)
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Limit lines to prevent memory issues
        lines = min(max(1, int(lines)), 10000)
        
        # Log file path - adjust based on your server setup
        log_file_path = "/var/www/campaign_platform/cron-deploy.log"
        
        # Fallback to relative path if absolute doesn't exist
        if not os.path.exists(log_file_path):
            # Try relative path from backend directory
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_file_path = os.path.join(backend_dir, "..", "cron-deploy.log")
            log_file_path = os.path.abspath(log_file_path)
        
        if not os.path.exists(log_file_path):
            return {
                "success": False,
                "message": f"Log file not found at {log_file_path}",
                "logs": [],
                "file_path": log_file_path
            }
        
        # Read last N lines from file
        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                # Get last N lines
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                
                # Get file stats
                file_stats = os.stat(log_file_path)
                
                return {
                    "success": True,
                    "logs": log_lines,
                    "total_lines": len(all_lines),
                    "returned_lines": len(log_lines),
                    "file_path": log_file_path,
                    "file_size": file_stats.st_size,
                    "last_modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat()
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading log file: {str(e)}",
                "logs": [],
                "file_path": log_file_path
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching logs: {str(e)}")


# ============================================
# OpenAI Usage Monitoring - COST CONTROL
# ============================================

@router.get("/openai/usage")
async def get_openai_usage(request: Request = None, hours: int = 24) -> Dict[str, Any]:
    """
    Get OpenAI API usage statistics for cost monitoring.
    COST CONTROL: Provides visibility into token usage and costs.
    
    Args:
        hours: Number of hours to look back (default 24)
    
    Returns:
        Usage breakdown by model and source with total costs
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Import usage logger from wrapper
        from leads.openai_wrapper import token_logger
        
        summary = token_logger.get_usage_summary(hours=hours)
        
        # Calculate totals
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        total_requests = 0
        
        breakdown = summary.get("breakdown", [])
        for item in breakdown:
            total_cost += item.get("total_cost", 0)
            total_input_tokens += item.get("total_input_tokens", 0)
            total_output_tokens += item.get("total_output_tokens", 0)
            total_requests += item.get("total_requests", 0)
        
        return {
            "success": True,
            "period_hours": hours,
            "totals": {
                "total_requests": total_requests,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_cost_usd": round(total_cost, 4),
                "avg_cost_per_request": round(total_cost / max(total_requests, 1), 6)
            },
            "by_model_and_source": breakdown,
            "cost_control_settings": {
                "kill_switch": os.getenv("DISABLE_OPENAI_CALLS", "false"),
                "default_model": "gpt-4o-mini",
                "max_output_tokens_default": 300,
                "max_output_tokens_background": 150
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching OpenAI usage: {str(e)}")


@router.get("/openai/usage/daily")
async def get_openai_daily_usage(request: Request = None) -> Dict[str, Any]:
    """Get daily OpenAI usage for the past 7 days."""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from leads.openai_wrapper import token_logger
        
        # Get usage for last 7 days
        usage_db = mongo_client['email_automation']
        usage_collection = usage_db['openai_usage_logs']
        
        from datetime import timedelta
        
        daily_usage = []
        for days_ago in range(7):
            day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
            day_end = day_start + timedelta(days=1)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": day_start, "$lt": day_end}}},
                {"$group": {
                    "_id": None,
                    "requests": {"$sum": 1},
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "cost": {"$sum": "$cost_usd"}
                }}
            ]
            
            result = list(usage_collection.aggregate(pipeline))
            if result:
                daily_usage.append({
                    "date": day_start.strftime("%Y-%m-%d"),
                    "requests": result[0]["requests"],
                    "input_tokens": result[0]["input_tokens"],
                    "output_tokens": result[0]["output_tokens"],
                    "cost_usd": round(result[0]["cost"], 4)
                })
            else:
                daily_usage.append({
                    "date": day_start.strftime("%Y-%m-%d"),
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0
                })
        
        return {
            "success": True,
            "daily_usage": daily_usage
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching daily usage: {str(e)}")


# ============================================
# Email Safety Status
# ============================================

@router.get("/email-status")
async def get_email_sending_status() -> Dict[str, Any]:
    """
    Get current email sending status (kill switch and dry-run mode)
    
    Returns:
        - email_sending_enabled: Whether emails can be sent
        - dry_run_mode: If true, emails are simulated only
        - can_send_real_emails: Combined check for actual sending
        - blocked_reason: Reason if sending is blocked
        - environment: Current env var values
    """
    return get_email_status()


# ============================================
# Email Signature Settings
# ============================================

# Collection for email signatures
email_signatures_collection = settings_db["email_signatures"]


@router.get("/email-signatures")
async def get_all_email_signatures(request: Request) -> Dict[str, Any]:
    """Get all email signatures for all configured email accounts"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        signatures = list(email_signatures_collection.find({}))
        for sig in signatures:
            sig["_id"] = str(sig["_id"])
        
        return {
            "success": True,
            "signatures": signatures
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching signatures: {str(e)}")


@router.get("/email-signature/{email}")
async def get_email_signature(email: str, request: Request) -> Dict[str, Any]:
    """Get email signature for a specific email address"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        signature = email_signatures_collection.find_one({"email": email})
        if signature:
            signature["_id"] = str(signature["_id"])
            return {
                "success": True,
                "email": email,
                "signature": signature.get("signature_html", ""),
                "signature_text": signature.get("signature_text", ""),
                "is_default": signature.get("is_default", False)
            }
        
        return {
            "success": True,
            "email": email,
            "signature": "",
            "signature_text": "",
            "is_default": False
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching signature: {str(e)}")


@router.put("/email-signature/{email}")
async def update_email_signature(
    email: str,
    request: Request,
    data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Update or create email signature for a specific email address"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        signature_html = data.get("signature_html", data.get("signature", ""))
        signature_text = data.get("signature_text", "")
        is_default = data.get("is_default", False)
        
        # If setting as default, unset other defaults
        if is_default:
            email_signatures_collection.update_many(
                {"email": {"$ne": email}},
                {"$set": {"is_default": False}}
            )
        
        email_signatures_collection.update_one(
            {"email": email},
            {
                "$set": {
                    "email": email,
                    "signature_html": signature_html,
                    "signature_text": signature_text,
                    "is_default": is_default,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        return {
            "success": True,
            "message": f"Signature updated for {email}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating signature: {str(e)}")


@router.delete("/email-signature/{email}")
async def delete_email_signature(email: str, request: Request) -> Dict[str, Any]:
    """Delete email signature for a specific email address"""
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        result = email_signatures_collection.delete_one({"email": email})
        
        if result.deleted_count > 0:
            return {
                "success": True,
                "message": f"Signature deleted for {email}"
            }
        else:
            return {
                "success": False,
                "message": f"No signature found for {email}"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting signature: {str(e)}")


# ============================================
# Cost Analytics - API Usage Monitoring
# ============================================

@router.get("/cost-analytics")
async def get_cost_analytics(request: Request = None, days: int = 7) -> Dict[str, Any]:
    """
    Get comprehensive cost analytics for all API services.
    Includes: Google CSE, OpenAI, and cache performance metrics.
    
    Args:
        days: Number of days to look back (default 7)
        
    Returns:
        Comprehensive cost breakdown and optimization metrics
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from datetime import timedelta
        
        # Get database references
        email_db = mongo_client['email_automation']
        
        # ============ Google CSE Cache Stats ============
        try:
            from leads.search_cache import get_cache_stats, get_cache_size
            cache_stats = get_cache_stats(days)
            cache_size = get_cache_size()
        except Exception as e:
            cache_stats = {"error": str(e)}
            cache_size = {"error": str(e)}
        
        # ============ Google CSE Usage ============
        cse_collection = email_db.get_collection('google_cse_usage')
        since = datetime.utcnow() - timedelta(days=days)
        
        cse_pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": None,
                "total_queries": {"$sum": 1},
                "total_results": {"$sum": "$results_count"}
            }}
        ]
        cse_result = list(cse_collection.aggregate(cse_pipeline))
        
        cse_usage = {
            "queries": cse_result[0]["total_queries"] if cse_result else 0,
            "results": cse_result[0]["total_results"] if cse_result else 0,
            "cost_per_query_usd": 0.005,  # $5 per 1000 queries
            "estimated_cost_usd": round((cse_result[0]["total_queries"] if cse_result else 0) * 0.005, 2)
        }
        
        # ============ OpenAI Usage ============
        openai_collection = email_db.get_collection('openai_usage_logs')
        
        openai_pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": "$model",
                "requests": {"$sum": 1},
                "input_tokens": {"$sum": "$input_tokens"},
                "output_tokens": {"$sum": "$output_tokens"},
                "cost_usd": {"$sum": "$cost_usd"}
            }}
        ]
        openai_result = list(openai_collection.aggregate(openai_pipeline))
        
        openai_usage = {
            "by_model": [{
                "model": r["_id"],
                "requests": r["requests"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "cost_usd": round(r["cost_usd"], 4)
            } for r in openai_result],
            "total_requests": sum(r["requests"] for r in openai_result),
            "total_cost_usd": round(sum(r["cost_usd"] for r in openai_result), 4)
        }
        
        # NOTE: Perplexity usage tracking removed - Perplexity integration has been deprecated.
        # Use Google CSE + OpenAI for AI discovery instead.
        
        # ============ Daily Breakdown ============
        daily_breakdown = []
        for days_ago in range(min(days, 7)):
            day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
            day_end = day_start + timedelta(days=1)
            date_str = day_start.strftime("%Y-%m-%d")
            
            # CSE for day
            cse_day = list(cse_collection.aggregate([
                {"$match": {"timestamp": {"$gte": day_start, "$lt": day_end}}},
                {"$group": {"_id": None, "queries": {"$sum": 1}}}
            ]))
            
            # OpenAI for day
            openai_day = list(openai_collection.aggregate([
                {"$match": {"timestamp": {"$gte": day_start, "$lt": day_end}}},
                {"$group": {"_id": None, "requests": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}}
            ]))
            
            # Cache metrics for day
            cache_metrics = email_db.get_collection('search_cache_metrics')
            cache_day = list(cache_metrics.aggregate([
                {"$match": {"date": date_str}},
                {"$group": {"_id": None, "hits": {"$sum": "$hits"}, "misses": {"$sum": "$misses"}}}
            ]))
            
            # Leads generated for day (from leads_enriched)
            leads_collection = email_db.get_collection('leads_enriched')
            leads_day = leads_collection.count_documents({
                "created_at": {"$gte": day_start, "$lt": day_end}
            })
            
            cse_queries = cse_day[0]["queries"] if cse_day else 0
            openai_requests = openai_day[0]["requests"] if openai_day else 0
            openai_cost = openai_day[0]["cost"] if openai_day else 0
            cache_hits = cache_day[0]["hits"] if cache_day else 0
            cache_misses = cache_day[0]["misses"] if cache_day else 0
            leads_count = leads_day if leads_day else 0
            
            cse_cost_day = round(cse_queries * 0.005, 4)
            total_day_cost = round(cse_cost_day + openai_cost, 4)
            cost_per_lead = round(total_day_cost / leads_count, 4) if leads_count > 0 else 0
            
            daily_breakdown.append({
                "date": date_str,
                "cse_queries": cse_queries,
                "cse_cost_usd": cse_cost_day,
                "openai_requests": openai_requests,
                "openai_cost_usd": round(openai_cost, 4),
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "cache_hit_rate": round(cache_hits / (cache_hits + cache_misses), 4) if (cache_hits + cache_misses) > 0 else 0,
                "leads_generated": leads_count,
                "cost_per_lead_usd": cost_per_lead,
                "total_cost_usd": total_day_cost
            })
        
        # ============ Cost Projections ============
        total_cost_period = cse_usage["estimated_cost_usd"] + openai_usage["total_cost_usd"]
        daily_average = total_cost_period / days if days > 0 else 0
        
        projections = {
            "daily_average_usd": round(daily_average, 2),
            "monthly_projection_usd": round(daily_average * 30, 2),
            "monthly_budget_usd": 100.0,  # Configurable
            "budget_status": "on_track" if daily_average * 30 <= 100 else "over_budget"
        }
        
        # ============ Optimization Recommendations ============
        recommendations = []
        
        cache_hit_rate = cache_stats.get("hit_rate", 0) if isinstance(cache_stats, dict) else 0
        if cache_hit_rate < 0.7:
            recommendations.append({
                "type": "cache",
                "severity": "warning",
                "message": f"Cache hit rate is {cache_hit_rate*100:.1f}%, below 70% target. Consider extending cache TTL."
            })
        else:
            recommendations.append({
                "type": "cache",
                "severity": "success",
                "message": f"Cache hit rate is excellent at {cache_hit_rate*100:.1f}%! Saving ~{cache_hit_rate*100:.0f}% on API costs."
            })
        
        if projections["monthly_projection_usd"] > projections["monthly_budget_usd"]:
            recommendations.append({
                "type": "budget",
                "severity": "critical",
                "message": f"Projected monthly cost (${projections['monthly_projection_usd']}) exceeds budget (${projections['monthly_budget_usd']})."
            })
        
        # Calculate total cost (CSE + OpenAI)
        total_cost_period = cse_usage["estimated_cost_usd"] + openai_usage["total_cost_usd"]
        
        return {
            "success": True,
            "period_days": days,
            "generated_at": datetime.utcnow().isoformat(),
            "cache_performance": {
                "stats": cache_stats,
                "size": cache_size
            },
            "google_cse": cse_usage,
            "openai": openai_usage,
            "daily_breakdown": daily_breakdown,
            "projections": projections,
            "recommendations": recommendations,
            "total_cost_usd": round(total_cost_period, 2)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching cost analytics: {str(e)}")


# ============================================
# AI Prompts Management
# ============================================

# Default prompts for auto-seeding (from ai_classifier.py)
DEFAULT_PROMPTS = {
    "lead_classification": {
        "name": "Lead Classification",
        "description": "System and user prompts for AI-powered lead enrichment and classification",
        "system_prompt": """B2B lead enrichment expert. Respond with JSON only.

Output Schema:
{"first_name":"str","last_name":"str","predicted_email":"firstname.lastname@domain.com","seniority_level":"C-Level|VP|Director|Manager|IC|Unknown","department":"Sales|Marketing|Engineering|Operations|Finance|HR|Product|Other","persona":"Decision Maker|Influencer|Gatekeeper|Practitioner","buying_role":"Economic Buyer|Technical Buyer|User Buyer|Champion|Influencer|Unknown","gender":"Male|Female|Unknown","company_size":"Startup|SMB|Mid-Market|Enterprise","region":"US|EU|APAC|LATAM|Other","inferred_location":"str","company_name":"str","company_domain":"str","company_website":"str","company_employee_count":"str","company_employee_count_range":"1-10|11-50|51-200|201-500|501-1000|1001-5000|5001-10000|10000+","company_founded":"str","company_industry":"str","company_type":"Public|Private|Startup|Non-Profit|Government","company_headquarters":"str","company_revenue_range":"$1M-$10M|$10M-$50M|$50M-$100M|$100M-$500M|$500M-$1B|$1B+","company_linkedin_url":"str","confidence_score":0.0-1.0}

Rules: C-Level=CEO/CTO/CFO/Founder. Startup=1-50,SMB=51-200,Mid-Market=201-1000,Enterprise=1000+. Use knowledge for known companies. Minimize nulls.""",
        "user_prompt_template": """Enrich lead:
Name:{name} Title:{title} URL:{linkedin_url}
Context:{snippet} Location:{location} Company:{company_name} Email:{email}
Return JSON.""",
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_output_tokens": 300
    },
    # NOTE: perplexity_company_discovery prompt removed - Perplexity integration deprecated.
    # Use Google CSE + OpenAI for AI discovery instead.
    "gemini_classify_lead": {
        "name": "Gemini Lead Classification",
        "description": "Gemini prompt for real-time lead classification from emails - optimized for free tier",
        "system_prompt": """You are a B2B lead classification expert. Analyze lead information and classify into appropriate categories.

Output JSON ONLY:
{
  "category": "CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM",
  "confidence": 0.0-1.0,
  "department": "Sales|Marketing|Engineering|HR|Finance|Operations|Legal|Other",
  "seniority": "C-Level|VP|Director|Manager|IC|Entry|Unknown",
  "reasoning": "brief explanation",
  "buying_intent": 0.0-1.0,
  "priority": "HIGH|MEDIUM|LOW"
}

Classification rules:
- CLIENT: Shows buying intent, product interest, or business opportunity
- VENDOR: Offering services/products, partnership proposals
- RECRUITER: Job opportunities, recruitment outreach
- INTERNAL: Company communications, team emails
- SPAM: Unsolicited marketing, low-value content

Buying Intent: 0=no interest, 1=ready to buy. Base on language urgency and specificity.""",
        "user_prompt_template": """Classify this lead:
Email: {email}
Name: {full_name}
Title: {title}
Company: {company}
Subject: {email_subject}
Body: {email_body}

Respond with JSON only.""",
        "model": "gemini-2.0-flash",
        "temperature": 0.3,
        "max_output_tokens": 500
    },
    "gemini_enrich_lead": {
        "name": "Gemini Lead Enrichment",
        "description": "Gemini prompt for enriching lead data with inferred details",
        "system_prompt": """You are a B2B lead intelligence expert. Enrich leads with inferred business information.

Output JSON ONLY:
{
  "title_variations": ["alternative title 1", "alternative title 2"],
  "inferred_skills": ["skill 1", "skill 2", "skill 3"],
  "industry_vertical": "industry name",
  "company_size_estimate": "Startup|SMB|Mid-Market|Enterprise",
  "likely_pain_points": ["pain point 1", "pain point 2"],
  "engagement_angle": "how to approach this lead"
}

Be specific and actionable. Base inferences on typical patterns for this role/company type.""",
        "user_prompt_template": """Enrich this lead:
Title: {title}
Company: {company}
LinkedIn: {linkedin_url}
Website: {company_website}

Return JSON only.""",
        "model": "gemini-2.0-flash",
        "temperature": 0.7,
        "max_output_tokens": 700
    },
    "gemini_extract_contacts": {
        "name": "Gemini Contact Extraction",
        "description": "Gemini prompt for extracting structured contact info from email bodies",
        "system_prompt": """Extract all contact information from email content.

Output JSON ONLY:
{
  "contacts": [
    {
      "name": "full name",
      "title": "job title",
      "email": "email address",
      "phone": "phone number",
      "company": "company name"
    }
  ],
  "primary_contact": {...},
  "signature_extracted": true/false
}

Extract from:
- Email signature
- Body mentions
- CC/BCC references
- Contact cards

Mark primary_contact as most senior or relevant person.
Leave empty fields as null.""",
        "user_prompt_template": """Extract contacts from this email:

{email_body}

Return JSON only.""",
        "model": "gemini-2.0-flash",
        "temperature": 0.5,
        "max_output_tokens": 1000
    },
    "gemini_summarize_email": {
        "name": "Gemini Email Summarization",
        "description": "Gemini prompt for intelligent email summarization and sentiment analysis",
        "system_prompt": """Analyze and summarize email content with business insights.

Output JSON ONLY:
{
  "summary": "2-3 sentence overview",
  "key_points": ["point 1", "point 2"],
  "action_items": ["action 1", "action 2"],
  "sentiment": "POSITIVE|NEUTRAL|NEGATIVE",
  "urgency": "HIGH|MEDIUM|LOW",
  "contains_offer": true/false,
  "next_steps": "recommended response"
}

Focus on business relevance and actionable insights.""",
        "user_prompt_template": """Summarize this email:

Subject: {subject}
Body: {body}

Return JSON only.""",
        "model": "gemini-2.0-flash",
        "temperature": 0.7,
        "max_output_tokens": 800
    },
    "gemini_segment_email": {
        "name": "Gemini Email Segmentation",
        "description": "Quick Gemini email type segmentation for real-time classification",
        "system_prompt": """Quickly segment email into appropriate category.

Output JSON ONLY:
{
  "segment": "CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explanation"
}

Definitions:
- CLIENT: Potential customer, inquiry, business opportunity
- VENDOR: Services/products offered, partnerships
- RECRUITER: Job opportunities, hiring outreach
- INTERNAL: Company communications, team updates
- SPAM: Unsolicited marketing, irrelevant content""",
        "user_prompt_template": """Segment this email:

From: {sender}
Subject: {subject}
Body (first 500 chars): {body}

Return JSON only.""",
        "model": "gemini-2.0-flash",
        "temperature": 0.3,
        "max_output_tokens": 200
    },
    "openai_web_search": {
        "name": "OpenAI Web Search Query Generator",
        "description": "OpenAI prompt for generating effective web search queries to find leads",
        "system_prompt": """You are a B2B lead researcher. Generate effective web search queries to find target prospects.

Format JSON ONLY:
{
  "queries": ["query 1", "query 2", "query 3"],
  "intent": "lead generation|company discovery|competitor research",
  "expected_results": "what we're looking for in results"
}

Create specific, targeted queries that will yield relevant B2B leads.""",
        "user_prompt_template": """Generate search queries to find leads:
Industry: {industry}
Company size: {company_size}
Location: {location}
Criteria: {criteria}

Return JSON with 3 search queries.""",
        "model": "gpt-4o-mini",
        "temperature": 0.5,
        "max_output_tokens": 300
    }
}



def seed_default_prompts():
    """Auto-seed default prompts if collection is empty"""
    try:
        if ai_prompts_collection.count_documents({}) == 0:
            for prompt_key, prompt_data in DEFAULT_PROMPTS.items():
                doc = {
                    "prompt_key": prompt_key,
                    **prompt_data,
                    "is_active": True,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                    "versions": [{
                        "version": 1,
                        "system_prompt": prompt_data["system_prompt"],
                        "user_prompt_template": prompt_data["user_prompt_template"],
                        "created_at": datetime.utcnow(),
                        "created_by": "system"
                    }],
                    "current_version": 1
                }
                ai_prompts_collection.insert_one(doc)
            print("AI Prompts: Seeded default prompts")
    except Exception as e:
        print(f"Error seeding default prompts: {e}")


@router.get("/ai-prompts")
async def list_ai_prompts(request: Request = None) -> Dict[str, Any]:
    """
    GET /settings/ai-prompts
    List all AI prompts with current versions.
    Auto-seeds default prompts if collection is empty.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Auto-seed if empty
        seed_default_prompts()
        
        prompts = list(ai_prompts_collection.find({}))
        
        # Clean up MongoDB ObjectId for JSON serialization
        for prompt in prompts:
            prompt["_id"] = str(prompt["_id"])
            if "created_at" in prompt:
                prompt["created_at"] = prompt["created_at"].isoformat() if hasattr(prompt["created_at"], "isoformat") else str(prompt["created_at"])
            if "updated_at" in prompt:
                prompt["updated_at"] = prompt["updated_at"].isoformat() if hasattr(prompt["updated_at"], "isoformat") else str(prompt["updated_at"])
            # Clean versions timestamps
            for v in prompt.get("versions", []):
                if "created_at" in v:
                    v["created_at"] = v["created_at"].isoformat() if hasattr(v["created_at"], "isoformat") else str(v["created_at"])
        
        return {
            "success": True,
            "prompts": prompts,
            "total": len(prompts)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching AI prompts: {str(e)}")


@router.get("/ai-prompts/{prompt_key}")
async def get_ai_prompt(prompt_key: str, request: Request = None) -> Dict[str, Any]:
    """
    GET /settings/ai-prompts/{prompt_key}
    Get specific prompt with version history.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        prompt = ai_prompts_collection.find_one({"prompt_key": prompt_key})
        
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")
        
        # Clean up for JSON
        prompt["_id"] = str(prompt["_id"])
        if "created_at" in prompt:
            prompt["created_at"] = prompt["created_at"].isoformat() if hasattr(prompt["created_at"], "isoformat") else str(prompt["created_at"])
        if "updated_at" in prompt:
            prompt["updated_at"] = prompt["updated_at"].isoformat() if hasattr(prompt["updated_at"], "isoformat") else str(prompt["updated_at"])
        for v in prompt.get("versions", []):
            if "created_at" in v:
                v["created_at"] = v["created_at"].isoformat() if hasattr(v["created_at"], "isoformat") else str(v["created_at"])
        
        return {
            "success": True,
            "prompt": prompt
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching AI prompt: {str(e)}")


@router.put("/ai-prompts/{prompt_key}")
async def update_ai_prompt(
    prompt_key: str,
    data: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """
    PUT /settings/ai-prompts/{prompt_key}
    Update prompt - creates new version with timestamp for rollback.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        existing = ai_prompts_collection.find_one({"prompt_key": prompt_key})
        
        if not existing:
            raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")
        
        # Get current version number
        current_version = existing.get("current_version", 1)
        new_version = current_version + 1
        
        # Create version snapshot
        version_snapshot = {
            "version": new_version,
            "system_prompt": data.get("system_prompt", existing.get("system_prompt", "")),
            "user_prompt_template": data.get("user_prompt_template", existing.get("user_prompt_template", "")),
            "created_at": datetime.utcnow(),
            "created_by": data.get("created_by", "user")
        }
        
        # Prepare update
        update_fields = {
            "updated_at": datetime.utcnow(),
            "current_version": new_version
        }
        
        # Update allowed fields
        allowed_fields = ["name", "description", "system_prompt", "user_prompt_template", 
                          "model", "temperature", "max_output_tokens", "is_active"]
        for field in allowed_fields:
            if field in data:
                update_fields[field] = data[field]
        
        # Perform update
        result = ai_prompts_collection.update_one(
            {"prompt_key": prompt_key},
            {
                "$set": update_fields,
                "$push": {"versions": version_snapshot}
            }
        )
        
        return {
            "success": True,
            "message": f"Prompt updated to version {new_version}",
            "version": new_version
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating AI prompt: {str(e)}")


@router.post("/ai-prompts/{prompt_key}/rollback/{version}")
async def rollback_ai_prompt(
    prompt_key: str,
    version: int,
    request: Request = None
) -> Dict[str, Any]:
    """
    POST /settings/ai-prompts/{prompt_key}/rollback/{version}
    Rollback to a specific version.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        existing = ai_prompts_collection.find_one({"prompt_key": prompt_key})
        
        if not existing:
            raise HTTPException(status_code=404, detail=f"Prompt '{prompt_key}' not found")
        
        # Find the target version
        versions = existing.get("versions", [])
        target_version = None
        for v in versions:
            if v.get("version") == version:
                target_version = v
                break
        
        if not target_version:
            raise HTTPException(status_code=404, detail=f"Version {version} not found")
        
        # Create new version as rollback
        new_version = existing.get("current_version", 1) + 1
        
        rollback_snapshot = {
            "version": new_version,
            "system_prompt": target_version["system_prompt"],
            "user_prompt_template": target_version["user_prompt_template"],
            "created_at": datetime.utcnow(),
            "created_by": f"rollback_from_v{version}"
        }
        
        # Update with rolled back content
        ai_prompts_collection.update_one(
            {"prompt_key": prompt_key},
            {
                "$set": {
                    "system_prompt": target_version["system_prompt"],
                    "user_prompt_template": target_version["user_prompt_template"],
                    "updated_at": datetime.utcnow(),
                    "current_version": new_version
                },
                "$push": {"versions": rollback_snapshot}
            }
        )
        
        return {
            "success": True,
            "message": f"Rolled back to version {version} (now version {new_version})",
            "new_version": new_version
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rolling back AI prompt: {str(e)}")


@router.post("/ai-prompts/{prompt_key}/test")
async def test_ai_prompt(
    prompt_key: str,
    data: Dict[str, Any] = Body(...),
    request: Request = None
) -> Dict[str, Any]:
    """
    POST /settings/ai-prompts/{prompt_key}/test
    Test prompt with sample data - returns AI output without saving.
    
    Body:
    {
        "system_prompt": "...",  # Optional - use prompt_key default if not provided
        "user_prompt_template": "...",  # Optional
        "sample_lead": {...}  # Optional - uses random lead from DB if not provided
    }
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Get prompt template
        prompt_doc = ai_prompts_collection.find_one({"prompt_key": prompt_key})
        
        system_prompt = data.get("system_prompt") or (prompt_doc.get("system_prompt") if prompt_doc else None)
        user_prompt_template = data.get("user_prompt_template") or (prompt_doc.get("user_prompt_template") if prompt_doc else None)
        
        if not system_prompt or not user_prompt_template:
            raise HTTPException(status_code=400, detail="Missing prompt templates")
        
        # Get sample lead - use provided or fetch random from DB
        sample_lead = data.get("sample_lead")
        
        if not sample_lead:
            # Fetch random lead from leads_raw
            email_db = mongo_client['email_automation']
            leads_raw = email_db['leads_raw']
            random_leads = list(leads_raw.aggregate([{"$sample": {"size": 1}}]))
            if random_leads:
                sample_lead = random_leads[0]
                sample_lead.pop("_id", None)
            else:
                # Use sample data
                sample_lead = {
                    "name": "John Smith",
                    "title": "VP of Sales",
                    "linkedin_url": "https://linkedin.com/in/johnsmith",
                    "company_name": "Acme Corp",
                    "snippet": "Enterprise sales leader with 15 years experience in B2B SaaS",
                    "location": "San Francisco, CA",
                    "email": ""
                }
        
        # Format user prompt with sample data
        user_prompt = user_prompt_template.format(
            name=sample_lead.get("name", "Unknown"),
            title=sample_lead.get("title", ""),
            linkedin_url=sample_lead.get("linkedin_url", ""),
            snippet=sample_lead.get("snippet", "-"),
            location=sample_lead.get("location", "-"),
            company_name=sample_lead.get("company_name", "-"),
            email=sample_lead.get("email", "-")
        )
        
        # Call OpenAI API for test
        try:
            from leads.openai_wrapper import chat_completion
            
            result = chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                source="prompt_test",
                max_output_tokens=data.get("max_output_tokens", 300)
            )
            
            return {
                "success": True,
                "sample_lead": sample_lead,
                "formatted_user_prompt": user_prompt,
                "ai_response": result.get("content", ""),
                "tokens_used": result.get("tokens_used", 0),
                "model": result.get("model", "gpt-4o-mini")
            }
            
        except Exception as api_error:
            return {
                "success": False,
                "sample_lead": sample_lead,
                "formatted_user_prompt": user_prompt,
                "error": str(api_error)
            }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing AI prompt: {str(e)}")


# ============================================
# API Prompt Documentation
# ============================================

@router.get("/ai-prompts-documentation")
async def get_prompts_documentation(request: Request = None) -> Dict[str, Any]:
    """
    GET /settings/ai-prompts-documentation
    Get comprehensive documentation of all prompts being used across the system.
    Shows which modules use which prompts and how they're integrated.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Get all prompts
        prompts = list(ai_prompts_collection.find({}))
        
        # Build documentation
        documentation = {
            "title": "Campaign Platform - AI Prompt Integration Documentation",
            "generated_at": datetime.utcnow().isoformat(),
            "total_prompts": len(prompts),
            "api_engines": {
                "gemini": {
                    "provider": "Google Gemini",
                    "tier": "Free (7 accounts, 15 RPM each, 1000 requests/day per key)",
                    "models": ["gemini-2.0-flash", "gemini-2.0-flash-exp"],
                    "cost": "$0/month",
                    "use_case": "Email classification, lead enrichment, contact extraction, email summarization",
                    "prompts": []
                },
                "openai": {
                    "provider": "OpenAI",
                    "tier": "Paid - GPT-4o-mini (~$0.00015 per input token, ~$0.0006 per output token)",
                    "models": ["gpt-4o-mini", "gpt-4o"],
                    "cost": "$10-20/month (primarily for web search)",
                    "use_case": "Lead classification (legacy), web search queries",
                    "prompts": []
                },
                "google_cse": {
                    "provider": "Google Custom Search",
                    "tier": "Free (100 queries/day)",
                    "models": ["Custom Search API v1"],
                    "cost": "$0/month (free tier)",
                    "use_case": "LinkedIn profile discovery, AI Database searches",
                    "prompts": []
                }
            },
            "prompt_details": [],
            "integration_points": {
                "email_processor": {
                    "module": "backend/leads/email_processor.py",
                    "functions": [
                        "segment_email()",
                        "extract_contact_info()",
                        "summarize_email()"
                    ],
                    "prompts_used": ["gemini_classify_lead", "gemini_extract_contacts", "gemini_summarize_email"]
                },
                "gemini_enrichment": {
                    "module": "backend/leads/gemini_enrichment.py",
                    "functions": [
                        "classify_lead()",
                        "enrich_lead()",
                        "extract_contact_info()",
                        "summarize_email()",
                        "segment_email()",
                        "batch_categorize()"
                    ],
                    "prompts_used": [
                        "gemini_classify_lead",
                        "gemini_enrich_lead",
                        "gemini_extract_contacts",
                        "gemini_summarize_email",
                        "gemini_segment_email"
                    ]
                },
                "ai_classifier": {
                    "module": "backend/email_sync/historical_classifier.py",
                    "functions": ["classify_email()"],
                    "prompts_used": ["lead_classification"]
                },
                "openai_web_search": {
                    "module": "backend/leads/router.py - run_web_search_job()",
                    "functions": ["perform_openai_web_search()"],
                    "prompts_used": ["openai_web_search"]
                }
            },
            "workflow_examples": {
                "email_classification_workflow": {
                    "step_1": {
                        "name": "Quick Email Segmentation",
                        "prompt": "gemini_segment_email",
                        "cost": "$0 (FREE Gemini)",
                        "latency": "~2 seconds"
                    },
                    "step_2": {
                        "name": "Contact Extraction",
                        "prompt": "gemini_extract_contacts",
                        "cost": "$0 (FREE Gemini)",
                        "latency": "~2 seconds"
                    },
                    "step_3": {
                        "name": "Email Summarization",
                        "prompt": "gemini_summarize_email",
                        "cost": "$0 (FREE Gemini)",
                        "latency": "~2 seconds"
                    },
                    "step_4": {
                        "name": "Full Classification (if high priority)",
                        "prompt": "gemini_classify_lead",
                        "cost": "$0 (FREE Gemini)",
                        "latency": "~2 seconds"
                    },
                    "total_cost_per_email": "$0",
                    "total_latency": "~8 seconds"
                },
                "lead_enrichment_workflow": {
                    "step_1": {
                        "name": "Classify Lead",
                        "prompt": "gemini_classify_lead",
                        "cost": "$0 (FREE Gemini)"
                    },
                    "step_2": {
                        "name": "Enrich with Inferred Details",
                        "prompt": "gemini_enrich_lead",
                        "cost": "$0 (FREE Gemini)"
                    },
                    "step_3": {
                        "name": "Cache Company Details (90-day TTL)",
                        "prompt": "None - uses company_cache.py",
                        "cost": "$0"
                    },
                    "total_cost_per_lead": "$0 (if cached) or $0 (if not cached, uses Gemini)"
                },
                "web_search_workflow": {
                    "step_1": {
                        "name": "Generate Search Queries",
                        "prompt": "openai_web_search",
                        "cost": "~$0.001-0.003 (OpenAI)",
                        "note": "Uses OpenAI web_search_preview tool for real-time web results"
                    },
                    "total_cost_per_search": "~$0.01-0.02"
                }
            }
        }
        
        # Populate prompt details
        for prompt in prompts:
            # Determine which engine this prompt belongs to
            prompt_key = prompt.get("prompt_key", "")
            model = prompt.get("model", "")
            
            if "gemini" in prompt_key.lower() or "gemini" in model.lower():
                engine = "gemini"
            elif "openai" in prompt_key.lower() or "gpt" in model.lower():
                engine = "openai"
            elif "google" in prompt_key.lower() or "cse" in prompt_key.lower():
                engine = "google_cse"
            else:
                engine = "other"
            
            # Add to engine's prompts list
            if engine in documentation["api_engines"]:
                documentation["api_engines"][engine]["prompts"].append({
                    "key": prompt_key,
                    "name": prompt.get("name", ""),
                    "model": model,
                    "is_active": prompt.get("is_active", True)
                })
            
            # Add full details
            documentation["prompt_details"].append({
                "prompt_key": prompt_key,
                "name": prompt.get("name", ""),
                "description": prompt.get("description", ""),
                "model": model,
                "temperature": prompt.get("temperature", 0.7),
                "max_output_tokens": prompt.get("max_output_tokens", 500),
                "is_active": prompt.get("is_active", True),
                "system_prompt": prompt.get("system_prompt", ""),
                "user_prompt_template": prompt.get("user_prompt_template", ""),
                "current_version": prompt.get("current_version", 1),
                "created_at": prompt.get("created_at").isoformat() if prompt.get("created_at") else None,
                "updated_at": prompt.get("updated_at").isoformat() if prompt.get("updated_at") else None
            })
        
        # Add cost summary
        documentation["cost_summary"] = {
            "monthly_total": "$117/month (93% reduction from $1,650)",
            "breakdown": {
                "gemini_free": "$0/month (7 accounts × 15 RPM)",
                "openai_search": "$90-120/month (only for web search)",
                "hunter_io_optional": "$99/month (optional - email pattern discovery)"
            },
            "cost_per_lead": "$0.0039/lead (down from $0.055/lead)",
            "savings_percentage": "93%"
        }
        
        return documentation
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching prompt documentation: {str(e)}")


@router.get("/ai-prompts-usage")
async def get_prompts_usage_stats(request: Request = None, days: int = 7) -> Dict[str, Any]:
    """
    GET /settings/ai-prompts-usage?days=7
    Get statistics on which prompts are being used most frequently.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        from datetime import timedelta
        
        # Get Gemini usage stats
        email_db = mongo_client['email_automation']
        gemini_requests = email_db.get_collection('gemini_requests')
        
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get usage by task type
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": "$task_type",
                "requests": {"$sum": 1},
                "tokens_used": {"$sum": "$tokens_used"},
                "successes": {"$sum": {"$cond": ["$success", 1, 0]}},
                "failures": {"$sum": {"$cond": ["$success", 0, 1]}}
            }}
        ]
        
        gemini_stats = list(gemini_requests.aggregate(pipeline))
        
        # Get OpenAI usage stats
        openai_logs = email_db.get_collection('openai_usage_logs')
        
        openai_pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": {"model": "$model", "source": "$source"},
                "requests": {"$sum": 1},
                "input_tokens": {"$sum": "$input_tokens"},
                "output_tokens": {"$sum": "$output_tokens"},
                "cost": {"$sum": "$cost_usd"}
            }}
        ]
        
        openai_stats = list(openai_logs.aggregate(openai_pipeline))
        
        return {
            "success": True,
            "period_days": days,
            "gemini_usage": {
                "by_task_type": [
                    {
                        "task_type": s["_id"],
                        "requests": s["requests"],
                        "tokens_used": s["tokens_used"],
                        "success_rate": round((s["successes"] / s["requests"]) * 100, 2) if s["requests"] > 0 else 0,
                        "failures": s["failures"]
                    }
                    for s in sorted(gemini_stats, key=lambda x: x["requests"], reverse=True)
                ],
                "total_requests": sum(s["requests"] for s in gemini_stats),
                "total_tokens": sum(s["tokens_used"] for s in gemini_stats),
                "cost": "$0 (FREE tier)"
            },
            "openai_usage": {
                "by_model_source": [
                    {
                        "model": s["_id"]["model"],
                        "source": s["_id"]["source"],
                        "requests": s["requests"],
                        "input_tokens": s["input_tokens"],
                        "output_tokens": s["output_tokens"],
                        "cost_usd": round(s["cost"], 4)
                    }
                    for s in sorted(openai_stats, key=lambda x: x["cost"], reverse=True)
                ],
                "total_requests": sum(s["requests"] for s in openai_stats),
                "total_cost_usd": round(sum(s["cost"] for s in openai_stats), 4)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching prompt usage stats: {str(e)}")


# ============================================
# CPX Diagnostic Endpoints
# ============================================

@router.get("/cpx-filters")
async def get_cpx_filter_settings(request: Request = None) -> Dict[str, Any]:
    """
    Get CPX survey filter settings for diagnostic purposes.
    
    Shows current filter values (max_loi, min_cpi, min_ir) that affect
    which CPX surveys are available to users. Over-restrictive filters
    may cause high screenout rates in lower-CPI markets like India.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Get filter settings from survey_filters document
        filters = app_settings_collection.find_one({"_id": "survey_filters"})
        
        # Default values
        defaults = {
            "max_loi": 20,
            "min_cpi": 1.0,
            "min_ir": 0,
            "deletion_period_days": 7,
            "auto_refresh_enabled": True,
            "refresh_interval_seconds": 60
        }
        
        if filters:
            current_settings = {
                "max_loi": filters.get("max_loi", defaults["max_loi"]),
                "min_cpi": filters.get("min_cpi", defaults["min_cpi"]),
                "min_ir": filters.get("min_ir", defaults["min_ir"]),
                "deletion_period_days": filters.get("deletion_period_days", defaults["deletion_period_days"]),
                "auto_refresh_enabled": filters.get("auto_refresh_enabled", defaults["auto_refresh_enabled"]),
                "refresh_interval_seconds": filters.get("refresh_interval_seconds", defaults["refresh_interval_seconds"]),
                "last_updated": filters.get("last_updated", "never").isoformat() if hasattr(filters.get("last_updated", "never"), 'isoformat') else str(filters.get("last_updated", "never"))
            }
        else:
            current_settings = defaults.copy()
            current_settings["last_updated"] = "never (using defaults)"
        
        # Market analysis
        analysis = {
            "india_market_analysis": {
                "typical_cpi_range": "$0.10 - $0.50",
                "current_min_cpi": current_settings["min_cpi"],
                "impact": "HIGH - Most India surveys filtered out" if current_settings["min_cpi"] > 0.3 else "LOW - India surveys should pass filter",
                "recommendation": "Set min_cpi to 0.10 or lower for India traffic" if current_settings["min_cpi"] > 0.3 else "Filter settings OK for India"
            },
            "us_market_analysis": {
                "typical_cpi_range": "$0.50 - $2.00",
                "current_min_cpi": current_settings["min_cpi"],
                "impact": "LOW" if current_settings["min_cpi"] <= 1.0 else "MEDIUM - Some US surveys filtered out",
                "recommendation": "Current settings acceptable for US market"
            },
            "loi_analysis": {
                "current_max_loi": current_settings["max_loi"],
                "impact": "LOW" if current_settings["max_loi"] >= 15 else "HIGH - Many surveys filtered out",
                "recommendation": "Max LOI of 15-20 minutes is reasonable" if current_settings["max_loi"] >= 15 else "Consider increasing max_loi to 15-20 minutes"
            }
        }
        
        return {
            "success": True,
            "current_settings": current_settings,
            "defaults": defaults,
            "market_analysis": analysis,
            "diagnosis": (
                "POTENTIAL ISSUE: min_cpi filter is too restrictive for India market. "
                "India surveys typically pay $0.10-$0.50. Consider lowering min_cpi to 0.10."
            ) if current_settings["min_cpi"] > 0.3 else (
                "Filter settings appear reasonable for multi-region traffic."
            )
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching CPX filter settings: {str(e)}")


@router.post("/cpx-filters")
async def update_cpx_filter_settings(
    request: Request,
    data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """
    Update CPX survey filter settings.
    
    Adjusts max_loi, min_cpi, min_ir values that control which
    CPX surveys are available to users.
    """
    try:
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        # Validate inputs
        allowed_fields = ["max_loi", "min_cpi", "min_ir", "deletion_period_days", "auto_refresh_enabled", "refresh_interval_seconds"]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update. Allowed: " + ", ".join(allowed_fields))
        
        # Add timestamp
        update_data["last_updated"] = datetime.utcnow()
        
        # Update in MongoDB
        result = app_settings_collection.update_one(
            {"_id": "survey_filters"},
            {"$set": update_data},
            upsert=True
        )
        
        # Get updated settings
        updated = app_settings_collection.find_one({"_id": "survey_filters"})
        
        return {
            "success": True,
            "message": "CPX filter settings updated",
            "updated_fields": list(update_data.keys()),
            "current_settings": {
                "max_loi": updated.get("max_loi"),
                "min_cpi": updated.get("min_cpi"),
                "min_ir": updated.get("min_ir"),
                "deletion_period_days": updated.get("deletion_period_days"),
                "auto_refresh_enabled": updated.get("auto_refresh_enabled"),
                "refresh_interval_seconds": updated.get("refresh_interval_seconds"),
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating CPX filter settings: {str(e)}")
