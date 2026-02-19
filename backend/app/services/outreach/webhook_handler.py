"""
Outreach webhook event handler.

Processes provider events and updates outreach state in Mongo collections.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


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

	def handle_bounce(self, provider_message_id: str, reason: str = "") -> dict:
		email = self.emails.find_one({"provider_message_id": provider_message_id})
		if not email:
			return {"success": False, "reason": "email_not_found"}
		return self._apply_terminal_event(email, event_type="bounced", reason=reason)

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

	def _apply_terminal_event(self, email: dict, event_type: str, reason: str = "") -> dict:
		now = datetime.utcnow()
		self.emails.update_one(
			{"_id": email["_id"]},
			{
				"$set": {
					"status": event_type,
					"updated_at": now,
					f"{event_type}_at": now,
					"error_message": reason,
				}
			},
		)

		self._insert_event(email_id=str(email["_id"]), event_type=event_type, payload={"reason": reason})

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

