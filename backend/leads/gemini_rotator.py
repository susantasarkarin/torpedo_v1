"""
Gemini API Key Rotation System
Manages 7 free-tier Gemini accounts with quota tracking and automatic rotation
Each account: 15 RPM, 1000 requests/day
Total capacity: 105 RPM, 7000 requests/day
"""

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pymongo import MongoClient
import google.generativeai as genai
from bson import ObjectId

class GeminiRotator:
    """Manages multiple Gemini API keys with automatic rotation and quota tracking"""
    
    MAX_RPM = 15  # Requests per minute per key
    MAX_DAILY_REQUESTS = 1000  # Daily requests per key
    TOTAL_KEYS = 10
    
    def __init__(self, mongo_uri: str = None, database_name: str = "email_automation"):
        """Initialize the rotator with MongoDB connection"""
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.settings_db = self.client["torpedo_settings"]
        
        # Collections
        self.quota_collection = self.db["gemini_quota"]
        self.requests_collection = self.db["gemini_requests"]
        
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
                    keys[i] = settings[key_name]
                else:
                    print(f"Warning: {key_name} not found in database")
            
            if not keys:
                raise ValueError("No Gemini API keys found in database")
            
            print(f"✓ Loaded {len(keys)} Gemini API keys from database")
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
        Get an available API key that hasn't exceeded quotas
        Returns: (key_index, api_key)
        """
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
        
        print(f"✓ Reset daily quotas for {self.TOTAL_KEYS} keys on {today}")
    
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
        print(f"   ✓ Got key {key_index}: {api_key[:20]}...\n")
        
        # Test logging a request
        print("2. Testing log_request():")
        rotator.log_request(
            key_index=key_index,
            tokens_used=150,
            task_type="test",
            success=True,
            metadata={"test": "data"}
        )
        print("   ✓ Logged test request\n")
        
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
        
        print("✅ All tests passed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
