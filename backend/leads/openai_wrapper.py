"""
CENTRALIZED AI API WRAPPER (OpenAI + Anthropic)
Cost-optimized wrapper with token logging, rate limiting, and safety guards.
Supports multi-provider routing with confidence-based escalation.

Key optimizations:
- Strict max_output_tokens enforcement (default 300, background tasks 150-200)
- Token usage logging to MongoDB
- Global kill switch via DISABLE_AI_CALLS env var
- Model routing: gpt-4o-mini by default, escalate to Claude for complex tasks
- Exponential backoff on retries
- Request source tracking (cron/api/user)
- Confidence-based escalation to premium models
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

# Anthropic import with fallback
try:
    from anthropic import Anthropic, APIError as AnthropicAPIError, RateLimitError as AnthropicRateLimitError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AnthropicAPIError = Exception
    AnthropicRateLimitError = Exception

load_dotenv()

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

# AI Provider types
AIProvider = Literal["openai", "anthropic"]

# Default token limits - COST CONTROL
DEFAULT_MAX_OUTPUT_TOKENS = 300       # Standard API responses
BACKGROUND_MAX_OUTPUT_TOKENS = 150    # Cron/background tasks
INTERNAL_MAX_OUTPUT_TOKENS = 200      # Internal/middleware tasks
ESCALATED_MAX_OUTPUT_TOKENS = 500     # Escalated to premium model

# Model routing - cost control
DEFAULT_MODEL = "gpt-4o-mini"  # ~$0.15/$0.60 per 1M tokens
PREMIUM_MODEL = "gpt-4o"       # ~$5/$15 per 1M tokens - USE SPARINGLY

# Anthropic models
ANTHROPIC_DEFAULT_MODEL = "claude-3-5-sonnet-20241022"  # ~$3/$15 per 1M tokens
ANTHROPIC_PREMIUM_MODEL = "claude-sonnet-4-20250514"        # ~$15/$75 per 1M tokens - BEST QUALITY

# Cost per 1K tokens
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-sonnet-4-20250514": {"input": 0.015, "output": 0.075},
}

# Confidence threshold for escalation
ESCALATION_CONFIDENCE_THRESHOLD = 0.7  # Below this, escalate to premium model

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 30.0

# Request source types for logging
RequestSource = Literal["api", "cron", "background", "user", "internal"]


# ============== GLOBAL KILL SWITCH ==============

def is_ai_disabled() -> bool:
    """
    Check if AI calls are disabled via environment variable.
    Set DISABLE_AI_CALLS=true or DISABLE_OPENAI_CALLS=true to disable all API calls.
    """
    return (
        os.getenv("DISABLE_AI_CALLS", "").lower() in ("true", "1", "yes") or
        os.getenv("DISABLE_OPENAI_CALLS", "").lower() in ("true", "1", "yes")
    )


# Legacy alias for backwards compatibility
def is_openai_disabled() -> bool:
    return is_ai_disabled()


# ============== TOKEN USAGE LOGGING ==============

class TokenUsageLogger:
    """
    Logs all AI API token usage to MongoDB for cost tracking.
    Collection: ai_usage_logs (renamed from openai_usage_logs)
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
                self._collection = self._client['email_automation']['ai_usage_logs']
                # Create indexes for efficient querying
                self._collection.create_index([("timestamp", -1)])
                self._collection.create_index([("source", 1), ("timestamp", -1)])
                self._collection.create_index([("model", 1), ("timestamp", -1)])
                self._collection.create_index([("provider", 1), ("timestamp", -1)])
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
        provider: str = "openai",
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
            "provider": provider,
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


def get_anthropic_api_key() -> Optional[str]:
    """
    Get Anthropic API key from database settings first, fallback to env var.
    """
    try:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        
        stored = app_settings.find_one({"_id": "app_config"})
        if stored and stored.get("anthropic_api_key"):
            return stored["anthropic_api_key"]
    except Exception as e:
        logger.debug(f"Could not fetch Anthropic key from DB: {e}")
    
    return os.getenv("ANTHROPIC_API_KEY")


# ============== CLIENT SINGLETONS ==============

_openai_client: Optional[OpenAI] = None
_anthropic_client: Optional["Anthropic"] = None


def get_openai_client() -> OpenAI:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        api_key = get_openai_api_key()
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured in settings or environment")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def get_anthropic_client() -> "Anthropic":
    """Get or create Anthropic client singleton."""
    global _anthropic_client
    if not ANTHROPIC_AVAILABLE:
        raise ValueError("Anthropic library not installed. Run: pip install anthropic")
    if _anthropic_client is None:
        api_key = get_anthropic_api_key()
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured in settings or environment")
        _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


def is_anthropic_model(model: str) -> bool:
    """Check if the model is an Anthropic model."""
    return model.startswith("claude")


# ============== MAIN API WRAPPER ==============

def chat_completion(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    model: str = DEFAULT_MODEL,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    allow_premium_model: bool = False,
    provider: Optional[AIProvider] = None
) -> Dict[str, Any]:
    """
    Centralized AI chat completion with cost controls.
    Supports OpenAI and Anthropic (Claude) models.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        source: Request source for logging and rate limiting
        endpoint: API endpoint name for logging
        model: Model to use (defaults to gpt-4o-mini for cost control)
        max_output_tokens: Max tokens in response (auto-set based on source if None)
        temperature: Model temperature (default 0.1 for consistency)
        response_format: Optional response format (e.g., {"type": "json_object"})
        allow_premium_model: Must be True to use premium models
        provider: Force provider ("openai" or "anthropic"). Auto-detected from model if None.
    
    Returns:
        Dict with 'content', 'usage', 'model', 'provider', 'success', 'error'
    """
    start_time = time.time()
    
    # Auto-detect provider from model name
    if provider is None:
        provider = "anthropic" if is_anthropic_model(model) else "openai"
    
    # Safety: Check kill switch
    if is_ai_disabled():
        logger.warning("AI calls disabled via DISABLE_AI_CALLS")
        return {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "model": model,
            "provider": provider,
            "success": False,
            "error": "AI calls are disabled"
        }
    
    # Safety: Check rate limits
    if not rate_limiter.is_allowed(source):
        return {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "model": model,
            "provider": provider,
            "success": False,
            "error": f"Rate limit exceeded for source: {source}"
        }
    
    # Model routing: prevent accidental premium model usage
    if provider == "openai":
        if model == PREMIUM_MODEL and not allow_premium_model:
            logger.warning(f"Downgrading {PREMIUM_MODEL} to {DEFAULT_MODEL} - set allow_premium_model=True")
            model = DEFAULT_MODEL
    elif provider == "anthropic":
        if model == ANTHROPIC_PREMIUM_MODEL and not allow_premium_model:
            logger.warning(f"Downgrading {ANTHROPIC_PREMIUM_MODEL} to {ANTHROPIC_DEFAULT_MODEL}")
            model = ANTHROPIC_DEFAULT_MODEL
    
    # Set max_output_tokens based on source if not specified
    if max_output_tokens is None:
        if source in ("cron", "background"):
            max_output_tokens = BACKGROUND_MAX_OUTPUT_TOKENS
        elif source == "internal":
            max_output_tokens = INTERNAL_MAX_OUTPUT_TOKENS
        else:
            max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
    
    # Route to appropriate provider
    if provider == "anthropic":
        return _anthropic_chat_completion(
            messages=messages,
            model=model,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            source=source,
            endpoint=endpoint,
            start_time=start_time,
            response_format=response_format
        )
    else:
        return _openai_chat_completion(
            messages=messages,
            model=model,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_format=response_format,
            source=source,
            endpoint=endpoint,
            start_time=start_time
        )


def _openai_chat_completion(
    messages: List[Dict[str, str]],
    model: str,
    max_output_tokens: int,
    temperature: float,
    source: RequestSource,
    endpoint: str,
    start_time: float,
    response_format: Optional[Dict] = None
) -> Dict[str, Any]:
    """Internal OpenAI implementation."""
    
    # Build API call kwargs
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_output_tokens
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
                provider="openai",
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
                "provider": "openai",
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
        provider="openai",
        endpoint=endpoint,
        latency_ms=latency_ms,
        success=False,
        error_message=last_error or "Unknown error"
    )
    
    return {
        "content": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": model,
        "provider": "openai",
        "success": False,
        "error": last_error
    }


def _anthropic_chat_completion(
    messages: List[Dict[str, str]],
    model: str,
    max_output_tokens: int,
    temperature: float,
    source: RequestSource,
    endpoint: str,
    start_time: float,
    response_format: Optional[Dict] = None
) -> Dict[str, Any]:
    """Internal Anthropic/Claude implementation."""
    
    if not ANTHROPIC_AVAILABLE:
        return {
            "content": "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "model": model,
            "provider": "anthropic",
            "success": False,
            "error": "Anthropic library not installed. Run: pip install anthropic"
        }
    
    # Convert messages format: extract system prompt if present
    system_prompt = ""
    anthropic_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_prompt = msg["content"]
        else:
            anthropic_messages.append({"role": msg["role"], "content": msg["content"]})
    
    # If response_format requires JSON, add instruction to system prompt
    if response_format and response_format.get("type") == "json_object":
        json_instruction = "\n\nRespond with valid JSON only. No markdown, no explanations."
        system_prompt = (system_prompt + json_instruction) if system_prompt else json_instruction.strip()
    
    # Retry with exponential backoff
    last_error = None
    retry_delay = INITIAL_RETRY_DELAY
    
    for attempt in range(MAX_RETRIES):
        try:
            client = get_anthropic_client()
            
            kwargs = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": max_output_tokens,
                "temperature": temperature
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            
            response = client.messages.create(**kwargs)
            
            # Extract usage stats
            usage = response.usage
            input_tokens = usage.input_tokens if usage else 0
            output_tokens = usage.output_tokens if usage else 0
            total_tokens = input_tokens + output_tokens
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log usage
            token_logger.log_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=model,
                source=source,
                provider="anthropic",
                endpoint=endpoint,
                latency_ms=latency_ms,
                success=True
            )
            
            # Extract content from response
            content = ""
            if response.content and len(response.content) > 0:
                content = response.content[0].text
            
            return {
                "content": content,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens
                },
                "model": model,
                "provider": "anthropic",
                "success": True,
                "error": None
            }
            
        except AnthropicRateLimitError as e:
            last_error = str(e)
            logger.warning(f"Anthropic rate limit hit, retrying in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            
        except AnthropicAPIError as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Anthropic API error, retrying: {e}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            
        except Exception as e:
            last_error = str(e)
            logger.error(f"Anthropic call failed: {e}")
            break
    
    # Log failed attempt
    latency_ms = int((time.time() - start_time) * 1000)
    token_logger.log_usage(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        model=model,
        source=source,
        provider="anthropic",
        endpoint=endpoint,
        latency_ms=latency_ms,
        success=False,
        error_message=last_error or "Unknown error"
    )
    
    return {
        "content": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": model,
        "provider": "anthropic",
        "success": False,
        "error": last_error
    }


# ============== CONFIDENCE-BASED ESCALATION ==============

def chat_completion_with_escalation(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    primary_model: str = DEFAULT_MODEL,
    escalation_model: str = ANTHROPIC_DEFAULT_MODEL,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    confidence_key: str = "confidence_score",
    confidence_threshold: float = ESCALATION_CONFIDENCE_THRESHOLD
) -> Dict[str, Any]:
    """
    Two-stage chat completion with confidence-based escalation.
    
    First tries with primary_model (cheap). If response has low confidence,
    escalates to escalation_model (expensive but better quality).
    
    Args:
        messages: List of message dicts
        source: Request source for logging
        endpoint: API endpoint name
        primary_model: First model to try (default: gpt-4o-mini)
        escalation_model: Fallback for low confidence (default: claude-3-5-sonnet)
        max_output_tokens: Max tokens in response
        temperature: Model temperature
        response_format: Optional response format
        confidence_key: JSON key containing confidence score
        confidence_threshold: Escalate if confidence below this (0.0-1.0)
    
    Returns:
        Dict with 'content', 'usage', 'model', 'provider', 'success', 'error', 'escalated'
    """
    import json
    
    # First attempt with primary model
    result = chat_completion(
        messages=messages,
        source=source,
        endpoint=endpoint,
        model=primary_model,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_format=response_format
    )
    
    result["escalated"] = False
    
    if not result["success"]:
        return result
    
    # Check confidence in response
    try:
        parsed = json.loads(result["content"])
        confidence = parsed.get(confidence_key, 1.0)
        
        if isinstance(confidence, (int, float)) and confidence < confidence_threshold:
            logger.info(f"Low confidence ({confidence:.2f}), escalating to {escalation_model}")
            
            # Escalate to better model
            escalated_result = chat_completion(
                messages=messages,
                source=source,
                endpoint=f"{endpoint}_escalated",
                model=escalation_model,
                max_output_tokens=max_output_tokens or ESCALATED_MAX_OUTPUT_TOKENS,
                temperature=temperature,
                response_format=response_format,
                allow_premium_model=True
            )
            
            escalated_result["escalated"] = True
            escalated_result["primary_confidence"] = confidence
            
            # Combine usage from both calls
            escalated_result["usage"]["total_input_tokens"] = (
                result["usage"]["input_tokens"] + escalated_result["usage"]["input_tokens"]
            )
            escalated_result["usage"]["total_output_tokens"] = (
                result["usage"]["output_tokens"] + escalated_result["usage"]["output_tokens"]
            )
            
            return escalated_result
            
    except (json.JSONDecodeError, KeyError, TypeError):
        # Can't parse confidence, return primary result
        pass
    
    return result


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
