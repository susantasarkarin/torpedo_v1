"""
Gemini API Key Rotation System
Manages 7 free-tier Gemini accounts with quota tracking and automatic rotation
Each account: 15 RPM, 1000 requests/day
Total capacity: 105 RPM, 7000 requests/day
"""

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pymongo import MongoClient
import google.generativeai as genai
from bson import ObjectId

class GeminiRotator:
    """Manages multiple Gemini API keys with automatic rotation and quota tracking"""
    
    MAX_RPM = 500          # Per-key RPM cap (paid tier; free tier was 15)
    MAX_DAILY_REQUESTS = 50000  # Per-key daily cap (paid tier; free tier was 1000/1500)
    TOTAL_KEYS = 10
    
    def __init__(self, mongo_uri: str = None, database_name: str = "campaign_platform"):
        """Initialize the rotator with MongoDB connection"""
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.settings_db = self.client["torpedo_settings"]
        
        # Collections
        self.quota_collection = self.db["gemini_quota"]
        self.requests_collection = self.db["gemini_requests"]

        # Thread-safety for concurrent runners
        self._key_lock = threading.Lock()

        # Load API keys from database
        self.api_keys = self._load_api_keys()
        
        # Initialize quota tracking
        self._initialize_quota_tracking()
    
    def _load_api_keys(self) -> Dict[int, str]:
        """Load Gemini API keys from torpedo_settings.app_settings"""
        try:
            settings = self.settings_db["app_settings"].find_one()
            if not settings:
                raise ValueError("No app_settings document found in torpedo_settings database")
            
            keys = {}
            for i in range(1, self.TOTAL_KEYS + 1):
                key_name = f"gemini_api_key_{i}"
                if key_name in settings:
                    raw_value = settings.get(key_name)
                    # Treat empty/null values as not configured so pipelines fail fast with a clear key list.
                    if isinstance(raw_value, str):
                        raw_value = raw_value.strip()
                    if raw_value:
                        keys[i] = raw_value
                else:
                    print(f"Warning: {key_name} not found in database")
            
            if not keys:
                raise ValueError("No Gemini API keys found in database")
            
            print(f"âœ“ Loaded {len(keys)} Gemini API keys from database")
            return keys
            
        except Exception as e:
            print(f"Error loading API keys from database: {e}")
            print("Falling back to environment variables...")
            
            # Fallback to environment variables
            keys = {}
            for i in range(1, self.TOTAL_KEYS + 1):
                key = os.getenv(f"GEMINI_API_KEY_{i}")
                if key:
                    keys[i] = key
            
            if not keys:
                raise ValueError("No Gemini API keys found in database or environment variables")
            
            return keys
    
    def _initialize_quota_tracking(self):
        """Initialize quota tracking documents for all keys"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        for key_index in self.api_keys.keys():
            existing = self.quota_collection.find_one({
                "key_index": key_index,
                "date": today
            })
            
            if not existing:
                self.quota_collection.insert_one({
                    "key_index": key_index,
                    "date": today,
                    "requests_count": 0,
                    "tokens_used": 0,
                    "last_request_time": None,
                    "minute_requests": [],  # Track requests in current minute
                    "created_at": datetime.now()
                })
        
        # Create indexes
        self.quota_collection.create_index([("key_index", 1), ("date", 1)], unique=True)
        self.quota_collection.create_index([("date", 1)])
        self.requests_collection.create_index([("key_index", 1), ("timestamp", -1)])
        self.requests_collection.create_index([("task_type", 1)])
    
    def get_available_key(self) -> Tuple[int, str]:
        """
        Get an available API key that hasn't exceeded quotas.
        Thread-safe: uses a lock so concurrent workers don't double-assign the same key.
        Returns: (key_index, api_key)
        """
        with self._key_lock:
            return self._get_available_key_locked()

    def _get_available_key_locked(self) -> Tuple[int, str]:
        """Inner implementation — must be called with _key_lock held."""
        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now()
        one_minute_ago = current_time - timedelta(minutes=1)
        
        # Try each key in order
        for key_index, api_key in self.api_keys.items():
            quota = self.quota_collection.find_one({
                "key_index": key_index,
                "date": today
            })
            
            if not quota:
                # Initialize if missing
                self._initialize_quota_tracking()
                quota = self.quota_collection.find_one({
                    "key_index": key_index,
                    "date": today
                })
            
            # Check daily quota
            if quota["requests_count"] >= self.MAX_DAILY_REQUESTS:
                continue
            
            # Check RPM quota
            recent_requests = [
                req for req in quota.get("minute_requests", [])
                if datetime.fromisoformat(req) > one_minute_ago
            ]
            
            if len(recent_requests) >= self.MAX_RPM:
                continue
            
            # This key is available
            return key_index, api_key
        
        # No keys available
        raise Exception(
            f"All {self.TOTAL_KEYS} Gemini API keys have exceeded their quotas. "
            f"Daily limit: {self.MAX_DAILY_REQUESTS} requests/key, RPM limit: {self.MAX_RPM}/key"
        )
    
    def log_request(self, key_index: int, tokens_used: int, task_type: str, 
                    success: bool = True, error: str = None, metadata: dict = None):
        """
        Log an API request to track quota usage
        
        Args:
            key_index: Which API key was used (1-7)
            tokens_used: Number of tokens consumed
            task_type: Type of task (classify, enrich, extract, summarize, segment, batch)
            success: Whether the request succeeded
            error: Error message if failed
            metadata: Additional metadata about the request
        """
        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now()
        
        # Update quota tracking
        self.quota_collection.update_one(
            {"key_index": key_index, "date": today},
            {
                "$inc": {
                    "requests_count": 1,
                    "tokens_used": tokens_used
                },
                "$set": {
                    "last_request_time": current_time.isoformat()
                },
                "$push": {
                    "minute_requests": {
                        "$each": [current_time.isoformat()],
                        "$slice": -self.MAX_RPM  # Keep only last MAX_RPM requests
                    }
                }
            }
        )
        
        # Log detailed request
        log_entry = {
            "key_index": key_index,
            "timestamp": current_time,
            "date": today,
            "task_type": task_type,
            "tokens_used": tokens_used,
            "success": success,
            "error": error,
            "metadata": metadata or {}
        }
        
        self.requests_collection.insert_one(log_entry)
    
    def check_quota(self, key_index: int = None) -> Dict:
        """
        Check quota usage for a specific key or all keys
        
        Args:
            key_index: Specific key to check (1-7), or None for all keys
            
        Returns:
            Dictionary with quota information
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        if key_index is not None:
            quota = self.quota_collection.find_one({
                "key_index": key_index,
                "date": today
            })
            
            if not quota:
                return {
                    "key_index": key_index,
                    "requests_today": 0,
                    "tokens_used": 0,
                    "remaining_requests": self.MAX_DAILY_REQUESTS,
                    "percentage_used": 0
                }
            
            remaining = self.MAX_DAILY_REQUESTS - quota["requests_count"]
            percentage = (quota["requests_count"] / self.MAX_DAILY_REQUESTS) * 100
            
            return {
                "key_index": key_index,
                "requests_today": quota["requests_count"],
                "tokens_used": quota["tokens_used"],
                "remaining_requests": remaining,
                "percentage_used": round(percentage, 2),
                "last_request": quota.get("last_request_time")
            }
        else:
            # Get status for all keys
            all_quotas = []
            total_requests = 0
            total_tokens = 0
            
            for ki in self.api_keys.keys():
                quota_info = self.check_quota(ki)
                all_quotas.append(quota_info)
                total_requests += quota_info["requests_today"]
                total_tokens += quota_info["tokens_used"]
            
            max_daily_total = self.MAX_DAILY_REQUESTS * self.TOTAL_KEYS
            remaining_total = max_daily_total - total_requests
            
            return {
                "total_keys": self.TOTAL_KEYS,
                "total_requests_today": total_requests,
                "total_tokens_used": total_tokens,
                "total_remaining_requests": remaining_total,
                "max_daily_capacity": max_daily_total,
                "percentage_used": round((total_requests / max_daily_total) * 100, 2),
                "keys": all_quotas
            }
    
    def get_usage_stats(self, days: int = 7) -> Dict:
        """
        Get usage statistics for the past N days
        
        Args:
            days: Number of days to look back
            
        Returns:
            Dictionary with usage statistics
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        pipeline = [
            {
                "$match": {
                    "timestamp": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": {
                        "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                        "task_type": "$task_type"
                    },
                    "count": {"$sum": 1},
                    "total_tokens": {"$sum": "$tokens_used"},
                    "success_count": {
                        "$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}
                    }
                }
            },
            {
                "$sort": {"_id.date": -1}
            }
        ]
        
        results = list(self.requests_collection.aggregate(pipeline))
        
        # Organize by date
        stats_by_date = {}
        for result in results:
            date = result["_id"]["date"]
            task_type = result["_id"]["task_type"]
            
            if date not in stats_by_date:
                stats_by_date[date] = {
                    "total_requests": 0,
                    "total_tokens": 0,
                    "success_rate": 0,
                    "by_task": {}
                }
            
            stats_by_date[date]["total_requests"] += result["count"]
            stats_by_date[date]["total_tokens"] += result["total_tokens"]
            stats_by_date[date]["by_task"][task_type] = {
                "count": result["count"],
                "tokens": result["total_tokens"],
                "success_count": result["success_count"]
            }
        
        # Calculate success rates
        for date, stats in stats_by_date.items():
            total_success = sum(
                task["success_count"] 
                for task in stats["by_task"].values()
            )
            stats["success_rate"] = round(
                (total_success / stats["total_requests"]) * 100, 2
            ) if stats["total_requests"] > 0 else 0
        
        return {
            "period": f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            "days": days,
            "stats_by_date": stats_by_date
        }
    
    def reset_daily_quotas(self):
        """Reset quotas for the new day (typically run by cron at midnight)"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        for key_index in self.api_keys.keys():
            self.quota_collection.update_one(
                {"key_index": key_index, "date": today},
                {
                    "$set": {
                        "requests_count": 0,
                        "tokens_used": 0,
                        "minute_requests": [],
                        "last_request_time": None,
                        "reset_at": datetime.now()
                    }
                },
                upsert=True
            )
        
        print(f"âœ“ Reset daily quotas for {self.TOTAL_KEYS} keys on {today}")
    
    def configure_genai(self, key_index: int):
        """Configure the google.generativeai library with the specified key"""
        if key_index not in self.api_keys:
            raise ValueError(f"Invalid key_index: {key_index}. Must be between 1 and {self.TOTAL_KEYS}")
        
        genai.configure(api_key=self.api_keys[key_index])
        return True
    
    def health_check(self) -> Dict:
        """Check health of all API keys"""
        today = datetime.now().strftime("%Y-%m-%d")
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "date": today,
            "keys": []
        }
        
        for key_index, api_key in self.api_keys.items():
            quota = self.check_quota(key_index)
            
            status = {
                "key_index": key_index,
                "configured": bool(api_key),
                "requests_today": quota["requests_today"],
                "remaining": quota["remaining_requests"],
                "percentage_used": quota["percentage_used"],
                "status": "healthy" if quota["remaining_requests"] > 100 else "warning" if quota["remaining_requests"] > 0 else "exhausted"
            }
            
            health_status["keys"].append(status)
        
        # Overall system status
        total_remaining = sum(k["remaining"] for k in health_status["keys"])
        health_status["system_status"] = "healthy" if total_remaining > 1000 else "degraded" if total_remaining > 100 else "critical"
        health_status["total_remaining_capacity"] = total_remaining
        
        return health_status


# ============================================================
# PIPELINE SYSTEM
# ============================================================
# 4 isolated key pools, each with 3 dedicated Gemini accounts:
#
#   outreach  â†’ keys 1,2,3   (AI email drafting — real-time)
#   sfw_bim   â†’ keys 4,5,6   (SFW + BIM enrichment + mail)
#   cogentix  â†’ keys 7,8,9   (Cogentix enrichment + mail)
#   mail      â†’ keys 10,11,12 (general mail capacity)
#
# Within each pipeline the rotator cycles key1â†’key2â†’key3â†’key1
# using a sliding 60-second RPM window so that by the time all
# 3 keys are saturated the earliest key's window has reset.
# ============================================================

DEFAULT_PIPELINE_KEY_MAP: Dict[str, List[int]] = {
    "outreach": [1, 2, 3],
    "sfw_bim":  [4, 5, 6],
    "cogentix": [7, 8, 9],
    "mail":     [10, 11, 12],
}

# ICP segment â†’ pipeline routing
SEGMENT_PIPELINE_MAP: Dict[str, str] = {
    "survey_fieldwork": "sfw_bim",
    "bimwave":          "sfw_bim",
    "dual_fit":         "sfw_bim",
    "cogentix":         "cogentix",
    "nurture":          "sfw_bim",  # fallback
}


class GeminiPipelineRotator:
    """
    RPM-aware + daily-cap-aware rotator for a fixed pool of Gemini keys.

    Strategy:
      - Cycle key_1 â†’ key_2 â†’ key_3 â†’ key_1 using a 60-second sliding RPM
        window (15 RPM per key, free tier).
      - Daily cap (1,500 req/day per key, free tier) is read from the
        gemini_quota MongoDB collection and cached for DAILY_CACHE_TTL seconds.
        Keys confirmed daily-exhausted are skipped proactively — no wasted 429.
      - Account names (gemini_account_N) are loaded once from app_settings so
        every log line and health-check shows which Google account owns the key.

    One instance per pipeline; obtain via get_pipeline_rotator().
    """

    RPM_LIMIT       = 15    # free-tier requests per minute per key
    DAILY_LIMIT     = 1500  # free-tier requests per day per key
    DAILY_CACHE_TTL = 120   # seconds between MongoDB daily-count refreshes

    def __init__(self, pipeline_name: str, key_indices: List[int],
                 base_rotator: "GeminiRotator"):
        self.pipeline_name = pipeline_name
        # Only include keys that are actually loaded in the base rotator
        self.key_indices = [i for i in key_indices if i in base_rotator.api_keys]
        self._base = base_rotator
        self._lock = threading.Lock()

        # Sliding-window timestamps per key (in-memory only, reset on restart)
        self._rpm_window: Dict[int, List[float]] = {
            idx: [] for idx in self.key_indices
        }

        # Daily cap cache — refreshed from MongoDB every DAILY_CACHE_TTL seconds
        self._daily_exhausted: set = set()   # key indices that hit 1,500/day
        self._daily_cache_time: float = 0.0  # epoch of last DB refresh

        # Account names — loaded once at startup
        self._account_names: Dict[int, str] = self._load_account_names()

        if not self.key_indices:
            raise ValueError(
                f"Pipeline '{pipeline_name}': none of the requested keys "
                f"{key_indices} are configured in the DB."
            )

    # ------------------------------------------------------------------
    # Account name helpers
    # ------------------------------------------------------------------

    def _load_account_names(self) -> Dict[int, str]:
        """Load gemini_account_N labels from torpedo_settings.app_settings."""
        try:
            settings = self._base.settings_db["app_settings"].find_one() or {}
            return {
                idx: settings.get(f"gemini_account_{idx}", f"key_{idx}")
                for idx in range(1, self._base.TOTAL_KEYS + 1)
            }
        except Exception:
            return {idx: f"key_{idx}" for idx in range(1, self._base.TOTAL_KEYS + 1)}

    def account_name(self, key_index: int) -> str:
        return self._account_names.get(key_index, f"key_{key_index}")

    # ------------------------------------------------------------------
    # Daily cap cache
    # ------------------------------------------------------------------

    def _refresh_daily_cache(self):
        """
        Query MongoDB for today's request counts and mark exhausted keys.
        Called WITHOUT holding _lock to avoid blocking other threads.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            docs = list(self._base.quota_collection.find(
                {"key_index": {"$in": self.key_indices}, "date": today},
                {"key_index": 1, "requests_count": 1}
            ))
            exhausted = {
                d["key_index"] for d in docs
                if d.get("requests_count", 0) >= self.DAILY_LIMIT
            }
        except Exception:
            exhausted = set()

        with self._lock:
            self._daily_exhausted = exhausted
            self._daily_cache_time = time.time()

    def _ensure_daily_cache(self):
        """Trigger a cache refresh if the TTL has expired. Called WITHOUT lock."""
        if time.time() - self._daily_cache_time > self.DAILY_CACHE_TTL:
            self._refresh_daily_cache()

    # ------------------------------------------------------------------
    # Core key selection
    # ------------------------------------------------------------------

    def get_available_key(self) -> Tuple[int, str]:
        """
        Block until a key with both RPM headroom AND daily quota remains.
        Returns (key_index, api_key).
        """
        # Refresh daily-cap cache outside the lock (DB I/O should not hold the lock)
        self._ensure_daily_cache()

        while True:
            with self._lock:
                now    = time.time()
                cutoff = now - 60.0

                # Only consider keys that haven't hit their daily cap
                candidates = [
                    idx for idx in self.key_indices
                    if idx not in self._daily_exhausted
                ]

                if not candidates:
                    # All keys daily-exhausted — surface a clear error
                    raise Exception(
                        f"Pipeline '{self.pipeline_name}': all keys have hit the "
                        f"{self.DAILY_LIMIT} req/day free-tier limit. "
                        "Quota resets at midnight UTC."
                    )

                sleep_until: Optional[float] = None

                for key_idx in candidates:
                    # Prune timestamps outside the 60-second window
                    window = self._rpm_window[key_idx] = [
                        t for t in self._rpm_window[key_idx] if t > cutoff
                    ]
                    if len(window) < self.RPM_LIMIT:
                        window.append(now)
                        return key_idx, self._base.api_keys[key_idx]
                    # Key RPM-saturated — record when its window opens next
                    earliest = window[0] + 60.0
                    if sleep_until is None or earliest < sleep_until:
                        sleep_until = earliest

                # All candidate keys RPM-saturated — release lock and wait
            wait_s = max(0.3, (sleep_until - time.time())) if sleep_until else 5.0
            time.sleep(wait_s)

    # ------------------------------------------------------------------
    # Logging + health
    # ------------------------------------------------------------------

    def log_request(self, key_index: int, tokens_used: int, task_type: str,
                    success: bool = True, error: str = None,
                    metadata: dict = None):
        """Delegate to base rotator so the gemini_quota audit trail stays intact."""
        self._base.log_request(
            key_index, tokens_used,
            f"{self.pipeline_name}:{task_type}",
            success=success, error=error,
            metadata={**(metadata or {}), "account": self.account_name(key_index)},
        )

    def health_check(self) -> Dict:
        """Return RPM usage + daily cap status for every key in the pool."""
        self._ensure_daily_cache()
        today = datetime.now().strftime("%Y-%m-%d")
        now   = time.time()
        cutoff = now - 60.0

        try:
            daily_counts = {
                d["key_index"]: d.get("requests_count", 0)
                for d in self._base.quota_collection.find(
                    {"key_index": {"$in": self.key_indices}, "date": today},
                    {"key_index": 1, "requests_count": 1}
                )
            }
        except Exception:
            daily_counts = {}

        keys_status = []
        with self._lock:
            for key_idx in self.key_indices:
                recent       = [t for t in self._rpm_window[key_idx] if t > cutoff]
                daily_used   = daily_counts.get(key_idx, 0)
                daily_remain = max(0, self.DAILY_LIMIT - daily_used)
                keys_status.append({
                    "key_index":      key_idx,
                    "account":        self.account_name(key_idx),
                    "rpm_used":       len(recent),
                    "rpm_headroom":   max(0, self.RPM_LIMIT - len(recent)),
                    "daily_used":     daily_used,
                    "daily_remaining": daily_remain,
                    "daily_exhausted": key_idx in self._daily_exhausted,
                })

        return {
            "pipeline": self.pipeline_name,
            "keys":     keys_status,
            "active_keys": len([k for k in keys_status if not k["daily_exhausted"]]),
        }


# Per-pipeline singleton cache
_pipeline_rotators: Dict[str, GeminiPipelineRotator] = {}
_pipeline_rotators_lock = threading.Lock()


def get_pipeline_rotator(pipeline_name: str) -> GeminiPipelineRotator:
    """
    Return the singleton GeminiPipelineRotator for the given pipeline.
    Pipeline key mapping is loaded from torpedo_settings.app_settings
    (field: gemini_pipeline_config) with DEFAULT_PIPELINE_KEY_MAP as fallback.
    """
    global _pipeline_rotators
    with _pipeline_rotators_lock:
        if pipeline_name not in _pipeline_rotators:
            base = get_rotator()
            # Allow runtime override via DB
            try:
                settings = base.settings_db["app_settings"].find_one()
                override = (settings or {}).get("gemini_pipeline_config")
                key_map: Dict[str, List[int]] = override or DEFAULT_PIPELINE_KEY_MAP
            except Exception:
                key_map = DEFAULT_PIPELINE_KEY_MAP

            key_indices = key_map.get(pipeline_name, list(range(1, 13)))
            _pipeline_rotators[pipeline_name] = GeminiPipelineRotator(
                pipeline_name, key_indices, base
            )
    return _pipeline_rotators[pipeline_name]


# ============================================================
# Singleton instance
_rotator_instance = None

def get_rotator() -> GeminiRotator:
    """Get or create the singleton GeminiRotator instance"""
    global _rotator_instance
    if _rotator_instance is None:
        _rotator_instance = GeminiRotator()
    return _rotator_instance


if __name__ == "__main__":
    # Test the rotator
    print("=== Gemini Rotator Test ===\n")
    
    try:
        rotator = GeminiRotator()
        
        # Test getting available key
        print("1. Testing get_available_key():")
        key_index, api_key = rotator.get_available_key()
        print(f"   âœ“ Got key {key_index}: {api_key[:20]}...\n")
        
        # Test logging a request
        print("2. Testing log_request():")
        rotator.log_request(
            key_index=key_index,
            tokens_used=150,
            task_type="test",
            success=True,
            metadata={"test": "data"}
        )
        print("   âœ“ Logged test request\n")
        
        # Check quota
        print("3. Testing check_quota():")
        quota = rotator.check_quota(key_index)
        print(f"   Key {key_index} quota: {quota['requests_today']}/{rotator.MAX_DAILY_REQUESTS} requests")
        print(f"   Tokens used: {quota['tokens_used']}")
        print(f"   Remaining: {quota['remaining_requests']}\n")
        
        # Check all quotas
        print("4. Testing check_quota() for all keys:")
        all_quotas = rotator.check_quota()
        print(f"   Total requests today: {all_quotas['total_requests_today']}/{all_quotas['max_daily_capacity']}")
        print(f"   Total tokens: {all_quotas['total_tokens_used']}")
        print(f"   Percentage used: {all_quotas['percentage_used']}%\n")
        
        # Health check
        print("5. Testing health_check():")
        health = rotator.health_check()
        print(f"   System status: {health['system_status']}")
        print(f"   Total remaining capacity: {health['total_remaining_capacity']}\n")
        
        # Usage stats
        print("6. Testing get_usage_stats():")
        stats = rotator.get_usage_stats(days=7)
        print(f"   Period: {stats['period']}")
        print(f"   Stats collected for {len(stats['stats_by_date'])} days\n")
        
        print("[ok] All tests passed!")
        
    except Exception as e:
        print(f"âŒ Error: {e}")
        import traceback
        traceback.print_exc()

