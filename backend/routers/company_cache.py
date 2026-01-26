"""
Company Cache Lookup Router
Provides fast lookup of company intelligence with automatic caching
Reduces API calls through 90-day TTL caching
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/company-cache",
    tags=["company-cache"]
)

# MongoDB connections
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# Databases
email_db = mongo_client["email_automation"]

# Collections
company_cache_collection = email_db["company_cache"]
company_enrichment_logs_collection = email_db["company_enrichment_logs"]


# ============== MODELS ==============

class CompanyLookupRequest(BaseModel):
    """Request to lookup/cache company data"""
    company_name: Optional[str] = None
    domain: Optional[str] = None
    linkedin_url: Optional[str] = None


class CompanyCacheResponse(BaseModel):
    """Cached company data"""
    company_name: str
    domain: Optional[str]
    employees: Optional[int]
    revenue: Optional[str]
    industry: Optional[str]
    founded: Optional[int]
    type: Optional[str]
    headquarters: Optional[str]
    description: Optional[str]
    funding_raised: Optional[str]
    last_funding_round: Optional[str]
    website: Optional[str]
    linkedin: Optional[str]
    crunchbase: Optional[str]


# ============== UTILITY FUNCTIONS ==============

def ensure_indexes():
    """Create necessary indexes for fast lookups"""
    try:
        # Lookup indexes
        company_cache_collection.create_index([("domain", 1)])
        company_cache_collection.create_index([("company_name", 1)])
        company_cache_collection.create_index([("linkedin_url", 1)])
        
        # TTL index - automatically remove expired documents
        company_cache_collection.create_index(
            [("expires_at", 1)],
            expireAfterSeconds=0
        )
        
        # Query efficiency
        company_cache_collection.create_index([("cache_hit_count", -1)])
        company_cache_collection.create_index([("last_accessed", -1)])
        
        logger.info("Indexes ensured for company_cache")
    except Exception as e:
        logger.warning(f"Failed to create indexes: {e}")


ensure_indexes()


# ============== ENDPOINTS ==============

@router.post("/lookup", summary="Lookup company data with caching")
async def lookup_company(request: CompanyLookupRequest) -> Dict:
    """
    Lookup company data from cache
    Automatically caches data for 90 days
    Returns hit rate and cache age
    """
    try:
        if not request.domain and not request.company_name and not request.linkedin_url:
            raise HTTPException(
                status_code=400,
                detail="Must provide domain, company_name, or linkedin_url"
            )
        
        # Build query
        query = {}
        if request.domain:
            query["domain"] = request.domain.lower()
        if request.company_name:
            query["company_name"] = {"$regex": request.company_name, "$options": "i"}
        if request.linkedin_url:
            query["linkedin_url"] = request.linkedin_url
        
        # Try to find in cache
        cached = company_cache_collection.find_one(query)
        
        if cached:
            # Hit! Update access info
            age_hours = (datetime.utcnow() - cached.get("created_at", datetime.utcnow())).total_seconds() / 3600
            
            company_cache_collection.update_one(
                {"_id": cached["_id"]},
                {
                    "$inc": {"cache_hit_count": 1},
                    "$set": {"last_accessed": datetime.utcnow()}
                }
            )
            
            return {
                "found": True,
                "source": "cache",
                "cache_age_hours": round(age_hours, 1),
                "cache_hits": cached.get("cache_hit_count", 0) + 1,
                "expires_in_days": round(
                    (cached.get("expires_at", datetime.utcnow()) - datetime.utcnow()).total_seconds() / 86400,
                    1
                ),
                "company": {
                    "name": cached.get("company_name"),
                    "domain": cached.get("domain"),
                    "employees": cached.get("employees"),
                    "revenue": cached.get("revenue"),
                    "industry": cached.get("industry"),
                    "founded": cached.get("founded"),
                    "type": cached.get("type"),
                    "headquarters": cached.get("headquarters"),
                    "description": cached.get("description"),
                    "funding_raised": cached.get("funding_raised"),
                    "last_funding_round": cached.get("last_funding_round"),
                    "website": cached.get("website"),
                    "linkedin": cached.get("linkedin_url"),
                    "crunchbase": cached.get("crunchbase_url")
                }
            }
        
        # Cache miss - return indicator
        return {
            "found": False,
            "source": "not_cached",
            "message": "Company data not in cache. Use /company-cache/enrich to add it.",
            "lookup_params": {
                "domain": request.domain,
                "company_name": request.company_name,
                "linkedin_url": request.linkedin_url
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in lookup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enrich", summary="Enrich and cache company data")
async def enrich_company(data: Dict) -> Dict:
    """
    Add or update company data in cache
    Automatically sets 90-day expiration
    """
    try:
        company_name = data.get("company_name") or data.get("name")
        domain = (data.get("domain") or "").lower()
        
        if not company_name:
            raise HTTPException(status_code=400, detail="company_name required")
        
        # Prepare cache document
        expires_at = datetime.utcnow() + timedelta(days=90)
        
        cache_doc = {
            "company_name": company_name,
            "domain": domain if domain else None,
            "employees": data.get("employees"),
            "revenue": data.get("revenue"),
            "industry": data.get("industry"),
            "founded": data.get("founded"),
            "type": data.get("type"),
            "headquarters": data.get("headquarters"),
            "description": data.get("description"),
            "funding_raised": data.get("funding_raised"),
            "last_funding_round": data.get("last_funding_round"),
            "website": data.get("website"),
            "linkedin_url": data.get("linkedin_url") or data.get("linkedin"),
            "crunchbase_url": data.get("crunchbase_url") or data.get("crunchbase"),
            "created_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
            "expires_at": expires_at,
            "cache_hit_count": 0,
            "enriched_by": data.get("enriched_by", "manual"),
            "metadata": {
                "source_tool": data.get("source_tool"),
                "confidence": data.get("confidence", 0.7),
                "notes": data.get("notes")
            }
        }
        
        # Upsert - update if exists, insert if not
        result = company_cache_collection.update_one(
            {"company_name": company_name, "domain": domain} if domain else {"company_name": company_name},
            {"$set": cache_doc},
            upsert=True
        )
        
        # Log enrichment
        company_enrichment_logs_collection.insert_one({
            "company_name": company_name,
            "domain": domain,
            "timestamp": datetime.utcnow(),
            "action": "enrich_and_cache",
            "enriched_by": data.get("enriched_by", "manual"),
            "updated_existing": result.matched_count > 0
        })
        
        return {
            "success": True,
            "company_name": company_name,
            "domain": domain,
            "cached": True,
            "expires_at": expires_at.isoformat(),
            "message": f"Company data cached for 90 days",
            "is_update": result.matched_count > 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in enrich: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", summary="Get cache statistics")
async def get_cache_stats() -> Dict:
    """Get company cache hit rates and performance metrics"""
    try:
        total_cached = company_cache_collection.count_documents({})
        
        # Get hit statistics
        hit_stats = list(company_cache_collection.aggregate([
            {
                "$group": {
                    "_id": None,
                    "total_hits": {"$sum": "$cache_hit_count"},
                    "avg_hits": {"$avg": "$cache_hit_count"},
                    "max_hits": {"$max": "$cache_hit_count"}
                }
            }
        ]))
        
        # Get expired documents count
        expired = company_cache_collection.count_documents(
            {"expires_at": {"$lt": datetime.utcnow()}}
        )
        
        # Get recently accessed
        recent = company_cache_collection.count_documents(
            {"last_accessed": {"$gte": datetime.utcnow() - timedelta(days=7)}}
        )
        
        if hit_stats:
            stats = hit_stats[0]
            hit_rate = (stats.get("total_hits", 0) / total_cached) if total_cached > 0 else 0
        else:
            hit_rate = 0
            stats = {"total_hits": 0, "avg_hits": 0, "max_hits": 0}
        
        return {
            "total_cached": total_cached,
            "expired_entries": expired,
            "active_entries": total_cached - expired,
            "recently_accessed": recent,
            "total_cache_hits": stats.get("total_hits", 0),
            "avg_hits_per_company": round(stats.get("avg_hits", 0), 1),
            "max_hits": stats.get("max_hits", 0),
            "overall_hit_rate": round(hit_rate, 2),
            "hit_rate_percent": round(hit_rate * 100, 1),
            "cache_effectiveness": {
                "note": "Higher hit rate = better cache effectiveness",
                "excellent": hit_rate >= 0.7,
                "good": 0.5 <= hit_rate < 0.7,
                "fair": 0.3 <= hit_rate < 0.5,
                "poor": hit_rate < 0.3
            }
        }
    except Exception as e:
        logger.error(f"Error fetching cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance", summary="Get cache performance metrics")
async def get_performance(days: int = Query(30, ge=1, le=365)) -> Dict:
    """
    Get cache performance over time
    - Hit rate trends
    - Most accessed companies
    - Cache turnover rate
    """
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get most accessed companies
        most_accessed = list(company_cache_collection.aggregate([
            {
                "$match": {
                    "last_accessed": {"$gte": cutoff_date}
                }
            },
            {
                "$sort": {"cache_hit_count": -1}
            },
            {
                "$limit": 20
            },
            {
                "$project": {
                    "company_name": 1,
                    "domain": 1,
                    "cache_hit_count": 1,
                    "last_accessed": 1
                }
            }
        ]))
        
        # Get enrichment logs for period
        logs = list(company_enrichment_logs_collection.find(
            {"timestamp": {"$gte": cutoff_date}}
        ).sort("timestamp", -1))
        
        # Calculate metrics
        total_enrichments = len(logs)
        updates = sum(1 for log in logs if log.get("updated_existing"))
        new_entries = total_enrichments - updates
        
        return {
            "period_days": days,
            "total_enrichments": total_enrichments,
            "new_entries": new_entries,
            "updated_entries": updates,
            "most_accessed_companies": [
                {
                    "name": company.get("company_name"),
                    "domain": company.get("domain"),
                    "cache_hits": company.get("cache_hit_count", 0),
                    "last_accessed": company.get("last_accessed", datetime.utcnow()).isoformat()
                }
                for company in most_accessed
            ],
            "enrichment_rate": round(total_enrichments / days, 1) if days > 0 else 0,
            "turnover_rate": "Active cache - regularly updated" if total_enrichments > 0 else "No recent activity"
        }
    except Exception as e:
        logger.error(f"Error fetching performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear-expired", summary="Clear expired cache entries")
async def clear_expired() -> Dict:
    """Remove all expired cache entries (older than 90 days)"""
    try:
        result = company_cache_collection.delete_many(
            {"expires_at": {"$lt": datetime.utcnow()}}
        )
        
        return {
            "success": True,
            "deleted_count": result.deleted_count,
            "message": f"Removed {result.deleted_count} expired entries"
        }
    except Exception as e:
        logger.error(f"Error clearing expired: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", summary="List cached companies")
async def list_cached(
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str = Query("cache_hit_count", enum=["cache_hit_count", "created_at", "last_accessed"])
) -> Dict:
    """List all cached companies with stats"""
    try:
        sort_order = -1 if sort_by in ["cache_hit_count", "last_accessed"] else 1
        
        companies = list(company_cache_collection.find(
            {"expires_at": {"$gte": datetime.utcnow()}}
        ).sort(sort_by, sort_order).limit(limit))
        
        return {
            "total": len(companies),
            "companies": [
                {
                    "name": c.get("company_name"),
                    "domain": c.get("domain"),
                    "industry": c.get("industry"),
                    "employees": c.get("employees"),
                    "cache_hits": c.get("cache_hit_count", 0),
                    "created_at": c.get("created_at", datetime.utcnow()).isoformat(),
                    "last_accessed": c.get("last_accessed", datetime.utcnow()).isoformat(),
                    "expires_at": c.get("expires_at", datetime.utcnow()).isoformat()
                }
                for c in companies
            ]
        }
    except Exception as e:
        logger.error(f"Error listing cached: {e}")
        raise HTTPException(status_code=500, detail=str(e))
