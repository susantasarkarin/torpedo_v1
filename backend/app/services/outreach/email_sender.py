"""
Email sender service for outreach.

Provides SMTP delivery and lightweight helpers used by the outreach pipeline.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
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
		sender: SenderAccount,
		to_email: str,
		subject: str,
		body_text: str,
		to_name: str = "",
		body_html: Optional[str] = None,
		reply_to: Optional[str] = None,
		tracking_id: Optional[str] = None,
	) -> SendEmailResult:
		"""Send an email using sender-level SMTP credentials."""
		try:
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

			logger.info("Outreach email sent to %s using %s", to_email, sender.email)
			return SendEmailResult(success=True, provider="smtp", message_id=message.get("Message-ID"))
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

