"""
AGENT 6 — QUALITY, SECURITY & COST OPTIMIZATION
Middleware and validation utilities
"""

import time
import hashlib
from functools import wraps
from typing import Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict


# ============== RATE LIMITING ==============

class RateLimiter:
    """
    Token bucket rate limiter for AI API calls.
    Prevents excessive OpenAI API usage.
    """
    
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, key: str = "default") -> bool:
        """Check if a request is allowed"""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.window_seconds)
        
        # Clean old requests
        self.requests[key] = [
            req_time for req_time in self.requests[key]
            if req_time > window_start
        ]
        
        # Check limit
        if len(self.requests[key]) >= self.max_requests:
            return False
        
        # Record this request
        self.requests[key].append(now)
        return True
    
    def wait_time(self, key: str = "default") -> float:
        """Get seconds to wait before next allowed request"""
        if self.is_allowed(key):
            return 0.0
        
        if not self.requests[key]:
            return 0.0
        
        oldest = min(self.requests[key])
        wait = (oldest + timedelta(seconds=self.window_seconds) - datetime.utcnow()).total_seconds()
        return max(0.0, wait)


# Global rate limiter for AI calls
ai_rate_limiter = RateLimiter(max_requests=50, window_seconds=60)


# ============== REQUEST DEDUPLICATION ==============

class RequestDeduplicator:
    """
    Prevent duplicate processing of the same lead.
    Uses in-memory cache with TTL.
    """
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self.cache = {}
    
    def get_key(self, linkedin_url: str) -> str:
        """Generate cache key"""
        return hashlib.md5(linkedin_url.encode()).hexdigest()
    
    def is_duplicate(self, linkedin_url: str) -> bool:
        """Check if this request is a duplicate"""
        key = self.get_key(linkedin_url)
        now = datetime.utcnow()
        
        if key in self.cache:
            cached_time = self.cache[key]
            if (now - cached_time).total_seconds() < self.ttl_seconds:
                return True
        
        return False
    
    def mark_processed(self, linkedin_url: str):
        """Mark a lead as being processed"""
        key = self.get_key(linkedin_url)
        self.cache[key] = datetime.utcnow()
    
    def cleanup(self):
        """Remove expired entries"""
        now = datetime.utcnow()
        expired = [
            key for key, time in self.cache.items()
            if (now - time).total_seconds() > self.ttl_seconds
        ]
        for key in expired:
            del self.cache[key]


# Global deduplicator
request_deduplicator = RequestDeduplicator(ttl_seconds=300)


# ============== VALIDATION UTILITIES ==============

def validate_linkedin_url(url: str) -> bool:
    """Validate LinkedIn URL format"""
    if not url:
        return False
    
    valid_prefixes = [
        "https://www.linkedin.com/in/",
        "https://linkedin.com/in/",
        "http://www.linkedin.com/in/",
        "http://linkedin.com/in/",
        "www.linkedin.com/in/",
        "linkedin.com/in/"
    ]
    
    return any(url.lower().startswith(prefix) for prefix in valid_prefixes)


def sanitize_lead_input(name: str, title: str, snippet: str) -> tuple:
    """Sanitize lead input to prevent injection"""
    # Basic sanitization
    name = name.strip()[:200] if name else ""
    title = title.strip()[:300] if title else ""
    snippet = snippet.strip()[:2000] if snippet else ""
    
    # Remove potential prompt injection patterns
    dangerous_patterns = [
        "ignore previous",
        "disregard above",
        "forget everything",
        "new instructions",
        "system:",
        "assistant:",
        "```"
    ]
    
    for pattern in dangerous_patterns:
        name = name.replace(pattern, "")
        title = title.replace(pattern, "")
        snippet = snippet.replace(pattern, "")
    
    return name, title, snippet


# ============== CONFIDENCE VALIDATION ==============

def is_low_confidence(confidence_score: float, threshold: float = 0.5) -> bool:
    """Check if classification has low confidence"""
    return confidence_score < threshold


def requires_manual_review(confidence_score: float, threshold: float = 0.4) -> bool:
    """Check if lead requires manual review"""
    return confidence_score < threshold


# ============== COST TRACKING ==============

class CostTracker:
    """Track AI API costs"""
    
    def __init__(self):
        self.total_cost = 0.0
        self.daily_costs = defaultdict(float)
        self.request_count = 0
    
    def add_cost(self, cost: float):
        """Record a cost"""
        self.total_cost += cost
        today = datetime.utcnow().strftime("%Y-%m-%d")
        self.daily_costs[today] += cost
        self.request_count += 1
    
    def get_daily_cost(self, date: str = None) -> float:
        """Get cost for a specific day"""
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        return self.daily_costs.get(date, 0.0)
    
    def get_stats(self) -> dict:
        """Get cost statistics"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        return {
            "total_cost_usd": round(self.total_cost, 4),
            "today_cost_usd": round(self.daily_costs.get(today, 0.0), 4),
            "total_requests": self.request_count,
            "avg_cost_per_request": round(self.total_cost / max(1, self.request_count), 6)
        }


# Global cost tracker
cost_tracker = CostTracker()


# ============== RETRY WITH BACKOFF ==============

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retry with exponential backoff"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


# ============== LOGGING UTILITIES ==============

def log_classification_event(
    event_type: str,
    lead_id: str,
    details: dict = None,
    error: str = None
):
    """Structured logging for classification events"""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "lead_id": lead_id,
        "details": details or {},
        "error": error
    }
    
    # In production, this would go to a proper logging system
    print(f"[LEAD_CLASSIFICATION] {log_entry}")
    
    return log_entry
