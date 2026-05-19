from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Body
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId

from ..router_shared import ai_companies_collection, _jobs_db
from ..service import leads_enriched_collection

def register_ai_database_routes(router: APIRouter):
    # ============== AI COMPANY DATABASE ENDPOINTS ==============

    class CompanyStatus:
        """Status of a company in the AI database"""
        PENDING = "pending"      # Discovered, not yet searched for contacts
        SEARCHING = "searching"  # Currently being searched
        COMPLETED = "completed"  # Contacts found and imported
        NO_RESULTS = "no_results"  # Searched but no contacts found
        ERROR = "error"          # Search failed


    @router.get("/ai-database/status")
    async def get_ai_database_status():
        """
        GET /leads/ai-database/status
        Get status of the AI Company Database.
        Returns counts by status and whether refill is needed.
        """
        try:
            from .ingestion_vm import get_google_api_credentials
            from .google_rate_limit import get_usage_stats
        
            # Check if Google CSE is configured
            api_key, cse_id = get_google_api_credentials()
            google_cse_configured = bool(api_key and cse_id)
        
            # Get Google CSE usage stats
            usage_stats = get_usage_stats()
        
            # Count companies by status
            pipeline = [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}}
            ]
            status_counts = {doc["_id"]: doc["count"] for doc in ai_companies_collection.aggregate(pipeline)}
        
            total = sum(status_counts.values())
            pending = status_counts.get(CompanyStatus.PENDING, 0)
            completed = status_counts.get(CompanyStatus.COMPLETED, 0)
        
            # Check if refill is needed (below 100 pending companies)
            needs_refill = pending < 100
        
            # Get recent companies for display
            recent_companies = list(ai_companies_collection.find(
                {},
                {"_id": 0, "name": 1, "domain": 1, "industry": 1, "status": 1, "discovered_at": 1}
            ).sort("discovered_at", -1).limit(20))
        
            # Convert datetime to string for JSON serialization
            for company in recent_companies:
                if company.get("discovered_at"):
                    company["discovered_at"] = company["discovered_at"].isoformat()
        
            return {
                "success": True,
                "total_companies": total,
                "by_status": {
                    "pending": pending,
                    "searching": status_counts.get(CompanyStatus.SEARCHING, 0),
                    "completed": completed,
                    "no_results": status_counts.get(CompanyStatus.NO_RESULTS, 0),
                    "error": status_counts.get(CompanyStatus.ERROR, 0)
                },
                "needs_refill": needs_refill,
                "refill_threshold": 100,
                "google_cse_configured": google_cse_configured,
                "google_cse_usage": {
                    "today_queries": usage_stats.get("today_queries", 0),
                    "daily_limit": usage_stats.get("daily_limit", 100),
                    "daily_remaining": usage_stats.get("daily_remaining", 100),
                },
                "recent_companies": recent_companies
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_companies": 0,
                "needs_refill": True
            }


    class RefillCompaniesRequest(BaseModel):
        """Request model for refilling the company database"""
        industry: str = "technology"
        location: str = "United States"
        count: int = 100
        criteria: str = ""


    class DirectDiscoveryRequest(BaseModel):
        """Request model for direct contact discovery using Google CSE + OpenAI"""
        designation: str = "Manager"
        industry: str = "technology"
        location: str = "United States"
        count: int = 10
        criteria: str = ""


    @router.post("/ai-database/discover-leads")
    async def discover_leads_direct(request: DirectDiscoveryRequest):
        """
        POST /leads/ai-database/discover-leads
        Lead discovery using Google Custom Search + OpenAI enrichment.
    
        Flow:
        1. Build search query from parameters
        2. Google CSE finds LinkedIn profiles
        3. OpenAI extracts/enriches lead data
        4. Import to database with auto-classification
    
        Cost: ~$0.005 per search (free tier: 100/day)
        """
        try:
            from .ingestion_vm import search_linkedin_leads, get_google_api_credentials
            from .google_rate_limit import can_make_query, record_query, get_usage_stats
            from .service import import_leads
            from .models import LeadRaw
        
            # Check if Google CSE is configured
            api_key, cse_id = get_google_api_credentials()
            if not api_key or not cse_id:
                raise HTTPException(
                    status_code=400,
                    detail="Google CSE not configured. Add GOOGLE_API_KEY and GOOGLE_CSE_ID in Settings."
                )
        
            # Check rate limit
            allowed, message = can_make_query()
            if not allowed:
                usage = get_usage_stats()
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {message}. Today: {usage['today_queries']}/{usage['daily_limit']}"
                )
        
            # Build search query
            # Format: "designation" industry location site:linkedin.com/in/
            query_parts = []
            if request.designation:
                query_parts.append(f'"{request.designation}"')
            if request.industry:
                query_parts.append(request.industry)
            if request.location:
                query_parts.append(request.location)
            if request.criteria:
                query_parts.append(request.criteria)
        
            query = " ".join(query_parts)
        
            # Search for LinkedIn profiles
            leads_data = await search_linkedin_leads(
                query=query,
                num_results=min(request.count, 10),  # Google CSE max 10 per query
                deduplicate=True
            )
        
            # Record the API usage
            record_query(1)
        
            if not leads_data:
                return {
                    "success": True,
                    "message": "No contacts found matching criteria. Try different search terms.",
                    "leads_imported": 0,
                    "query_used": query
                }
        
            # Convert to LeadRaw and import
            leads = []
            for data in leads_data:
                linkedin_url = data.get("linkedin_url", "")
                if linkedin_url and not linkedin_url.startswith("http"):
                    linkedin_url = f"https://{linkedin_url}"
            
                lead = LeadRaw(
                    name=data.get("name", "Unknown"),
                    title=data.get("title", request.designation),
                    company_name=data.get("company_name", ""),
                    linkedin_url=linkedin_url,
                    snippet=data.get("snippet", f"AI Discovery: {request.designation} at {request.industry}"),
                    location=data.get("location", request.location),
                    email=data.get("email", ""),
                    source="google_cse_discovery",
                    import_batch_id=f"discovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                )
                leads.append(lead)
        
            # Import with auto-classification
            import_result = import_leads(leads, auto_classify=True)
        
            return {
                "success": True,
                "contacts_found": len(leads_data),
                "leads_imported": import_result.get("imported", 0),
                "duplicates": import_result.get("duplicates", 0),
                "method": "google_cse_openai",
                "query_used": query,
                "cost_estimate": "$0.00 (free tier)" if get_usage_stats()["today_queries"] <= 100 else f"${0.005:.4f}",
                "contacts": leads_data[:5]  # Return sample for UI display
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Discovery error: {str(e)}")


    # NOTE: /ai-database/refill endpoint removed - was using Perplexity which is no longer supported.
    # Use /ai-database/discover-leads with Google CSE instead.


    @router.get("/ai-database/companies")
    async def get_ai_database_companies(
        status: Optional[str] = None,
        industry: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ):
        """
        GET /leads/ai-database/companies
        Get companies from the AI database with optional filtering.
        """
        try:
            query = {}
            if status:
                query["status"] = status
            if industry:
                query["industry"] = {"$regex": industry, "$options": "i"}
        
            companies = list(ai_companies_collection.find(
                query,
                {"_id": 0}
            ).sort("discovered_at", -1).skip(skip).limit(limit))
        
            total = ai_companies_collection.count_documents(query)
        
            # Convert datetime to string for JSON serialization
            for company in companies:
                if company.get("discovered_at"):
                    company["discovered_at"] = company["discovered_at"].isoformat()
                if company.get("last_searched"):
                    company["last_searched"] = company["last_searched"].isoformat()
        
            return {
                "success": True,
                "companies": companies,
                "total": total,
                "limit": limit,
                "skip": skip
            }
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


    # NOTE: /ai-database/process-batch endpoint removed - was using Perplexity which is no longer supported.
    # Use /ai-database/discover-leads with Google CSE instead.


    @router.delete("/ai-database/clear")
    async def clear_ai_database(status: Optional[str] = None):
        """
        DELETE /leads/ai-database/clear
        Clear companies from AI database.
        Optional: filter by status to only clear certain records.
        """
        try:
            query = {}
            if status:
                query["status"] = status
        
            result = ai_companies_collection.delete_many(query)
        
            return {
                "success": True,
                "deleted": result.deleted_count,
                "filter": status or "all"
            }
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


    # ============== AI DATABASE WORKBOOKS (Clay-style) ==============

    class CompanyDiscoveryRequest(BaseModel):
        """Request model for company discovery"""
        industry: str = "technology"
        location: str = "United States"
        count: int = 20


    class JobDiscoveryRequest(BaseModel):
        """Request model for job discovery"""
        job_title: str = "Software Engineer"
        location: str = "United States"
        count: int = 20


    class LocalBusinessDiscoveryRequest(BaseModel):
        """Request model for local business discovery"""
        business_type: str = "restaurant"
        location: str = "New York"
        count: int = 20


    @router.get("/ai-database/workbooks")
    async def get_workbooks():
        """
        GET /leads/ai-database/workbooks
        Get list of discovery workbooks (saved searches/results).
        """
        try:
            # Use existing companies as workbooks or create a workbooks collection
            workbooks_collection = _jobs_db.get_collection("ai_workbooks")
        
            workbooks = list(workbooks_collection.find(
                {},
                {"_id": 1, "name": 1, "tags": 1, "created_at": 1, "last_opened": 1, "owner": 1, "access": 1, "is_favorite": 1, "leads_count": 1, "discovery_type": 1}
            ).sort("created_at", -1).limit(50))
        
            # Convert ObjectId to string
            for wb in workbooks:
                wb["_id"] = str(wb["_id"])
        
            return {"success": True, "workbooks": workbooks}
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


    @router.post("/ai-database/workbooks")
    async def create_workbook(request: dict = Body(...)):
        """
        POST /leads/ai-database/workbooks
        Create a new workbook.
        """
        try:
            workbooks_collection = _jobs_db.get_collection("ai_workbooks")
        
            workbook = {
                "name": request.get("name", "Untitled workbook"),
                "tags": request.get("tags", []),
                "created_at": datetime.utcnow(),
                "last_opened": datetime.utcnow(),
                "owner": "You",
                "access": "Edit",
                "is_favorite": False,
                "leads_count": 0,
                "discovery_type": request.get("discovery_type", "manual")
            }
        
            result = workbooks_collection.insert_one(workbook)
            workbook["_id"] = str(result.inserted_id)
        
            return {"success": True, "workbook": workbook}
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


    # NOTE: The following Perplexity-dependent endpoints have been removed:
    # - POST /ai-database/discover-companies
    # - POST /ai-database/discover-jobs
    # - POST /ai-database/discover-local
    # Use POST /ai-database/discover-leads with Google CSE + OpenAI instead.


    # ============== GOOGLE CSE HEALTH & USAGE ENDPOINTS ==============

    @router.get("/ai-database/google-health")
    async def get_google_cse_health():
        """
        GET /leads/ai-database/google-health
        Check if Google CSE API is properly configured and working.
        """
        try:
            from .ingestion_vm import get_google_api_credentials, perform_google_search
        
            api_key, cse_id = get_google_api_credentials()
        
            if not api_key:
                return {
                    "status": "not_configured",
                    "message": "GOOGLE_API_KEY not set. Add it in Settings or .env file.",
                    "setup_url": "https://console.cloud.google.com/apis/credentials"
                }
        
            if not cse_id:
                return {
                    "status": "not_configured",
                    "message": "GOOGLE_CSE_ID not set. Create a Custom Search Engine and add the ID.",
                    "setup_url": "https://programmablesearchengine.google.com/"
                }
        
            # Test the API with a simple query
            try:
                test_results = await perform_google_search("test site:linkedin.com", num_results=1)
            
                if test_results is not None:
                    return {
                        "status": "valid",
                        "message": "Google CSE is configured and working correctly.",
                        "api_key_prefix": api_key[:8] + "...",
                        "cse_id_prefix": cse_id[:8] + "..."
                    }
                else:
                    return {
                        "status": "error",
                        "message": "API responded but returned no results. Check CSE configuration."
                    }
            except Exception as api_error:
                error_msg = str(api_error)
                if "403" in error_msg or "forbidden" in error_msg.lower():
                    return {
                        "status": "invalid_key",
                        "message": "API key is invalid or Custom Search API is not enabled.",
                        "setup_url": "https://console.cloud.google.com/apis/library/customsearch.googleapis.com"
                    }
                elif "429" in error_msg:
                    return {
                        "status": "quota_exceeded",
                        "message": "Daily quota exceeded. Free tier: 100 queries/day."
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"API test failed: {error_msg}"
                    }
        
        except Exception as e:
            return {
                "status": "error",
                "message": f"Health check failed: {str(e)}"
            }


    @router.get("/ai-database/google-usage")
    async def get_google_cse_usage():
        """
        GET /leads/ai-database/google-usage
        Get Google CSE usage statistics and rate limit status.
        """
        try:
            from .google_rate_limit import get_usage_stats, estimate_monthly_cost, get_historical_usage
        
            stats = get_usage_stats()
            cost_estimate = estimate_monthly_cost()
            history = get_historical_usage(7)
        
            return {
                "success": True,
                "today": {
                    "queries": stats["today_queries"],
                    "limit": stats["daily_limit"],
                    "remaining": stats["daily_remaining"],
                    "percentage_used": round((stats["today_queries"] / stats["daily_limit"]) * 100, 1) if stats["daily_limit"] > 0 else 0
                },
                "hourly": {
                    "queries": stats["hourly_queries"],
                    "limit": stats["hourly_limit"],
                    "remaining": stats["hourly_remaining"]
                },
                "monthly_estimate": cost_estimate,
                "rate_limit_enabled": stats["rate_limit_enabled"],
                "history": history
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


    @router.post("/ai-database/google-usage/reset")
    async def reset_google_cse_usage():
        """
        POST /leads/ai-database/google-usage/reset
        Reset today's Google CSE usage counter (admin function).
        """
        try:
            from .google_rate_limit import reset_daily_counter
        
            stats = reset_daily_counter()
        
            return {
                "success": True,
                "message": "Usage counter reset successfully",
                "stats": stats
            }
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


    # ============== BULK SERVICE TYPE TAGGING ==============

    class BulkServiceTypeRequest(BaseModel):
        lead_ids: List[str]
        service_type: str

    @router.post("/bulk-service-type")
    async def bulk_update_service_type(request: BulkServiceTypeRequest):
        """
        POST /leads/bulk-service-type
        Bulk update service_type for selected leads.
        Valid types: Data Services, Insights Services, Error
        """
        valid_types = ["Data Services", "Insights Services", "Error"]
        if request.service_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid service_type. Must be one of: {valid_types}")
    
        from bson import ObjectId
        object_ids = []
        for lid in request.lead_ids:
            try:
                object_ids.append(ObjectId(lid))
            except Exception:
                pass
    
        if not object_ids:
            raise HTTPException(status_code=400, detail="No valid lead IDs provided")
    
        result = leads_enriched_collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"service_type": request.service_type}}
        )
    
        return {
            "success": True,
            "updated_count": result.modified_count,
            "message": f"Tagged {result.modified_count} lead(s) as '{request.service_type}'"
        }
