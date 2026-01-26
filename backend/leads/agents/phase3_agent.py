"""
Phase 3 Agent: Email Pattern Discovery + Company Cache Intelligence
====================================================================

This agent handles:
1. Email Pattern Discovery - Analyzes mail_pool to discover email formats per domain
2. Company Cache Intelligence - Caches company data with 90-day TTL

Tasks:
- Scan mail_pool for unprocessed emails
- Extract domains and discover email patterns (firstname.lastname, etc.)
- Calculate pattern confidence scores
- Cache company intelligence with automatic expiration
- Track cache hit rates and performance
"""

import os
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from .base_agent import BaseAgent, AgentResult, AgentStatus, AgentRegistry

logger = logging.getLogger(__name__)


@AgentRegistry.register
class Phase3Agent(BaseAgent):
    """
    Phase 3 Agent: Email Pattern Discovery + Company Cache
    
    Capabilities:
    - Discovers email format patterns from mail_pool
    - Predicts email addresses for new contacts
    - Caches company enrichment data (90-day TTL)
    - Tracks cache performance metrics
    """
    
    def __init__(self):
        super().__init__(name="Phase3_PatternCache", phase=3)
        
        # Default configuration
        self.config = {
            "min_samples_for_pattern": 3,
            "max_emails_per_batch": 1000,
            "cache_ttl_days": 90,
            "confidence_threshold": 0.5,
            "skip_generic_domains": True,
            "generic_domains": [
                "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                "icloud.com", "aol.com", "live.com", "msn.com"
            ]
        }
    
    def get_description(self) -> str:
        return """Phase 3 Agent: Email Pattern Discovery + Company Cache
        
        - Analyzes emails to discover company email patterns
        - Predicts email addresses: firstname.lastname@company.com
        - Caches company intelligence with 90-day TTL
        - Tracks cache hit rates for optimization"""
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Phase 3 tasks:
        1. Discover email patterns from mail_pool
        2. Update company cache with new data
        3. Clean expired cache entries
        """
        self.log_info("Starting Phase 3 execution...")
        
        results = {
            "pattern_discovery": {},
            "company_cache": {},
            "cleanup": {}
        }
        
        # Task 1: Email Pattern Discovery
        try:
            pattern_results = await self._discover_email_patterns(input_data)
            results["pattern_discovery"] = pattern_results
            self.add_metric("patterns_discovered", pattern_results.get("new_patterns", 0))
        except Exception as e:
            self.log_error(f"Pattern discovery failed: {e}")
            results["pattern_discovery"] = {"error": str(e)}
        
        # Task 2: Company Cache Management
        try:
            if input_data.get("companies_to_cache"):
                cache_results = await self._cache_companies(input_data["companies_to_cache"])
                results["company_cache"] = cache_results
                self.add_metric("companies_cached", cache_results.get("cached", 0))
        except Exception as e:
            self.log_error(f"Company caching failed: {e}")
            results["company_cache"] = {"error": str(e)}
        
        # Task 3: Cleanup expired entries
        try:
            cleanup_results = await self._cleanup_expired()
            results["cleanup"] = cleanup_results
            self.add_metric("expired_cleaned", cleanup_results.get("removed", 0))
        except Exception as e:
            self.log_error(f"Cleanup failed: {e}")
            results["cleanup"] = {"error": str(e)}
        
        # Calculate totals
        self.add_metric("records_processed", 
            results["pattern_discovery"].get("emails_analyzed", 0) +
            results["company_cache"].get("cached", 0)
        )
        self.add_metric("records_success",
            results["pattern_discovery"].get("new_patterns", 0) +
            results["company_cache"].get("cached", 0)
        )
        
        return results
    
    async def _discover_email_patterns(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Discover email patterns from mail_pool.
        Groups emails by domain and identifies common formats.
        """
        self.log_info("Starting email pattern discovery...")
        
        # Get collections
        mail_pool = self.gmail_db['mail_pool']
        patterns_collection = self.db['email_patterns']
        
        # Find unprocessed emails
        limit = input_data.get("limit", self.config["max_emails_per_batch"])
        
        query = {"processed_for_patterns": {"$ne": True}}
        if self.config["skip_generic_domains"]:
            # Exclude generic email domains
            generic_pattern = "|".join(self.config["generic_domains"])
            query["from_email"] = {"$not": {"$regex": f"@({generic_pattern})$", "$options": "i"}}
        
        emails = list(mail_pool.find(query).limit(limit))
        
        if not emails:
            self.log_info("No new emails to process for patterns")
            return {"emails_analyzed": 0, "new_patterns": 0, "updated_patterns": 0}
        
        self.log_info(f"Analyzing {len(emails)} emails for patterns...")
        
        # Group emails by domain
        domain_emails: Dict[str, List[Dict]] = defaultdict(list)
        
        for email in emails:
            from_email = email.get("from_email", "")
            if "@" in from_email:
                domain = from_email.split("@")[-1].lower()
                domain_emails[domain].append({
                    "email": from_email.lower(),
                    "name": email.get("from_name", "")
                })
        
        # Discover patterns per domain
        new_patterns = 0
        updated_patterns = 0
        
        for domain, senders in domain_emails.items():
            if len(senders) < self.config["min_samples_for_pattern"]:
                continue
            
            # Analyze pattern
            pattern_info = self._analyze_domain_pattern(domain, senders)
            
            if pattern_info and pattern_info["confidence"] >= self.config["confidence_threshold"]:
                # Check if pattern exists
                existing = patterns_collection.find_one({"domain": domain})
                
                if existing:
                    # Update existing pattern
                    patterns_collection.update_one(
                        {"domain": domain},
                        {
                            "$set": {
                                "pattern": pattern_info["pattern"],
                                "confidence": pattern_info["confidence"],
                                "sample_count": pattern_info["sample_count"],
                                "sample_emails": pattern_info["samples"][:5],
                                "updated_at": datetime.utcnow(),
                                "version": existing.get("version", 0) + 1
                            }
                        }
                    )
                    updated_patterns += 1
                else:
                    # Insert new pattern
                    patterns_collection.insert_one({
                        "domain": domain,
                        "pattern": pattern_info["pattern"],
                        "confidence": pattern_info["confidence"],
                        "sample_count": pattern_info["sample_count"],
                        "sample_emails": pattern_info["samples"][:5],
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "version": 1
                    })
                    new_patterns += 1
        
        # Mark emails as processed
        email_ids = [e["_id"] for e in emails]
        mail_pool.update_many(
            {"_id": {"$in": email_ids}},
            {"$set": {"processed_for_patterns": True, "pattern_processed_at": datetime.utcnow()}}
        )
        
        self.log_info(f"Pattern discovery complete: {new_patterns} new, {updated_patterns} updated")
        
        return {
            "emails_analyzed": len(emails),
            "domains_analyzed": len(domain_emails),
            "new_patterns": new_patterns,
            "updated_patterns": updated_patterns
        }
    
    def _analyze_domain_pattern(self, domain: str, senders: List[Dict]) -> Optional[Dict[str, Any]]:
        """
        Analyze email addresses to discover the pattern for a domain.
        
        Common patterns:
        - firstname.lastname@domain.com
        - firstnamelastname@domain.com
        - firstname_lastname@domain.com
        - firstname@domain.com
        - f.lastname@domain.com
        - flastname@domain.com
        """
        patterns_found = defaultdict(int)
        
        for sender in senders:
            email = sender["email"]
            name = sender.get("name", "")
            
            local_part = email.split("@")[0].lower()
            
            # Detect pattern type
            if "." in local_part and len(local_part.split(".")) == 2:
                parts = local_part.split(".")
                if len(parts[0]) > 1 and len(parts[1]) > 1:
                    patterns_found["firstname.lastname"] += 1
                elif len(parts[0]) == 1:
                    patterns_found["f.lastname"] += 1
            elif "_" in local_part:
                patterns_found["firstname_lastname"] += 1
            elif local_part.isalpha() and len(local_part) > 3:
                # Could be firstnamelastname or just firstname
                if len(local_part) > 10:
                    patterns_found["firstnamelastname"] += 1
                else:
                    patterns_found["firstname"] += 1
            else:
                patterns_found["other"] += 1
        
        if not patterns_found:
            return None
        
        # Get most common pattern
        best_pattern = max(patterns_found, key=patterns_found.get)
        pattern_count = patterns_found[best_pattern]
        total = sum(patterns_found.values())
        
        # Calculate confidence
        confidence = min(pattern_count / max(total, 1), 1.0)
        # Boost confidence with more samples
        sample_boost = min(len(senders) / 10.0, 0.3)
        confidence = min(confidence + sample_boost, 1.0)
        
        return {
            "pattern": best_pattern,
            "confidence": round(confidence, 3),
            "sample_count": len(senders),
            "samples": [s["email"] for s in senders[:5]]
        }
    
    async def _cache_companies(self, companies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Cache company data with 90-day TTL.
        """
        self.log_info(f"Caching {len(companies)} companies...")
        
        cache_collection = self.db['company_cache']
        
        cached = 0
        updated = 0
        errors = 0
        
        ttl_days = self.config["cache_ttl_days"]
        expires_at = datetime.utcnow() + timedelta(days=ttl_days)
        
        for company in companies:
            try:
                domain = company.get("domain", "").lower()
                if not domain:
                    continue
                
                cache_doc = {
                    "domain": domain,
                    "company_name": company.get("company_name", ""),
                    "employees": company.get("employees"),
                    "revenue": company.get("revenue"),
                    "industry": company.get("industry"),
                    "founded": company.get("founded"),
                    "headquarters": company.get("headquarters"),
                    "description": company.get("description"),
                    "linkedin_url": company.get("linkedin_url"),
                    "website": company.get("website"),
                    "expires_at": expires_at,
                    "cached_at": datetime.utcnow(),
                    "cache_hit_count": 0
                }
                
                result = cache_collection.update_one(
                    {"domain": domain},
                    {"$set": cache_doc, "$inc": {"version": 1}},
                    upsert=True
                )
                
                if result.upserted_id:
                    cached += 1
                else:
                    updated += 1
                    
            except Exception as e:
                self.log_warning(f"Failed to cache company {company.get('domain')}: {e}")
                errors += 1
        
        self.log_info(f"Company cache: {cached} new, {updated} updated, {errors} errors")
        
        return {
            "cached": cached,
            "updated": updated,
            "errors": errors
        }
    
    async def _cleanup_expired(self) -> Dict[str, Any]:
        """
        Remove expired cache entries.
        """
        self.log_info("Cleaning up expired cache entries...")
        
        cache_collection = self.db['company_cache']
        patterns_collection = self.db['email_patterns']
        
        now = datetime.utcnow()
        
        # Clean expired company cache
        company_result = cache_collection.delete_many({
            "expires_at": {"$lt": now}
        })
        
        # Clean old patterns (older than 180 days without updates)
        cutoff = now - timedelta(days=180)
        pattern_result = patterns_collection.delete_many({
            "updated_at": {"$lt": cutoff},
            "sample_count": {"$lt": 5}  # Low confidence patterns
        })
        
        self.log_info(f"Cleanup: {company_result.deleted_count} companies, {pattern_result.deleted_count} patterns removed")
        
        return {
            "companies_removed": company_result.deleted_count,
            "patterns_removed": pattern_result.deleted_count,
            "removed": company_result.deleted_count + pattern_result.deleted_count
        }
    
    async def lookup_company(self, domain: str) -> Optional[Dict[str, Any]]:
        """
        Look up company in cache.
        Increments hit counter on success.
        """
        cache_collection = self.db['company_cache']
        
        company = cache_collection.find_one_and_update(
            {"domain": domain.lower(), "expires_at": {"$gt": datetime.utcnow()}},
            {
                "$inc": {"cache_hit_count": 1},
                "$set": {"last_accessed": datetime.utcnow()}
            },
            return_document=True
        )
        
        if company:
            company.pop("_id", None)
            return company
        return None
    
    async def predict_email(self, domain: str, first_name: str, last_name: str) -> Optional[Dict[str, Any]]:
        """
        Predict email address based on discovered pattern.
        """
        patterns_collection = self.db['email_patterns']
        
        pattern = patterns_collection.find_one({"domain": domain.lower()})
        
        if not pattern:
            return None
        
        first = first_name.lower().strip()
        last = last_name.lower().strip()
        pattern_type = pattern["pattern"]
        
        # Generate email based on pattern
        if pattern_type == "firstname.lastname":
            predicted = f"{first}.{last}@{domain}"
        elif pattern_type == "firstnamelastname":
            predicted = f"{first}{last}@{domain}"
        elif pattern_type == "firstname_lastname":
            predicted = f"{first}_{last}@{domain}"
        elif pattern_type == "firstname":
            predicted = f"{first}@{domain}"
        elif pattern_type == "f.lastname":
            predicted = f"{first[0]}.{last}@{domain}"
        elif pattern_type == "flastname":
            predicted = f"{first[0]}{last}@{domain}"
        else:
            predicted = f"{first}.{last}@{domain}"  # Default
        
        return {
            "predicted_email": predicted,
            "pattern": pattern_type,
            "confidence": pattern["confidence"],
            "sample_count": pattern["sample_count"]
        }
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get Phase 3 statistics.
        """
        patterns_collection = self.db['email_patterns']
        cache_collection = self.db['company_cache']
        
        now = datetime.utcnow()
        
        # Pattern stats
        total_patterns = patterns_collection.count_documents({})
        high_confidence = patterns_collection.count_documents({"confidence": {"$gte": 0.8}})
        
        # Cache stats
        total_cached = cache_collection.count_documents({})
        active_cached = cache_collection.count_documents({"expires_at": {"$gt": now}})
        
        # Hit rate
        pipeline = [
            {"$group": {
                "_id": None,
                "total_hits": {"$sum": "$cache_hit_count"},
                "avg_hits": {"$avg": "$cache_hit_count"}
            }}
        ]
        hit_stats = list(cache_collection.aggregate(pipeline))
        
        return {
            "patterns": {
                "total": total_patterns,
                "high_confidence": high_confidence,
                "high_confidence_pct": round(high_confidence / max(total_patterns, 1) * 100, 1)
            },
            "cache": {
                "total": total_cached,
                "active": active_cached,
                "expired": total_cached - active_cached,
                "total_hits": hit_stats[0]["total_hits"] if hit_stats else 0,
                "avg_hits": round(hit_stats[0]["avg_hits"], 2) if hit_stats else 0
            }
        }
