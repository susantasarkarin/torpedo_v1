"""
AI-POWERED QUERY GENERATOR (Phase 2)
Replaces naive micro-queries with smart macro discovery plans.

Benefits:
    - 30-40% fewer Google CSE queries
    - Better search coverage with diverse angles
    - Smarter targeting based on persona/industry combos

Example:
    Before: 35 queries like "CEO fintech Bangalore"
    After:  15 smart queries covering same ground with better coverage
"""

import os

try:
    from app.services.prompt_templates import LINKEDIN_SEARCH_PLAN_PROMPT as SEARCH_PLAN_SYSTEM_PROMPT
except ImportError:
    from ..app.services.prompt_templates import LINKEDIN_SEARCH_PLAN_PROMPT as SEARCH_PLAN_SYSTEM_PROMPT
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Cache for generated search plans
search_plans_cache = db['search_plans_cache']

# Create TTL index (24 hour cache for search plans)
try:
    search_plans_cache.create_index("created_at", expireAfterSeconds=72 * 60 * 60)
    search_plans_cache.create_index("plan_hash", unique=True)
except:
    pass


# SEARCH_PLAN_SYSTEM_PROMPT is imported from app.services.prompt_templates at the top of this file


SEARCH_PLAN_USER_PROMPT = """Generate {count} diverse Google search queries to find:

Target Persona: {persona}
Industry: {industry}
Location: {location}
Additional Context: {context}

Return JSON: {{"queries": ["query1", "query2", ...]}}"""


def generate_search_plan_hash(persona: str, industry: str, location: str) -> str:
    """Generate hash for caching search plans"""
    content = f"{persona.lower()}|{industry.lower()}|{location.lower()}"
    return hashlib.sha256(content.encode()).hexdigest()


def get_cached_search_plan(persona: str, industry: str, location: str) -> Optional[List[str]]:
    """Check if we have a cached search plan"""
    plan_hash = generate_search_plan_hash(persona, industry, location)
    
    cached = search_plans_cache.find_one({
        "plan_hash": plan_hash,
        "created_at": {"$gt": datetime.utcnow() - timedelta(hours=24)}
    })
    
    if cached:
        return cached.get("queries", [])
    return None


def cache_search_plan(persona: str, industry: str, location: str, queries: List[str]):
    """Cache a generated search plan"""
    plan_hash = generate_search_plan_hash(persona, industry, location)
    
    search_plans_cache.replace_one(
        {"plan_hash": plan_hash},
        {
            "plan_hash": plan_hash,
            "persona": persona,
            "industry": industry,
            "location": location,
            "queries": queries,
            "query_count": len(queries),
            "created_at": datetime.utcnow()
        },
        upsert=True
    )


def generate_search_plan(
    persona: str,
    industry: str,
    location: str = "",
    count: int = 15,
    context: str = "",
    use_cache: bool = True
) -> List[str]:
    """
    Generate a smart search plan using AI.
    
    Args:
        persona: Target persona (e.g., "CEO", "VP Sales", "CTO")
        industry: Target industry (e.g., "fintech", "healthcare", "SaaS")
        location: Target location (e.g., "California", "India", "Europe")
        count: Number of queries to generate
        context: Additional context or requirements
        use_cache: Whether to use cached plans
        
    Returns:
        List of search query strings
    """
    # Check cache first
    if use_cache:
        cached = get_cached_search_plan(persona, industry, location)
        if cached:
            print(f"[QueryGen] Using cached plan ({len(cached)} queries)")
            return cached
    
    # Import here to avoid circular dependency
    try:
        from .openai_wrapper import chat_completion, is_ai_disabled
        
        if is_ai_disabled():
            return _generate_fallback_queries(persona, industry, location, count)
        
        user_prompt = SEARCH_PLAN_USER_PROMPT.format(
            count=count,
            persona=persona,
            industry=industry,
            location=location or "Global",
            context=context or "Focus on decision-makers"
        )
        
        result = chat_completion(
            messages=[
                {"role": "system", "content": SEARCH_PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            source="background",
            endpoint="generate_search_plan",
            # Qwen-only policy: no explicit model= here so chat_completion()
            # resolves to its governed default (CHEAP_MODEL = Qwen).
            max_output_tokens=500,
            temperature=0.7,  # Higher for variety
            response_format={"type": "json_object"}
        )
        
        if not result["success"]:
            print(f"[QueryGen] AI failed: {result['error']}, using fallback")
            return _generate_fallback_queries(persona, industry, location, count)
        
        # Parse response
        parsed = json.loads(result["content"])
        queries = parsed.get("queries", [])
        
        if not queries:
            return _generate_fallback_queries(persona, industry, location, count)
        
        # Cache the plan
        cache_search_plan(persona, industry, location, queries)
        
        print(f"[QueryGen] Generated {len(queries)} smart queries")
        return queries
        
    except Exception as e:
        print(f"[QueryGen] Error: {e}, using fallback")
        return _generate_fallback_queries(persona, industry, location, count)


def _generate_fallback_queries(
    persona: str,
    industry: str,
    location: str,
    count: int
) -> List[str]:
    """
    Generate queries without AI (fallback).
    Uses template-based expansion.
    """
    import random
    
    # Title variations
    title_expansions = {
        "ceo": ["CEO", "Chief Executive Officer", "Founder", "Co-Founder", "Owner", "President"],
        "cto": ["CTO", "Chief Technology Officer", "VP Engineering", "Head of Engineering", "Tech Lead"],
        "cfo": ["CFO", "Chief Financial Officer", "VP Finance", "Finance Director", "Controller"],
        "cmo": ["CMO", "Chief Marketing Officer", "VP Marketing", "Head of Marketing", "Marketing Director"],
        "vp sales": ["VP Sales", "Sales Director", "Head of Sales", "Chief Revenue Officer", "Sales VP"],
        "director": ["Director", "Senior Director", "Managing Director", "Associate Director"],
        "manager": ["Manager", "Senior Manager", "Team Lead", "Department Head"],
    }
    
    # Get title variations
    persona_lower = persona.lower()
    titles = title_expansions.get(persona_lower, [persona])
    
    # Industry variations
    industry_terms = [industry]
    if industry.lower() == "technology":
        industry_terms = ["technology", "software", "tech", "IT", "SaaS"]
    elif industry.lower() == "fintech":
        industry_terms = ["fintech", "financial technology", "payments", "banking tech", "finance"]
    elif industry.lower() == "healthcare":
        industry_terms = ["healthcare", "healthtech", "medical", "health tech", "biotech"]
    
    # Build queries
    queries = []
    for _ in range(count):
        title = random.choice(titles)
        ind = random.choice(industry_terms)
        
        query = f'"{title}" {ind}'
        if location:
            query += f" {location}"
        
        queries.append(query)
    
    # Deduplicate
    queries = list(set(queries))
    
    return queries[:count]


def generate_batch_search_plans(
    target_profiles: List[Dict[str, str]],
    queries_per_profile: int = 10
) -> Dict[str, List[str]]:
    """
    Generate search plans for multiple target profiles.
    
    Args:
        target_profiles: List of dicts with {persona, industry, location}
        queries_per_profile: Number of queries per profile
        
    Returns:
        Dict mapping profile key to query list
    """
    plans = {}
    
    for profile in target_profiles:
        persona = profile.get("persona", "")
        industry = profile.get("industry", "")
        location = profile.get("location", "")
        
        if not persona and not industry:
            continue
        
        key = f"{persona}|{industry}|{location}"
        queries = generate_search_plan(
            persona=persona,
            industry=industry,
            location=location,
            count=queries_per_profile
        )
        
        plans[key] = queries
    
    return plans


# ============== QUERY OPTIMIZATION ==============

def optimize_existing_queries(queries: List[str]) -> List[str]:
    """
    Optimize a list of existing queries by deduplicating
    and removing redundant variations.
    """
    # Normalize and deduplicate
    seen = set()
    optimized = []
    
    for query in queries:
        # Normalize: lowercase, remove extra spaces
        normalized = ' '.join(query.lower().split())
        
        # Remove site: prefix for comparison
        comparison = normalized.replace('site:linkedin.com/in/', '').strip()
        
        if comparison not in seen:
            seen.add(comparison)
            optimized.append(query)
    
    return optimized


def estimate_query_savings(
    original_count: int,
    optimized_count: int,
    cost_per_query: float = 0.005  # $5 per 1000 queries
) -> Dict[str, Any]:
    """Calculate estimated savings from query optimization"""
    saved_queries = original_count - optimized_count
    saved_cost = saved_queries * cost_per_query
    
    return {
        "original_queries": original_count,
        "optimized_queries": optimized_count,
        "queries_saved": saved_queries,
        "reduction_percent": round((saved_queries / original_count) * 100, 1) if original_count > 0 else 0,
        "cost_saved_usd": round(saved_cost, 2)
    }


def get_query_generation_stats() -> Dict[str, Any]:
    """Get query generation statistics"""
    try:
        total_plans = search_plans_cache.count_documents({})
        
        # Cache hit rate (from logs if available)
        cache_hits = search_plans_cache.count_documents({"cache_hit": True})
        cache_misses = search_plans_cache.count_documents({"cache_hit": False})
        total = cache_hits + cache_misses
        
        return {
            "total_plans": total_plans,
            "cache_hit_rate": cache_hits / total if total > 0 else 0,
            "fallbacks_used": search_plans_cache.count_documents({"used_fallback": True})
        }
    except Exception as e:
        return {
            "total_plans": 0,
            "cache_hit_rate": 0,
            "fallbacks_used": 0,
            "error": str(e)
        }


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        print("Usage:")
        print("  python query_generator.py <persona> <industry> [location]")
        print("  python query_generator.py 'VP Sales' 'SaaS' 'California'")
        print("\nExample output:")
        queries = generate_search_plan("CEO", "fintech", "India", count=10)
        for i, q in enumerate(queries, 1):
            print(f"  {i}. {q}")
    else:
        persona = sys.argv[1]
        industry = sys.argv[2] if len(sys.argv) > 2 else ""
        location = sys.argv[3] if len(sys.argv) > 3 else ""
        
        print(f"\nGenerating search plan for: {persona} in {industry} ({location or 'Global'})")
        queries = generate_search_plan(persona, industry, location, count=15)
        
        print(f"\n{len(queries)} queries generated:\n")
        for i, q in enumerate(queries, 1):
            print(f"  {i}. {q}")
