"""
CENTRALIZED OPENAI API WRAPPER
Cost-optimized wrapper with token logging, rate limiting, and safety guards.

Key optimizations:
- Strict max_output_tokens enforcement (default 300, background tasks 150-200)
- Token usage logging to MongoDB
- Global kill switch via DISABLE_OPENAI_CALLS env var
- Model routing: gpt-4o-mini by default, escalate only when required
- Exponential backoff on retries
- Request source tracking (cron/api/user)
"""

import os
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from functools import wraps

from openai import OpenAI, APIError, RateLimitError, APIConnectionError
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

# Default token limits - COST CONTROL
DEFAULT_MAX_OUTPUT_TOKENS = 300       # Standard API responses
BACKGROUND_MAX_OUTPUT_TOKENS = 150    # Cron/background tasks
INTERNAL_MAX_OUTPUT_TOKENS = 200      # Internal/middleware tasks

# Model routing - cost control
DEFAULT_MODEL = "gpt-4o-mini"  # ~$0.15/$0.60 per 1M tokens
PREMIUM_MODEL = "gpt-4o"       # ~$5/$15 per 1M tokens - USE SPARINGLY

# Cost per 1K tokens
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
}

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 30.0

# Request source types for logging
RequestSource = Literal["api", "cron", "background", "user", "internal"]


# ============== GLOBAL KILL SWITCH ==============

def is_openai_disabled() -> bool:
    """
    Check if OpenAI calls are disabled via environment variable.
    Set DISABLE_OPENAI_CALLS=true to disable all API calls.
    """
    return os.getenv("DISABLE_OPENAI_CALLS", "").lower() in ("true", "1", "yes")


# ============== TOKEN USAGE LOGGING ==============

class TokenUsageLogger:
    """
    Logs all OpenAI API token usage to MongoDB for cost tracking.
    Collection: openai_usage_logs
    """
    
    def __init__(self):
        self._client = None
        self._collection = None
    
    def _get_collection(self):
        """Lazy initialization of MongoDB connection."""
        if self._collection is None:
            try:
                mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
                self._client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
                self._collection = self._client['email_automation']['openai_usage_logs']
                # Create indexes for efficient querying
                self._collection.create_index([("timestamp", -1)])
                self._collection.create_index([("source", 1), ("timestamp", -1)])
                self._collection.create_index([("model", 1), ("timestamp", -1)])
            except Exception as e:
                logger.warning(f"Could not connect to MongoDB for token logging: {e}")
        return self._collection
    
    def log_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        model: str,
        source: RequestSource,
        endpoint: str = "",
        latency_ms: int = 0,
        success: bool = True,
        error_message: str = ""
    ):
        """
        Log token usage for cost tracking and analysis.
        """
        collection = self._get_collection()
        if collection is None:
            return
        
        costs = MODEL_COSTS.get(model, MODEL_COSTS[DEFAULT_MODEL])
        cost_usd = (input_tokens / 1000 * costs["input"]) + (output_tokens / 1000 * costs["output"])
        
        doc = {
            "timestamp": datetime.utcnow(),
            "model": model,
            "source": source,
            "endpoint": endpoint,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(cost_usd, 6),
            "latency_ms": latency_ms,
            "success": success,
            "error_message": error_message
        }
        
        try:
            collection.insert_one(doc)
        except Exception as e:
            logger.warning(f"Failed to log token usage: {e}")
    
    def get_usage_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get usage summary for the last N hours."""
        collection = self._get_collection()
        if collection is None:
            return {}
        
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(hours=hours)
        
        pipeline = [
            {"$match": {"timestamp": {"$gte": since}}},
            {"$group": {
                "_id": {"model": "$model", "source": "$source"},
                "total_requests": {"$sum": 1},
                "total_input_tokens": {"$sum": "$input_tokens"},
                "total_output_tokens": {"$sum": "$output_tokens"},
                "total_cost": {"$sum": "$cost_usd"},
                "avg_latency": {"$avg": "$latency_ms"}
            }}
        ]
        
        try:
            results = list(collection.aggregate(pipeline))
            return {
                "period_hours": hours,
                "breakdown": results
            }
        except Exception:
            return {}


# Global logger instance
token_logger = TokenUsageLogger()


# ============== RATE LIMITER ==============

class OpenAIRateLimiter:
    """
    Rate limiter with separate limits for different sources.
    Prevents runaway costs from cron jobs or background workers.
    """
    
    def __init__(self):
        self.limits = {
            "cron": {"max_per_minute": 10, "max_per_hour": 100},
            "background": {"max_per_minute": 20, "max_per_hour": 300},
            "api": {"max_per_minute": 30, "max_per_hour": 500},
            "user": {"max_per_minute": 60, "max_per_hour": 1000},
            "internal": {"max_per_minute": 20, "max_per_hour": 200}
        }
        self.request_times: Dict[str, List[datetime]] = {}
    
    def is_allowed(self, source: RequestSource) -> bool:
        """Check if request is allowed under rate limits."""
        from datetime import timedelta
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        key = source
        if key not in self.request_times:
            self.request_times[key] = []
        
        # Clean old entries
        self.request_times[key] = [t for t in self.request_times[key] if t > hour_ago]
        
        limits = self.limits.get(source, self.limits["api"])
        
        # Check per-minute limit
        recent_minute = len([t for t in self.request_times[key] if t > minute_ago])
        if recent_minute >= limits["max_per_minute"]:
            logger.warning(f"Rate limit exceeded for source '{source}': {recent_minute}/min")
            return False
        
        # Check per-hour limit
        if len(self.request_times[key]) >= limits["max_per_hour"]:
            logger.warning(f"Hourly rate limit exceeded for source '{source}'")
            return False
        
        self.request_times[key].append(now)
        return True


rate_limiter = OpenAIRateLimiter()


# ============== API KEY MANAGEMENT ==============

def get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from database settings first, fallback to env var.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        
        stored = app_settings.find_one({"_id": "app_config"})
        if stored and stored.get("openai_api_key"):
            return stored["openai_api_key"]
    except Exception as e:
        logger.debug(f"Could not fetch OpenAI key from DB: {e}")
    
    return os.getenv("OPENAI_API_KEY")


# ============== OPENAI CLIENT SINGLETON ==============

_openai_client: Optional[OpenAI] = None


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        api_key = get_openai_api_key()
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured in settings or environment")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


# ============== MAIN API WRAPPER ==============

def chat_completion(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    model: str = DEFAULT_MODEL,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    allow_premium_model: bool = False
) -> Dict[str, Any]:
    """
    Centralized OpenAI chat completion with cost controls.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        source: Request source for logging and rate limiting
        endpoint: API endpoint name for logging
        model: Model to use (defaults to gpt-4o-mini for cost control)
        max_output_tokens: Max tokens in response (auto-set based on source if None)
        temperature: Model temperature (default 0.1 for consistency)
        response_format: Optional response format (e.g., {"type": "json_object"})
        allow_premium_model: Must be True to use gpt-4o (prevents accidental usage)
    
    Returns:
        Dict with 'content', 'usage', 'model', 'success', 'error'
    """
    start_time = time.time()
    
    # Safety: Check kill switch
    if is_openai_disabled():
        logger.warning("OpenAI calls disabled via DISABLE_OPENAI_CALLS")
        return {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "model": model,
            "success": False,
            "error": "OpenAI calls are disabled"
        }
    
    # Safety: Check rate limits
    if not rate_limiter.is_allowed(source):
        return {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "model": model,
            "success": False,
            "error": f"Rate limit exceeded for source: {source}"
        }
    
    # Model routing: prevent accidental premium model usage
    if model == PREMIUM_MODEL and not allow_premium_model:
        logger.warning(f"Downgrading {PREMIUM_MODEL} to {DEFAULT_MODEL} - set allow_premium_model=True to use premium")
        model = DEFAULT_MODEL
    
    # Set max_output_tokens based on source if not specified
    if max_output_tokens is None:
        if source in ("cron", "background"):
            max_output_tokens = BACKGROUND_MAX_OUTPUT_TOKENS
        elif source == "internal":
            max_output_tokens = INTERNAL_MAX_OUTPUT_TOKENS
        else:
            max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
    
    # Build API call kwargs
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_output_tokens  # ENFORCED: No open-ended responses
    }
    if response_format:
        kwargs["response_format"] = response_format
    
    # Retry with exponential backoff
    last_error = None
    retry_delay = INITIAL_RETRY_DELAY
    
    for attempt in range(MAX_RETRIES):
        try:
            client = get_openai_client()
            response = client.chat.completions.create(**kwargs)
            
            # Extract usage stats
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log usage
            token_logger.log_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=model,
                source=source,
                endpoint=endpoint,
                latency_ms=latency_ms,
                success=True
            )
            
            return {
                "content": response.choices[0].message.content,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens
                },
                "model": model,
                "success": True,
                "error": None
            }
            
        except RateLimitError as e:
            last_error = str(e)
            logger.warning(f"OpenAI rate limit hit, retrying in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            
        except (APIError, APIConnectionError) as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"OpenAI API error, retrying: {e}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"OpenAI call failed: {e}")
            break
    
    # Log failed attempt
    latency_ms = int((time.time() - start_time) * 1000)
    token_logger.log_usage(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        model=model,
        source=source,
        endpoint=endpoint,
        latency_ms=latency_ms,
        success=False,
        error_message=last_error or "Unknown error"
    )
    
    return {
        "content": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": model,
        "success": False,
        "error": last_error
    }


# ============== BATCH PROCESSING UTILITIES ==============

def batch_chat_completion(
    items: List[Any],
    prompt_generator: callable,
    source: RequestSource = "background",
    batch_size: int = 5,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = BACKGROUND_MAX_OUTPUT_TOKENS,
    system_prompt: str = ""
) -> List[Dict[str, Any]]:
    """
    Process multiple items in batched API calls.
    
    Instead of making 1 API call per item, batches items into single requests.
    Reduces context/system prompt token overhead significantly.
    
    Args:
        items: List of items to process
        prompt_generator: Function that takes list of items and returns user prompt
        source: Request source for logging
        batch_size: Number of items per API call (default 5)
        model: Model to use
        max_output_tokens: Max tokens (scales with batch size)
        system_prompt: System prompt (sent once per batch, not per item)
    
    Returns:
        List of results, one per input item
    """
    all_results = []
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        
        # Generate prompt for this batch
        user_prompt = prompt_generator(batch)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # Scale max tokens for batch
        scaled_tokens = max_output_tokens * len(batch)
        
        result = chat_completion(
            messages=messages,
            source=source,
            endpoint="batch_processing",
            model=model,
            max_output_tokens=min(scaled_tokens, 1500),  # Cap at 1500
            response_format={"type": "json_object"}
        )
        
        if result["success"]:
            try:
                import json
                parsed = json.loads(result["content"])
                # Expect array response
                if isinstance(parsed, list):
                    all_results.extend(parsed)
                elif "results" in parsed:
                    all_results.extend(parsed["results"])
                else:
                    all_results.append(parsed)
            except:
                all_results.extend([{"error": "parse_failed"} for _ in batch])
        else:
            all_results.extend([{"error": result["error"]} for _ in batch])
        
        # Small delay between batches to avoid rate limits
        if i + batch_size < len(items):
            time.sleep(0.5)
    
    return all_results


# ============== OPTIMIZED PROMPT CONSTANTS ==============

# Reusable brevity instructions - prepend to system prompts
BREVITY_INSTRUCTIONS = """Respond concisely. Do not explain unless asked. Prefer JSON over prose."""

# Reusable JSON-only instruction
JSON_ONLY_INSTRUCTION = """Respond with valid JSON only. No markdown, no explanations."""

# Reusable output format enforcement
def build_system_prompt(
    role_description: str,
    output_instructions: str = "",
    include_brevity: bool = True,
    json_only: bool = False
) -> str:
    """
    Build optimized system prompt with consistent format.
    Keeps system prompt under 200 tokens where possible.
    """
    parts = []
    
    if include_brevity:
        parts.append(BREVITY_INSTRUCTIONS)
    
    if json_only:
        parts.append(JSON_ONLY_INSTRUCTION)
    
    # Keep role description concise
    parts.append(role_description.strip())
    
    if output_instructions:
        parts.append(output_instructions.strip())
    
    return " ".join(parts)


# ============== USAGE SUMMARY ENDPOINT ==============

def get_daily_usage_report() -> Dict[str, Any]:
    """Get a daily usage report for monitoring."""
    return token_logger.get_usage_summary(hours=24)


def get_hourly_usage_report() -> Dict[str, Any]:
    """Get an hourly usage report for monitoring."""
    return token_logger.get_usage_summary(hours=1)
