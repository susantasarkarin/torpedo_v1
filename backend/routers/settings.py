"""
Settings Router - Handles application settings management
"""
from fastapi import APIRouter, Body, HTTPException, Request
from typing import Dict, Any
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

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
            "google_api_key": stored.get("google_api_key", os.getenv("GOOGLE_API_KEY", "")),
            "google_cse_id": stored.get("google_cse_id", os.getenv("GOOGLE_CSE_ID", "")),
            "google_sheets_service_account": stored.get("google_sheets_service_account", os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT", "")),
        }
        
        # Mask sensitive fields for display
        masked_settings = {**settings}
        sensitive_fields = ["cpx_secure_hash_key", "openai_api_key", "google_api_key", "google_sheets_service_account"]
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
            "openai_api_key",
            "google_api_key", "google_cse_id", "google_sheets_service_account"
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
