"""
Lead Agent Celery Tasks
Background tasks for AI lead generation agent pipeline
"""

import os
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from celery_app import celery_app
from db_pools import get_db

logger = logging.getLogger(__name__)


# ============== HELPER FUNCTIONS ==============

def get_agents_db():
    """Get database connection for agent operations."""
    db_name = os.getenv("LEAD_AGENTS_DB", "email_automation")
    return get_db(db_name)


def update_job_status(
    job_id: str,
    status: str = None,
    current_agent: str = None,
    progress_percent: float = None,
    completed_steps: int = None,
    **kwargs
):
    """Update job status in MongoDB."""
    try:
        db = get_agents_db()
        jobs = db['agent_jobs']
        
        update_data = {"updated_at": datetime.utcnow()}
        
        if status:
            update_data["status"] = status
        if current_agent:
            update_data["current_agent"] = current_agent
        if progress_percent is not None:
            update_data["progress_percent"] = progress_percent
        if completed_steps is not None:
            update_data["completed_steps"] = completed_steps
        
        # Add any additional fields
        for key, value in kwargs.items():
            if value is not None:
                update_data[key] = value
        
        jobs.update_one(
            {"job_id": job_id},
            {"$set": update_data}
        )
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")


def broadcast_progress(job_id: str, data: Dict[str, Any]):
    """Broadcast progress update via WebSocket."""
    try:
        from websocket_manager import manager
        import asyncio
        
        message = {
            "type": "agent_progress",
            "job_id": job_id,
            **data
        }
        
        # Run async broadcast in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                manager.broadcast_to_channel("lead_generation", message)
            )
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"Failed to broadcast progress: {e}")


# ============== MAIN PIPELINE TASK ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_lead_generation_pipeline',
    max_retries=1,
    default_retry_delay=60,
    time_limit=3600,  # 1 hour timeout
)
def run_lead_generation_pipeline(
    self,
    job_id: str,
    company_ids: List[str] = None,
    config_id: str = None,
    agents_to_run: List[str] = None,
    icp_criteria: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Main orchestrator for lead generation pipeline.
    
    Flow:
    1. Company Discovery (if no companies provided)
    2. Contact Finder (for each company)
    3. Deduplication Check
    4. Lead Enricher
    5. Lead Scorer
    6. Outreach Composer
    
    Args:
        job_id: Unique job identifier
        company_ids: Optional list of company IDs to process (skip discovery)
        config_id: Agent configuration preset ID
        agents_to_run: Specific agents to run (defaults to all)
        icp_criteria: ICP criteria for company discovery
        
    Returns:
        Job result summary
    """
    from bson import ObjectId
    from agents import CompanyDiscoveryAgent, ContactFinderAgent, LeadEnricherAgent, LeadScorerAgent, OutreachComposerAgent, LeadDeduplicator, DAILY_LEAD_LIMIT, LEADS_PER_BATCH
    from agents.schemas import AgentConfig, AgentStatus
    
    db = get_agents_db()
    task_id = self.request.id
    
    # Default agents to run
    if agents_to_run is None:
        if company_ids:
            # Skip discovery if companies provided
            agents_to_run = ["contact_finder", "lead_enricher", "lead_scorer", "outreach_composer"]
        else:
            agents_to_run = ["company_discovery", "contact_finder", "lead_enricher", "lead_scorer", "outreach_composer"]
    
    total_steps = len(agents_to_run)
    completed_steps = 0
    
    # Initialize job
    update_job_status(
        job_id,
        status=AgentStatus.RUNNING.value,
        started_at=datetime.utcnow(),
        total_steps=total_steps,
        agents_to_run=agents_to_run
    )
    
    broadcast_progress(job_id, {
        "status": "running",
        "message": "Starting lead generation pipeline",
        "total_steps": total_steps
    })
    
    try:
        # Load config
        config_data = {}
        if config_id:
            config_doc = db['agent_configurations'].find_one({"config_id": config_id})
            if config_doc:
                config_data = config_doc
        
        # Initialize components
        deduplicator = LeadDeduplicator()
        
        # Check quota
        quota_status = deduplicator.get_quota_status()
        if quota_status['is_limit_reached']:
            update_job_status(
                job_id,
                status=AgentStatus.FAILED.value,
                errors=["Daily lead limit reached"]
            )
            return {
                'status': 'error',
                'error': f"Daily lead limit of {DAILY_LEAD_LIMIT} reached",
                'job_id': job_id
            }
        
        # Track results
        companies_found = []
        contacts_found = []
        leads_enriched = []
        leads_scored = []
        emails_composed = []
        duplicates_skipped = 0
        errors = []
        
        # ========== STEP 1: Company Discovery ==========
        if "company_discovery" in agents_to_run:
            update_job_status(job_id, current_agent="company_discovery")
            broadcast_progress(job_id, {
                "current_agent": "company_discovery",
                "message": "Discovering companies matching ICP..."
            })
            
            try:
                discovery_config = config_data.get("company_discovery", {})
                if icp_criteria:
                    discovery_config.update(icp_criteria)
                
                agent = CompanyDiscoveryAgent(discovery_config)
                result = agent.execute(discovery_config, use_web_search=True)
                
                if result.success and result.data:
                    companies_found = result.data.get("companies", [])
                    
                    # Store discovered companies
                    for company in companies_found:
                        db['ai_discovered_companies'].update_one(
                            {"domain": company.get("domain")},
                            {
                                "$set": {
                                    **company,
                                    "discovered_at": datetime.utcnow(),
                                    "job_id": job_id
                                }
                            },
                            upsert=True
                        )
                    
                    logger.info(f"Discovered {len(companies_found)} companies")
                else:
                    errors.append(f"Company discovery failed: {result.error}")
                    
            except Exception as e:
                errors.append(f"Company discovery error: {str(e)}")
                logger.error(f"Company discovery failed: {e}")
            
            completed_steps += 1
            update_job_status(
                job_id,
                completed_steps=completed_steps,
                progress_percent=(completed_steps / total_steps) * 100,
                companies_found=len(companies_found)
            )
        
        # If companies were provided, load them
        if company_ids:
            for cid in company_ids:
                company = db['ai_discovered_companies'].find_one({"_id": ObjectId(cid)})
                if company:
                    companies_found.append(company)
        
        # ========== STEP 2: Contact Finder ==========
        if "contact_finder" in agents_to_run and companies_found:
            update_job_status(job_id, current_agent="contact_finder")
            broadcast_progress(job_id, {
                "current_agent": "contact_finder",
                "message": f"Finding contacts at {len(companies_found)} companies..."
            })
            
            try:
                contact_config = config_data.get("contact_finder", {})
                agent = ContactFinderAgent(contact_config)
                
                for company in companies_found:
                    # Check quota before each batch
                    if deduplicator.get_quota_status()['remaining'] < LEADS_PER_BATCH:
                        errors.append("Daily quota reached during contact finding")
                        break
                    
                    result = agent.execute(
                        {
                            "company_name": company.get("name", ""),
                            "company_domain": company.get("domain", "")
                        },
                        use_web_search=True
                    )
                    
                    if result.success and result.data:
                        batch_contacts = result.data.get("contacts", [])

                        # Parse first_name / last_name if only a combined name is present
                        for c in batch_contacts:
                            # Strip LinkedIn/title suffix (e.g. "Nick Graham | VP, PepsiCo | LinkedIn")
                            if c.get("name"):
                                c["name"] = c["name"].split(" | ")[0].strip()
                            if not c.get("first_name") and c.get("name"):
                                parts = c["name"].strip().split(" ", 1)
                                c["first_name"] = parts[0]
                                c["last_name"] = parts[1] if len(parts) > 1 else ""

                        # Deduplicate
                        new_contacts, dupes = deduplicator.check_duplicates(batch_contacts)
                        duplicates_skipped += len(dupes)
                        
                        contacts_found.extend(new_contacts)
                        
                        # Store raw leads
                        for contact in new_contacts:
                            lead_doc = {
                                **contact,
                                "source": "ai_agent",
                                "source_details": {
                                    "agent": "contact_finder",
                                    "job_id": job_id
                                },
                                "created_at": datetime.utcnow(),
                                "classification_status": "Pending"
                            }
                            db['leads_raw'].insert_one(lead_doc)
                        
                        # Increment quota
                        deduplicator.increment_quota(len(new_contacts))
                
                logger.info(f"Found {len(contacts_found)} contacts, skipped {duplicates_skipped} duplicates")
                
            except Exception as e:
                errors.append(f"Contact finder error: {str(e)}")
                logger.error(f"Contact finder failed: {e}")
            
            completed_steps += 1
            update_job_status(
                job_id,
                completed_steps=completed_steps,
                progress_percent=(completed_steps / total_steps) * 100,
                contacts_found=len(contacts_found),
                duplicates_skipped=duplicates_skipped
            )
        
        # ========== STEP 3: Lead Enricher ==========
        if "lead_enricher" in agents_to_run and contacts_found:
            update_job_status(job_id, current_agent="lead_enricher")
            broadcast_progress(job_id, {
                "current_agent": "lead_enricher",
                "message": f"Enriching {len(contacts_found)} leads..."
            })
            
            try:
                enricher_config = config_data.get("lead_enricher", {})
                agent = LeadEnricherAgent(enricher_config)
                
                # Process in batches
                for i in range(0, len(contacts_found), LEADS_PER_BATCH):
                    batch = contacts_found[i:i + LEADS_PER_BATCH]
                    result = agent.execute({"leads": batch}, use_web_search=True)
                    
                    if result.success and result.data:
                        enriched_batch = result.data.get("enriched_leads", [])
                        leads_enriched.extend(enriched_batch)
                        
                        # Update leads_raw with enriched data
                        for enriched in enriched_batch:
                            if enriched.get("lead_id"):
                                db['leads_raw'].update_one(
                                    {"_id": ObjectId(enriched["lead_id"])},
                                    {"$set": {
                                        "enrichment_data": enriched,
                                        "enriched_at": datetime.utcnow()
                                    }}
                                )
                
                logger.info(f"Enriched {len(leads_enriched)} leads")
                
            except Exception as e:
                errors.append(f"Lead enricher error: {str(e)}")
                logger.error(f"Lead enricher failed: {e}")
            
            completed_steps += 1
            update_job_status(
                job_id,
                completed_steps=completed_steps,
                progress_percent=(completed_steps / total_steps) * 100,
                leads_enriched=len(leads_enriched)
            )
        
        # Use enriched leads if available, otherwise use contacts
        leads_to_score = leads_enriched if leads_enriched else contacts_found
        
        # ========== STEP 4: Lead Scorer ==========
        if "lead_scorer" in agents_to_run and leads_to_score:
            update_job_status(job_id, current_agent="lead_scorer")
            broadcast_progress(job_id, {
                "current_agent": "lead_scorer",
                "message": f"Scoring {len(leads_to_score)} leads..."
            })
            
            try:
                scorer_config = config_data.get("lead_scorer", {})
                agent = LeadScorerAgent(scorer_config)
                
                # Process in batches
                for i in range(0, len(leads_to_score), LEADS_PER_BATCH):
                    batch = leads_to_score[i:i + LEADS_PER_BATCH]
                    result = agent.execute({"leads": batch}, use_web_search=False)
                    
                    if result.success and result.data:
                        scored_batch = result.data.get("scored_leads", [])
                        leads_scored.extend(scored_batch)
                        
                        # Store in leads_enriched collection
                        for scored in scored_batch:
                            enriched_doc = {
                                **scored,
                                "created_at": datetime.utcnow(),
                                "job_id": job_id
                            }
                            db['leads_enriched'].update_one(
                                {"email": scored.get("email")},
                                {"$set": enriched_doc},
                                upsert=True
                            )
                
                logger.info(f"Scored {len(leads_scored)} leads")
                
            except Exception as e:
                errors.append(f"Lead scorer error: {str(e)}")
                logger.error(f"Lead scorer failed: {e}")
            
            completed_steps += 1
            update_job_status(
                job_id,
                completed_steps=completed_steps,
                progress_percent=(completed_steps / total_steps) * 100,
                leads_scored=len(leads_scored)
            )
        
        # ========== STEP 5: Outreach Composer ==========
        if "outreach_composer" in agents_to_run and leads_scored:
            update_job_status(job_id, current_agent="outreach_composer")
            broadcast_progress(job_id, {
                "current_agent": "outreach_composer",
                "message": f"Composing emails for {len(leads_scored)} leads..."
            })
            
            try:
                composer_config = config_data.get("outreach_composer", {})
                agent = OutreachComposerAgent(composer_config)
                
                # Only compose for qualified leads
                qualified_leads = [l for l in leads_scored if l.get("is_qualified", False)]
                
                # Process in batches
                for i in range(0, len(qualified_leads), LEADS_PER_BATCH):
                    batch = qualified_leads[i:i + LEADS_PER_BATCH]
                    result = agent.execute({"leads": batch}, use_web_search=False)
                    
                    if result.success and result.data:
                        email_batch = result.data.get("drafts", [])
                        emails_composed.extend(email_batch)
                        
                        # Store drafts
                        for draft in email_batch:
                            draft_doc = {
                                **draft,
                                "created_at": datetime.utcnow(),
                                "job_id": job_id,
                                "status": "draft"
                            }
                            db['lead_outreach_drafts'].insert_one(draft_doc)
                
                logger.info(f"Composed {len(emails_composed)} email drafts")
                
            except Exception as e:
                errors.append(f"Outreach composer error: {str(e)}")
                logger.error(f"Outreach composer failed: {e}")
            
            completed_steps += 1
            update_job_status(
                job_id,
                completed_steps=completed_steps,
                progress_percent=100,
                emails_composed=len(emails_composed)
            )
        
        # ========== COMPLETE ==========
        final_status = AgentStatus.COMPLETED.value if not errors else AgentStatus.COMPLETED.value
        
        update_job_status(
            job_id,
            status=final_status,
            completed_at=datetime.utcnow(),
            progress_percent=100,
            errors=errors if errors else None
        )
        
        broadcast_progress(job_id, {
            "status": "completed",
            "message": "Lead generation pipeline completed",
            "companies_found": len(companies_found),
            "contacts_found": len(contacts_found),
            "leads_enriched": len(leads_enriched),
            "leads_scored": len(leads_scored),
            "emails_composed": len(emails_composed),
            "duplicates_skipped": duplicates_skipped
        })
        
        return {
            'status': 'success',
            'job_id': job_id,
            'task_id': task_id,
            'companies_found': len(companies_found),
            'contacts_found': len(contacts_found),
            'leads_enriched': len(leads_enriched),
            'leads_scored': len(leads_scored),
            'emails_composed': len(emails_composed),
            'duplicates_skipped': duplicates_skipped,
            'errors': errors
        }
        
    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        
        update_job_status(
            job_id,
            status=AgentStatus.FAILED.value,
            completed_at=datetime.utcnow(),
            errors=[str(e)]
        )
        
        broadcast_progress(job_id, {
            "status": "failed",
            "message": f"Pipeline failed: {str(e)}"
        })
        
        return {
            'status': 'error',
            'job_id': job_id,
            'error': str(e)
        }


# ============== INDIVIDUAL AGENT TASKS ==============

@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_company_discovery',
    max_retries=3,
    default_retry_delay=30,
    rate_limit='10/m',
)
def run_company_discovery(
    self,
    job_id: str,
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Run Company Discovery Agent independently."""
    from agents import CompanyDiscoveryAgent
    
    try:
        agent = CompanyDiscoveryAgent(config)
        result = agent.execute(config, use_web_search=True)
        
        if result.success:
            return {
                'status': 'success',
                'job_id': job_id,
                'data': result.data,
                'tokens_used': result.tokens_used,
                'cost_usd': result.cost_usd
            }
        else:
            return {
                'status': 'error',
                'job_id': job_id,
                'error': result.error
            }
    except Exception as e:
        logger.error(f"Company discovery task failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_contact_finder',
    max_retries=3,
    default_retry_delay=30,
    rate_limit='10/m',
)
def run_contact_finder(
    self,
    job_id: str,
    company_name: str,
    company_domain: str = "",
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Run Contact Finder Agent for a single company."""
    from agents import ContactFinderAgent
    
    try:
        agent = ContactFinderAgent(config)
        result = agent.execute(
            {"company_name": company_name, "company_domain": company_domain},
            use_web_search=True
        )
        
        if result.success:
            return {
                'status': 'success',
                'job_id': job_id,
                'company': company_name,
                'data': result.data,
                'tokens_used': result.tokens_used,
                'cost_usd': result.cost_usd
            }
        else:
            return {
                'status': 'error',
                'job_id': job_id,
                'company': company_name,
                'error': result.error
            }
    except Exception as e:
        logger.error(f"Contact finder task failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_lead_enricher',
    max_retries=3,
    default_retry_delay=30,
    rate_limit='10/m',
)
def run_lead_enricher(
    self,
    job_id: str,
    leads: List[Dict[str, Any]],
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Run Lead Enricher Agent for a batch of leads."""
    from agents import LeadEnricherAgent
    
    try:
        agent = LeadEnricherAgent(config)
        result = agent.execute({"leads": leads}, use_web_search=True)
        
        if result.success:
            return {
                'status': 'success',
                'job_id': job_id,
                'data': result.data,
                'tokens_used': result.tokens_used,
                'cost_usd': result.cost_usd
            }
        else:
            return {
                'status': 'error',
                'job_id': job_id,
                'error': result.error
            }
    except Exception as e:
        logger.error(f"Lead enricher task failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_lead_scorer',
    max_retries=3,
    default_retry_delay=30,
    rate_limit='10/m',
)
def run_lead_scorer(
    self,
    job_id: str,
    leads: List[Dict[str, Any]],
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Run Lead Scorer Agent for a batch of leads."""
    from agents import LeadScorerAgent
    
    try:
        agent = LeadScorerAgent(config)
        result = agent.execute({"leads": leads}, use_web_search=False)
        
        if result.success:
            return {
                'status': 'success',
                'job_id': job_id,
                'data': result.data,
                'tokens_used': result.tokens_used,
                'cost_usd': result.cost_usd
            }
        else:
            return {
                'status': 'error',
                'job_id': job_id,
                'error': result.error
            }
    except Exception as e:
        logger.error(f"Lead scorer task failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(
    bind=True,
    name='backend.tasks.lead_agent_tasks.run_outreach_composer',
    max_retries=3,
    default_retry_delay=30,
    rate_limit='10/m',
)
def run_outreach_composer(
    self,
    job_id: str,
    leads: List[Dict[str, Any]],
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Run Outreach Composer Agent for a batch of leads."""
    from agents import OutreachComposerAgent
    
    try:
        agent = OutreachComposerAgent(config)
        result = agent.execute({"leads": leads}, use_web_search=False)
        
        if result.success:
            return {
                'status': 'success',
                'job_id': job_id,
                'data': result.data,
                'tokens_used': result.tokens_used,
                'cost_usd': result.cost_usd
            }
        else:
            return {
                'status': 'error',
                'job_id': job_id,
                'error': result.error
            }
    except Exception as e:
        logger.error(f"Outreach composer task failed: {e}")
        raise self.retry(exc=e)


# ============== QUOTA MANAGEMENT TASKS ==============

@celery_app.task(
    name='backend.tasks.lead_agent_tasks.reset_daily_quota',
)
def reset_daily_quota() -> Dict[str, Any]:
    """Reset daily lead quota at midnight. Schedule with Celery Beat."""
    try:
        db = get_agents_db()
        today = datetime.utcnow().date()
        
        db['scheduler_settings'].update_one(
            {"_id": "agent_quota"},
            {
                "$set": {
                    "date": str(today),
                    "leads_generated": 0,
                    "reset_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        logger.info("Daily lead quota reset successfully")
        return {'status': 'success', 'date': str(today)}
        
    except Exception as e:
        logger.error(f"Failed to reset quota: {e}")
        return {'status': 'error', 'error': str(e)}
