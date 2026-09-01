"""
OpenAI API Key Rotation System
Manages multiple OpenAI API keys with quota tracking and automatic rotation.
Pay-as-you-go: RPM / daily caps are configurable safeguards, not hard provider limits.
"""

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pymongo import MongoClient
import openai

# ---------------------------------------------------------------------------
# Pipeline key mapping — 4 isolated pools, each with 3 dedicated keys.
#
#   outreach  â†’ keys 1,2,3   (AI email drafting — real-time)
#   sfw_bim   â†’ keys 4,5,6   (SFW + BIM enrichment + mail)
#   cogentix  â†’ keys 7,8,9   (Cogentix enrichment + mail)
#   mail      â†’ keys 10,11,12 (general mail capacity)
# ---------------------------------------------------------------------------

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
    "nurture":          "sfw_bim",
}


class OpenAIRotator:
    """Manages multiple OpenAI API keys with automatic rotation and quota tracking."""

    MAX_RPM = 500               # Per-key RPM safeguard
    MAX_DAILY_REQUESTS = 50_000 # Per-key daily safeguard
    TOTAL_KEYS = 10

    def __init__(self, mongo_uri: str = None, database_name: str = "campaign_platform"):
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.settings_db = self.client["torpedo_settings"]

        self.quota_collection = self.db["openai_quota"]
        self.requests_collection = self.db["openai_requests"]

        self._key_lock = threading.Lock()
        self.api_keys = self._load_api_keys()
        self._initialize_quota_tracking()

    # ------------------------------------------------------------------
    # Key loading
    # ------------------------------------------------------------------

    def _load_api_keys(self) -> Dict[int, str]:
        """Load OpenAI API keys from torpedo_settings.app_settings."""
        try:
            settings = self.settings_db["app_settings"].find_one()
            if not settings:
                raise ValueError("No app_settings document found in torpedo_settings")

            keys = {}
            for i in range(1, self.TOTAL_KEYS + 1):
                key_name = f"openai_api_key_{i}"
                val = settings.get(key_name, "")
                if val:
                    keys[i] = val

            # Fallback: single legacy key stored as openai_api_key
            if not keys:
                legacy = settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
                if legacy:
                    keys[1] = legacy

            if not keys:
                raise ValueError("No OpenAI API keys found in database or environment")

            print(f"âœ“ Loaded {len(keys)} OpenAI API keys from database")
            return keys

        except Exception as e:
            print(f"Error loading OpenAI keys from database: {e}")
            print("Falling back to environment variables...")

            keys = {}
            for i in range(1, self.TOTAL_KEYS + 1):
                env_key = os.getenv(f"OPENAI_API_KEY_{i}")
                if env_key:
                    keys[i] = env_key
            if not keys:
                legacy = os.getenv("OPENAI_API_KEY", "")
                if legacy:
                    keys[1] = legacy
            if not keys:
                raise ValueError("No OpenAI API keys found in database or environment")
            return keys

    # ------------------------------------------------------------------
    # Quota tracking
    # ------------------------------------------------------------------

    def _initialize_quota_tracking(self):
        today = datetime.now().strftime("%Y-%m-%d")
        for key_index in self.api_keys.keys():
            existing = self.quota_collection.find_one({"key_index": key_index, "date": today})
            if not existing:
                self.quota_collection.insert_one({
                    "key_index": key_index,
                    "date": today,
                    "requests_count": 0,
                    "tokens_used": 0,
                    "last_request_time": None,
                    "minute_requests": [],
                    "created_at": datetime.now(),
                })
        self.quota_collection.create_index([("key_index", 1), ("date", 1)], unique=True)
        self.quota_collection.create_index([("date", 1)])
        self.requests_collection.create_index([("key_index", 1), ("timestamp", -1)])
        self.requests_collection.create_index([("task_type", 1)])

    # ------------------------------------------------------------------
    # Key selection
    # ------------------------------------------------------------------

    def get_available_key(self) -> Tuple[int, str]:
        with self._key_lock:
            return self._get_available_key_locked()

    def _get_available_key_locked(self) -> Tuple[int, str]:
        today = datetime.now().strftime("%Y-%m-%d")
        one_minute_ago = datetime.now() - timedelta(minutes=1)

        for key_index, api_key in self.api_keys.items():
            quota = self.quota_collection.find_one({"key_index": key_index, "date": today})
            if not quota:
                self._initialize_quota_tracking()
                quota = self.quota_collection.find_one({"key_index": key_index, "date": today})

            if quota["requests_count"] >= self.MAX_DAILY_REQUESTS:
                continue

            recent = [r for r in quota.get("minute_requests", [])
                      if datetime.fromisoformat(r) > one_minute_ago]
            if len(recent) >= self.MAX_RPM:
                continue

            return key_index, api_key

        raise Exception(
            f"All {self.TOTAL_KEYS} OpenAI API keys have exceeded safeguard quotas. "
            f"Daily limit: {self.MAX_DAILY_REQUESTS}/key, RPM limit: {self.MAX_RPM}/key"
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_request(self, key_index: int, tokens_used: int, task_type: str,
                    success: bool = True, error: str = None, metadata: dict = None):
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        self.quota_collection.update_one(
            {"key_index": key_index, "date": today},
            {
                "$inc": {"requests_count": 1, "tokens_used": tokens_used},
                "$set": {"last_request_time": now.isoformat()},
                "$push": {
                    "minute_requests": {
                        "$each": [now.isoformat()],
                        "$slice": -self.MAX_RPM,
                    }
                },
            },
        )
        self.requests_collection.insert_one({
            "key_index": key_index,
            "timestamp": now,
            "date": today,
            "task_type": task_type,
            "tokens_used": tokens_used,
            "success": success,
            "error": error,
            "metadata": metadata or {},
        })

    # ------------------------------------------------------------------
    # Quota / health
    # ------------------------------------------------------------------

    def check_quota(self, key_index: int = None) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        if key_index is not None:
            quota = self.quota_collection.find_one({"key_index": key_index, "date": today})
            if not quota:
                return {"key_index": key_index, "requests_today": 0, "tokens_used": 0,
                        "remaining_requests": self.MAX_DAILY_REQUESTS, "percentage_used": 0}
            remaining = self.MAX_DAILY_REQUESTS - quota["requests_count"]
            pct = (quota["requests_count"] / self.MAX_DAILY_REQUESTS) * 100
            return {"key_index": key_index, "requests_today": quota["requests_count"],
                    "tokens_used": quota["tokens_used"], "remaining_requests": remaining,
                    "percentage_used": round(pct, 2), "last_request": quota.get("last_request_time")}
        else:
            all_quotas = []
            total_req = total_tok = 0
            for ki in self.api_keys:
                qi = self.check_quota(ki)
                all_quotas.append(qi)
                total_req += qi["requests_today"]
                total_tok += qi["tokens_used"]
            max_total = self.MAX_DAILY_REQUESTS * self.TOTAL_KEYS
            return {"total_keys": self.TOTAL_KEYS, "total_requests_today": total_req,
                    "total_tokens_used": total_tok,
                    "total_remaining_requests": max_total - total_req,
                    "max_daily_capacity": max_total,
                    "percentage_used": round((total_req / max_total) * 100, 2),
                    "keys": all_quotas}

    def health_check(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        health = {"timestamp": datetime.now().isoformat(), "date": today, "keys": []}
        for key_index, api_key in self.api_keys.items():
            q = self.check_quota(key_index)
            status = "healthy" if q["remaining_requests"] > 100 else "warning" if q["remaining_requests"] > 0 else "exhausted"
            health["keys"].append({"key_index": key_index, "configured": bool(api_key),
                                   "requests_today": q["requests_today"],
                                   "remaining": q["remaining_requests"],
                                   "percentage_used": q["percentage_used"],
                                   "status": status})
        total_rem = sum(k["remaining"] for k in health["keys"])
        health["system_status"] = "healthy" if total_rem > 1000 else "degraded" if total_rem > 100 else "critical"
        health["total_remaining_capacity"] = total_rem
        return health


class OpenAIPipelineRotator:
    """
    RPM-aware + daily-cap-aware rotator for a fixed pool of OpenAI keys.
    One instance per pipeline; obtain via get_pipeline_rotator().
    """

    RPM_LIMIT       = 500
    DAILY_LIMIT     = 50_000
    DAILY_CACHE_TTL = 120

    def __init__(self, pipeline_name: str, key_indices: List[int],
                 base_rotator: "OpenAIRotator"):
        self.pipeline_name = pipeline_name
        self.key_indices = [i for i in key_indices if i in base_rotator.api_keys]
        self._base = base_rotator
        self._lock = threading.Lock()

        self._rpm_window: Dict[int, List[float]] = {i: [] for i in self.key_indices}
        self._daily_exhausted: set = set()
        self._daily_cache_time: float = 0.0
        self._account_names: Dict[int, str] = self._load_account_names()

        if not self.key_indices:
            raise ValueError(
                f"Pipeline '{pipeline_name}': none of the requested keys "
                f"{key_indices} are configured in the DB."
            )

    def _load_account_names(self) -> Dict[int, str]:
        try:
            settings = self._base.settings_db["app_settings"].find_one() or {}
            return {i: settings.get(f"openai_account_{i}", f"key_{i}")
                    for i in range(1, self._base.TOTAL_KEYS + 1)}
        except Exception:
            return {i: f"key_{i}" for i in range(1, self._base.TOTAL_KEYS + 1)}

    def account_name(self, key_index: int) -> str:
        return self._account_names.get(key_index, f"key_{key_index}")

    def _refresh_daily_cache(self):
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            docs = list(self._base.quota_collection.find(
                {"key_index": {"$in": self.key_indices}, "date": today},
                {"key_index": 1, "requests_count": 1},
            ))
            exhausted = {d["key_index"] for d in docs
                         if d.get("requests_count", 0) >= self.DAILY_LIMIT}
        except Exception:
            exhausted = set()
        with self._lock:
            self._daily_exhausted = exhausted
            self._daily_cache_time = time.time()

    def _ensure_daily_cache(self):
        if time.time() - self._daily_cache_time > self.DAILY_CACHE_TTL:
            self._refresh_daily_cache()

    def get_available_key(self) -> Tuple[int, str]:
        self._ensure_daily_cache()
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - 60.0
                candidates = [i for i in self.key_indices if i not in self._daily_exhausted]
                if not candidates:
                    raise Exception(
                        f"Pipeline '{self.pipeline_name}': all keys have hit the "
                        f"{self.DAILY_LIMIT} req/day safeguard limit."
                    )
                sleep_until: Optional[float] = None
                for key_idx in candidates:
                    window = self._rpm_window[key_idx] = [
                        t for t in self._rpm_window[key_idx] if t > cutoff
                    ]
                    if len(window) < self.RPM_LIMIT:
                        window.append(now)
                        return key_idx, self._base.api_keys[key_idx]
                    earliest = window[0] + 60.0
                    if sleep_until is None or earliest < sleep_until:
                        sleep_until = earliest
            wait_s = max(0.3, (sleep_until - time.time())) if sleep_until else 5.0
            time.sleep(wait_s)

    def log_request(self, key_index: int, tokens_used: int, task_type: str,
                    success: bool = True, error: str = None, metadata: dict = None):
        self._base.log_request(
            key_index, tokens_used, f"{self.pipeline_name}:{task_type}",
            success=success, error=error,
            metadata={**(metadata or {}), "account": self.account_name(key_index)},
        )

    def health_check(self) -> Dict:
        self._ensure_daily_cache()
        today = datetime.now().strftime("%Y-%m-%d")
        now = time.time()
        cutoff = now - 60.0
        try:
            daily_counts = {
                d["key_index"]: d.get("requests_count", 0)
                for d in self._base.quota_collection.find(
                    {"key_index": {"$in": self.key_indices}, "date": today},
                    {"key_index": 1, "requests_count": 1},
                )
            }
        except Exception:
            daily_counts = {}

        keys_status = []
        with self._lock:
            for key_idx in self.key_indices:
                recent = [t for t in self._rpm_window[key_idx] if t > cutoff]
                daily_used = daily_counts.get(key_idx, 0)
                keys_status.append({
                    "key_index": key_idx,
                    "account": self.account_name(key_idx),
                    "rpm_used": len(recent),
                    "rpm_headroom": max(0, self.RPM_LIMIT - len(recent)),
                    "daily_used": daily_used,
                    "daily_remaining": max(0, self.DAILY_LIMIT - daily_used),
                    "daily_exhausted": key_idx in self._daily_exhausted,
                })
        return {
            "pipeline": self.pipeline_name,
            "keys": keys_status,
            "active_keys": len([k for k in keys_status if not k["daily_exhausted"]]),
        }


# ------------------------------------------------------------------
# Singleton caches
# ------------------------------------------------------------------

_rotator_instance: Optional[OpenAIRotator] = None
_pipeline_rotators: Dict[str, OpenAIPipelineRotator] = {}
_pipeline_rotators_lock = threading.Lock()


def get_rotator() -> OpenAIRotator:
    global _rotator_instance
    if _rotator_instance is None:
        _rotator_instance = OpenAIRotator()
    return _rotator_instance


def get_pipeline_rotator(pipeline_name: str) -> OpenAIPipelineRotator:
    global _pipeline_rotators
    with _pipeline_rotators_lock:
        if pipeline_name not in _pipeline_rotators:
            base = get_rotator()
            try:
                settings = base.settings_db["app_settings"].find_one()
                override = (settings or {}).get("openai_pipeline_config")
                key_map = override or DEFAULT_PIPELINE_KEY_MAP
            except Exception:
                key_map = DEFAULT_PIPELINE_KEY_MAP
            key_indices = key_map.get(pipeline_name, list(range(1, 13)))
            _pipeline_rotators[pipeline_name] = OpenAIPipelineRotator(
                pipeline_name, key_indices, base,
            )
    return _pipeline_rotators[pipeline_name]

