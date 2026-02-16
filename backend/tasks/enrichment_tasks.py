"""
Potential Client Enrichment Celery Tasks
Background tasks for auto-enriching new potential clients using OpenAI web search
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set

from celery_app import celery_app
from db_pools import get_db

logger = logging.getLogger(__name__)


# ============== HELPER FUNCTIONS ==============

def get_survey_pool_db():
    """Get MongoDB connection for survey pool operations."""
    return get_db('email_automation')


def get_known_companies() -> Set[str]:
    """
    Extract all unique company/client names from CINT/CPX survey pool.
    Returns a set of normalized company names.
    """
    known = set()
    
    try:
        # Get from CINT surveys
        cint_db = get_db('cint_surveys')
        if cint_db is not None:
            cint_surveys = cint_db['surveys']
            for survey in cint_surveys.find({}, {"account_name": 1, "client_name": 1}):
                if survey.get("account_name"):
                    known.add(survey["account_name"].strip())
                elif survey.get("client_name"):
                    known.add(survey["client_name"].strip())
    except Exception as e:
        logger.warning(f"Error fetching CINT surveys: {e}")
    
    try:
        # Get from CPX surveys
        cpx_db = get_db('cpx_surveys')
        if cpx_db is not None:
            cpx_surveys = cpx_db['surveys']
            for survey in cpx_surveys.find({}, {"account_name": 1, "client_name": 1}):
                if survey.get("account_name"):
                    known.add(survey["account_name"].strip())
                elif survey.get("client_name"):
                    known.add(survey["client_name"].strip())
    except Exception as e:
        logger.warning(f"Error fetching CPX surveys: {e}")
    
    # Filter out empty strings and N/A values
    known = {c for c in known if c and c != "N/A" and len(c) > 1}
    
    return known


def get_previously_enriched_companies() -> Set[str]:
    """Get set of company names that have already been enriched."""
    try:
        db = get_survey_pool_db()
        enriched = db['potential_client_leads']
        
        # Get companies enriched in the last 7 days
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        cursor = enriched.find(
            {"enriched_at": {"$gte": seven_days_ago}},
            {"company": 1}
        )
        
        return {doc["company"].lower() for doc in cursor if doc.get("company")}
    except Exception as e:
        logger.error(f"Error getting enriched companies: {e}")
        return set()


def log_enrichment_run(
    run_id: str,
    companies_found: int,
    companies_to_enrich: int,
    companies_enriched: int,
    errors: int,
    duration_seconds: float
):
    """Log the enrichment run for monitoring."""
    try:
        db = get_survey_pool_db()
        runs = db['enrichment_runs']
        
        runs.insert_one({
            "run_id": run_id,
            "timestamp": datetime.utcnow(),
            "companies_found": companies_found,
            "companies_to_enrich": companies_to_enrich,
            "companies_enriched": companies_enriched,
            "errors": errors,
            "duration_seconds": duration_seconds
        })
    except Exception as e:
        logger.error(f"Error logging enrichment run: {e}")


# ============== MAIN ENRICHMENT TASK ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.enrichment_tasks.auto_enrich_potential_clients',
    max_retries=2,
    default_retry_delay=300,  # 5 minutes
    time_limit=1800,  # 30 minute timeout
)
def auto_enrich_potential_clients(
    self,
    max_companies: int = 10,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Automatically enrich new potential clients detected in the survey pool.
    
    This task is scheduled to run periodically and will:
    1. Scan CINT/CPX survey pools for unique client/company names
    2. Check which companies haven't been enriched yet
    3. Enrich up to max_companies using OpenAI web search
    
    Args:
        max_companies: Maximum number of companies to enrich per run
        force_refresh: If True, re-enrich even existing companies
        
    Returns:
        Summary of enrichment results
    """
    import time
    import uuid
    
    run_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    logger.info(f"Starting auto-enrichment run {run_id}")
    
    try:
        from leads.web_search_enrichment import (
            enrich_company_with_websearch,
            get_unenriched_companies
        )
        
        # Step 1: Get all known companies from survey pools
        known_companies = get_known_companies()
        logger.info(f"Found {len(known_companies)} unique companies in survey pools")
        
        if not known_companies:
            return {
                "run_id": run_id,
                "status": "no_companies",
                "message": "No companies found in survey pools"
            }
        
        # Step 2: Find companies that need enrichment
        unenriched = get_unenriched_companies(list(known_companies))
        logger.info(f"Found {len(unenriched)} companies needing enrichment")
        
        if not unenriched:
            duration = time.time() - start_time
            log_enrichment_run(run_id, len(known_companies), 0, 0, 0, duration)
            return {
                "run_id": run_id,
                "status": "complete",
                "message": "All companies already enriched",
                "companies_found": len(known_companies),
                "duration_seconds": round(duration, 2)
            }
        
        # Step 3: Enrich up to max_companies
        to_enrich = unenriched[:max_companies]
        enriched_count = 0
        error_count = 0
        
        for i, company in enumerate(to_enrich):
            logger.info(f"Enriching {i+1}/{len(to_enrich)}: {company}")
            
            try:
                result = enrich_company_with_websearch(
                    company_name=company,
                    additional_context="Market research company from Cint API survey pool",
                    force_refresh=force_refresh
                )
                
                if result.get("success", True) and not result.get("error"):
                    enriched_count += 1
                    logger.info(f"Successfully enriched: {company}")
                else:
                    error_count += 1
                    logger.warning(f"Failed to enrich {company}: {result.get('error')}")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Error enriching {company}: {e}")
            
            # Rate limiting: wait between requests
            if i < len(to_enrich) - 1:
                time.sleep(3)  # 3 second delay between API calls
        
        # Step 4: Log results
        duration = time.time() - start_time
        log_enrichment_run(
            run_id, 
            len(known_companies), 
            len(unenriched), 
            enriched_count, 
            error_count, 
            duration
        )
        
        remaining = len(unenriched) - len(to_enrich)
        
        return {
            "run_id": run_id,
            "status": "complete",
            "companies_found": len(known_companies),
            "companies_to_enrich": len(unenriched),
            "enriched": enriched_count,
            "errors": error_count,
            "remaining": remaining,
            "duration_seconds": round(duration, 2)
        }
        
    except Exception as e:
        logger.error(f"Auto-enrichment failed: {e}", exc_info=True)
        raise self.retry(exc=e)


# ============== SCHEDULED ENRICHMENT CHECK ==============

@celery_app.task(
    name='backend.tasks.enrichment_tasks.check_new_potential_clients',
    time_limit=60
)
def check_new_potential_clients() -> Dict[str, Any]:
    """
    Quick check for new potential clients without enriching.
    Can be scheduled frequently to detect new companies.
    
    Returns:
        Count of new/unenriched companies
    """
    try:
        from leads.web_search_enrichment import get_unenriched_companies
        
        known_companies = get_known_companies()
        unenriched = get_unenriched_companies(list(known_companies))
        
        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_companies": len(known_companies),
            "unenriched_count": len(unenriched),
            "needs_enrichment": len(unenriched) > 0
        }
        
        # If there are new companies, trigger enrichment
        if len(unenriched) > 0:
            logger.info(f"Found {len(unenriched)} new companies - triggering enrichment")
            auto_enrich_potential_clients.apply_async(
                kwargs={"max_companies": 5},
                countdown=10  # Start after 10 seconds
            )
        
        return result
        
    except Exception as e:
        logger.error(f"Error checking new potential clients: {e}")
        return {"error": str(e)}


# ============== BULK ENRICHMENT TASK ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.enrichment_tasks.bulk_enrich_companies',
    max_retries=1,
    time_limit=3600,  # 1 hour timeout
)
def bulk_enrich_companies(
    self,
    company_names: List[str],
    delay_seconds: float = 3.0
) -> Dict[str, Any]:
    """
    Bulk enrich a list of specified companies.
    
    Args:
        company_names: List of company names to enrich
        delay_seconds: Delay between API calls
        
    Returns:
        Summary of enrichment results
    """
    import time
    
    logger.info(f"Starting bulk enrichment for {len(company_names)} companies")
    
    try:
        from leads.web_search_enrichment import enrich_company_with_websearch
        
        enriched_count = 0
        error_count = 0
        results = []
        
        for i, company in enumerate(company_names):
            logger.info(f"Bulk enriching {i+1}/{len(company_names)}: {company}")
            
            try:
                result = enrich_company_with_websearch(company_name=company)
                
                if result.get("success", True) and not result.get("error"):
                    enriched_count += 1
                    results.append({"company": company, "status": "success"})
                else:
                    error_count += 1
                    results.append({"company": company, "status": "error", "error": result.get("error")})
                    
            except Exception as e:
                error_count += 1
                results.append({"company": company, "status": "error", "error": str(e)})
            
            # Rate limiting
            if i < len(company_names) - 1:
                time.sleep(delay_seconds)
        
        return {
            "status": "complete",
            "total": len(company_names),
            "enriched": enriched_count,
            "errors": error_count,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Bulk enrichment failed: {e}", exc_info=True)
        raise self.retry(exc=e)
