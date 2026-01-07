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
            "openai_api_key": stored.get("openai_api_key", os.getenv("OPENAI_API_KEY", "")),
            "anthropic_api_key": stored.get("anthropic_api_key", os.getenv("ANTHROPIC_API_KEY", "")),
            "google_api_key": stored.get("google_api_key", os.getenv("GOOGLE_API_KEY", "")),
            "google_cse_id": stored.get("google_cse_id", os.getenv("GOOGLE_CSE_ID", "")),
            "google_sheets_service_account": stored.get("google_sheets_service_account", os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT", "")),
            # Rate limiting settings for Google CSE ($50/month budget)
            "google_cse_daily_limit": stored.get("google_cse_daily_limit", 400),
            "google_cse_hourly_limit": stored.get("google_cse_hourly_limit", 50),
            "google_cse_query_delay": stored.get("google_cse_query_delay", 3),
            "google_cse_monthly_budget": stored.get("google_cse_monthly_budget", 50.0),
            "google_cse_rate_limit_enabled": stored.get("google_cse_rate_limit_enabled", True),
        }
        
        # Mask sensitive fields for display
        masked_settings = {**settings}
        sensitive_fields = ["cpx_secure_hash_key", "openai_api_key", "anthropic_api_key", "google_api_key", "google_sheets_service_account"]
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
            "openai_api_key", "anthropic_api_key",
            "google_api_key", "google_cse_id", "google_sheets_service_account",
            # Rate limiting settings for Google CSE cost control
            "google_cse_daily_limit", "google_cse_hourly_limit", "google_cse_query_delay",
            "google_cse_monthly_budget", "google_cse_rate_limit_enabled"
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
    Get survey filter settings (Max LOI, Min CPI, Deletion Period)
    """
    try:
        # Verify session
        session_id = request.headers.get("Authorization")
        if not session_id:
            raise HTTPException(status_code=401, detail="Missing session token")
        
        stored = get_settings_by_key("survey_filters")
        
        # Default filter values
        filters = {
            "max_loi": stored.get("max_loi", 20),  # Maximum Length of Interview in minutes
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
        "max_loi": 20,
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
        
        allowed_keys = ["max_loi", "min_cpi", "deletion_period_days", "auto_refresh_enabled", "refresh_interval_seconds"]
        filtered = {k: v for k, v in filters.items() if k in allowed_keys and v is not None}
        
        # Validation
        if "max_loi" in filtered:
            filtered["max_loi"] = max(1, min(120, int(filtered["max_loi"])))
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
        
        # Test API call
        url = "https://offers.cpx-research.com/api/get-surveys.php"
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
            
            cse_queries = cse_day[0]["queries"] if cse_day else 0
            openai_requests = openai_day[0]["requests"] if openai_day else 0
            openai_cost = openai_day[0]["cost"] if openai_day else 0
            cache_hits = cache_day[0]["hits"] if cache_day else 0
            cache_misses = cache_day[0]["misses"] if cache_day else 0
            
            daily_breakdown.append({
                "date": date_str,
                "cse_queries": cse_queries,
                "cse_cost_usd": round(cse_queries * 0.005, 3),
                "openai_requests": openai_requests,
                "openai_cost_usd": round(openai_cost, 4),
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "cache_hit_rate": round(cache_hits / (cache_hits + cache_misses), 4) if (cache_hits + cache_misses) > 0 else 0,
                "total_cost_usd": round((cse_queries * 0.005) + openai_cost, 4)
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
