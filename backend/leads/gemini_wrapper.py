"""
GEMINI API WRAPPER WITH MULTI-KEY ROTATION
Cost-optimized wrapper using Google Gemini 1.5 Flash with automatic key rotation
to stay within free tier limits.

Free Tier Limits (per API key):
- Requests Per Day (RPD): Up to 1,000 requests
- Requests Per Minute (RPM): 15 requests
- Tokens Per Minute (TPM): 1,000,000 tokens

Key Features:
- Multiple API key rotation for scale
- Rate limiting per key (RPM tracking)
- Daily quota tracking per key (RPD)
- Automatic failover to next key
- Token usage logging to MongoDB
- Cost tracking (free tier = $0)
"""

import os
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from threading import Lock
from collections import defaultdict
from dataclasses import dataclass, field

from pymongo import MongoClient
from dotenv import load_dotenv

# Google Generative AI import
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    try:
        import google.generativeai as genai
        GEMINI_AVAILABLE = True
    except ImportError:
        GEMINI_AVAILABLE = False
        genai = None

load_dotenv()

logger = logging.getLogger(__name__)

# ============== CONFIGURATION ==============

# Available Gemini models
GEMINI_FLASH_MODEL = "gemini-2.0-flash"  # Fast, efficient, good for classification
GEMINI_PRO_MODEL = "gemini-2.5-pro"       # More capable for complex extraction
GEMINI_FLASH_PREVIEW = "gemini-2.5-flash"  # Latest flash preview

# Default model for email classification
DEFAULT_GEMINI_MODEL = GEMINI_FLASH_MODEL

# Free tier limits
FREE_TIER_RPD = 1000      # Requests per day per key
FREE_TIER_RPM = 15        # Requests per minute per key
FREE_TIER_TPM = 1_000_000 # Tokens per minute per key

# Rate limit buffer (leave some margin)
SAFE_RPM = 12  # Use 12 instead of 15 for safety
SAFE_RPD = 950 # Use 950 instead of 1000 for safety

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2.0
MAX_RETRY_DELAY = 30.0


# ============== API KEY MANAGEMENT ==============

@dataclass
class ApiKeyStats:
    """Track usage statistics for an API key"""
    key_id: str
    requests_today: int = 0
    requests_this_minute: int = 0
    tokens_this_minute: int = 0
    last_request_time: datetime = field(default_factory=datetime.utcnow)
    last_minute_reset: datetime = field(default_factory=datetime.utcnow)
    last_day_reset: datetime = field(default_factory=datetime.utcnow)
    total_requests: int = 0
    total_tokens: int = 0
    errors: int = 0
    is_exhausted: bool = False
    exhausted_until: Optional[datetime] = None


class GeminiKeyManager:
    """
    Manages multiple Gemini API keys with rotation and rate limiting.
    """
    
    def __init__(self):
        self._lock = Lock()
        self._keys: List[str] = []
        self._key_stats: Dict[str, ApiKeyStats] = {}
        self._current_key_index = 0
        self._clients: Dict[str, Any] = {}
        self._load_keys()
    
    def _load_keys_from_db(self) -> List[str]:
        """Load API keys from database settings"""
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
            settings_db = client["torpedo_settings"]
            app_settings = settings_db["app_settings"]
            
            stored = app_settings.find_one({"_id": "app_config"})
            if stored and stored.get("gemini_api_keys"):
                keys_str = stored["gemini_api_keys"]
                return [k.strip() for k in keys_str.split(",") if k.strip()]
        except Exception as e:
            logger.debug(f"Could not fetch Gemini keys from DB: {e}")
        return []
    
    def _load_keys(self):
        """Load API keys from database settings first, then environment variables"""
        keys = []
        
        # Try database first
        db_keys = self._load_keys_from_db()
        if db_keys:
            keys.extend(db_keys)
            logger.info(f"✅ Loaded {len(db_keys)} Gemini API key(s) from database")
        
        # Check for comma-separated keys in env
        multi_keys = os.getenv("GEMINI_API_KEYS", "")
        if multi_keys:
            env_keys = [k.strip() for k in multi_keys.split(",") if k.strip() and k.strip() not in keys]
            keys.extend(env_keys)
        
        # Check for numbered keys (GEMINI_API_KEY_1 through GEMINI_API_KEY_20)
        for i in range(1, 21):
            key = os.getenv(f"GEMINI_API_KEY_{i}", "")
            if key and key not in keys:
                keys.append(key)
        
        # Fallback to single key
        single_key = os.getenv("GEMINI_API_KEY", "")
        if single_key and single_key not in keys:
            keys.append(single_key)
        
        # Also check GOOGLE_API_KEY (common alternative)
        google_key = os.getenv("GOOGLE_API_KEY", "")
        if google_key and google_key not in keys:
            keys.append(google_key)
        
        self._keys = keys
        
        # Initialize stats for each key
        for i, key in enumerate(keys):
            key_id = f"key_{i+1}"
            self._key_stats[key] = ApiKeyStats(key_id=key_id)
        
        if keys:
            logger.info(f"✅ Loaded {len(keys)} Gemini API key(s)")
        else:
            logger.warning("⚠️ No Gemini API keys found. Set GEMINI_API_KEY or GEMINI_API_KEYS env var.")
    
    def _reset_minute_counters(self, key: str):
        """Reset per-minute counters if a minute has passed"""
        stats = self._key_stats.get(key)
        if not stats:
            return
        
        now = datetime.utcnow()
        if (now - stats.last_minute_reset).total_seconds() >= 60:
            stats.requests_this_minute = 0
            stats.tokens_this_minute = 0
            stats.last_minute_reset = now
    
    def _reset_day_counters(self, key: str):
        """Reset per-day counters if a day has passed"""
        stats = self._key_stats.get(key)
        if not stats:
            return
        
        now = datetime.utcnow()
        if (now - stats.last_day_reset).total_seconds() >= 86400:
            stats.requests_today = 0
            stats.last_day_reset = now
            stats.is_exhausted = False
            stats.exhausted_until = None
    
    def _is_key_available(self, key: str) -> Tuple[bool, str]:
        """Check if a key is available for use"""
        stats = self._key_stats.get(key)
        if not stats:
            return False, "Key not found"
        
        self._reset_minute_counters(key)
        self._reset_day_counters(key)
        
        # Check if exhausted and waiting for reset
        if stats.is_exhausted:
            if stats.exhausted_until and datetime.utcnow() < stats.exhausted_until:
                return False, f"Key exhausted until {stats.exhausted_until}"
            stats.is_exhausted = False
        
        # Check daily limit
        if stats.requests_today >= SAFE_RPD:
            stats.is_exhausted = True
            stats.exhausted_until = stats.last_day_reset + timedelta(days=1)
            return False, f"Daily limit reached ({stats.requests_today}/{SAFE_RPD})"
        
        # Check per-minute limit
        if stats.requests_this_minute >= SAFE_RPM:
            return False, f"Minute limit reached ({stats.requests_this_minute}/{SAFE_RPM})"
        
        return True, "Available"
    
    def get_available_key(self) -> Tuple[Optional[str], str]:
        """Get the next available API key with round-robin rotation"""
        with self._lock:
            if not self._keys:
                return None, "No API keys configured"
            
            # Try each key starting from current index
            for _ in range(len(self._keys)):
                key = self._keys[self._current_key_index]
                available, reason = self._is_key_available(key)
                
                if available:
                    return key, reason
                
                # Move to next key
                self._current_key_index = (self._current_key_index + 1) % len(self._keys)
            
            return None, "All API keys exhausted or rate limited"
    
    def record_usage(self, key: str, tokens: int = 0, success: bool = True):
        """Record API usage for a key"""
        with self._lock:
            stats = self._key_stats.get(key)
            if not stats:
                return
            
            stats.last_request_time = datetime.utcnow()
            stats.requests_today += 1
            stats.requests_this_minute += 1
            stats.tokens_this_minute += tokens
            stats.total_requests += 1
            stats.total_tokens += tokens
            
            if not success:
                stats.errors += 1
            
            # Rotate to next key after each request to distribute load
            self._current_key_index = (self._current_key_index + 1) % len(self._keys)
    
    def mark_key_exhausted(self, key: str, duration_seconds: int = 60):
        """Mark a key as temporarily exhausted (e.g., after rate limit error)"""
        with self._lock:
            stats = self._key_stats.get(key)
            if stats:
                stats.is_exhausted = True
                stats.exhausted_until = datetime.utcnow() + timedelta(seconds=duration_seconds)
    
    def get_client(self, key: str):
        """Get or create a Gemini client for a key"""
        if not GEMINI_AVAILABLE:
            raise RuntimeError("Google Generative AI library not installed. Run: pip install google-generativeai")
        
        if key not in self._clients:
            client = genai.Client(api_key=key)
            self._clients[key] = client
        
        return self._clients[key]
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all API keys"""
        status = {
            "total_keys": len(self._keys),
            "available_keys": 0,
            "keys": []
        }
        
        for key in self._keys:
            stats = self._key_stats.get(key)
            if not stats:
                continue
            
            self._reset_minute_counters(key)
            self._reset_day_counters(key)
            
            available, reason = self._is_key_available(key)
            if available:
                status["available_keys"] += 1
            
            status["keys"].append({
                "key_id": stats.key_id,
                "key_preview": f"{key[:8]}...{key[-4:]}",
                "available": available,
                "reason": reason,
                "requests_today": stats.requests_today,
                "requests_this_minute": stats.requests_this_minute,
                "total_requests": stats.total_requests,
                "total_tokens": stats.total_tokens,
                "errors": stats.errors,
                "is_exhausted": stats.is_exhausted
            })
        
        return status
    
    @property
    def key_count(self) -> int:
        """Return number of configured keys"""
        return len(self._keys)


# Global key manager instance
_key_manager: Optional[GeminiKeyManager] = None


def get_key_manager() -> GeminiKeyManager:
    """Get the global key manager instance"""
    global _key_manager
    if _key_manager is None:
        _key_manager = GeminiKeyManager()
    return _key_manager


# ============== MONGODB TOKEN LOGGING ==============

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')

def _get_log_collection():
    """Get MongoDB collection for token logging"""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        db = client['torpedo_gmail']
        return db['gemini_usage_logs']
    except Exception as e:
        logger.warning(f"Could not connect to MongoDB for logging: {e}")
        return None


def log_gemini_usage(
    key_id: str,
    model: str,
    endpoint: str,
    source: str,
    input_tokens: int,
    output_tokens: int,
    success: bool,
    latency_ms: int,
    error_message: Optional[str] = None
):
    """Log Gemini API usage to MongoDB"""
    try:
        collection = _get_log_collection()
        if collection is None:
            return
        
        log_entry = {
            "key_id": key_id,
            "model": model,
            "endpoint": endpoint,
            "source": source,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "success": success,
            "latency_ms": latency_ms,
            "error_message": error_message,
            "cost_usd": 0.0,  # Free tier
            "timestamp": datetime.utcnow()
        }
        
        collection.insert_one(log_entry)
    except Exception as e:
        logger.warning(f"Failed to log Gemini usage: {e}")


# ============== MAIN API FUNCTION ==============

def gemini_generate(
    prompt: str,
    system_instruction: Optional[str] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    max_output_tokens: int = 500,
    temperature: float = 0.3,
    response_format: str = "json",  # "json" or "text"
    source: str = "background",
    endpoint: str = "general",
    retries: int = MAX_RETRIES
) -> Dict[str, Any]:
    """
    Generate content using Gemini API with automatic key rotation.
    
    Args:
        prompt: The user prompt
        system_instruction: Optional system instruction
        model: Gemini model to use
        max_output_tokens: Maximum tokens in response
        temperature: Creativity (0.0-1.0)
        response_format: "json" or "text"
        source: Request source for logging
        endpoint: Endpoint name for logging
        retries: Number of retries on failure
    
    Returns:
        Dict with:
        - success: bool
        - content: str (response text)
        - parsed: dict (if JSON format)
        - tokens: dict with input/output counts
        - error: str (if failed)
    """
    if not GEMINI_AVAILABLE:
        return {
            "success": False,
            "content": "",
            "error": "Google Generative AI library not installed",
            "tokens": {"input": 0, "output": 0}
        }
    
    key_manager = get_key_manager()
    
    if key_manager.key_count == 0:
        return {
            "success": False,
            "content": "",
            "error": "No Gemini API keys configured",
            "tokens": {"input": 0, "output": 0}
        }
    
    last_error = None
    
    for attempt in range(retries):
        # Get an available key
        api_key, availability_reason = key_manager.get_available_key()
        
        if not api_key:
            last_error = f"No available API keys: {availability_reason}"
            # Wait before retry if all keys are minute-limited
            if "Minute limit" in availability_reason:
                time.sleep(5)
                continue
            break
        
        start_time = time.time()
        
        try:
            client = key_manager.get_client(api_key)
            stats = key_manager._key_stats.get(api_key)
            key_id = stats.key_id if stats else "unknown"
            
            # Build generation config
            generation_config = {
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            }
            
            # Add JSON response format if requested
            if response_format == "json":
                generation_config["response_mime_type"] = "application/json"
            
            # Build the full prompt
            contents = prompt
            if system_instruction:
                contents = f"{system_instruction}\n\n{prompt}"
            
            # Make the API call
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=generation_config
            )
            
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Extract token counts (estimate if not provided)
            input_tokens = len(prompt.split()) * 1.3  # Rough estimate
            output_tokens = len(response.text.split()) * 1.3 if response.text else 0
            
            # Try to get actual token counts from response
            if hasattr(response, 'usage_metadata'):
                if hasattr(response.usage_metadata, 'prompt_token_count'):
                    input_tokens = response.usage_metadata.prompt_token_count
                if hasattr(response.usage_metadata, 'candidates_token_count'):
                    output_tokens = response.usage_metadata.candidates_token_count
            
            total_tokens = int(input_tokens + output_tokens)
            
            # Record successful usage
            key_manager.record_usage(api_key, tokens=total_tokens, success=True)
            
            # Log to MongoDB
            log_gemini_usage(
                key_id=key_id,
                model=model,
                endpoint=endpoint,
                source=source,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                success=True,
                latency_ms=latency_ms
            )
            
            # Parse JSON if requested
            content = response.text or ""
            parsed = None
            
            if response_format == "json" and content:
                try:
                    # Handle markdown code blocks
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    
                    parsed = json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON response: {e}")
                    # Return text anyway
                    parsed = None
            
            return {
                "success": True,
                "content": content,
                "parsed": parsed,
                "tokens": {
                    "input": int(input_tokens),
                    "output": int(output_tokens),
                    "total": total_tokens
                },
                "key_id": key_id,
                "model": model
            }
        
        except Exception as e:
            error_str = str(e)
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Record failed usage
            key_manager.record_usage(api_key, tokens=0, success=False)
            
            # Check for rate limit errors
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                logger.warning(f"Rate limit hit on {key_manager._key_stats.get(api_key).key_id}: {e}")
                key_manager.mark_key_exhausted(api_key, duration_seconds=60)
                last_error = f"Rate limited: {e}"
                continue
            
            # Log error
            stats = key_manager._key_stats.get(api_key)
            key_id = stats.key_id if stats else "unknown"
            
            log_gemini_usage(
                key_id=key_id,
                model=model,
                endpoint=endpoint,
                source=source,
                input_tokens=0,
                output_tokens=0,
                success=False,
                latency_ms=latency_ms,
                error_message=str(e)[:500]
            )
            
            last_error = str(e)
            
            # Exponential backoff for other errors
            if attempt < retries - 1:
                delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                time.sleep(delay)
    
    return {
        "success": False,
        "content": "",
        "parsed": None,
        "error": last_error or "Unknown error",
        "tokens": {"input": 0, "output": 0, "total": 0}
    }


# ============== CONVENIENCE FUNCTIONS ==============

def gemini_classify_email(
    subject: str,
    body: str,
    from_email: str,
    to_email: str = "",
    source: str = "background"
) -> Dict[str, Any]:
    """
    Classify an email using Gemini (convenience wrapper).
    Uses minimal tokens for cost efficiency.
    """
    system_prompt = """You are an email classifier. Analyze the email and output JSON only.

Categories:
- client: Inbound emails from prospects/customers seeking services or products
- vendor: From suppliers, service providers, partners
- internal: Same company domain, team communications  
- promotional: Marketing emails, newsletters, sales pitches
- invoice: Billing, payments, invoices
- banking: Bank communications, statements
- automated: Auto-replies, notifications, system emails
- spam: Junk mail, scams
- others: Cannot determine

Output format:
{"category": "<category>", "confidence": 0.0-1.0, "is_sales_lead": true/false, "lead_info": {"full_name": "", "first_name": "", "last_name": "", "email": "", "website": "", "domain": ""}}

If is_sales_lead is true, extract lead_info from the email signature and content."""
    
    # Truncate body for efficiency
    body_preview = body[:800] if body else ""
    
    user_prompt = f"""From: {from_email or '-'}
To: {to_email or '-'}
Subject: {subject or '-'}
Body:
{body_preview}

Classify this email and extract lead info if it's a potential sales lead."""
    
    return gemini_generate(
        prompt=user_prompt,
        system_instruction=system_prompt,
        model=GEMINI_FLASH_MODEL,
        max_output_tokens=300,
        temperature=0.1,
        response_format="json",
        source=source,
        endpoint="email_classify"
    )


def gemini_extract_lead(
    email_content: str,
    sender_email: str,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Extract lead information from an email using Gemini.
    For emails identified as potential sales leads.
    """
    system_prompt = """Extract lead information from this email. Look for:
1. Contact name in signature, greeting, or email
2. Company information
3. Website/domain from signature or email domain
4. Any other useful business info

Output JSON:
{
    "full_name": "Full name if found",
    "first_name": "First name",
    "last_name": "Last name", 
    "email": "Email address",
    "title": "Job title if found",
    "company_name": "Company name if found",
    "website": "Website URL if found",
    "domain": "Domain (extracted from email or website)",
    "phone": "Phone number if found",
    "linkedin_url": "LinkedIn URL if found",
    "confidence": 0.0-1.0
}

Only include fields you can confidently extract. Use empty string for unknown fields."""
    
    return gemini_generate(
        prompt=f"Email from: {sender_email}\n\nContent:\n{email_content[:1500]}",
        system_instruction=system_prompt,
        model=GEMINI_FLASH_MODEL,
        max_output_tokens=400,
        temperature=0.2,
        response_format="json",
        source=source,
        endpoint="lead_extract"
    )


def get_gemini_status() -> Dict[str, Any]:
    """Get status of Gemini API keys and usage"""
    key_manager = get_key_manager()
    status = key_manager.get_status()
    status["gemini_available"] = GEMINI_AVAILABLE
    status["default_model"] = DEFAULT_GEMINI_MODEL
    return status


# ============== BATCH PROCESSING ==============

def gemini_batch_classify(
    emails: List[Dict[str, str]],
    source: str = "background",
    delay_between_requests: float = 4.5  # Stay under 15 RPM
) -> List[Dict[str, Any]]:
    """
    Batch classify multiple emails with rate limiting.
    
    Args:
        emails: List of dicts with 'subject', 'body', 'from_email', 'to_email'
        source: Request source for logging
        delay_between_requests: Seconds to wait between requests
    
    Returns:
        List of classification results
    """
    results = []
    
    for i, email in enumerate(emails):
        result = gemini_classify_email(
            subject=email.get("subject", ""),
            body=email.get("body", ""),
            from_email=email.get("from_email", ""),
            to_email=email.get("to_email", ""),
            source=source
        )
        
        results.append({
            "index": i,
            "email_id": email.get("email_id"),
            "result": result
        })
        
        # Rate limit delay (except for last request)
        if i < len(emails) - 1:
            time.sleep(delay_between_requests)
    
    return results
