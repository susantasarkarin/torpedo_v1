"""
Outreach System Celery Tasks.
Background tasks for AI-powered cold outreach orchestration, scheduling, and webhook processing.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
try:
    from ai_governance.claude_gateway import AsyncClaudeChatClient
except ImportError:  # package context (tests import as backend.*)
    from backend.ai_governance.claude_gateway import AsyncClaudeChatClient

from celery_app import celery_app
from db_pools import get_background_db

logger = logging.getLogger(__name__)


def _to_object_id(value: Any) -> Any:
	if isinstance(value, ObjectId):
		return value
	if isinstance(value, str) and ObjectId.is_valid(value):
		return ObjectId(value)
	return value


def _safe_email_recipient(email_doc: dict) -> str:
	return (
		email_doc.get("to_email")
		or email_doc.get("recipient_email")
		or email_doc.get("contact_email")
		or ""
	)


@celery_app.task(
	bind=True,
	name="backend.tasks.outreach_tasks.schedule_campaign_batch_task",
	max_retries=2,
	default_retry_delay=30,
	autoretry_for=(Exception,),
	retry_backoff=True,
	queue="api_tasks",
	routing_key="outreach.schedule",
)
def schedule_campaign_batch_task(
	self,
	campaign_id: str,
	organization_id: str,
	batch_size: int = 100,
) -> Dict[str, Any]:
	"""Schedule a batch of queued campaign leads for outreach."""
	from app.services.outreach import OutreachSchedulerService

	task_id = self.request.id
	db = get_background_db()
	scheduler_service = OutreachSchedulerService(db)

	result = scheduler_service.schedule_campaign_batch(
		campaign_id=campaign_id,
		batch_size=batch_size,
	)

	scheduled_count = int(result.get("scheduled", 0)) if result.get("success") else 0
	logger.info("Scheduled %s leads for campaign %s", scheduled_count, campaign_id)

	return {
		"status": "success" if result.get("success") else "error",
		"campaign_id": campaign_id,
		"organization_id": organization_id,
		"scheduled_count": scheduled_count,
		"details": result,
		"task_id": task_id,
		"completed_at": datetime.utcnow().isoformat(),
	}


@celery_app.task(
	bind=True,
	name="backend.tasks.outreach_tasks.send_scheduled_emails_task",
	max_retries=2,
	default_retry_delay=60,
	autoretry_for=(Exception,),
	retry_backoff=True,
	queue="api_tasks",
	routing_key="outreach.send",
)
def send_scheduled_emails_task(
	self,
	organization_id: str,
	limit: int = 50,
) -> Dict[str, Any]:
	"""Send due scheduled emails for an organization."""
	import asyncio

	from app.services.outreach import EmailSenderService, OutreachSchedulerService, SenderAccount

	task_id = self.request.id
	db = get_background_db()

	scheduler = OutreachSchedulerService(db)
	email_sender = EmailSenderService(tracking_domain=os.getenv("TRACKING_DOMAIN"))

	due_emails = scheduler.get_due_emails(limit=limit)

	sent_count = 0
	failed_count = 0
	skipped_count = 0
	errors: list[dict] = []

	emails_col = db["outreach_emails"]
	senders_col = db["outreach_senders"]

	for email_doc in due_emails:
		if organization_id and str(email_doc.get("organization_id", "")) != str(organization_id):
			skipped_count += 1
			continue

		email_id = email_doc.get("_id")
		sender_raw_id = _to_object_id(email_doc.get("sender_id"))
		if not sender_raw_id:
			skipped_count += 1
			errors.append({"email_id": str(email_id), "error": "Missing sender_id"})
			continue

		sender_doc = senders_col.find_one({"_id": sender_raw_id})
		if not sender_doc:
			failed_count += 1
			errors.append({"email_id": str(email_id), "error": "Sender not found"})
			continue

		try:
			sender_payload = dict(sender_doc)
			sender_payload["id"] = str(sender_payload.pop("_id"))
			sender = SenderAccount(**sender_payload)

			recipient = _safe_email_recipient(email_doc)
			subject = email_doc.get("subject", "")
			body_text = email_doc.get("body_text") or email_doc.get("body") or ""
			body_html = email_doc.get("body_html")
			tracking_id = email_doc.get("tracking_id") or str(email_id)

			result = asyncio.run(
				email_sender.send_email(
					sender=sender,
					to_email=recipient,
					subject=subject,
					body_text=body_text,
					body_html=body_html,
					tracking_id=tracking_id,
				)
			)

			if result.success:
				now = datetime.utcnow()
				emails_col.update_one(
					{"_id": email_id},
					{
						"$set": {
							"status": "sent",
							"sent_at": now,
							"updated_at": now,
							"provider": result.provider,
							"provider_message_id": result.message_id,
						}
					},
				)
				senders_col.update_one(
					{"_id": sender_raw_id},
					{
						"$inc": {"daily_sent_count": 1, "hourly_sent_count": 1},
						"$set": {"last_send_time": now, "updated_at": now},
					},
				)
				sent_count += 1
			else:
				failed_count += 1
				emails_col.update_one(
					{"_id": email_id},
					{
						"$set": {
							"status": "failed",
							"error_message": result.error,
							"updated_at": datetime.utcnow(),
						}
					},
				)
				errors.append({"email_id": str(email_id), "error": result.error})

		except Exception as exc:
			failed_count += 1
			errors.append({"email_id": str(email_id), "error": str(exc)})
			logger.exception("Failed to send scheduled email %s", email_id)

	return {
		"status": "success",
		"organization_id": organization_id,
		"sent_count": sent_count,
		"failed_count": failed_count,
		"skipped_count": skipped_count,
		"task_id": task_id,
		"completed_at": datetime.utcnow().isoformat(),
		"errors": errors,
	}


@celery_app.task(
	bind=True,
	name="backend.tasks.outreach_tasks.process_webhook_event_task",
	max_retries=1,
	default_retry_delay=10,
	autoretry_for=(Exception,),
	retry_backoff=True,
	queue="api_tasks",
	routing_key="outreach.webhook",
)
def process_webhook_event_task(
	self,
	event_type: str,
	provider_data: Dict[str, Any],
) -> Dict[str, Any]:
	"""Process webhook events from email providers."""
	from app.services.outreach import OutreachWebhookHandler

	task_id = self.request.id
	db = get_background_db()
	webhook_handler = OutreachWebhookHandler(db)

	if event_type == "open":
		tracking_id = provider_data.get("tracking_id")
		result = webhook_handler.handle_open(tracking_id)
	elif event_type == "click":
		tracking_id = provider_data.get("tracking_id")
		result = webhook_handler.handle_click(tracking_id, provider_data.get("url", ""))
	elif event_type == "bounce":
		result = webhook_handler.handle_bounce(
			provider_data.get("message_id", ""),
			provider_data.get("reason", "unknown"),
		)
	elif event_type == "complaint":
		result = webhook_handler.handle_complaint(
			provider_data.get("message_id", ""),
			provider_data.get("reason", "unknown"),
		)
	elif event_type == "reply":
		result = webhook_handler.handle_reply(
			provider_data.get("message_id"),
			provider_data.get("from_email", ""),
			provider_data.get("body_text", ""),
			provider_data.get("subject", ""),
		)
	else:
		result = {"success": False, "reason": f"Unknown event type: {event_type}"}

	return {
		"status": "success" if result.get("success") else "error",
		"event_type": event_type,
		"result": result,
		"task_id": task_id,
		"processed_at": datetime.utcnow().isoformat(),
	}


@celery_app.task(
	bind=True,
	name="backend.tasks.outreach_tasks.process_outreach_lead_task",
	max_retries=2,
	default_retry_delay=60,
	autoretry_for=(Exception,),
	retry_backoff=True,
	queue="api_tasks",
	routing_key="outreach.process",
)
def process_outreach_lead_task(
	self,
	lead_id: str,
	company_data: Dict[str, Any],
	organization_id: str,
) -> Dict[str, Any]:
	"""Async wrapper for processing a new lead through the outreach pipeline."""
	import asyncio

	from app.services.outreach import CompanyData, OutreachOrchestrator

	task_id = self.request.id
	db = get_background_db()

	async def _run() -> Dict[str, Any]:
		ai_client = AsyncClaudeChatClient()  # governed Claude client via ai_governance
		orchestrator = OutreachOrchestrator(ai_client=ai_client, db=db)

		lead_doc = db["outreach_leads"].find_one({"_id": _to_object_id(lead_id)}) or {}

		company_payload = {
			"company_name": company_data.get("company_name") or lead_doc.get("company_name") or "Unknown",
			"website_text": company_data.get("website_text", ""),
			"about_text": company_data.get("about_text", ""),
			"careers_page": company_data.get("careers_page", ""),
			"recent_news": company_data.get("recent_news", ""),
			"industry": company_data.get("industry", ""),
			"company_size": company_data.get("company_size", ""),
			"trigger_event": company_data.get("trigger_event", ""),
			"linkedin_data": company_data.get("linkedin_data"),
			"additional_context": company_data.get("additional_context"),
		}

		result = await orchestrator.process_new_lead(
			company_data=CompanyData(**company_payload),
			contact_name=company_data.get("contact_name") or lead_doc.get("contact_name") or "there",
			contact_role=company_data.get("contact_role") or lead_doc.get("contact_role") or "",
			contact_email=company_data.get("contact_email") or lead_doc.get("contact_email") or "",
			campaign_positioning=company_data.get("campaign_positioning", ""),
			cta_style=company_data.get("cta_style", "soft"),
			sender_name=company_data.get("sender_name", ""),
			sender_title=company_data.get("sender_title", ""),
			sender_company=company_data.get("sender_company", ""),
			recipient_timezone=company_data.get("recipient_timezone", "UTC"),
		)

		now = datetime.utcnow()
		db["outreach_leads"].update_one(
			{"_id": _to_object_id(lead_id)},
			{
				"$set": {
					"organization_id": organization_id,
					"lead_score": result.lead_score,
					"outreach_action": result.action,
					"outreach_reason": result.reason,
					"updated_at": now,
				}
			},
		)

		if result.success and result.email:
			db["outreach_emails"].insert_one(
				{
					"lead_id": lead_id,
					"organization_id": organization_id,
					"to_email": company_data.get("contact_email") or lead_doc.get("contact_email"),
					"subject": result.email.subject,
					"body": result.email.body,
					"body_text": result.email.body,
					"status": "queued",
					"scheduled_for": now,
					"sender_id": result.sender_allocation.selected_sender_id if result.sender_allocation else None,
					"tracking_id": str(ObjectId()),
					"created_at": now,
					"updated_at": now,
				}
			)

		return {
			"status": "success" if result.success else "partial",
			"lead_id": lead_id,
			"organization_id": organization_id,
			"action": result.action,
			"reason": result.reason,
			"lead_score": result.lead_score,
			"email_generated": bool(result.email),
			"task_id": task_id,
			"completed_at": now.isoformat(),
		}

	return asyncio.run(_run())