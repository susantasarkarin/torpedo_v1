"""
Core Celery Tasks for Email Processing & Outreach.

Handles asynchronous email sending, enrichment, and campaign automation.
"""

import logging
import asyncio
from typing import Optional
from datetime import datetime, timedelta

from celery import shared_task, Task
try:
    from ai_governance.claude_gateway import AsyncClaudeChatClient
except ImportError:  # package context (tests import as backend.*)
    from backend.ai_governance.claude_gateway import AsyncClaudeChatClient
import os

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code in sync Celery context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# =============================================================================
# Email Processing Tasks
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_email_queue(self):
    """
    Process queued emails and send them.
    
    This runs every minute and processes emails that are:
    - Status = QUEUED
    - scheduled_for <= now
    """
    logger.info("Processing email queue...")
    
    try:
        # TODO: Implement with actual database query
        # For now, just log that the task ran
        logger.info("Email queue processed successfully")
        return {"status": "success", "emails_processed": 0}
        
    except Exception as e:
        logger.error(f"Error processing email queue: {e}")
        self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def send_email_task(self, email_id: str, recipient: str, subject: str, body: str):
    """
    Send a single email.
    
    In production, integrate with:
    - SMTP
    - SendGrid
    - Mailgun
    - Amazon SES
    """
    logger.info(f"Sending email {email_id} to {recipient}")
    
    try:
        # TODO: Implement actual email sending
        # For now, just log the action
        logger.info(f"Email sent successfully: {email_id}")
        
        return {
            "success": True,
            "email_id": email_id,
            "recipient": recipient,
            "sent_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to send email {email_id}: {e}")
        self.retry(exc=e)


@shared_task(bind=True)
def process_followups(self):
    """
    Process follow-up emails for leads.
    
    Finds leads that:
    - Have been contacted
    - Haven't replied
    - next_action_at <= now
    - Haven't exceeded max follow-ups
    """
    logger.info("Processing follow-ups...")
    
    try:
        # TODO: Query database for leads needing follow-ups
        # then call generate_followup_task for each
        logger.info("Follow-ups processed successfully")
        return {"status": "success", "leads_processed": 0}
        
    except Exception as e:
        logger.error(f"Error processing follow-ups: {e}")


@shared_task(bind=True, max_retries=2)
def generate_followup_task(self, lead_id: str, contact_email: str, company_name: str):
    """
    Generate and queue a follow-up email for a lead.
    """
    logger.info(f"Generating follow-up for lead {lead_id} ({contact_email})")
    
    async def _generate():
        try:
            ai_client = AsyncClaudeChatClient()  # governed Claude client via ai_governance
            
            from app.services.outreach import (
                EmailGeneratorService,
                FollowUpRequest,
                GeneratedEmail
            )
            
            email_service = EmailGeneratorService(ai_client)
            
            # Create stub original email (in production, fetch from DB)
            original_email = GeneratedEmail(
                subject="[Previous subject]",
                body="[Previous body]"
            )
            
            # Generate follow-up
            followup_request = FollowUpRequest(
                original_email=original_email,
                days_since_sent=3,
                open_count=0,
                contact_name=contact_email.split("@")[0],
                company_name=company_name
            )
            
            followup = await email_service.generate_followup(followup_request)
            
            logger.info(f"Follow-up generated for {lead_id}")
            
            # Queue for sending
            send_email_task.delay(
                lead_id,
                contact_email,
                followup.subject,
                followup.body
            )
            
            return {"success": True, "lead_id": lead_id}
            
        except Exception as e:
            logger.error(f"Failed to generate follow-up for {lead_id}: {e}")
            raise
    
    return run_async(_generate())


# =============================================================================
# Lead Enrichment Tasks
# =============================================================================

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def enrich_lead_task(self, lead_id: str, company_name: str, website_url: str = None):
    """
    Enrich a lead with AI intelligence and score.
    """
    logger.info(f"Enriching lead {lead_id}: {company_name}")
    
    async def _enrich():
        try:
            ai_client = AsyncClaudeChatClient()  # governed Claude client via ai_governance
            
            from app.services.outreach import (
                LeadIntelligenceService,
                CompanyData
            )
            
            intelligence_service = LeadIntelligenceService(ai_client)
            
            # Build company data (in production, fetch from database/scraping)
            company_data = CompanyData(
                company_name=company_name,
                website_text="[Website content would be scraped here]",
                industry="",
                company_size=""
            )
            
            # Extract and score
            intelligence, score = await intelligence_service.extract_and_score(company_data)
            
            logger.info(f"Lead {lead_id} scored: {score.lead_score}")
            
            # If score is good, queue for email generation
            if score.should_outreach:
                generate_outreach_email_task.delay(lead_id, company_name)
            
            return {
                "success": True,
                "lead_id": lead_id,
                "score": score.lead_score,
                "tier": score.priority_tier
            }
            
        except Exception as e:
            logger.error(f"Failed to enrich lead {lead_id}: {e}")
            raise
    
    return run_async(_enrich())


@shared_task(bind=True, max_retries=1)
def generate_outreach_email_task(self, lead_id: str, company_name: str, contact_email: str = ""):
    """
    Generate an outreach email for an enriched lead.
    """
    logger.info(f"Generating outreach email for {lead_id}")
    
    async def _generate():
        try:
            ai_client = AsyncClaudeChatClient()  # governed Claude client via ai_governance
            
            from app.services.outreach import (
                EmailGeneratorService,
                EmailGenerationRequest,
                LeadIntelligence,
                BuyerPersona,
                HiringSignals
            )
            
            email_service = EmailGeneratorService(ai_client)
            
            # Create stub intelligence (in production, retrieve from previous enrichment)
            intelligence = LeadIntelligence(
                growth_stage="Scaling",
                business_priorities=["Growth", "Efficiency"],
                hiring_signals=HiringSignals(active=False),
                expansion_indicators=[],
                operational_bottlenecks=["Outreach automation"],
                revenue_pressure=7,
                buyer_persona=BuyerPersona(
                    title="VP of Sales",
                    reasoning="Responsible for revenue growth"
                ),
                urgency_score=8,
                personalization_hooks=[]
            )
            
            # Generate email
            email_request = EmailGenerationRequest(
                contact_name="Contact",
                contact_role="VP Sales",
                company_name=company_name,
                intelligence=intelligence,
                campaign_positioning="Sales automation and outreach optimization"
            )
            
            email, spam_result = await email_service.generate_and_validate(email_request)
            
            if email and spam_result.is_safe_to_send:
                logger.info(f"Email generated for {lead_id}, queuing for send")
                
                # Queue email for sending
                send_email_task.delay(
                    lead_id,
                    contact_email or "contact@example.com",
                    email.subject,
                    email.body
                )
                
                return {"success": True, "lead_id": lead_id, "email_generated": True}
            else:
                logger.warning(f"Email for {lead_id} failed spam check")
                return {"success": False, "lead_id": lead_id, "reason": "Spam check failed"}
            
        except Exception as e:
            logger.error(f"Failed to generate email for {lead_id}: {e}")
            raise
    
    return run_async(_generate())


# =============================================================================
# Maintenance Tasks
# =============================================================================

@shared_task
def reset_daily_limits():
    """Reset daily sending limits for all senders."""
    logger.info("Resetting daily sending limits...")
    # TODO: Update database to reset daily counts
    return {"status": "success"}


@shared_task
def reset_hourly_limits():
    """Reset hourly sending limits for all senders."""
    logger.info("Resetting hourly sending limits...")
    # TODO: Update database to reset hourly counts
    return {"status": "success"}


@shared_task
def check_sender_health():
    """Check and update sender account health."""
    logger.info("Checking sender health...")
    # TODO: Query database for sender metrics and update health scores
    return {"status": "success"}


@shared_task
def cleanup_old_data():
    """Clean up old email events and logs."""
    logger.info("Cleaning up old data...")
    cutoff_date = datetime.utcnow() - timedelta(days=90)
    # TODO: Delete old email events before cutoff_date
    return {"status": "success", "cleaned_until": cutoff_date.isoformat()}


@shared_task
def generate_campaign_report(campaign_id: str):
    """Generate weekly or daily campaign report."""
    logger.info(f"Generating report for campaign {campaign_id}")
    # TODO: Aggregate campaign metrics and generate AI-powered insights
    return {"status": "success", "campaign_id": campaign_id}


# =============================================================================
# Process Reply Tasks
# =============================================================================

@shared_task(bind=True, max_retries=1)
def process_reply_task(self, from_email: str, subject: str, body: str):
    """
    Process an incoming email reply.
    """
    logger.info(f"Processing reply from {from_email}")
    
    async def _process():
        try:
            ai_client = AsyncClaudeChatClient()  # governed Claude client via ai_governance
            
            from app.services.outreach import (
                ReplyHandlerService,
                ReplyContext
            )
            
            reply_service = ReplyHandlerService(ai_client)
            
            context = ReplyContext(
                reply_text=body,
                original_email_subject=subject,
                original_email_body="[Original email]",
                contact_name=from_email.split("@")[0],
                company_name=""
            )
            
            # Classify reply
            classification = await reply_service.classify_reply(context)
            
            logger.info(f"Reply classified as: {classification.classification}")
            
            # TODO: Update database with classification
            # TODO: Generate auto-response if appropriate
            
            return {
                "success": True,
                "from_email": from_email,
                "classification": classification.classification,
                "confidence": classification.confidence
            }
            
        except Exception as e:
            logger.error(f"Failed to process reply from {from_email}: {e}")
            raise
    
    return run_async(_process())
