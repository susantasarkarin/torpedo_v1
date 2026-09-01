"""
URL VALIDATION MODULE (Phase 4)
Validates LinkedIn URLs before enrichment to save API costs.

Problem:
- AI-generated URLs may be hallucinated (2-3% error rate)
- Enriching invalid URLs wastes OpenAI API costs
- Bad leads pollute CRM and hurt deliverability

Solution:
- HTTP HEAD check before enrichment
- Cache validation results (1 week TTL)
- Skip invalid URLs, log for review
"""

import os
import asyncio
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from pymongo import MongoClient
from dotenv import load_dotenv


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    from database import get_client
    return get_client()


load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
client = _get_pooled_client()
db = client['email_automation']

# URL validation cache (7 day TTL)
url_validation_cache = db['url_validation_cache']
url_validation_logs = db['url_validation_logs']

try:
    url_validation_cache.create_index("url_hash", unique=True)
    url_validation_cache.create_index("validated_at", expireAfterSeconds=7 * 24 * 60 * 60)
    url_validation_cache.create_index("is_valid")
    
    url_validation_logs.create_index("validated_at")
    url_validation_logs.create_index([("is_valid", 1), ("validated_at", -1)])
except Exception:
    pass


# ============== CONFIGURATION ==============

# Common user agents for requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Timeout for validation requests
VALIDATION_TIMEOUT = 10.0

# Batch size for concurrent validation
VALIDATION_BATCH_SIZE = 10

# Rate limit delay between batches
VALIDATION_BATCH_DELAY = 1.0


# ============== VALIDATION FUNCTIONS ==============

def get_url_hash(url: str) -> str:
    """Generate hash for URL caching"""
    normalized = url.lower().strip().rstrip('/')
    return hashlib.sha256(normalized.encode()).hexdigest()


def get_cached_validation(url: str) -> Optional[bool]:
    """Check if URL has been validated before"""
    url_hash = get_url_hash(url)
    
    cached = url_validation_cache.find_one({
        "url_hash": url_hash,
        "validated_at": {"$gt": datetime.utcnow() - timedelta(days=7)}
    })
    
    if cached:
        return cached.get("is_valid")
    return None


def cache_validation(url: str, is_valid: bool, status_code: int = 0, error: str = ""):
    """Cache URL validation result"""
    url_hash = get_url_hash(url)
    
    url_validation_cache.replace_one(
        {"url_hash": url_hash},
        {
            "url_hash": url_hash,
            "url": url,
            "is_valid": is_valid,
            "status_code": status_code,
            "error": error,
            "validated_at": datetime.utcnow()
        },
        upsert=True
    )


def log_validation(url: str, is_valid: bool, status_code: int, error: str = "", source: str = ""):
    """Log validation attempt for analytics"""
    url_validation_logs.insert_one({
        "url": url,
        "is_valid": is_valid,
        "status_code": status_code,
        "error": error,
        "source": source,
        "validated_at": datetime.utcnow()
    })


async def validate_linkedin_url(
    url: str,
    use_cache: bool = True,
    source: str = ""
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate a LinkedIn URL by checking if it returns a valid response.
    
    Args:
        url: LinkedIn profile URL to validate
        use_cache: Whether to use cached results
        source: Source for logging (e.g., "google_cse", "csv_import")
        
    Returns:
        Tuple of (is_valid, metadata_dict)
    """
    # Basic format check
    if not url or "linkedin.com/in/" not in url.lower():
        return False, {"error": "Invalid LinkedIn URL format", "status_code": 0}
    
    # Check cache
    if use_cache:
        cached = get_cached_validation(url)
        if cached is not None:
            return cached, {"from_cache": True}
    
    # Make HEAD request to validate
    import random
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        response = requests.head(
            url,
            headers=headers,
            timeout=VALIDATION_TIMEOUT,
            allow_redirects=True
        )
        
        status_code = response.status_code
        
        # Valid responses: 200, 302 (redirect to login), 303
        # Invalid: 404, 410 (gone), 403 (blocked)
        is_valid = status_code in [200, 301, 302, 303, 307, 308]
        
        # 404 is definitively invalid
        if status_code == 404:
            is_valid = False
        
        # Cache result
        cache_validation(url, is_valid, status_code)
        
        # Log
        log_validation(url, is_valid, status_code, source=source)
        
        return is_valid, {
            "status_code": status_code,
            "from_cache": False
        }
            
    except requests.exceptions.Timeout:
        # Timeout - assume valid (don't block on slow responses)
        cache_validation(url, True, 0, "Timeout")
        return True, {"error": "Timeout", "status_code": 0}
        
    except requests.exceptions.RequestException as e:
        # Connection error - assume valid (network issue)
        return True, {"error": str(e), "status_code": 0}
        
    except Exception as e:
        return True, {"error": str(e), "status_code": 0}


async def validate_urls_batch(
    urls: List[str],
    source: str = ""
) -> Dict[str, Tuple[bool, Dict]]:
    """
    Validate multiple URLs concurrently.
    
    Args:
        urls: List of URLs to validate
        source: Source for logging
        
    Returns:
        Dict mapping URL to (is_valid, metadata)
    """
    results = {}
    
    # Process in batches to avoid overwhelming
    for i in range(0, len(urls), VALIDATION_BATCH_SIZE):
        batch = urls[i:i + VALIDATION_BATCH_SIZE]
        
        # Validate concurrently
        tasks = [validate_linkedin_url(url, source=source) for url in batch]
        batch_results = await asyncio.gather(*tasks)
        
        for url, result in zip(batch, batch_results):
            results[url] = result
        
        # Rate limit between batches
        if i + VALIDATION_BATCH_SIZE < len(urls):
            await asyncio.sleep(VALIDATION_BATCH_DELAY)
    
    return results


def validate_url_sync(url: str, source: str = "") -> Tuple[bool, Dict]:
    """Synchronous wrapper for URL validation"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(validate_linkedin_url(url, source=source))


def validate_urls_batch_sync(urls: List[str], source: str = "") -> Dict[str, Tuple[bool, Dict]]:
    """Synchronous wrapper for batch URL validation"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(validate_urls_batch(urls, source=source))


# ============== LEAD FILTERING ==============

async def filter_valid_leads(
    leads: List[Dict],
    url_field: str = "linkedin_url"
) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter leads to only those with valid LinkedIn URLs.
    
    Args:
        leads: List of lead dicts
        url_field: Field name containing LinkedIn URL
        
    Returns:
        Tuple of (valid_leads, invalid_leads)
    """
    if not leads:
        return [], []
    
    # Extract URLs
    urls = [lead.get(url_field, "") for lead in leads]
    
    # Validate
    validation_results = await validate_urls_batch(urls, source="lead_filter")
    
    valid_leads = []
    invalid_leads = []
    
    for lead in leads:
        url = lead.get(url_field, "")
        is_valid, _ = validation_results.get(url, (False, {}))
        
        if is_valid:
            valid_leads.append(lead)
        else:
            lead["_validation_failed"] = True
            invalid_leads.append(lead)
    
    return valid_leads, invalid_leads


# ============== STATS ==============

def get_validation_stats(days: int = 7) -> Dict[str, Any]:
    """Get URL validation statistics"""
    since = datetime.utcnow() - timedelta(days=days)
    
    pipeline = [
        {"$match": {"validated_at": {"$gte": since}}},
        {"$group": {
            "_id": "$is_valid",
            "count": {"$sum": 1}
        }}
    ]
    
    results = list(url_validation_logs.aggregate(pipeline))
    
    valid_count = 0
    invalid_count = 0
    
    for r in results:
        if r["_id"]:
            valid_count = r["count"]
        else:
            invalid_count = r["count"]
    
    total = valid_count + invalid_count
    
    # Status code breakdown
    status_pipeline = [
        {"$match": {"validated_at": {"$gte": since}}},
        {"$group": {
            "_id": "$status_code",
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    
    status_results = list(url_validation_logs.aggregate(status_pipeline))
    
    return {
        "period_days": days,
        "total_validated": total,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "valid_rate": round(valid_count / total, 3) if total > 0 else 0,
        "invalid_rate": round(invalid_count / total, 3) if total > 0 else 0,
        "cache_size": url_validation_cache.count_documents({}),
        "status_breakdown": {str(r["_id"]): r["count"] for r in status_results}
    }


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    import sys
    
    async def main():
        if len(sys.argv) < 2:
            print("URL Validation Module")
            print("\nUsage:")
            print("  python url_validator.py <linkedin_url>")
            print("  python url_validator.py stats")
            print("\nExample:")
            print("  python url_validator.py https://linkedin.com/in/johndoe")
            return
        
        if sys.argv[1] == "stats":
            stats = get_validation_stats()
            print(f"\n=== URL Validation Stats (Last {stats['period_days']} Days) ===")
            print(f"  Total Validated:  {stats['total_validated']}")
            print(f"  Valid URLs:       {stats['valid_count']} ({stats['valid_rate']:.1%})")
            print(f"  Invalid URLs:     {stats['invalid_count']} ({stats['invalid_rate']:.1%})")
            print(f"  Cache Size:       {stats['cache_size']}")
            if stats.get("status_breakdown"):
                print(f"\n  Status Codes:")
                for code, count in stats["status_breakdown"].items():
                    print(f"    {code}: {count}")
        else:
            url = sys.argv[1]
            print(f"\nValidating: {url}")
            
            is_valid, metadata = await validate_linkedin_url(url, use_cache=False)
            
            if is_valid:
                print(f"✅ Valid (status: {metadata.get('status_code', 'unknown')})")
            else:
                print(f"❌ Invalid (status: {metadata.get('status_code', 'unknown')})")
                if metadata.get("error"):
                    print(f"   Error: {metadata['error']}")
    
    asyncio.run(main())
