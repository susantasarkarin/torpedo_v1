"""
SENDING ENGINE
==============

Email sending with thread continuity and provider integration.

Thread Continuity:
- Generate unique Message-ID for each send
- Set In-Reply-To header to previous message_id
- Set References header with all previous message_ids
- Preserve thread_id for Gmail/Exchange
- Follow-ups MUST reply in same thread
- NEVER start new thread for follow-ups

Provider Support:
- Gmail API
- SMTP
- Microsoft Graph (future)

Rate Limiting:
- Randomized send intervals (60-180 seconds)
- Per-mailbox rate limiting
- Automatic retry on transient failures
"""

import logging
import os
import uuid
import time
import random
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pymongo.database import Database

# ── TESTING MODE (env-var controlled, defaults to OFF) ───────────────────────
TEST_MODE = os.getenv("OUTREACH_TEST_MODE", "false").lower() == "true"
TEST_OVERRIDE_EMAIL = os.getenv("OUTREACH_TEST_EMAIL", "") if TEST_MODE else None
# ─────────────────────────────────────────────────────────────────────────────

from .models import (
    Lead,
    EmailSend,
    SendStatus,
    PersonalizationLevel,
    SendLogEntry,
)
from .mailbox_manager import MailboxManager
from .template_renderer import TemplateRenderer
from .ai_context_generator import AIContextGenerator
from .workflow_engine import WorkflowEngine, WorkflowStatus

logger = logging.getLogger(__name__)



def _mock_sends_enabled() -> bool:
    """
    Fake deliveries are a test affordance and nothing else.

    Read at call time and default OFF, so the only way to get a fabricated
    "sent" is to ask for one explicitly.
    """
    return os.getenv("OUTREACH_ALLOW_MOCK_SENDS", "").strip().lower() in (
        "1", "true", "yes", "on")


class SendingEngine:
    """
    Core email sending engine with thread continuity.
    
    Responsibilities:
    - Send emails with proper threading headers
    - Track message_ids for thread continuity
    - Update lead records after send
    - Handle provider-specific implementations
    - Randomize send intervals
    - Log all sends
    """
    
    # Send interval range for randomization
    MIN_SEND_INTERVAL_SECONDS = 60
    MAX_SEND_INTERVAL_SECONDS = 180
    
    def __init__(
        self,
        db: Database,
        gmail_service: Optional[Any] = None,
        smtp_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize sending engine.
        
        Args:
            db: MongoDB database instance
            gmail_service: Gmail API service instance
            smtp_config: SMTP configuration dict
        """
        self.db = db
        self.gmail_service = gmail_service
        self.smtp_config = smtp_config
        
        # Initialize dependencies
        self.mailbox_manager = MailboxManager(db)
        self.template_renderer = TemplateRenderer(db)
        self.ai_generator = AIContextGenerator(db)
        self.workflow_engine = WorkflowEngine(db)
        
        # Collections
        self.leads_collection = db["outreach_leads_v2"]
        self.sends_collection = db["outreach_sends_v2"]
        self.logs_collection = db["outreach_send_logs"]
        self.campaigns_collection = db["outreach_campaigns_v2"]
        self.suppression_collection = db["outreach_bounce_suppression"]

        self._setup_indexes()

    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            self.sends_collection.create_index([("message_id", 1)], unique=True)
            self.sends_collection.create_index([("campaign_id", 1), ("lead_id", 1)])
            self.sends_collection.create_index([("status", 1), ("scheduled_at", 1)])
            # Bounce suppression — unique on email for fast O(1) lookup
            self.suppression_collection.create_index([("email", 1)], unique=True)
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")

    # ============== BOUNCE SUPPRESSION ==============

    def is_suppressed(self, email: str) -> bool:
        """Return True if email is on the global bounce suppression list."""
        return self.suppression_collection.count_documents(
            {"email": email.lower().strip()}, limit=1
        ) > 0

    def record_bounce(self, email: str, campaign_id: str, lead_id: str) -> None:
        """
        Add email to the global bounce suppression list and mark the lead.
        Call this whenever a bounce event is received.
        """
        email = email.lower().strip()
        now = datetime.utcnow()
        try:
            self.suppression_collection.update_one(
                {"email": email},
                {"$setOnInsert": {
                    "email": email,
                    "bounced_at": now,
                    "bounced_campaign_id": campaign_id,
                    "created_at": now,
                }},
                upsert=True,
            )
        except Exception as e:
            logger.warning(f"Suppression insert failed for {email}: {e}")

        # Mark lead in leads_enriched (global leads collection)
        try:
            enriched = self.db["leads_enriched"]
            enriched.update_one(
                {"email": email},
                {"$set": {"email_status": "bounced", "bounce_suppressed": True, "bounced_at": now}},
            )
        except Exception as e:
            logger.warning(f"Failed to mark lead as bounced in leads_enriched: {e}")

        # Mark in outreach_leads_v2 too
        try:
            self.leads_collection.update_one(
                {"lead_id": lead_id},
                {"$set": {"bounce_suppressed": True, "bounced_at": now}},
            )
        except Exception as e:
            logger.warning(f"Failed to mark outreach lead as bounced: {e}")

        logger.info(f"Bounce suppression recorded for {email} (campaign={campaign_id})")
    
    # ============== MAIN SEND METHOD ==============
    

    def _identity_for_gate(self, lead: dict, campaign_id: str) -> str:
        """
        The sending mailbox address — that is what carries the reputation and
        therefore the budget, so the cap must be keyed on it rather than on the
        campaign. Falls back to the campaign id only when no mailbox has been
        assigned yet, which keeps an unassigned lead from sharing one bucket
        with every other channel.
        """
        mailbox_id = lead.get("assigned_mailbox_id")
        if mailbox_id:
            try:
                mailbox = self.mailbox_manager.get_mailbox(mailbox_id) or {}
                addr = mailbox.get("email") or mailbox.get("from_email")
                if addr:
                    return str(addr).strip().lower()
            except Exception:
                logger.debug("could not resolve mailbox %s for budget identity",
                             mailbox_id, exc_info=True)
        return f"campaign:{campaign_id}"

    def send_email(
        self,
        lead_id: str,
        campaign_id: str,
        step_number: int,
        template_id: str,
        dry_run: bool = False
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Send email to lead with full personalization and thread continuity.
        
        Args:
            lead_id: Lead to send to
            campaign_id: Campaign ID
            step_number: Current workflow step
            template_id: Template to use
            dry_run: If True, don't actually send
            
        Returns:
            Tuple of (success, message, message_id)
        """
        start_time = datetime.utcnow()
        
        try:
            # Get lead
            lead = self.leads_collection.find_one({"lead_id": lead_id})
            if not lead:
                return False, f"Lead {lead_id} not found", None

            # ── Shared send gates ────────────────────────────────────────────
            # This engine delivers its own mail (SMTP/SES), so it never passed
            # through messaging.facade.send() and inherited none of its
            # guarantees. It checked ONE of the three bounce lists — the line
            # below, kept as a fast local path — and nothing else: no kill
            # switch, no cross-channel budget, no unified suppression, no
            # placeholder-domain blocklist. This is the path that over-sent in
            # August. facade.gate() applies all of them before every message.
            to_email = (lead.get("email") or "").strip().lower()
            if to_email and self.is_suppressed(to_email):
                logger.info(f"Suppressed send to {to_email}: address is on bounce suppression list")
                return False, f"Suppressed: {to_email} is on the global bounce list", None

            identity = self._identity_for_gate(lead, campaign_id)
            try:
                from messaging import facade as _facade
            except ImportError:  # pragma: no cover - packaging fallback
                from backend.messaging import facade as _facade
            gate_block = _facade.gate(to_email, identity=identity,
                                      channel="outreach", transactional=False)
            if gate_block:
                reason, category = gate_block
                logger.info("send gated (%s) to=%s campaign=%s: %s",
                            category, to_email, campaign_id, reason)
                _facade._log.record(identity=identity, to_email=to_email,
                                    subject=None, channel="outreach",
                                    status={"suppressed": "suppressed",
                                            "budget": "budget_blocked"}.get(category, "failed"),
                                    error=reason,
                                    metadata={"campaign_id": campaign_id,
                                              "lead_id": lead_id,
                                              "step": step_number})
                return False, f"{category}: {reason}", None
            # ─────────────────────────────────────────────────────────────────

            # ── Pre-send email validation (syntax + MX + role-based) ────────
            try:
                from app.services.outreach.email_validator import EmailValidator
                validator = EmailValidator(self.db)
                is_valid, reason = validator.validate_before_send(to_email)
                if not is_valid:
                    logger.info(f"Pre-send validation failed for {to_email}: {reason}")
                    return False, f"Validation failed: {reason}", None
            except ImportError:
                logger.debug("email_validator not available, skipping pre-send validation")
            # ─────────────────────────────────────────────────────────────────

            # Get campaign
            campaign = self.campaigns_collection.find_one({"campaign_id": campaign_id})
            if not campaign:
                return False, f"Campaign {campaign_id} not found", None

            # Get or assign mailbox (STICKY)
            mailbox_id = lead.get("assigned_mailbox_id")
            
            # Cold email routing override: route based on service type
            if not mailbox_id:
                try:
                    from .cold_email_router import get_sender_for_lead
                    routed_email, routed_name, service_type = get_sender_for_lead(
                        lead, campaign
                    )
                    # Find matching mailbox by email address
                    routed_mailbox = self.mailbox_manager.get_mailbox_by_email(routed_email)
                    if routed_mailbox:
                        mailbox_id = routed_mailbox.get("mailbox_id")
                        logger.info(
                            f"Cold email routing: {lead.get('email')} → "
                            f"{routed_email} (service={service_type})"
                        )
                except Exception as e:
                    logger.warning(f"Cold email routing failed, falling back to default: {e}")
            
            # Default mailbox assignment if routing didn't provide one
            if not mailbox_id:
                mailbox_id, msg = self.mailbox_manager.assign_mailbox_to_lead(
                    lead_id,
                    campaign.get("mailbox_ids", [])
                )
                if not mailbox_id:
                    return False, f"Could not assign mailbox: {msg}", None
            
            # Check mailbox rate limits
            can_send, reason = self.mailbox_manager.can_send_from_mailbox(mailbox_id)
            if not can_send:
                return False, f"Mailbox throttled: {reason}", None
            
            # Get mailbox
            mailbox = self.mailbox_manager.get_mailbox(mailbox_id)
            if not mailbox:
                return False, f"Mailbox {mailbox_id} not found", None
            
            # Get personalization level
            personalization_level = PersonalizationLevel(
                lead.get("personalization_level", PersonalizationLevel.LIGHT.value)
            )
            
            # Get or generate AI context block (REUSE existing)
            ai_context_block = None
            ai_hook = None
            ai_tokens_used = 0
            
            if personalization_level in (PersonalizationLevel.MEDIUM, PersonalizationLevel.HEAVY):
                ai_context_block, tokens = self.ai_generator.get_or_generate_context_block(
                    lead_id,
                    personalization_level
                )
                ai_tokens_used += tokens
            
            if personalization_level == PersonalizationLevel.HEAVY:
                ai_hook, tokens = self.ai_generator.generate_hook_sentence(
                    lead_id,
                    personalization_level
                )
                ai_tokens_used += tokens
            
            # Get signature
            signature_html = self.mailbox_manager.get_mailbox_signature(mailbox_id, "html")
            signature_plain = self.mailbox_manager.get_mailbox_signature(mailbox_id, "plain")
            
            # Render email
            rendered = self.template_renderer.render_email(
                template_id=template_id,
                lead_data=lead,
                ai_context_block=ai_context_block,
                ai_hook=ai_hook,
                signature_html=signature_html,
                signature_plain=signature_plain,
                personalization_level=personalization_level
            )
            
            # Generate Message-ID for thread continuity
            message_id = self._generate_message_id(mailbox.get("email_address", ""))
            
            # Build threading headers
            in_reply_to = lead.get("message_id_last_sent")
            references = lead.get("references", []).copy()
            thread_id = lead.get("thread_id")
            
            if in_reply_to:
                references.append(in_reply_to)
            
            # ── Testing override: redirect all sends to test inbox ────────
            actual_to_email = lead["email"]
            if TEST_OVERRIDE_EMAIL:
                logger.warning(
                    f"[TEST MODE] Redirecting email from {actual_to_email} "
                    f"to {TEST_OVERRIDE_EMAIL}"
                )
                actual_to_email = TEST_OVERRIDE_EMAIL
            # ────────────────────────────────────────────────────────────────

            # Create send record
            send_record = EmailSend(
                campaign_id=campaign_id,
                lead_id=lead_id,
                mailbox_id=mailbox_id,
                workflow_step=step_number,
                template_id=template_id,
                to_email=actual_to_email,
                from_email=mailbox.get("email_address", ""),
                from_name=mailbox.get("display_name", ""),
                subject=rendered["subject"],
                body_html=rendered["body_html"],
                body_plain=rendered["body_plain"],
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=references,
                thread_id=thread_id,
                status=SendStatus.SENDING,
                personalization_level=personalization_level,
                ai_tokens_used=ai_tokens_used,
            )
            
            # Dry run - don't actually send
            if dry_run:
                logger.info(f"DRY RUN: Would send to {actual_to_email} (lead email: {lead['email']})")
                return True, "Dry run successful", message_id
            
            # Actually send the email
            success, send_result = self._send_via_provider(
                mailbox=mailbox,
                send_record=send_record
            )
            
            # Update send record
            now = datetime.utcnow()
            if success:
                send_record.status = SendStatus.SENT
                send_record.sent_at = now
                
                # Provider may return thread_id
                if send_result.get("thread_id"):
                    send_record.thread_id = send_result["thread_id"]
                    thread_id = send_record.thread_id
                
                if send_result.get("provider_message_id"):
                    send_record.provider_message_id = send_result["provider_message_id"]
            else:
                send_record.status = SendStatus.FAILED
                send_record.error_message = send_result.get("error", "Unknown error")
            
            # Save send record
            self.sends_collection.insert_one(send_record.model_dump())
            
            if success:
                # Update lead record
                self._update_lead_after_send(
                    lead_id=lead_id,
                    message_id=message_id,
                    thread_id=thread_id,
                    references=references,
                    step_number=step_number
                )
                
                # Increment mailbox send count
                self.mailbox_manager.increment_send_count(mailbox_id)

                # Count this send in the ONE log the cross-channel budget
                # reads. Without it, budget.allows() sees zero outreach volume
                # for the identity and every cap is computed against a
                # fraction of the real number.
                try:
                    from messaging import facade as _f
                except ImportError:  # pragma: no cover
                    from backend.messaging import facade as _f
                _f._log.record(
                    identity=self._identity_for_gate(lead, campaign_id),
                    to_email=(lead.get("email") or "").strip().lower(),
                    subject=send_record.subject, channel="outreach",
                    status="sent", provider_message_id=message_id,
                    metadata={"campaign_id": campaign_id, "lead_id": lead_id,
                              "step": step_number, "mailbox_id": mailbox_id})
                
                # Update campaign stats
                self._update_campaign_stats(campaign_id, "sent")

                # Mirror onto the CRM spine timeline (best-effort, non-fatal)
                try:
                    from app.services.spine_connector import mirror_email_activity_to_spine
                    lead_name = (lead.get("name") or lead.get("full_name")
                                 or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip())
                    mirror_email_activity_to_spine(
                        direction="sent",
                        email=lead.get("email", ""),
                        name=lead_name or None,
                        company=lead.get("company") or lead.get("company_name"),
                        subject=send_record.subject,
                        source="outreach",
                        source_id=message_id,
                    )
                except Exception:
                    pass

                # Log the send
                self._log_send(
                    send_record=send_record,
                    success=True,
                    render_time_ms=0,
                    send_time_ms=int((datetime.utcnow() - start_time).total_seconds() * 1000)
                )
                
                logger.info(f"Sent email to {lead['email']} (step {step_number})")
                return True, "Email sent successfully", message_id
            else:
                # Log failure
                self._log_send(
                    send_record=send_record,
                    success=False,
                    error_type="send_failure",
                    error_message=send_record.error_message
                )
                
                return False, send_record.error_message or "Send failed", None
            
        except Exception as e:
            logger.error(f"Send error for lead {lead_id}: {e}", exc_info=True)
            return False, str(e), None
    
    # ============== THREAD CONTINUITY ==============
    
    def _generate_message_id(self, email_domain: str) -> str:
        """
        Generate unique Message-ID for thread continuity.
        
        Format: <uuid@domain>
        """
        unique_id = str(uuid.uuid4())
        
        # Extract domain from email
        if "@" in email_domain:
            domain = email_domain.split("@")[1]
        else:
            domain = email_domain or "outreach.local"
        
        return f"<{unique_id}@{domain}>"
    
    def _update_lead_after_send(
        self,
        lead_id: str,
        message_id: str,
        thread_id: Optional[str],
        references: List[str],
        step_number: int
    ):
        """
        Update lead record after successful send.
        """
        now = datetime.utcnow()
        
        update = {
            "message_id_last_sent": message_id,
            "references": references + [message_id],
            "last_sent_at": now,
            "current_step": step_number,
            "updated_at": now,
            "$inc": {"emails_sent": 1}
        }
        
        if thread_id:
            update["thread_id"] = thread_id
        
        # Separate $inc from $set
        inc_updates = {"emails_sent": 1}
        set_updates = {
            "message_id_last_sent": message_id,
            "references": references + [message_id],
            "last_sent_at": now,
            "current_step": step_number,
            "updated_at": now,
        }
        
        if thread_id:
            set_updates["thread_id"] = thread_id
        
        self.leads_collection.update_one(
            {"lead_id": lead_id},
            {"$set": set_updates, "$inc": inc_updates}
        )
    
    # ============== PROVIDER IMPLEMENTATIONS ==============
    
    def _send_via_provider(
        self,
        mailbox: Dict[str, Any],
        send_record: EmailSend
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Send email via configured provider.
        """
        provider = mailbox.get("provider", "gmail")

        if provider == "ses":
            return self._send_via_ses(mailbox, send_record)
        if provider == "gmail" and self.gmail_service:
            return self._send_via_gmail(mailbox, send_record)
        if provider == "smtp":
            return self._send_via_smtp(mailbox, send_record)

        # NOT a mock. A misconfigured mailbox is a failure, not a delivery.
        #
        # This used to fall through to _mock_send(), which returns
        # success=True with a fabricated "mock_..." provider id. The caller
        # cannot tell that apart from a real send: it marks the lead sent,
        # advances the workflow step, increments the mailbox counter and
        # schedules the follow-up. An entire sequence could complete without a
        # single email leaving the building.
        #
        # The most likely trigger is not an exotic provider name — it is
        # provider="gmail" (the DEFAULT) with self.gmail_service unset, which
        # is exactly the state this engine is constructed in unless a caller
        # passes one.
        #
        # Mocking belongs in tests, where it can be injected deliberately.
        if _mock_sends_enabled():
            logger.warning("OUTREACH_ALLOW_MOCK_SENDS is on — faking a send to "
                           "%s. This must never be set in production.",
                           send_record.to_email)
            return self._mock_send(send_record)

        reason = (f"mailbox provider {provider!r} is not usable"
                  + (" (gmail selected but no gmail_service was provided)"
                     if provider == "gmail" else ""))
        logger.error("refusing to send to %s: %s", send_record.to_email, reason)
        return False, {"error": reason}
    
    def _send_via_gmail(
        self,
        mailbox: Dict[str, Any],
        send_record: EmailSend
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Send email via Gmail API with threading support.
        """
        try:
            import base64
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Build MIME message
            msg = MIMEMultipart("alternative")
            msg["To"] = send_record.to_email
            msg["From"] = f"{send_record.from_name} <{send_record.from_email}>"
            msg["Subject"] = send_record.subject
            msg["Message-ID"] = send_record.message_id
            
            # Threading headers
            if send_record.in_reply_to:
                msg["In-Reply-To"] = send_record.in_reply_to
            
            if send_record.references:
                msg["References"] = " ".join(send_record.references)
            
            # Attach plain text and HTML
            msg.attach(MIMEText(send_record.body_plain, "plain"))
            msg.attach(MIMEText(send_record.body_html, "html"))
            
            # Encode for Gmail API
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            
            # Build request body
            body = {"raw": raw}
            
            # Include thread_id for replies
            if send_record.thread_id:
                body["threadId"] = send_record.thread_id
            
            # Send via Gmail API
            result = self.gmail_service.users().messages().send(
                userId="me",
                body=body
            ).execute()
            
            return True, {
                "provider_message_id": result.get("id"),
                "thread_id": result.get("threadId")
            }
            
        except Exception as e:
            logger.error(f"Gmail send error: {e}")
            return False, {"error": str(e)}
    
    def _send_via_smtp(
        self,
        mailbox: Dict[str, Any],
        send_record: EmailSend
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Send email via SMTP.
        """
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            # Build message
            msg = MIMEMultipart("alternative")
            msg["To"] = send_record.to_email
            msg["From"] = f"{send_record.from_name} <{send_record.from_email}>"
            msg["Subject"] = send_record.subject
            msg["Message-ID"] = send_record.message_id
            
            # Threading headers
            if send_record.in_reply_to:
                msg["In-Reply-To"] = send_record.in_reply_to
            
            if send_record.references:
                msg["References"] = " ".join(send_record.references)
            
            msg.attach(MIMEText(send_record.body_plain, "plain"))
            msg.attach(MIMEText(send_record.body_html, "html"))
            
            # Get SMTP config
            host = self.smtp_config.get("host")
            port = self.smtp_config.get("port", 587)
            user = self.smtp_config.get("user")
            password = self.smtp_config.get("password")
            
            # Send
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                server.login(user, password)
                server.send_message(msg)
            
            return True, {"provider_message_id": send_record.message_id}
            
        except Exception as e:
            logger.error(f"SMTP send error: {e}")
            return False, {"error": str(e)}
    
    def _send_via_ses(
        self,
        mailbox: Dict[str, Any],
        send_record: EmailSend
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Send email via AWS SES SDK (boto3).
        Uses send_raw_email for full MIME control and thread headers.
        Credentials are read from mailbox record (aws_access_key_id / aws_secret_access_key)
        or fall back to environment / IAM role.
        """
        try:
            import boto3
            from botocore.exceptions import ClientError

            # Build MIME message
            msg = MIMEMultipart("alternative")
            msg["To"] = send_record.to_email
            msg["From"] = f"{send_record.from_name} <{send_record.from_email}>"
            msg["Subject"] = send_record.subject
            msg["Message-ID"] = send_record.message_id

            if send_record.in_reply_to:
                msg["In-Reply-To"] = send_record.in_reply_to
            if send_record.references:
                msg["References"] = " ".join(send_record.references)

            msg.attach(MIMEText(send_record.body_plain, "plain"))
            msg.attach(MIMEText(send_record.body_html, "html"))

            # Build boto3 client — use mailbox credentials if provided, else env/IAM
            ses_kwargs: Dict[str, Any] = {
                "region_name": mailbox.get("aws_region", "us-east-1"),
            }
            if mailbox.get("aws_access_key_id"):
                ses_kwargs["aws_access_key_id"] = mailbox["aws_access_key_id"]
                ses_kwargs["aws_secret_access_key"] = mailbox["aws_secret_access_key"]

            client = boto3.client("ses", **ses_kwargs)

            response = client.send_raw_email(
                Source=f"{send_record.from_name} <{send_record.from_email}>",
                Destinations=[send_record.to_email],
                RawMessage={"Data": msg.as_bytes()},
            )

            ses_message_id = response.get("MessageId", send_record.message_id)
            logger.info(f"SES send OK → {send_record.to_email} | SES MessageId={ses_message_id}")
            return True, {"provider_message_id": ses_message_id}

        except Exception as e:
            logger.error(f"SES send error: {e}")
            return False, {"error": str(e)}

    def _mock_send(self, send_record: EmailSend) -> Tuple[bool, Dict[str, Any]]:
        """
        Mock send for testing.
        """
        logger.info(f"MOCK SEND to {send_record.to_email}: {send_record.subject}")
        
        # Simulate send delay
        time.sleep(0.1)
        
        return True, {
            "provider_message_id": f"mock_{send_record.message_id}",
            "thread_id": send_record.thread_id or f"thread_{uuid.uuid4().hex[:12]}"
        }
    
    # ============== BULK SENDING ==============
    
    def send_batch(
        self,
        campaign_id: str,
        limit: int = 50,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Send batch of emails for campaign with randomized intervals.
        
        Args:
            campaign_id: Campaign to process
            limit: Max emails to send in this batch
            dry_run: If True, don't actually send
            
        Returns:
            Batch result summary
        """
        # Get leads ready to send
        leads = self.workflow_engine.get_leads_ready_to_send(
            campaign_id=campaign_id,
            limit=limit
        )
        
        if not leads:
            return {
                "success": True,
                "sent": 0,
                "failed": 0,
                "message": "No leads ready to send"
            }
        
        # Get campaign for template mapping
        campaign = self.campaigns_collection.find_one({"campaign_id": campaign_id})
        if not campaign:
            return {
                "success": False,
                "error": f"Campaign {campaign_id} not found"
            }
        
        workflow_steps = campaign.get("workflow_steps", [])
        
        sent_count = 0
        failed_count = 0
        errors = []
        
        for i, lead in enumerate(leads):
            lead_id = lead.get("lead_id")
            current_step = lead.get("current_step", 0)
            
            # Get template for current step
            if current_step >= len(workflow_steps):
                logger.warning(f"Lead {lead_id} at invalid step {current_step}")
                continue
            
            step_config = workflow_steps[current_step]
            template_id = step_config.get("template_id")
            
            if not template_id:
                logger.warning(f"No template for step {current_step}")
                continue
            
            # Send email
            success, message, msg_id = self.send_email(
                lead_id=lead_id,
                campaign_id=campaign_id,
                step_number=current_step,
                template_id=template_id,
                dry_run=dry_run
            )
            
            if success:
                sent_count += 1
                
                # Advance workflow to next step
                if not dry_run:
                    self.workflow_engine.advance_workflow(lead_id)
            else:
                failed_count += 1
                errors.append({"lead_id": lead_id, "error": message})
            
            # Randomized delay between sends (except for last)
            if i < len(leads) - 1 and not dry_run:
                delay = random.randint(
                    self.MIN_SEND_INTERVAL_SECONDS,
                    self.MAX_SEND_INTERVAL_SECONDS
                )
                logger.debug(f"Waiting {delay}s before next send")
                time.sleep(delay)
        
        return {
            "success": True,
            "sent": sent_count,
            "failed": failed_count,
            "errors": errors[:10],  # Limit errors in response
            "dry_run": dry_run
        }
    
    # ============== LOGGING ==============
    
    def _log_send(
        self,
        send_record: EmailSend,
        success: bool,
        render_time_ms: int = 0,
        send_time_ms: int = 0,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """
        Log send for observability.
        """
        log_entry = {
            "log_id": str(uuid.uuid4()),
            "send_id": send_record.send_id,
            "campaign_id": send_record.campaign_id,
            "lead_id": send_record.lead_id,
            "personalization_level": send_record.personalization_level.value,
            "mailbox_used": send_record.mailbox_id,
            "ai_tokens_used": send_record.ai_tokens_used,
            "message_id": send_record.message_id,
            "thread_id": send_record.thread_id,
            "workflow_step": send_record.workflow_step,
            "status": "sent" if success else "failed",
            "error_type": error_type,
            "error_message": error_message,
            "render_time_ms": render_time_ms,
            "send_time_ms": send_time_ms,
            "logged_at": datetime.utcnow()
        }
        
        try:
            self.logs_collection.insert_one(log_entry)
        except Exception as e:
            logger.warning(f"Failed to log send: {e}")
    
    def _update_campaign_stats(self, campaign_id: str, event: str):
        """
        Update campaign statistics.
        """
        inc_field = f"total_emails_{event}" if event == "sent" else f"leads_{event}"
        
        self.campaigns_collection.update_one(
            {"campaign_id": campaign_id},
            {
                "$inc": {"total_emails_sent": 1} if event == "sent" else {},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
    
    # ============== WEBHOOKS / EVENT HANDLERS ==============
    
    def handle_bounce(
        self,
        message_id: str,
        bounce_type: str = "unknown",
        bounce_reason: Optional[str] = None
    ):
        """
        Handle email bounce event.
        """
        # Find send record by message_id
        send = self.sends_collection.find_one({"message_id": message_id})
        if not send:
            logger.warning(f"Bounce received for unknown message_id: {message_id}")
            return
        
        lead_id = send.get("lead_id")
        campaign_id = send.get("campaign_id")
        mailbox_id = send.get("mailbox_id")
        
        # Update send record
        now = datetime.utcnow()
        self.sends_collection.update_one(
            {"message_id": message_id},
            {"$set": {
                "status": SendStatus.BOUNCED.value,
                "bounced_at": now,
                "bounce_type": bounce_type,
                "bounce_reason": bounce_reason
            }}
        )
        
        # Stop workflow
        self.workflow_engine.handle_bounce_detected(
            lead_id,
            bounce_type,
            bounce_reason
        )
        
        # Update mailbox bounce rate
        self.mailbox_manager.update_bounce_rate(mailbox_id)
        
        # Log error
        self._log_send(
            send_record=EmailSend(**send),
            success=False,
            error_type="bounce",
            error_message=f"{bounce_type}: {bounce_reason}"
        )
        
        logger.info(f"Handled bounce for lead {lead_id}")
    
    def handle_reply(
        self,
        message_id: str,
        reply_type: str = "neutral",
        reply_email_id: Optional[str] = None
    ):
        """
        Handle reply detection event.
        """
        # Find send record
        send = self.sends_collection.find_one({"message_id": message_id})
        if not send:
            # Try by thread_id
            send = self.sends_collection.find_one({"thread_id": message_id})
        
        if not send:
            logger.warning(f"Reply received for unknown message: {message_id}")
            return
        
        lead_id = send.get("lead_id")
        
        # Update send record
        now = datetime.utcnow()
        self.sends_collection.update_one(
            {"send_id": send.get("send_id")},
            {"$set": {
                "status": SendStatus.REPLIED.value,
                "replied_at": now
            }}
        )
        
        # Stop workflow
        self.workflow_engine.handle_reply_detected(
            lead_id,
            reply_type,
            reply_email_id
        )
        
        logger.info(f"Handled reply for lead {lead_id} (type: {reply_type})")
