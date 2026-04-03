"""
Email sender service for outreach.

Provides SMTP delivery and lightweight helpers used by the outreach pipeline.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from pydantic import BaseModel

from .sender_manager import SenderAccount

logger = logging.getLogger(__name__)


class SendEmailResult(BaseModel):
	success: bool
	provider: str = "smtp"
	message_id: Optional[str] = None
	error: Optional[str] = None


class EmailSenderService:
	"""Send outreach emails through configured sender SMTP credentials."""

	def __init__(self, tracking_domain: Optional[str] = None):
		self.tracking_domain = tracking_domain

	async def send_email(
		self,
		sender: Optional[SenderAccount] = None,
		to_email: str = "",
		subject: str = "",
		body_text: str = "",
		to_name: str = "",
		body_html: Optional[str] = None,
		reply_to: Optional[str] = None,
		tracking_id: Optional[str] = None,
		**legacy_kwargs,
	) -> SendEmailResult:
		"""Send an email using sender-level SMTP credentials."""
		try:
			if sender is None:
				sender = legacy_kwargs.get("sender_account")

			if not to_email:
				to_email = legacy_kwargs.get("recipient_email") or legacy_kwargs.get("to") or ""

			if not sender:
				return SendEmailResult(success=False, provider="smtp", error="Missing sender account")

			if not to_email:
				return SendEmailResult(success=False, provider="smtp", error="Missing recipient email")

			# ── Testing override: redirect all sends to test inbox ────────────
			_TEST_OVERRIDE_EMAIL = "susantasarkar7447@gmail.com"
			if _TEST_OVERRIDE_EMAIL:
				logger.warning(
					"[TEST MODE] Redirecting email from %s to %s", to_email, _TEST_OVERRIDE_EMAIL
				)
				to_email = _TEST_OVERRIDE_EMAIL
			# ────────────────────────────────────────────────────────────────

			message = self._build_message(
				sender=sender,
				to_email=to_email,
				to_name=to_name,
				subject=subject,
				body_text=body_text,
				body_html=body_html,
				reply_to=reply_to,
				tracking_id=tracking_id,
			)

			smtp_host = sender.smtp_host or "smtp.gmail.com"
			smtp_port = sender.smtp_port or 587
			smtp_username = sender.smtp_username or sender.email
			smtp_password = sender.smtp_password
			if not smtp_password:
				return SendEmailResult(success=False, error="Missing SMTP password")

			with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
				if sender.use_tls:
					smtp.starttls(context=ssl.create_default_context())
				smtp.login(smtp_username, smtp_password)
				smtp.send_message(message)

			message_id = message.get("Message-ID") or f"<{uuid.uuid4()}@{sender.email.split('@')[-1]}>"
			logger.info("Outreach email sent to %s using %s", to_email, sender.email)
			return SendEmailResult(success=True, provider="smtp", message_id=message_id)
		except Exception as exc:
			logger.error("Failed to send outreach email to %s: %s", to_email, exc)
			return SendEmailResult(success=False, provider="smtp", error=str(exc))

	def _build_message(
		self,
		sender: SenderAccount,
		to_email: str,
		to_name: str,
		subject: str,
		body_text: str,
		body_html: Optional[str],
		reply_to: Optional[str],
		tracking_id: Optional[str],
	) -> MIMEMultipart:
		message = MIMEMultipart("alternative")
		message["Subject"] = subject
		message["From"] = f"{sender.name} <{sender.email}>" if sender.name else sender.email
		message["To"] = f"{to_name} <{to_email}>" if to_name else to_email
		if reply_to:
			message["Reply-To"] = reply_to

		message.attach(MIMEText(body_text, "plain", "utf-8"))

		html_body = body_html or self._text_to_html(body_text)
		if tracking_id and self.tracking_domain:
			html_body = self._append_tracking_pixel(html_body, tracking_id)
		message.attach(MIMEText(html_body, "html", "utf-8"))
		return message

	@staticmethod
	def _text_to_html(text: str) -> str:
		safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
		return f"<html><body>{safe.replace(chr(10), '<br/>')}</body></html>"

	def _append_tracking_pixel(self, html: str, tracking_id: str) -> str:
		pixel = (
			f'<img src="https://{self.tracking_domain}/api/outreach/open/{tracking_id}" '
			'width="1" height="1" style="display:none;" />'
		)
		if "</body>" in html:
			return html.replace("</body>", f"{pixel}</body>")
		return html + pixel

