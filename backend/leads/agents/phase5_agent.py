"""
Phase 5 Agent: Automated Enrichment Pipeline
=============================================

This agent handles:
1. Automated lead enrichment with company data
2. Contact information enhancement
3. Lead scoring based on enrichment data
4. Pipeline automation triggers

Tasks:
- Process unriched leads automatically
- Enrich with company data from cache or external APIs
- Apply email pattern prediction for contacts
- Calculate lead scores
- Trigger downstream workflows
"""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from .base_agent import BaseAgent, AgentResult, AgentStatus, AgentRegistry

logger = logging.getLogger(__name__)


@AgentRegistry.register
class Phase5Agent(BaseAgent):
    """
    Phase 5 Agent: Automated Enrichment Pipeline
    
    Capabilities:
    - Auto-enriches leads with company data
    - Predicts contact emails using patterns
    - Calculates lead scores
    - Triggers workflow automations
    """
    
    def __init__(self):
        super().__init__(name="Phase5_Enrichment", phase=5)
        
        # Default configuration
        self.config = {
            "batch_size": 50,
            "max_leads_per_run": 500,
            "enable_company_enrichment": True,
            "enable_email_prediction": True,
            "enable_lead_scoring": True,
            "enable_workflow_triggers": True,
            "min_score_for_high_priority": 70,
            "enrichment_sources": ["cache", "linkedin", "clearbit"],
            "score_weights": {
                "company_size": 0.25,
                "industry_match": 0.20,
                "email_verified": 0.15,
                "has_linkedin": 0.15,
                "title_match": 0.15,
                "recency": 0.10
            }
        }
    
    def get_description(self) -> str:
        return """Phase 5 Agent: Automated Enrichment Pipeline
        
        - Automatically enriches leads with company data
        - Predicts emails using discovered patterns
        - Calculates lead scores based on ICP match
        - Triggers workflow automations for high-value leads"""
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Phase 5 enrichment pipeline.
        """
        self.log_info("Starting Phase 5 Automated Enrichment...")
        
        results = {
            "company_enrichment": {},
            "email_prediction": {},
            "lead_scoring": {},
            "workflow_triggers": {},
            "summary": {}
        }
        
        # Get leads to process
        leads = await self._get_unenriched_leads(input_data)
        
        if not leads:
            self.log_info("No leads to enrich")
            return {"message": "No leads to process", "processed": 0}
        
        self.log_info(f"Processing {len(leads)} leads...")
        self.add_metric("records_processed", len(leads))
        
        enriched_leads = leads
        
        # Task 1: Company Enrichment
        if self.config["enable_company_enrichment"]:
            try:
                enriched_leads, company_results = await self._enrich_companies(enriched_leads)
                results["company_enrichment"] = company_results
            except Exception as e:
                self.log_error(f"Company enrichment failed: {e}")
                results["company_enrichment"] = {"error": str(e)}
        
        # Task 2: Email Prediction
        if self.config["enable_email_prediction"]:
            try:
                enriched_leads, email_results = await self._predict_emails(enriched_leads)
                results["email_prediction"] = email_results
            except Exception as e:
                self.log_error(f"Email prediction failed: {e}")
                results["email_prediction"] = {"error": str(e)}
        
        # Task 3: Lead Scoring
        if self.config["enable_lead_scoring"]:
            try:
                enriched_leads, scoring_results = await self._score_leads(enriched_leads)
                results["lead_scoring"] = scoring_results
            except Exception as e:
                self.log_error(f"Lead scoring failed: {e}")
                results["lead_scoring"] = {"error": str(e)}
        
        # Task 4: Save enriched leads
        try:
            save_results = await self._save_enriched_leads(enriched_leads)
            results["summary"]["saved"] = save_results
        except Exception as e:
            self.log_error(f"Failed to save leads: {e}")
        
        # Task 5: Workflow Triggers
        if self.config["enable_workflow_triggers"]:
            try:
                trigger_results = await self._trigger_workflows(enriched_leads)
                results["workflow_triggers"] = trigger_results
            except Exception as e:
                self.log_error(f"Workflow triggers failed: {e}")
                results["workflow_triggers"] = {"error": str(e)}
        
        # Summary
        results["summary"]["total_processed"] = len(leads)
        results["summary"]["enriched"] = results["company_enrichment"].get("enriched", 0)
        results["summary"]["emails_predicted"] = results["email_prediction"].get("predicted", 0)
        results["summary"]["scored"] = results["lead_scoring"].get("scored", 0)
        
        self.add_metric("records_success", results["summary"]["enriched"])
        
        return results
    
    async def _get_unenriched_leads(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get leads that need enrichment.
        """
        leads_collection = self.db['leads_raw']
        
        # Custom lead IDs if provided
        if input_data.get("lead_ids"):
            from bson import ObjectId
            query = {"_id": {"$in": [ObjectId(lid) for lid in input_data["lead_ids"]]}}
        else:
            # Find unenriched leads
            query = {
                "$or": [
                    {"enriched": {"$ne": True}},
                    {"enriched_at": {"$lt": datetime.utcnow() - timedelta(days=30)}}
                ]
            }
        
        limit = input_data.get("limit", self.config["max_leads_per_run"])
        
        leads = list(leads_collection.find(query).limit(limit))
        
        # Convert ObjectId to string for processing
        for lead in leads:
            lead["_id"] = str(lead["_id"])
        
        return leads
    
    async def _enrich_companies(self, leads: List[Dict[str, Any]]) -> tuple:
        """
        Enrich leads with company data from cache or external sources.
        """
        self.log_info("Enriching company data...")
        
        cache_collection = self.db['company_cache']
        
        enriched = 0
        cache_hits = 0
        cache_misses = 0
        
        for lead in leads:
            domain = lead.get("company_domain") or lead.get("domain") or ""
            
            if not domain and "@" in lead.get("email", ""):
                # Extract domain from email
                domain = lead["email"].split("@")[-1].lower()
                # Skip generic domains
                if domain in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]:
                    domain = ""
            
            if not domain:
                continue
            
            # Try cache first
            cached = cache_collection.find_one_and_update(
                {"domain": domain.lower(), "expires_at": {"$gt": datetime.utcnow()}},
                {
                    "$inc": {"cache_hit_count": 1},
                    "$set": {"last_accessed": datetime.utcnow()}
                },
                return_document=True
            )
            
            if cached:
                cache_hits += 1
                lead["company_data"] = {
                    "name": cached.get("company_name"),
                    "employees": cached.get("employees"),
                    "revenue": cached.get("revenue"),
                    "industry": cached.get("industry"),
                    "headquarters": cached.get("headquarters"),
                    "linkedin_url": cached.get("linkedin_url"),
                    "source": "cache"
                }
                lead["company_enriched"] = True
                enriched += 1
            else:
                cache_misses += 1
                lead["company_enriched"] = False
        
        hit_rate = cache_hits / max(cache_hits + cache_misses, 1) * 100
        
        self.log_info(f"Company enrichment: {enriched} enriched, {hit_rate:.1f}% cache hit rate")
        
        return leads, {
            "enriched": enriched,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "hit_rate": round(hit_rate, 1)
        }
    
    async def _predict_emails(self, leads: List[Dict[str, Any]]) -> tuple:
        """
        Predict email addresses using discovered patterns.
        """
        self.log_info("Predicting emails...")
        
        patterns_collection = self.db['email_patterns']
        
        predicted = 0
        skipped = 0
        
        for lead in leads:
            # Skip if already has verified email
            if lead.get("email_verified"):
                skipped += 1
                continue
            
            domain = lead.get("company_domain") or lead.get("domain") or ""
            first_name = lead.get("first_name", "")
            last_name = lead.get("last_name", "")
            
            if not domain or not first_name:
                skipped += 1
                continue
            
            # Look up pattern
            pattern = patterns_collection.find_one({"domain": domain.lower()})
            
            if not pattern:
                skipped += 1
                continue
            
            # Generate predicted email
            first = first_name.lower().strip()
            last = last_name.lower().strip() if last_name else ""
            pattern_type = pattern["pattern"]
            
            if pattern_type == "firstname.lastname" and last:
                predicted_email = f"{first}.{last}@{domain}"
            elif pattern_type == "firstnamelastname" and last:
                predicted_email = f"{first}{last}@{domain}"
            elif pattern_type == "firstname_lastname" and last:
                predicted_email = f"{first}_{last}@{domain}"
            elif pattern_type == "firstname":
                predicted_email = f"{first}@{domain}"
            elif pattern_type == "f.lastname" and last:
                predicted_email = f"{first[0]}.{last}@{domain}"
            elif pattern_type == "flastname" and last:
                predicted_email = f"{first[0]}{last}@{domain}"
            else:
                # Default fallback
                if last:
                    predicted_email = f"{first}.{last}@{domain}"
                else:
                    predicted_email = f"{first}@{domain}"
            
            lead["predicted_email"] = predicted_email
            lead["email_prediction"] = {
                "email": predicted_email,
                "pattern": pattern_type,
                "confidence": pattern["confidence"],
                "verified": False
            }
            predicted += 1
        
        self.log_info(f"Email prediction: {predicted} predicted, {skipped} skipped")
        
        return leads, {
            "predicted": predicted,
            "skipped": skipped
        }
    
    async def _score_leads(self, leads: List[Dict[str, Any]]) -> tuple:
        """
        Calculate lead scores based on enrichment data.
        """
        self.log_info("Scoring leads...")
        
        weights = self.config["score_weights"]
        scored = 0
        high_priority = 0
        
        for lead in leads:
            score = 0
            score_breakdown = {}
            
            # Company size score
            company_data = lead.get("company_data", {})
            employees = company_data.get("employees", 0)
            if employees:
                if employees >= 1000:
                    size_score = 100
                elif employees >= 200:
                    size_score = 80
                elif employees >= 50:
                    size_score = 60
                else:
                    size_score = 40
                score += size_score * weights["company_size"]
                score_breakdown["company_size"] = size_score
            
            # Industry match (placeholder - would need ICP config)
            industry = company_data.get("industry", "")
            if industry:
                # Assume match for now - would check against ICP
                industry_score = 70
                score += industry_score * weights["industry_match"]
                score_breakdown["industry_match"] = industry_score
            
            # Email verified
            if lead.get("email_verified"):
                email_score = 100
            elif lead.get("predicted_email"):
                email_score = lead.get("email_prediction", {}).get("confidence", 0.5) * 100
            else:
                email_score = 0
            score += email_score * weights["email_verified"]
            score_breakdown["email_verified"] = email_score
            
            # Has LinkedIn
            if lead.get("linkedin_url") or company_data.get("linkedin_url"):
                linkedin_score = 100
            else:
                linkedin_score = 0
            score += linkedin_score * weights["has_linkedin"]
            score_breakdown["has_linkedin"] = linkedin_score
            
            # Title match (placeholder)
            title = lead.get("title", "")
            if title:
                if any(kw in title.lower() for kw in ["vp", "director", "head", "chief", "ceo", "cto"]):
                    title_score = 100
                elif any(kw in title.lower() for kw in ["manager", "lead", "senior"]):
                    title_score = 70
                else:
                    title_score = 40
                score += title_score * weights["title_match"]
                score_breakdown["title_match"] = title_score
            
            # Recency
            created_at = lead.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                days_old = (datetime.utcnow() - created_at.replace(tzinfo=None)).days
                if days_old <= 7:
                    recency_score = 100
                elif days_old <= 30:
                    recency_score = 70
                elif days_old <= 90:
                    recency_score = 40
                else:
                    recency_score = 20
                score += recency_score * weights["recency"]
                score_breakdown["recency"] = recency_score
            
            # Final score
            final_score = min(round(score), 100)
            lead["lead_score"] = final_score
            lead["score_breakdown"] = score_breakdown
            
            if final_score >= self.config["min_score_for_high_priority"]:
                lead["priority"] = "high"
                high_priority += 1
            elif final_score >= 50:
                lead["priority"] = "medium"
            else:
                lead["priority"] = "low"
            
            scored += 1
        
        avg_score = sum(l.get("lead_score", 0) for l in leads) / max(len(leads), 1)
        
        self.log_info(f"Lead scoring: {scored} scored, {high_priority} high priority, avg score {avg_score:.1f}")
        
        return leads, {
            "scored": scored,
            "high_priority": high_priority,
            "average_score": round(avg_score, 1)
        }
    
    async def _save_enriched_leads(self, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Save enriched leads back to database.
        """
        self.log_info("Saving enriched leads...")
        
        leads_collection = self.db['leads_raw']
        enrichment_logs = self.db['enrichment_logs']
        
        from bson import ObjectId
        
        saved = 0
        errors = 0
        
        for lead in leads:
            try:
                lead_id = lead.pop("_id")
                
                update_data = {
                    "company_data": lead.get("company_data"),
                    "company_enriched": lead.get("company_enriched", False),
                    "predicted_email": lead.get("predicted_email"),
                    "email_prediction": lead.get("email_prediction"),
                    "lead_score": lead.get("lead_score"),
                    "score_breakdown": lead.get("score_breakdown"),
                    "priority": lead.get("priority"),
                    "enriched": True,
                    "enriched_at": datetime.utcnow(),
                    "enriched_by": "Phase5Agent"
                }
                
                leads_collection.update_one(
                    {"_id": ObjectId(lead_id)},
                    {"$set": update_data}
                )
                
                # Log enrichment
                enrichment_logs.insert_one({
                    "lead_id": lead_id,
                    "action": "phase5_enrichment",
                    "enriched_at": datetime.utcnow(),
                    "company_enriched": lead.get("company_enriched", False),
                    "email_predicted": bool(lead.get("predicted_email")),
                    "lead_score": lead.get("lead_score")
                })
                
                saved += 1
                
            except Exception as e:
                self.log_warning(f"Failed to save lead: {e}")
                errors += 1
        
        self.log_info(f"Saved {saved} leads, {errors} errors")
        
        return {"saved": saved, "errors": errors}
    
    async def _trigger_workflows(self, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Trigger downstream workflows for high-priority leads.
        """
        self.log_info("Triggering workflows...")
        
        workflow_queue = self.db['workflow_queue']
        
        triggered = 0
        
        for lead in leads:
            if lead.get("priority") == "high":
                # Queue for outreach workflow
                workflow_queue.insert_one({
                    "lead_id": lead.get("_id"),
                    "workflow_type": "high_priority_outreach",
                    "status": "pending",
                    "priority": lead.get("lead_score", 0),
                    "created_at": datetime.utcnow(),
                    "lead_data": {
                        "email": lead.get("email") or lead.get("predicted_email"),
                        "company": lead.get("company_data", {}).get("name"),
                        "score": lead.get("lead_score")
                    }
                })
                triggered += 1
        
        self.log_info(f"Triggered {triggered} workflows")
        
        return {
            "triggered": triggered,
            "workflow_type": "high_priority_outreach"
        }
    
    async def get_pipeline_stats(self) -> Dict[str, Any]:
        """
        Get enrichment pipeline statistics.
        """
        leads_collection = self.db['leads_raw']
        enrichment_logs = self.db['enrichment_logs']
        
        # Lead stats
        total_leads = leads_collection.count_documents({})
        enriched_leads = leads_collection.count_documents({"enriched": True})
        high_priority = leads_collection.count_documents({"priority": "high"})
        
        # Score distribution
        score_pipeline = [
            {"$match": {"lead_score": {"$exists": True}}},
            {"$bucket": {
                "groupBy": "$lead_score",
                "boundaries": [0, 25, 50, 75, 100, 101],
                "default": "unknown",
                "output": {"count": {"$sum": 1}}
            }}
        ]
        score_dist = list(leads_collection.aggregate(score_pipeline))
        
        # Recent enrichments
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        enriched_today = enrichment_logs.count_documents({
            "enriched_at": {"$gte": today}
        })
        
        return {
            "total_leads": total_leads,
            "enriched_leads": enriched_leads,
            "enrichment_rate": round(enriched_leads / max(total_leads, 1) * 100, 1),
            "high_priority_leads": high_priority,
            "enriched_today": enriched_today,
            "score_distribution": score_dist
        }
