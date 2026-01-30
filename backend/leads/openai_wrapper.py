"""
CENTRALIZED AI API WRAPPER (OpenAI Only - Web Search)
[DEPRECATED] Email classification/summarization now uses Gemini via ai_governance module.

Key Features:
- OpenAI for web search and external lead discovery ONLY
- Email operations MUST use backend.ai_governance.gemini_gateway
- Token usage logging to MongoDB
- Global kill switch via DISABLE_AI_CALLS env var

GOVERNANCE NOTE:
- Gemini: Email classification, summarization, lead extraction (via ai_governance)
- OpenAI: Web search, company discovery, web enrichment ONLY
"""

import os
import time
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from functools import wraps

from openai import OpenAI, APIError, RateLimitError, APIConnectionError
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

# AI Provider types (Gemini handled separately in ai_governance)
AIProvider = Literal["openai"]

# DEFAULT PROVIDER: OpenAI for web search only
DEFAULT_PROVIDER = "openai"

# Default token limits - COST CONTROL
DEFAULT_MAX_OUTPUT_TOKENS = 300       # Standard API responses
BACKGROUND_MAX_OUTPUT_TOKENS = 150    # Cron/background tasks
INTERNAL_MAX_OUTPUT_TOKENS = 200      # Internal/middleware tasks
ESCALATED_MAX_OUTPUT_TOKENS = 500     # Escalated to premium model

# OpenAI models
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"  # ~$0.15/$0.60 per 1M tokens
OPENAI_PREMIUM_MODEL = "gpt-4o"       # ~$5/$15 per 1M tokens - USE SPARINGLY

# Default model (OpenAI only)
DEFAULT_MODEL = OPENAI_DEFAULT_MODEL
PREMIUM_MODEL = OPENAI_PREMIUM_MODEL

# Cost per 1K tokens
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.005, "output": 0.015},
}

# Confidence threshold for escalation
ESCALATION_CONFIDENCE_THRESHOLD = 0.7

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 30.0

# Request source types for logging
RequestSource = Literal["api", "cron", "background", "user", "internal"]

# Task types for model routing
# NOTE: Email tasks MUST use Gemini via ai_governance module
TaskType = Literal[
    # OpenAI tasks (web search only)
    "web_search",
    "company_discovery",
    "web_enrichment",
    # DEPRECATED: Use ai_governance.gemini_gateway for these
    "email_classification",  # -> ai_governance.classify_email()
    "email_summary",         # -> ai_governance.summarize_email()
    "contact_extraction",    # -> ai_governance.extract_leads_from_email()
    # Default (web search)
    "default"
]

# Tasks that use OpenAI (web search only)
OPENAI_REQUIRED_TASKS = frozenset({
    "web_search",
    "company_discovery", 
    "web_enrichment",
    "default",
})

# DEPRECATED: Email tasks now use Gemini via ai_governance
# These will raise an error if called through this wrapper
GEMINI_REQUIRED_TASKS = frozenset({
    "email_classification",
    "email_summary",
    "email_thread_summary", 
    "contact_extraction",
})


def get_model_for_task(task_type: str = "default") -> tuple:
    """
    Get the optimal (provider, model) for a given task type.
    
    GOVERNANCE POLICY:
    - OpenAI: Web search, company discovery, web enrichment ONLY
    - Gemini (via ai_governance): All email operations
    
    Args:
        task_type: Type of task (see TaskType literals)
        
    Returns:
        Tuple of (provider, model)
        
    Raises:
        ValueError: If task_type should use Gemini instead
    """
    if task_type in GEMINI_REQUIRED_TASKS:
        raise ValueError(
            f"Task '{task_type}' must use Gemini via ai_governance module. "
            f"Import: from ai_governance import classify_email, summarize_email, extract_leads_from_email"
        )
    return ("openai", OPENAI_DEFAULT_MODEL)


# ============== GLOBAL KILL SWITCH ==============

def is_ai_disabled() -> bool:
    """
    Check if AI calls are disabled via environment variable.
    Set DISABLE_AI_CALLS=true to disable all API calls.
    """
    return os.getenv("DISABLE_AI_CALLS", "").lower() in ("true", "1", "yes")


# ============== TOKEN USAGE LOGGING ==============

class TokenUsageLogger:
    """
    Logs all AI API token usage to MongoDB for cost tracking.
    Collection: ai_usage_logs
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
                self._collection.create_index([("timestamp", -1)])
                self._collection.create_index([("source", 1), ("timestamp", -1)])
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
        error_message: str = "",
        input_data: Optional[str] = None,
        output_response: Optional[str] = None,
        confidence_score: Optional[float] = None
    ):
        """Log token usage for cost tracking."""
        collection = self._get_collection()
        if collection is None:
            return
        
        costs = MODEL_COSTS.get(model, MODEL_COSTS[OPENAI_DEFAULT_MODEL])
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
        
        if input_data is not None:
            doc["input_data"] = input_data[:2000] if len(input_data) > 2000 else input_data
        if output_response is not None:
            doc["output_response"] = output_response[:2000] if len(output_response) > 2000 else output_response
        if confidence_score is not None:
            doc["confidence_score"] = confidence_score
        
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
                "_id": {"model": "$model", "provider": "$provider"},
                "total_requests": {"$sum": 1},
                "total_input_tokens": {"$sum": "$input_tokens"},
                "total_output_tokens": {"$sum": "$output_tokens"},
                "total_cost": {"$sum": "$cost_usd"},
                "avg_latency": {"$avg": "$latency_ms"}
            }}
        ]
        
        try:
            results = list(collection.aggregate(pipeline))
            return {"period_hours": hours, "breakdown": results}
        except Exception:
            return {}


token_logger = TokenUsageLogger()


# ============== RATE LIMITER ==============

class RateLimiter:
    """Rate limiter with separate limits for different sources."""
    
    def __init__(self):
        self.limits = {
            "cron": {"max_per_minute": 50, "max_per_hour": 1000},
            "background": {"max_per_minute": 50, "max_per_hour": 1500},
            "api": {"max_per_minute": 20, "max_per_hour": 400},
            "user": {"max_per_minute": 30, "max_per_hour": 500},
            "internal": {"max_per_minute": 10, "max_per_hour": 150},
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
        
        self.request_times[key] = [t for t in self.request_times[key] if t > hour_ago]
        
        limits = self.limits.get(source, self.limits["api"])
        
        recent_minute = len([t for t in self.request_times[key] if t > minute_ago])
        if recent_minute >= limits["max_per_minute"]:
            logger.warning(f"Rate limit exceeded for source '{source}': {recent_minute}/min")
            return False
        
        if len(self.request_times[key]) >= limits["max_per_hour"]:
            logger.warning(f"Hourly rate limit exceeded for source '{source}'")
            return False
        
        self.request_times[key].append(now)
        return True


rate_limiter = RateLimiter()


# ============== API KEY MANAGEMENT ==============

def get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from database settings first, fallback to env var."""
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


# DEPRECATED: get_deepseek_api_key removed per AI Governance spec
# Use Gemini for email operations via ai_governance module


# ============== CLIENT SINGLETONS ==============

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


# DEPRECATED: get_deepseek_client removed per AI Governance spec


def reset_clients():
    """Reset client singletons (useful when API keys change)."""
    global _openai_client
    _openai_client = None


# ============== MAIN API WRAPPER ==============

def chat_completion(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    model: str = None,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    allow_premium_model: bool = False,
    provider: Optional[AIProvider] = None
) -> Dict[str, Any]:
    """
    Centralized AI chat completion with cost controls.
    OpenAI ONLY - for web search and external lead discovery.
    
    NOTE: Email operations MUST use ai_governance.gemini_gateway
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        source: Request source for logging and rate limiting
        endpoint: API endpoint name for logging
        model: Model to use (defaults to gpt-4o-mini)
        max_output_tokens: Max tokens in response
        temperature: Model temperature (default 0.1)
        response_format: Optional response format (e.g., {"type": "json_object"})
        allow_premium_model: Must be True to use premium models
        provider: Force provider (only "openai" supported)
    
    Returns:
        Dict with 'content', 'usage', 'model', 'provider', 'success', 'error'
    """
    start_time = time.time()
    
    # Always use OpenAI (governance policy)
    provider = "openai"
    if model is None:
        model = OPENAI_DEFAULT_MODEL
    
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
    if model == OPENAI_PREMIUM_MODEL and not allow_premium_model:
        logger.warning(f"Downgrading {OPENAI_PREMIUM_MODEL} to {OPENAI_DEFAULT_MODEL}")
        model = OPENAI_DEFAULT_MODEL
    
    # Set max_output_tokens based on source if not specified
    if max_output_tokens is None:
        if source in ("cron", "background"):
            max_output_tokens = BACKGROUND_MAX_OUTPUT_TOKENS
        elif source == "internal":
            max_output_tokens = INTERNAL_MAX_OUTPUT_TOKENS
        else:
            max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
    
    # Route to OpenAI only
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


# DEPRECATED: _deepseek_chat_completion removed per AI Governance spec
# All email operations now use Gemini via ai_governance module


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
    
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_output_tokens
    }
    if response_format:
        kwargs["response_format"] = response_format
    
    last_error = None
    retry_delay = INITIAL_RETRY_DELAY
    
    for attempt in range(MAX_RETRIES):
        try:
            client = get_openai_client()
            response = client.chat.completions.create(**kwargs)
            
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0
            
            latency_ms = int((time.time() - start_time) * 1000)
            response_content = response.choices[0].message.content
            
            input_summary = " | ".join([f"{m['role']}: {m['content'][:200]}" for m in messages])
            
            token_logger.log_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                model=model,
                source=source,
                provider="openai",
                endpoint=endpoint,
                latency_ms=latency_ms,
                success=True,
                input_data=input_summary,
                output_response=response_content
            )
            
            return {
                "content": response_content,
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
    
    latency_ms = int((time.time() - start_time) * 1000)
    input_summary = " | ".join([f"{m['role']}: {m['content'][:200]}" for m in messages])
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
        error_message=last_error or "Unknown error",
        input_data=input_summary
    )
    
    return {
        "content": "",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "model": model,
        "provider": "openai",
        "success": False,
        "error": last_error
    }


# ============== CONFIDENCE-BASED ESCALATION ==============

def chat_completion_with_escalation(
    messages: List[Dict[str, str]],
    source: RequestSource = "api",
    endpoint: str = "",
    primary_model: str = OPENAI_DEFAULT_MODEL,  # Use gpt-4o-mini as primary
    escalation_model: str = OPENAI_PREMIUM_MODEL,
    max_output_tokens: Optional[int] = None,
    temperature: float = 0.1,
    response_format: Optional[Dict] = None,
    confidence_key: str = "confidence_score",
    confidence_threshold: float = ESCALATION_CONFIDENCE_THRESHOLD
) -> Dict[str, Any]:
    """
    Two-stage chat completion with confidence-based escalation.
    
    Tier 1: OpenAI gpt-4o-mini (primary classification)
    Tier 2: OpenAI GPT-4o (better quality) if confidence < 0.7
    """
    
    # Determine primary provider
    primary_provider = "deepseek" if is_deepseek_model(primary_model) else "openai"
    
    # First attempt with primary model
    result = chat_completion(
        messages=messages,
        source=source,
        endpoint=endpoint,
        model=primary_model,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_format=response_format,
        provider=primary_provider
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
            
            escalated_result = chat_completion(
                messages=messages,
                source=source,
                endpoint=f"{endpoint}_escalated",
                model=escalation_model,
                max_output_tokens=max_output_tokens or ESCALATED_MAX_OUTPUT_TOKENS,
                temperature=temperature,
                response_format=response_format,
                allow_premium_model=True,
                provider="openai"
            )
            
            escalated_result["escalated"] = True
            escalated_result["primary_confidence"] = confidence
            
            return escalated_result
            
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    
    return result


# ============== BATCH PROCESSING ==============

def batch_chat_completion(
    items: List[Any],
    prompt_generator: callable,
    source: RequestSource = "background",
    batch_size: int = 10,
    model: str = OPENAI_DEFAULT_MODEL,
    max_output_tokens: int = 1500,
    system_prompt: str = "",
    provider: str = "openai"
) -> List[Dict[str, Any]]:
    """
    Process multiple items in batched API calls.
    Uses OpenAI by default.
    """
    all_results = []
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        
        user_prompt = prompt_generator(batch)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        result = chat_completion(
            messages=messages,
            source=source,
            endpoint="batch_processing",
            model=model,
            max_output_tokens=max_output_tokens,
            response_format={"type": "json_object"},
            provider=provider
        )
        
        if result["success"]:
            try:
                parsed = json.loads(result["content"])
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
        
        if i + batch_size < len(items):
            time.sleep(0.5)
    
    return all_results


# ============== UTILITY FUNCTIONS ==============

BREVITY_INSTRUCTIONS = """Respond concisely. Do not explain unless asked. Prefer JSON over prose."""
JSON_ONLY_INSTRUCTION = """Respond with valid JSON only. No markdown, no explanations."""


def build_system_prompt(
    role_description: str,
    output_instructions: str = "",
    include_brevity: bool = True,
    json_only: bool = False
) -> str:
    """Build optimized system prompt."""
    parts = []
    
    if include_brevity:
        parts.append(BREVITY_INSTRUCTIONS)
    
    if json_only:
        parts.append(JSON_ONLY_INSTRUCTION)
    
    parts.append(role_description.strip())
    
    if output_instructions:
        parts.append(output_instructions.strip())
    
    return " ".join(parts)


def get_daily_usage_report() -> Dict[str, Any]:
    """Get a daily usage report for monitoring."""
    return token_logger.get_usage_summary(hours=24)


def get_hourly_usage_report() -> Dict[str, Any]:
    """Get an hourly usage report for monitoring."""
    return token_logger.get_usage_summary(hours=1)
