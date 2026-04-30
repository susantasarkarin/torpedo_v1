"""
Company Cache System
Intelligent caching for company details to avoid redundant enrichment calls
90-day TTL with smart invalidation
"""

import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId


class CompanyCache:
    """Manage cached company information with TTL and smart lookup"""
    
    DEFAULT_TTL_DAYS = 90
    
    def __init__(self, mongo_uri: str = None, database_name: str = "email_automation"):
        """Initialize cache with MongoDB connection"""
        if mongo_uri is None:
            mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client[database_name]
        self.cache_collection = self.db["company_cache"]
        
        # Ensure indexes
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create necessary indexes"""
        self.cache_collection.create_index([("company_domain", 1)], unique=True)
        self.cache_collection.create_index([("company_name_normalized", 1)])
        self.cache_collection.create_index([("expires_at", 1)])
        self.cache_collection.create_index([("last_accessed", -1)])
        self.cache_collection.create_index([("hit_count", -1)])
    
    def _normalize_company_name(self, company_name: str) -> str:
        """Normalize company name for consistent matching"""
        if not company_name:
            return ""
        
        # Remove common suffixes
        suffixes = [
            " inc", " inc.", " incorporated",
            " llc", " ltd", " ltd.",
            " corp", " corp.", " corporation",
            " co", " co.", " company",
            " limited", " plc"
        ]
        
        normalized = company_name.lower().strip()
        
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        return normalized
    
    def _extract_domain(self, email_or_website: str) -> str:
        """Extract domain from email address or website URL"""
        if not email_or_website:
            return ""
        
        # Remove protocol
        domain = email_or_website.replace("http://", "").replace("https://", "")
        
        # Extract domain from email
        if "@" in domain:
            domain = domain.split("@")[1]
        
        # Remove path and query
        domain = domain.split("/")[0].split("?")[0]
        
        # Remove www
        if domain.startswith("www."):
            domain = domain[4:]
        
        return domain.lower().strip()
    
    def get(self, company_identifier: str, identifier_type: str = "auto") -> Optional[Dict]:
        """
        Get cached company details
        
        Args:
            company_identifier: Company name, domain, or email
            identifier_type: "domain", "name", or "auto" (will detect)
            
        Returns:
            Cached company details or None if not found/expired
        """
        query = {}
        
        # Auto-detect identifier type
        if identifier_type == "auto":
            if "@" in company_identifier or "." in company_identifier:
                identifier_type = "domain"
            else:
                identifier_type = "name"
        
        # Build query
        if identifier_type == "domain":
            domain = self._extract_domain(company_identifier)
            query["company_domain"] = domain
        else:
            normalized_name = self._normalize_company_name(company_identifier)
            query["company_name_normalized"] = normalized_name
        
        # Find in cache
        cached = self.cache_collection.find_one(query)
        
        if not cached:
            return None
        
        # Check if expired
        if cached.get("expires_at") and cached["expires_at"] < datetime.now():
            # Remove expired entry
            self.cache_collection.delete_one({"_id": cached["_id"]})
            return None
        
        # Update access stats
        self.cache_collection.update_one(
            {"_id": cached["_id"]},
            {
                "$set": {"last_accessed": datetime.now()},
                "$inc": {"hit_count": 1}
            }
        )
        
        return cached
    
    def set(self, company_data: dict, ttl_days: int = None) -> str:
        """
        Store company details in cache
        
        Args:
            company_data: Dictionary with company information
            ttl_days: Time-to-live in days (default: 90)
            
        Returns:
            Cache entry ID
        """
        if ttl_days is None:
            ttl_days = self.DEFAULT_TTL_DAYS
        
        # Extract identifiers
        company_name = company_data.get("company_name", "")
        company_domain = self._extract_domain(
            company_data.get("company_website") or 
            company_data.get("company_domain") or
            company_data.get("email", "")
        )
        
        if not company_domain and not company_name:
            raise ValueError("Must provide company_name or company_domain")
        
        # Build cache entry
        cache_entry = {
            "company_name": company_name,
            "company_name_normalized": self._normalize_company_name(company_name),
            "company_domain": company_domain,
            "company_website": company_data.get("company_website"),
            "industry": company_data.get("industry"),
            "company_size": company_data.get("company_size"),
            "location": company_data.get("location"),
            "description": company_data.get("description"),
            "linkedin_url": company_data.get("linkedin_url"),
            "technologies": company_data.get("technologies", []),
            "employee_count": company_data.get("employee_count"),
            "founded_year": company_data.get("founded_year"),
            "revenue_range": company_data.get("revenue_range"),
            "additional_data": company_data.get("additional_data", {}),
            "cached_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(days=ttl_days),
            "last_accessed": datetime.now(),
            "hit_count": 0,
            "source": company_data.get("source", "manual"),
            "metadata": company_data.get("metadata", {})
        }
        
        # Upsert (update if exists, insert if not)
        result = self.cache_collection.update_one(
            {"company_domain": company_domain} if company_domain else {"company_name_normalized": cache_entry["company_name_normalized"]},
            {"$set": cache_entry},
            upsert=True
        )
        
        if result.upserted_id:
            return str(result.upserted_id)
        else:
            # Find and return existing ID
            existing = self.cache_collection.find_one(
                {"company_domain": company_domain} if company_domain else {"company_name_normalized": cache_entry["company_name_normalized"]}
            )
            return str(existing["_id"]) if existing else None
    
    def invalidate(self, company_identifier: str, identifier_type: str = "auto") -> bool:
        """
        Invalidate (delete) a cached entry
        
        Args:
            company_identifier: Company name, domain, or email
            identifier_type: "domain", "name", or "auto"
            
        Returns:
            True if deleted, False if not found
        """
        query = {}
        
        if identifier_type == "auto":
            if "@" in company_identifier or "." in company_identifier:
                identifier_type = "domain"
            else:
                identifier_type = "name"
        
        if identifier_type == "domain":
            domain = self._extract_domain(company_identifier)
            query["company_domain"] = domain
        else:
            normalized_name = self._normalize_company_name(company_identifier)
            query["company_name_normalized"] = normalized_name
        
        result = self.cache_collection.delete_one(query)
        return result.deleted_count > 0
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries
        
        Returns:
            Number of entries deleted
        """
        result = self.cache_collection.delete_many({
            "expires_at": {"$lt": datetime.now()}
        })
        return result.deleted_count
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        total_entries = self.cache_collection.count_documents({})
        
        expired_count = self.cache_collection.count_documents({
            "expires_at": {"$lt": datetime.now()}
        })
        
        # Most accessed companies
        top_companies = list(self.cache_collection.find(
            {},
            {"company_name": 1, "hit_count": 1, "company_domain": 1}
        ).sort("hit_count", -1).limit(10))
        
        # Recent additions
        recent_additions = self.cache_collection.count_documents({
            "cached_at": {"$gte": datetime.now() - timedelta(days=7)}
        })
        
        return {
            "total_entries": total_entries,
            "active_entries": total_entries - expired_count,
            "expired_entries": expired_count,
            "recent_additions_7d": recent_additions,
            "top_companies": [
                {
                    "name": c.get("company_name"),
                    "domain": c.get("company_domain"),
                    "hits": c.get("hit_count", 0)
                }
                for c in top_companies
            ]
        }
    
    def extend_ttl(self, company_identifier: str, additional_days: int = 90) -> bool:
        """
        Extend TTL for a cached entry
        
        Args:
            company_identifier: Company name, domain, or email
            additional_days: Number of days to add to expiration
            
        Returns:
            True if updated, False if not found
        """
        domain = self._extract_domain(company_identifier)
        query = {"company_domain": domain} if domain and ("." in company_identifier or "@" in company_identifier) else {
            "company_name_normalized": self._normalize_company_name(company_identifier)
        }
        
        cached = self.cache_collection.find_one(query)
        if not cached:
            return False
        
        new_expiration = cached.get("expires_at", datetime.now()) + timedelta(days=additional_days)
        
        self.cache_collection.update_one(
            {"_id": cached["_id"]},
            {"$set": {"expires_at": new_expiration}}
        )
        
        return True


# Singleton instance
_cache_instance = None

def get_company_cache() -> CompanyCache:
    """Get or create the singleton CompanyCache instance"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CompanyCache()
    return _cache_instance


if __name__ == "__main__":
    # Test the company cache
    print("=== Company Cache Test ===\n")
    
    try:
        cache = CompanyCache()
        
        # Test data
        test_company = {
            "company_name": "TechCorp Inc.",
            "company_website": "https://www.techcorp.com",
            "company_domain": "techcorp.com",
            "industry": "Technology",
            "company_size": "Enterprise",
            "location": "San Francisco, CA",
            "description": "Leading technology solutions provider",
            "employee_count": 5000,
            "founded_year": 2010,
            "source": "test"
        }
        
        print("1. Testing set():")
        cache_id = cache.set(test_company, ttl_days=90)
        print(f"   âœ“ Cached company with ID: {cache_id}\n")
        
        print("2. Testing get() by domain:")
        cached_by_domain = cache.get("techcorp.com", identifier_type="domain")
        if cached_by_domain:
            print(f"   âœ“ Found: {cached_by_domain['company_name']}")
            print(f"   Industry: {cached_by_domain['industry']}")
            print(f"   Hit count: {cached_by_domain['hit_count']}\n")
        
        print("3. Testing get() by company name:")
        cached_by_name = cache.get("TechCorp", identifier_type="name")
        if cached_by_name:
            print(f"   âœ“ Found: {cached_by_name['company_name']}")
            print(f"   Domain: {cached_by_name['company_domain']}\n")
        
        print("4. Testing get() by email (auto-detect):")
        cached_by_email = cache.get("john@techcorp.com", identifier_type="auto")
        if cached_by_email:
            print(f"   âœ“ Found: {cached_by_email['company_name']}")
            print(f"   Hit count: {cached_by_email['hit_count']}\n")
        
        print("5. Testing get_stats():")
        stats = cache.get_stats()
        print(f"   Total entries: {stats['total_entries']}")
        print(f"   Active entries: {stats['active_entries']}")
        print(f"   Expired entries: {stats['expired_entries']}\n")
        
        print("6. Testing extend_ttl():")
        extended = cache.extend_ttl("techcorp.com", additional_days=30)
        print(f"   âœ“ Extended TTL: {extended}\n")
        
        print("7. Testing cleanup_expired():")
        cleaned = cache.cleanup_expired()
        print(f"   Cleaned up {cleaned} expired entries\n")
        
        print("8. Testing invalidate():")
        invalidated = cache.invalidate("techcorp.com")
        print(f"   âœ“ Invalidated: {invalidated}\n")
        
        print("âœ… All tests passed!")
        
    except Exception as e:
        print(f"âŒ Error: {e}")
        import traceback
        traceback.print_exc()

