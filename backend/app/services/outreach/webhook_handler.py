"""
Outreach webhook event handler.

Processes provider events and updates outreach state in Mongo collections.
Includes hard/soft bounce classification and soft-bounce retry logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

SOFT_BOUNCE_MAX_RETRIES = 3
SOFT_BOUNCE_RETRY_HOURS = [24, 48, 72]  # hours after first bounce for each retry


class BounceType(str, Enum):
	HARD = "hard"
	SOFT = "soft"


def classify_bounce(reason: str = "", smtp_code: int = 0, sns_bounce_type: str = "") -> BounceType:
	"""Classify a bounce as hard or soft using SMTP codes, SNS type, and keyword fallback."""
	# SNS bounce type takes precedence
	if sns_bounce_type:
		sbt = sns_bounce_type.lower()
		if sbt in ("permanent", "undetermined"):
			return BounceType.HARD
		if sbt == "transient":
			return BounceType.SOFT

	# SMTP code classification
	if smtp_code:
		if 500 <= smtp_code <= 599:
			return BounceType.HARD
		if 400 <= smtp_code <= 499:
			return BounceType.SOFT

	# Keyword fallback
	reason_lower = (reason or "").lower()
	hard_keywords = ["invalid", "does not exist", "user unknown", "no such user",
					  "rejected", "permanently", "disabled", "deactivated"]
	soft_keywords = ["full", "over quota", "temporarily", "try again", "rate limit",
					 "connection", "timeout", "unavailable", "busy"]

	if any(kw in reason_lower for kw in hard_keywords):
		return BounceType.HARD
	if any(kw in reason_lower for kw in soft_keywords):
		return BounceType.SOFT

	# Default to hard (safe side — prevents repeated sends to bad addresses)
	return BounceType.HARD


class OutreachWebhookHandler:
	"""Normalize inbound provider events into outreach collections."""

	def __init__(self, db: Any):
		self.db = db
		self.emails = db["outreach_emails"]
		self.events = db["outreach_events"]
		self.leads = db["outreach_leads"]
		self.senders = db["outreach_senders"]

	def handle_open(self, tracking_id: str, meta: Optional[dict] = None) -> dict:
		return self._handle_event("opened", tracking_id, meta=meta)

	def handle_click(self, tracking_id: str, url: str, meta: Optional[dict] = None) -> dict:
		payload = dict(meta or {})
		payload["url"] = url
		return self._handle_event("clicked", tracking_id, meta=payload)

	def handle_bounce(
		self,
		provider_message_id: str,
		reason: str = "",
		smtp_code: int = 0,
		sns_bounce_type: str = "",
	) -> dict:
		email = self.emails.find_one({"provider_message_id": provider_message_id})
		if not email:
			return {"success": False, "reason": "email_not_found"}

		bounce_type = classify_bounce(reason, smtp_code, sns_bounce_type)

		if bounce_type == BounceType.SOFT:
			return self._handle_soft_bounce(email, reason=reason)

		return self._apply_terminal_event(email, event_type="bounced", reason=reason,
										  extra={"bounce_type": "hard"})

	def handle_complaint(self, provider_message_id: str, reason: str = "") -> dict:
		email = self.emails.find_one({"provider_message_id": provider_message_id})
		if not email:
			return {"success": False, "reason": "email_not_found"}
		return self._apply_terminal_event(email, event_type="complained", reason=reason)

	def handle_reply(
		self,
		provider_message_id: Optional[str],
		from_email: str,
		body_text: str,
		subject: str = "",
	) -> dict:
		email = None
		if provider_message_id:
			email = self.emails.find_one({"provider_message_id": provider_message_id})
		if not email:
			email = self.emails.find_one({"to_email": from_email}, sort=[("sent_at", -1)])
		if not email:
			return {"success": False, "reason": "email_not_found"}

		now = datetime.utcnow()
		self.emails.update_one(
			{"_id": email["_id"]},
			{
				"$set": {
					"status": "replied",
					"replied_at": now,
					"updated_at": now,
				}
			},
		)

		self._insert_event(
			email_id=str(email["_id"]),
			event_type="replied",
			payload={"from_email": from_email, "subject": subject, "body": body_text[:4000]},
		)

		if email.get("lead_id"):
			self.leads.update_one(
				{"_id": email["lead_id"]},
				{"$set": {"status": "replied", "replied_at": now, "next_action_at": None}},
			)

		return {"success": True, "email_id": str(email["_id"]), "event": "replied"}

	# ------------------------------------------------------------------
	# Soft bounce handling with retry logic
	# ------------------------------------------------------------------

	def _handle_soft_bounce(self, email: dict, reason: str = "") -> dict:
		"""Soft bounce: schedule retry or escalate to hard after max retries."""
		now = datetime.utcnow()
		lead_id = email.get("lead_id")

		# Get current soft bounce count from lead
		lead = self.leads.find_one({"_id": lead_id}) if lead_id else None
		soft_count = (lead.get("soft_bounce_count", 0) if lead else 0) + 1

		if soft_count >= SOFT_BOUNCE_MAX_RETRIES:
			# Escalate to hard bounce
			logger.warning(
				"Soft bounce limit reached (%d) for email=%s — escalating to hard bounce",
				soft_count, email.get("_id"),
			)
			if lead_id:
				self.leads.update_one(
					{"_id": lead_id},
					{"$set": {"soft_bounce_count": soft_count, "updated_at": now}},
				)
			return self._apply_terminal_event(
				email, event_type="bounced", reason=f"soft_escalated: {reason}",
				extra={"bounce_type": "hard", "soft_bounce_count": soft_count},
			)

		# Schedule retry
		retry_hours = SOFT_BOUNCE_RETRY_HOURS[min(soft_count - 1, len(SOFT_BOUNCE_RETRY_HOURS) - 1)]
		next_retry = now + timedelta(hours=retry_hours)

		self.emails.update_one(
			{"_id": email["_id"]},
			{"$set": {
				"status": "soft_bounced",
				"bounce_type": "soft",
				"soft_bounce_count": soft_count,
				"next_retry_at": next_retry,
				"updated_at": now,
				"error_message": reason,
			}},
		)

		if lead_id:
			self.leads.update_one(
				{"_id": lead_id},
				{"$set": {
					"soft_bounce_count": soft_count,
					"next_retry_at": next_retry,
					"updated_at": now,
				}},
			)

		self._insert_event(
			email_id=str(email["_id"]),
			event_type="soft_bounced",
			payload={"reason": reason, "retry_number": soft_count, "next_retry_at": next_retry.isoformat()},
		)

		logger.info(
			"Soft bounce #%d for email=%s — retry scheduled at %s",
			soft_count, email.get("_id"), next_retry.isoformat(),
		)
		return {
			"success": True,
			"email_id": str(email["_id"]),
			"event": "soft_bounced",
			"retry_number": soft_count,
			"next_retry_at": next_retry.isoformat(),
		}

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _handle_event(self, event_type: str, tracking_id: str, meta: Optional[dict] = None) -> dict:
		email = self.emails.find_one({"tracking_id": tracking_id})
		if not email:
			return {"success": False, "reason": "tracking_id_not_found"}

		now = datetime.utcnow()
		update_fields: dict[str, Any] = {"updated_at": now}

		if event_type == "opened":
			update_fields["open_count"] = int(email.get("open_count", 0)) + 1
			update_fields.setdefault("first_opened_at", email.get("first_opened_at") or now)
			update_fields["last_opened_at"] = now
			if email.get("status") in {"queued", "sent", "delivered"}:
				update_fields["status"] = "opened"

		if event_type == "clicked":
			update_fields["click_count"] = int(email.get("click_count", 0)) + 1
			update_fields.setdefault("first_clicked_at", email.get("first_clicked_at") or now)
			if email.get("status") in {"queued", "sent", "delivered", "opened"}:
				update_fields["status"] = "clicked"

		self.emails.update_one({"_id": email["_id"]}, {"$set": update_fields})
		self._insert_event(email_id=str(email["_id"]), event_type=event_type, payload=meta or {})

		return {"success": True, "email_id": str(email["_id"]), "event": event_type}

	def _apply_terminal_event(self, email: dict, event_type: str, reason: str = "",
							  extra: Optional[dict] = None) -> dict:
		now = datetime.utcnow()
		update_set = {
			"status": event_type,
			"updated_at": now,
			f"{event_type}_at": now,
			"error_message": reason,
		}
		if extra:
			update_set.update(extra)

		self.emails.update_one({"_id": email["_id"]}, {"$set": update_set})

		self._insert_event(email_id=str(email["_id"]), event_type=event_type,
						   payload={"reason": reason, **(extra or {})})

		sender_id = email.get("sender_id")
		if sender_id:
			if event_type == "bounced":
				self.senders.update_one({"_id": sender_id}, {"$inc": {"total_bounces": 1}})
			elif event_type == "complained":
				self.senders.update_one({"_id": sender_id}, {"$inc": {"total_complaints": 1}})

		lead_id = email.get("lead_id")
		if lead_id:
			new_status = "bounced" if event_type == "bounced" else "unsubscribed"
			self.leads.update_one({"_id": lead_id}, {"$set": {"status": new_status, "updated_at": now}})

		logger.warning("Processed terminal outreach event %s for email=%s", event_type, email.get("_id"))
		return {"success": True, "email_id": str(email["_id"]), "event": event_type}

	def _insert_event(self, email_id: str, event_type: str, payload: dict) -> None:
		self.events.insert_one(
			{
				"email_id": email_id,
				"event_type": event_type,
				"payload": payload,
				"created_at": datetime.utcnow(),
			}
		)

