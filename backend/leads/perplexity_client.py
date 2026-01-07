"""
PERPLEXITY DISCOVERY CLIENT (Phase 3)
AI-powered market research for lead discovery planning.

IMPORTANT: Use Perplexity ONLY for discovery/research, NOT for:
- Direct LinkedIn URL sourcing (will hallucinate URLs)
- Batch lead generation (use Google CSE for verification)

Good use cases:
- Market mapping ("List 20 fintech startups in Bangalore")
- Role discovery ("What job titles report to VP Sales?")
- Company research ("Who are competitors of Stripe?")
- Industry insights ("What are trends in healthcare SaaS?")

Cost: ~$5/1000 requests (sonar), ~$20/1000 (sonar-pro)
"""

import os
import json
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Settings
_settings_db = client['torpedo_settings']
_app_settings = _settings_db['app_settings']

# Discovery cache (24h TTL for market research)
discovery_cache = db['discovery_cache']

try:
    discovery_cache.create_index("query_hash", unique=True)
    discovery_cache.create_index("created_at", expireAfterSeconds=24 * 60 * 60)
    discovery_cache.create_index("query_type")
except:
    pass

# Usage tracking
perplexity_usage = db['perplexity_usage_logs']
try:
    perplexity_usage.create_index("timestamp")
    perplexity_usage.create_index([("query_type", 1), ("timestamp", -1)])
except:
    pass


# ============== CONFIGURATION ==============

# Perplexity models
SONAR_MODEL = "sonar"  # $5/1000 requests - fast, good for simple queries
SONAR_PRO_MODEL = "sonar-pro"  # $20/1000 requests - better for complex research

# Cost per request
MODEL_COSTS = {
    "sonar": 0.005,  # $5/1000
    "sonar-pro": 0.02,  # $20/1000
}

# Rate limits (configurable in settings)
DEFAULT_HOURLY_LIMIT = 50
DEFAULT_DAILY_LIMIT = 200


# ============== API KEY MANAGEMENT ==============

def get_perplexity_api_key() -> Optional[str]:
    """Get Perplexity API key from database or environment"""
    try:
        stored = _app_settings.find_one({"_id": "app_config"})
        if stored and stored.get("perplexity_api_key"):
            return stored["perplexity_api_key"]
    except Exception:
        pass
    
    return os.getenv("PERPLEXITY_API_KEY")


def is_perplexity_enabled() -> bool:
    """Check if Perplexity is enabled and configured"""
    api_key = get_perplexity_api_key()
    
    if not api_key:
        return False
    
    try:
        settings = _app_settings.find_one({"_id": "app_config"})
        if settings and settings.get("perplexity_enabled") is False:
            return False
    except:
        pass
    
    return True


def get_perplexity_settings() -> Dict[str, Any]:
    """Get Perplexity-related settings"""
    try:
        settings = _app_settings.find_one({"_id": "app_config"}) or {}
        return {
            "enabled": settings.get("perplexity_enabled", True),
            "hourly_limit": settings.get("perplexity_hourly_limit", DEFAULT_HOURLY_LIMIT),
            "daily_limit": settings.get("perplexity_daily_limit", DEFAULT_DAILY_LIMIT),
            "default_model": settings.get("perplexity_default_model", SONAR_MODEL),
        }
    except:
        return {
            "enabled": True,
            "hourly_limit": DEFAULT_HOURLY_LIMIT,
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "default_model": SONAR_MODEL,
        }


# ============== RATE LIMITING ==============

def check_rate_limit() -> tuple[bool, str]:
    """Check if we're within rate limits. Returns (allowed, message)"""
    settings = get_perplexity_settings()
    
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Count recent requests
    hourly_count = perplexity_usage.count_documents({
        "timestamp": {"$gte": hour_ago}
    })
    
    daily_count = perplexity_usage.count_documents({
        "timestamp": {"$gte": day_start}
    })
    
    if hourly_count >= settings["hourly_limit"]:
        return False, f"Hourly limit reached ({hourly_count}/{settings['hourly_limit']})"
    
    if daily_count >= settings["daily_limit"]:
        return False, f"Daily limit reached ({daily_count}/{settings['daily_limit']})"
    
    return True, "OK"


def log_usage(query_type: str, model: str, success: bool, error: str = ""):
    """Log Perplexity API usage"""
    perplexity_usage.insert_one({
        "timestamp": datetime.utcnow(),
        "query_type": query_type,
        "model": model,
        "cost_usd": MODEL_COSTS.get(model, 0.005),
        "success": success,
        "error": error
    })


# ============== CACHING ==============

def get_discovery_cache_key(query: str, query_type: str) -> str:
    """Generate cache key for discovery query"""
    content = f"{query_type}:{query.lower().strip()}"
    return hashlib.sha256(content.encode()).hexdigest()


def get_cached_discovery(query: str, query_type: str) -> Optional[Dict]:
    """Check cache for previous discovery result"""
    cache_key = get_discovery_cache_key(query, query_type)
    
    cached = discovery_cache.find_one({
        "query_hash": cache_key,
        "created_at": {"$gt": datetime.utcnow() - timedelta(hours=24)}
    })
    
    if cached:
        return cached.get("result")
    return None


def cache_discovery(query: str, query_type: str, result: Dict):
    """Cache discovery result"""
    cache_key = get_discovery_cache_key(query, query_type)
    
    discovery_cache.replace_one(
        {"query_hash": cache_key},
        {
            "query_hash": cache_key,
            "query": query,
            "query_type": query_type,
            "result": result,
            "created_at": datetime.utcnow()
        },
        upsert=True
    )


# ============== API CALLS ==============

async def perplexity_query(
    query: str,
    query_type: str = "general",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Make a query to Perplexity API.
    
    Args:
        query: The query/question to ask
        query_type: Type of query for logging (market_map, role_discovery, etc.)
        model: Model to use (sonar or sonar-pro)
        system_prompt: Optional system prompt override
        use_cache: Whether to use cached results
        
    Returns:
        Dict with {success, content, citations, error}
    """
    # Check cache first
    if use_cache:
        cached = get_cached_discovery(query, query_type)
        if cached:
            return {
                "success": True,
                "content": cached.get("content", ""),
                "citations": cached.get("citations", []),
                "from_cache": True
            }
    
    # Check if enabled
    if not is_perplexity_enabled():
        return {
            "success": False,
            "error": "Perplexity not configured. Set PERPLEXITY_API_KEY in environment or settings."
        }
    
    # Check rate limits
    allowed, message = check_rate_limit()
    if not allowed:
        return {
            "success": False,
            "error": f"Rate limit: {message}"
        }
    
    # Get settings and API key
    settings = get_perplexity_settings()
    api_key = get_perplexity_api_key()
    model = model or settings["default_model"]
    
    # Default system prompt for discovery
    if not system_prompt:
        system_prompt = """You are a B2B market research assistant. 
Provide accurate, factual information with specific details.
When listing companies or people, include relevant details like location, size, and industry.
Always cite your sources when possible."""
    
    # Make API call
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "max_tokens": 1000,
        "temperature": 0.2,  # Lower for factual responses
        "return_citations": True
    }
    
    try:
        response = requests.post(
            url, 
            headers=headers, 
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            error_msg = f"API error: {response.status_code}"
            try:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", error_msg)
            except:
                pass
            
            log_usage(query_type, model, False, error_msg)
            return {"success": False, "error": error_msg}
        
        data = response.json()
        
        # Extract content and citations
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = data.get("citations", [])
        
        # Log usage
        log_usage(query_type, model, True)
        
        # Cache result
        result = {
            "content": content,
            "citations": citations
        }
        cache_discovery(query, query_type, result)
        
        return {
            "success": True,
            "content": content,
            "citations": citations,
            "model": model,
            "from_cache": False
        }
            
    except requests.exceptions.Timeout:
        log_usage(query_type, model, False, "Timeout")
        return {"success": False, "error": "Request timeout"}
    except Exception as e:
        log_usage(query_type, model, False, str(e))
        return {"success": False, "error": str(e)}


# Synchronous wrapper for compatibility
def perplexity_query_sync(
    query: str,
    query_type: str = "general",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """Synchronous wrapper for perplexity_query"""
    import asyncio
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        perplexity_query(query, query_type, model, system_prompt, use_cache)
    )


# ============== DISCOVERY FUNCTIONS ==============

async def discover_companies(
    industry: str,
    location: str = "",
    count: int = 20,
    criteria: str = ""
) -> Dict[str, Any]:
    """
    Discover companies in a specific industry/location.
    
    Args:
        industry: Industry to search (e.g., "fintech", "healthtech")
        location: Geographic focus (e.g., "India", "Silicon Valley")
        count: Number of companies to find
        criteria: Additional criteria (e.g., "funded startups", "enterprise")
        
    Returns:
        Dict with list of companies and metadata
    """
    query = f"List {count} {criteria} {industry} companies"
    if location:
        query += f" in {location}"
    query += ". For each, provide: company name, description, approximate size, and headquarters location."
    
    result = await perplexity_query(
        query=query,
        query_type="company_discovery",
        model=SONAR_MODEL
    )
    
    return result


async def discover_roles(
    base_role: str,
    industry: str = ""
) -> Dict[str, Any]:
    """
    Discover related job titles and roles.
    
    Args:
        base_role: Starting role (e.g., "VP Sales")
        industry: Optional industry context
        
    Returns:
        Dict with related roles and hierarchy
    """
    query = f"What job titles are similar to or report to {base_role}"
    if industry:
        query += f" in the {industry} industry"
    query += "? List specific titles used on LinkedIn profiles."
    
    result = await perplexity_query(
        query=query,
        query_type="role_discovery",
        model=SONAR_MODEL
    )
    
    return result


async def discover_market_insights(
    topic: str,
    focus: str = ""
) -> Dict[str, Any]:
    """
    Get market insights for targeting decisions.
    
    Args:
        topic: Market topic (e.g., "B2B SaaS sales", "healthcare IT")
        focus: Specific focus area
        
    Returns:
        Dict with market insights
    """
    query = f"What are the current trends in {topic}"
    if focus:
        query += f", specifically regarding {focus}"
    query += "? Include key companies and decision-maker roles."
    
    result = await perplexity_query(
        query=query,
        query_type="market_insights",
        model=SONAR_MODEL
    )
    
    return result


async def research_company(domain: str) -> Dict[str, Any]:
    """
    Research a specific company by domain.
    NOTE: Use this instead of web scraping for company info.
    
    Args:
        domain: Company domain (e.g., "stripe.com")
        
    Returns:
        Dict with company information
    """
    query = f"""Research the company at {domain}. Provide:
1. Official company name
2. Industry/sector
3. Approximate employee count
4. Headquarters location
5. Key products/services
6. Recent news or developments
7. Main competitors"""
    
    result = await perplexity_query(
        query=query,
        query_type="company_research",
        model=SONAR_PRO_MODEL  # Use pro for detailed research
    )
    
    return result


# ============== USAGE STATS ==============

def get_perplexity_usage_stats(days: int = 7) -> Dict[str, Any]:
    """Get Perplexity API usage statistics"""
    since = datetime.utcnow() - timedelta(days=days)
    
    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {
            "_id": {"query_type": "$query_type", "model": "$model"},
            "count": {"$sum": 1},
            "total_cost": {"$sum": "$cost_usd"},
            "success_count": {"$sum": {"$cond": ["$success", 1, 0]}}
        }},
        {"$sort": {"count": -1}}
    ]
    
    results = list(perplexity_usage.aggregate(pipeline))
    
    total_requests = sum(r["count"] for r in results)
    total_cost = sum(r["total_cost"] for r in results)
    total_success = sum(r["success_count"] for r in results)
    
    return {
        "period_days": days,
        "total_requests": total_requests,
        "total_cost_usd": round(total_cost, 2),
        "success_rate": round(total_success / total_requests, 2) if total_requests > 0 else 0,
        "by_type": {
            f"{r['_id']['query_type']}_{r['_id']['model']}": {
                "count": r["count"],
                "cost": round(r["total_cost"], 2)
            }
            for r in results
        }
    }


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    import sys
    import asyncio
    
    async def main():
        if len(sys.argv) < 2:
            print("Perplexity Discovery Client")
            print("\nUsage:")
            print("  python perplexity_client.py companies <industry> [location]")
            print("  python perplexity_client.py roles <base_role> [industry]")
            print("  python perplexity_client.py research <domain>")
            print("  python perplexity_client.py stats")
            print("\nExamples:")
            print("  python perplexity_client.py companies 'fintech' 'India'")
            print("  python perplexity_client.py roles 'VP Sales' 'SaaS'")
            print("  python perplexity_client.py research 'stripe.com'")
            return
        
        command = sys.argv[1]
        
        if command == "companies":
            industry = sys.argv[2] if len(sys.argv) > 2 else "technology"
            location = sys.argv[3] if len(sys.argv) > 3 else ""
            
            print(f"\nDiscovering {industry} companies in {location or 'Global'}...")
            result = await discover_companies(industry, location)
            
            if result["success"]:
                print(f"\n{result['content']}")
                if result.get("citations"):
                    print(f"\nSources: {', '.join(result['citations'][:3])}")
            else:
                print(f"\nError: {result['error']}")
        
        elif command == "roles":
            base_role = sys.argv[2] if len(sys.argv) > 2 else "VP Sales"
            industry = sys.argv[3] if len(sys.argv) > 3 else ""
            
            print(f"\nDiscovering roles similar to {base_role}...")
            result = await discover_roles(base_role, industry)
            
            if result["success"]:
                print(f"\n{result['content']}")
            else:
                print(f"\nError: {result['error']}")
        
        elif command == "research":
            domain = sys.argv[2] if len(sys.argv) > 2 else "stripe.com"
            
            print(f"\nResearching {domain}...")
            result = await research_company(domain)
            
            if result["success"]:
                print(f"\n{result['content']}")
            else:
                print(f"\nError: {result['error']}")
        
        elif command == "stats":
            stats = get_perplexity_usage_stats()
            print(f"\n=== Perplexity Usage (Last {stats['period_days']} Days) ===")
            print(f"  Total Requests: {stats['total_requests']}")
            print(f"  Total Cost:     ${stats['total_cost_usd']}")
            print(f"  Success Rate:   {stats['success_rate']:.0%}")
        
        else:
            print(f"Unknown command: {command}")
    
    asyncio.run(main())
