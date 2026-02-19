"""
Outreach System Celery Tasks
Background tasks for AI-powered cold outreach orchestration, scheduling, and webhook processing
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from celery_app import celery_app
from db_pools import get_background_db, get_background_collection

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name='backend.tasks.outreach_tasks.schedule_campaign_batch_task',
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    queue='api_tasks',
    routing_key='outreach.schedule',
)
def schedule_campaign_batch_task(
    self,
    campaign_id: str,
    organization_id: str,
    batch_size: int = 100
) -> Dict[str, Any]:
    """
    Schedule a batch of queued campaign leads for outreach.
    
    Args:
        campaign_id: MongoDB ObjectId of the campaign
        organization_id: MongoDB ObjectId of the organization
        batch_size: Number of leads to schedule per batch (default 100)
        
    Returns:
        Scheduling result with count and status
    """
    from bson import ObjectId
    from app.services.outreach import OutreachSchedulerService
    
    task_id = self.request.id
    
    try:
        db = get_background_db()
        scheduler_service = OutreachSchedulerService(db)
        
        # Schedule the campaign batch (sync method)
        scheduled_count = scheduler_service.schedule_campaign_batch(
            campaign_id=campaign_id,
            organization_id=organization_id,
            batch_size=batch_size
        )
        
        logger.info(f"✅ Scheduled {scheduled_count} leads for campaign {campaign_id}")
        
        return {
            'status': 'success',
            'campaign_id': campaign_id,
            'scheduled_count': scheduled_count,
            'task_id': task_id,
            'completed_at': datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ Schedule batch failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'campaign_id': campaign_id,
            'task_id': task_id
        }


@celery_app.task(
    bind=True,
    name='backend.tasks.outreach_tasks.send_scheduled_emails_task',
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    queue='api_tasks',
    routing_key='outreach.send',
)
def send_scheduled_emails_task(
    self,
    organization_id: str,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Send scheduled outreach emails for an organization.
    Runs async operations within the sync Celery task using asyncio.run().
    
    Args:
        organization_id: MongoDB ObjectId of the organization
        limit: Max number of emails to send in this batch (default 50)
        
    Returns:
        Send result with success/failure counts
    """
    from bson import ObjectId
    from app.services.outreach import (
        OutreachSchedulerService,
        OutreachOrchestrator,
        EmailSenderService
    )
    
    task_id = self.request.id
    
    def _run_async_sends():
        """Wrapper to run async email sends"""
        return asyncio.run(_execute_sends(organization_id, limit))
    
    async def _execute_sends(org_id: str, send_limit: int):
        """Async implementation of email sending"""
        db = get_background_db()
        
        # Get due emails
        scheduler = OutreachSchedulerService(db)
        due_emails = scheduler.get_due_emails(
            organization_id=org_id,
            limit=send_limit
        )
        
        email_sender = EmailSenderService(db)
        orchestrator = OutreachOrchestrator(
            ai_client=None,  # Not needed for sending; already generated emails
            db=db,
            lead_intelligence_service=None,
            email_generator_service=None,
            reply_handler_service=None,
            sender_manager_service=None,
            guardrails_service=None,
            optimizer_service=None
        )
        
        sent_count = 0
        failed_count = 0
        errors = []
        
        for email_doc in due_emails:
            try:
                # Get the sender account
                from bson import ObjectId
                sender_id = ObjectId(email_doc['sender_id'])
                senders_col = db['outreach_senders']
                sender_account = senders_col.find_one({'_id': sender_id})
                
                if not sender_account:
                    logger.warning(f"Sender not found: {sender_id}")
                    failed_count += 1
                    continue
                
                # Convert to SenderAccount model
                from app.services.outreach import SenderAccount
                sender = SenderAccount(**sender_account)
                
                # Send email
                result = await email_sender.send_email(
                    sender_account=sender,
                    recipient_email=email_doc['recipient_email'],
                    subject=email_doc['subject'],
                    body_text=email_doc.get('body_text', ''),
                    body_html=email_doc.get('body_html'),
                    tracking_id=str(email_doc['_id']),
                    tracking_domain=None  # Could be configured
                )
                
                if result.success:
                    # Record the send
                    orchestrator.record_send(
                        email_id=str(email_doc['_id']),
                        provider_message_id=result.message_id,
                        timestamp=datetime.utcnow()
                    )
                    sent_count += 1
                    logger.info(f"✅ Sent email {email_doc['_id']} to {email_doc['recipient_email']}")
                else:
                    failed_count += 1
                    errors.append({
                        'email_id': str(email_doc['_id']),
                        'error': result.error
                    })
                    logger.warning(f"Failed to send email {email_doc['_id']}: {result.error}")
            
            except Exception as e:
                failed_count += 1
                errors.append({
                    'email_id': str(email_doc.get('_id', 'unknown')),
                    'error': str(e)
                })
                logger.error(f"Error sending email: {e}")
        
        return {
            'sent_count': sent_count,
            'failed_count': failed_count,
            'errors': errors
        }
    
    try:
        # Execute async sends
        result = _run_async_sends()
        
        logger.info(f"✅ Send batch complete: {result['sent_count']} sent, {result['failed_count']} failed")
        
        return {
            'status': 'success',
            'organization_id': organization_id,
            'sent_count': result['sent_count'],
            'failed_count': result['failed_count'],
            'task_id': task_id,
            'completed_at': datetime.utcnow().isoformat(),
            'errors': result['errors'] if result['failed_count'] > 0 else None
        }
    
    except Exception as e:
        logger.error(f"❌ Send scheduled emails failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'organization_id': organization_id,
            'task_id': task_id
        }


@celery_app.task(
    bind=True,
    name='backend.tasks.outreach_tasks.process_webhook_event_task',
    max_retries=1,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
    queue='api_tasks',
    routing_key='outreach.webhook',
)
def process_webhook_event_task(
    self,
    event_type: str,
    provider_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process incoming webhook events from email providers (SES, SendGrid, etc.).
    
    Args:
        event_type: Type of event ('open', 'click', 'bounce', 'complaint', 'reply')
        provider_data: Provider-specific event data
        
    Returns:
        Processing result with status
    """
    from app.services.outreach import OutreachWebhookHandler
    
    task_id = self.request.id
    
    try:
        db = get_background_db()
        webhook_handler = OutreachWebhookHandler(db)
        
        # Route event to appropriate handler
        if event_type == 'open':
            tracking_id = provider_data.get('tracking_id')
            if not tracking_id:
                return {'status': 'error', 'error': 'Missing tracking_id for open event'}
            webhook_handler.handle_open(tracking_id)
        
        elif event_type == 'click':
            tracking_id = provider_data.get('tracking_id')
            url = provider_data.get('url')
            if not tracking_id:
                return {'status': 'error', 'error': 'Missing tracking_id for click event'}
            webhook_handler.handle_click(tracking_id, url)
        
        elif event_type == 'bounce':
            message_id = provider_data.get('message_id')
            reason = provider_data.get('reason', 'unknown')
            if not message_id:
                return {'status': 'error', 'error': 'Missing message_id for bounce event'}
            webhook_handler.handle_bounce(message_id, reason)
        
        elif event_type == 'complaint':
            message_id = provider_data.get('message_id')
            reason = provider_data.get('reason', 'unknown')
            if not message_id:
                return {'status': 'error', 'error': 'Missing message_id for complaint event'}
            webhook_handler.handle_complaint(message_id, reason)
        
        elif event_type == 'reply':
            message_id = provider_data.get('message_id')
            from_email = provider_data.get('from_email')
            body_text = provider_data.get('body_text', '')
            if not message_id:
                return {'status': 'error', 'error': 'Missing message_id for reply event'}
            webhook_handler.handle_reply(message_id, from_email, body_text)
        
        else:
            return {'status': 'error', 'error': f'Unknown event type: {event_type}'}
        
        logger.info(f"✅ Processed {event_type} webhook event")
        
        return {
            'status': 'success',
            'event_type': event_type,
            'task_id': task_id,
            'processed_at': datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ Webhook processing failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'event_type': event_type,
            'task_id': task_id
        }


@celery_app.task(
    bind=True,
    name='backend.tasks.outreach_tasks.process_outreach_lead_task',
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    queue='api_tasks',
    routing_key='outreach.process',
)
def process_outreach_lead_task(
    self,
    lead_id: str,
    company_data: Dict[str, Any],
    organization_id: str
) -> Dict[str, Any]:
    """
    Async wrapper for processing a new lead through the full outreach pipeline.
    
    Args:
        lead_id: MongoDB ObjectId of the lead
        company_data: Company intelligence data (from lead_intelligence service)
        organization_id: MongoDB ObjectId of the organization
        
    Returns:
        Processing result with email and next actions
    """
    task_id = self.request.id
    
    def _run_async_processing():
        """Wrapper to run async lead processing"""
        return asyncio.run(_execute_processing(lead_id, company_data, organization_id))
    
    async def _execute_processing(l_id: str, c_data: Dict, o_id: str):
        """Async implementation of lead processing"""
        from app.services.outreach import OutreachOrchestrator
        from openai import AsyncOpenAI
        
        openai_client = AsyncOpenAI()
        db = get_background_db()
        
        # Create orchestrator with all services
        orchestrator = OutreachOrchestrator(
            ai_client=openai_client,
            db=db
        )
        
        # Process the lead through the full pipeline
        result = await orchestrator.process_new_lead(
            lead_id=l_id,
            company_data=c_data,
            organization_id=o_id
        )
        
        return result
    
    try:
        # Execute async processing
        result = _run_async_processing()
        
        logger.info(f"✅ Processed lead {lead_id}: {result.success}")
        
        return {
            'status': 'success' if result.success else 'partial',
            'lead_id': lead_id,
            'email_generated': bool(result.email),
            'next_action': result.recommended_action,
            'task_id': task_id,
            'completed_at': datetime.utcnow().isoformat(),
            'metadata': result.metadata
        }
    
    except Exception as e:
        logger.error(f"❌ Lead processing failed for {lead_id}: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'lead_id': lead_id,
            'task_id': task_id
        }
