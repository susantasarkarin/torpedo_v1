"""
Outreach scheduler service.

Schedules queued outreach emails with send-window and quota checks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class OutreachSchedulerService:
	"""Mongo-backed scheduling utility for outreach emails."""

	def __init__(self, db: Any):
		self.db = db
		self.emails = db["outreach_emails"]
		self.leads = db["outreach_leads"]
		self.campaigns = db["outreach_campaigns"]
		self.senders = db["outreach_senders"]

	def schedule_campaign_batch(self, campaign_id: str, batch_size: int = 50) -> dict:
		campaign = self.campaigns.find_one({"_id": campaign_id})
		if not campaign:
			return {"success": False, "reason": "Campaign not found"}

		queued_leads = list(
			self.leads.find(
				{
					"campaign_id": campaign_id,
					"status": {"$in": ["queued", "scored"]},
					"$or": [{"next_action_at": None}, {"next_action_at": {"$lte": datetime.utcnow()}}],
				}
			).limit(batch_size)
		)

		if not queued_leads:
			return {"success": True, "scheduled": 0}

		scheduled = 0
		for lead in queued_leads:
			sender = self._allocate_sender(campaign.get("organization_id"))
			if not sender:
				continue

			send_at = self._next_send_time(
				start_hour=campaign.get("send_start_hour", 8),
				end_hour=campaign.get("send_end_hour", 18),
				blocked_days=campaign.get("send_days_blocked", [5, 6]),
			)

			self.emails.update_many(
				{
					"lead_id": str(lead.get("_id")),
					"status": "queued",
					"$or": [{"scheduled_for": None}, {"scheduled_for": {"$exists": False}}],
				},
				{
					"$set": {
						"scheduled_for": send_at,
						"sender_id": str(sender.get("_id")),
						"updated_at": datetime.utcnow(),
					}
				},
			)

			self.leads.update_one(
				{"_id": lead["_id"]},
				{"$set": {"status": "scheduled", "updated_at": datetime.utcnow()}},
			)
			scheduled += 1

		logger.info("Scheduled %s leads for campaign %s", scheduled, campaign_id)
		return {"success": True, "scheduled": scheduled}

	def get_due_emails(self, limit: int = 100) -> list[dict]:
		now = datetime.utcnow()
		return list(
			self.emails.find(
				{
					"status": "queued",
					"$or": [{"scheduled_for": None}, {"scheduled_for": {"$lte": now}}],
				}
			)
			.sort("scheduled_for", 1)
			.limit(limit)
		)

	def defer_email(self, email_id: str, minutes: int = 30) -> None:
		self.emails.update_one(
			{"_id": email_id},
			{
				"$set": {
					"scheduled_for": datetime.utcnow() + timedelta(minutes=minutes),
					"updated_at": datetime.utcnow(),
				}
			},
		)

	def _allocate_sender(self, organization_id: Optional[str]) -> Optional[dict]:
		query: dict = {"is_active": True}
		if organization_id:
			query["organization_id"] = organization_id

		return self.senders.find_one(
			{
				**query,
				"health_score": {"$gte": 70},
				"$expr": {"$lt": ["$daily_sent_count", "$daily_limit"]},
			},
			sort=[("health_score", -1), ("daily_sent_count", 1)],
		)

	@staticmethod
	def _next_send_time(start_hour: int, end_hour: int, blocked_days: list[int]) -> datetime:
		now = datetime.now(timezone.utc)
		candidate = now

		if candidate.hour < start_hour:
			candidate = candidate.replace(hour=start_hour, minute=0, second=0, microsecond=0)
		elif candidate.hour >= end_hour:
			candidate = (candidate + timedelta(days=1)).replace(
				hour=start_hour,
				minute=0,
				second=0,
				microsecond=0,
			)

		while candidate.weekday() in blocked_days:
			candidate = (candidate + timedelta(days=1)).replace(
				hour=start_hour,
				minute=0,
				second=0,
				microsecond=0,
			)

		return candidate.replace(tzinfo=None)

