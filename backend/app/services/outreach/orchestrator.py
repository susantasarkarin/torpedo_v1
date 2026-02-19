"""
Outreach Orchestrator.

Main coordinator for the AI-powered outreach system.
Coordinates all services with proper guardrails and flow control.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .email_generator import (
    EmailGenerationRequest,
    EmailGeneratorService,
    FollowUpRequest,
    GeneratedEmail,
    SpamCheckResult,
)
from .guardrails import GuardrailsService, OutreachLimits, RiskLevel
from .lead_intelligence import CompanyData, LeadIntelligenceService
from .optimizer import CampaignData, CampaignOptimizerService, OptimizationReport
from .reply_handler import AutoResponse, ClassifiedReply, ReplyContext, ReplyHandlerService
from .sender_manager import SenderAccount, SenderAllocation, SenderManagerService

logger = logging.getLogger(__name__)


class OutreachResult(BaseModel):
    success: bool
    action: str
    reason: Optional[str] = None
    email: Optional[GeneratedEmail] = None
    spam_check: Optional[SpamCheckResult] = None
    sender_allocation: Optional[SenderAllocation] = None
    lead_score: Optional[int] = None
    risk_assessment: Optional[RiskLevel] = None
    metadata: dict = Field(default_factory=dict)


class FollowUpResult(BaseModel):
    success: bool
    action: str
    reason: Optional[str] = None
    email: Optional[GeneratedEmail] = None


class ReplyProcessingResult(BaseModel):
    classification: ClassifiedReply
    auto_response: Optional[AutoResponse] = None
    should_halt: bool = False
    should_remove_from_sequence: bool = False
    needs_human_review: bool = False
    risk_level: str = "low"


class OutreachOrchestrator:
    """
    Main orchestrator for the outreach system.

    Principles:
    - AI handles intelligence generation
    - System (guardrails) handles constraints
    - Never skip safety checks
    - Always log decisions
    """

    def __init__(
        self,
        ai_client: Any,
        db: Any = None,
        limits: Optional[OutreachLimits] = None,
    ):
        self.ai_client = ai_client
        self.db = db

        self.intelligence = LeadIntelligenceService(ai_client)
        self.email_generator = EmailGeneratorService(ai_client)
        self.reply_handler = ReplyHandlerService(ai_client)
        self.sender_manager = SenderManagerService(ai_client=ai_client, db=db)
        self.optimizer = CampaignOptimizerService(ai_client=ai_client, db=db)
        self.guardrails = GuardrailsService(limits)

        logger.info("OutreachOrchestrator initialized")

    async def process_new_lead(
        self,
        company_data: CompanyData,
        contact_name: str,
        contact_role: str,
        contact_email: str,
        campaign_positioning: str = "",
        cta_style: str = "soft",
        sender_name: str = "",
        sender_title: str = "",
        sender_company: str = "",
        recipient_timezone: str = "UTC",
    ) -> OutreachResult:
        logger.info("Processing new lead: %s", contact_email)

        try:
            intelligence, score = await self.intelligence.extract_and_score(company_data)

            can_outreach, reason = self.guardrails.can_outreach_lead(
                lead_score=score.lead_score,
                previous_emails_sent=0,
                last_email_date=None,
            )
            if not can_outreach:
                return OutreachResult(
                    success=False,
                    action="skip",
                    reason=reason,
                    lead_score=score.lead_score,
                )

            can_send_now, time_reason = self.guardrails.is_valid_send_time(
                recipient_timezone=recipient_timezone
            )
            if not can_send_now:
                return OutreachResult(
                    success=False,
                    action="defer",
                    reason=time_reason,
                    lead_score=score.lead_score,
                    metadata={"intelligence": intelligence.model_dump()},
                )

            sender_allocation = await self.sender_manager.allocate_sender(
                recipient_timezone=recipient_timezone,
                priority=score.priority_tier,
            )
            if not sender_allocation.selected_sender_id:
                return OutreachResult(
                    success=False,
                    action="defer",
                    reason=sender_allocation.reasoning,
                    sender_allocation=sender_allocation,
                    lead_score=score.lead_score,
                )

            selected_sender = self.sender_manager.get_sender(sender_allocation.selected_sender_id)
            if selected_sender:
                sender_ok, sender_reason = self.guardrails.can_sender_send(
                    sender_id=selected_sender.id,
                    sender_daily_count=selected_sender.daily_sent_count,
                    sender_hourly_count=selected_sender.hourly_sent_count,
                    sender_bounce_rate=selected_sender.bounce_rate,
                    sender_complaint_rate=selected_sender.complaint_rate,
                    sender_health_score=selected_sender.health_score,
                )
                if not sender_ok:
                    return OutreachResult(
                        success=False,
                        action="defer",
                        reason=sender_reason,
                        sender_allocation=sender_allocation,
                        lead_score=score.lead_score,
                    )

            email_request = EmailGenerationRequest(
                contact_name=contact_name,
                contact_role=contact_role,
                company_name=company_data.company_name,
                intelligence=intelligence,
                trigger_event=company_data.trigger_event,
                campaign_positioning=campaign_positioning,
                cta_style=cta_style,
                sender_name=sender_name,
                sender_title=sender_title,
                sender_company=sender_company,
            )
            email, spam_check = await self.email_generator.generate_and_validate(email_request)

            risk = self.guardrails.assess_send_risk(
                sender_id=sender_allocation.selected_sender_id,
                sender_bounce_rate=selected_sender.bounce_rate if selected_sender else 0.0,
                sender_complaint_rate=selected_sender.complaint_rate if selected_sender else 0.0,
                sender_health_score=selected_sender.health_score if selected_sender else 100.0,
                lead_score=score.lead_score,
                email_spam_score=spam_check.spam_score,
                is_first_email=True,
            )
            if not risk.should_proceed:
                return OutreachResult(
                    success=False,
                    action="halt",
                    reason="Risk too high for auto-send",
                    email=email,
                    spam_check=spam_check,
                    sender_allocation=sender_allocation,
                    lead_score=score.lead_score,
                    risk_assessment=risk,
                )

            return OutreachResult(
                success=True,
                action="send",
                email=email,
                spam_check=spam_check,
                sender_allocation=sender_allocation,
                lead_score=score.lead_score,
                risk_assessment=risk,
                metadata={
                    "intelligence": intelligence.model_dump(),
                    "score_details": score.model_dump(),
                },
            )
        except Exception as exc:
            logger.error("Failed to process lead %s: %s", contact_email, exc)
            return OutreachResult(success=False, action="error", reason=str(exc))

    async def process_followup(
        self,
        contact_email: str,
        contact_name: str,
        company_name: str,
        original_subject: str,
        original_body: str,
        days_since_sent: int,
        open_count: int,
        click_count: int = 0,
        previous_emails_count: int = 1,
        last_email_date: Optional[datetime] = None,
        intelligence_summary: str = "",
    ) -> FollowUpResult:
        logger.info("Processing follow-up for %s", contact_email)

        can_outreach, reason = self.guardrails.can_outreach_lead(
            lead_score=70,
            previous_emails_sent=previous_emails_count,
            last_email_date=last_email_date,
        )
        if not can_outreach:
            return FollowUpResult(success=False, action="skip", reason=reason)

        try:
            original_email = GeneratedEmail(subject=original_subject, body=original_body)
            request = FollowUpRequest(
                original_email=original_email,
                days_since_sent=days_since_sent,
                open_count=open_count,
                click_count=click_count,
                intelligence_summary=intelligence_summary,
                followup_number=previous_emails_count,
                contact_name=contact_name,
                company_name=company_name,
            )
            followup = await self.email_generator.generate_followup(request)
            return FollowUpResult(success=True, action="send_followup", email=followup)
        except Exception as exc:
            logger.error("Failed to generate follow-up for %s: %s", contact_email, exc)
            return FollowUpResult(success=False, action="error", reason=str(exc))

    async def process_reply(
        self,
        reply_text: str,
        original_email_subject: str,
        original_email_body: str,
        contact_name: str = "",
        company_name: str = "",
        thread_history: Optional[list] = None,
    ) -> ReplyProcessingResult:
        context = ReplyContext(
            reply_text=reply_text,
            original_email_subject=original_email_subject,
            original_email_body=original_email_body,
            thread_history=thread_history or [],
            contact_name=contact_name,
            company_name=company_name,
        )

        classification = await self.reply_handler.classify_reply(context)

        is_risk, risk_level, _ = self.guardrails.check_reply_risk(
            classification.classification,
            classification.confidence,
        )

        should_halt = classification.classification in ["Legal Warning", "Spam Complaint Risk"]
        should_remove = classification.classification in [
            "Not Interested",
            "Legal Warning",
            "Spam Complaint Risk",
        ]
        needs_review = classification.needs_human_review or is_risk

        auto_response = None
        if not should_halt and not needs_review:
            can_respond, _ = self.guardrails.can_auto_respond(
                classification.classification,
                classification.confidence,
            )
            if can_respond:
                auto_response = await self.reply_handler.generate_auto_response(
                    classification,
                    context,
                )

        return ReplyProcessingResult(
            classification=classification,
            auto_response=auto_response,
            should_halt=should_halt,
            should_remove_from_sequence=should_remove,
            needs_human_review=needs_review,
            risk_level=risk_level,
        )

    async def get_weekly_optimization(
        self,
        campaign_data: Optional[CampaignData] = None,
        period_days: int = 7,
    ) -> OptimizationReport:
        return await self.optimizer.generate_weekly_report(
            campaign_data=campaign_data,
            period_days=period_days,
        )

    def register_sender(self, sender: SenderAccount) -> str:
        return self.sender_manager.register_sender(sender)

    def record_send(self, sender_id: str) -> None:
        self.sender_manager.record_send(sender_id)
        self.guardrails.record_send()

    def record_bounce(self, sender_id: str) -> None:
        self.sender_manager.record_bounce(sender_id)

    def record_complaint(self, sender_id: str) -> None:
        self.sender_manager.record_complaint(sender_id)
        logger.critical("Complaint recorded for sender %s", sender_id)
"""
Outreach Orchestrator.

Main coordinator for the AI-powered outreach system.
Coordinates all services with proper guardrails and flow control.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from .lead_intelligence import (
    LeadIntelligenceService,
    CompanyData
)
from .email_generator import (
    EmailGeneratorService,
    EmailGenerationRequest,
    FollowUpRequest
)
from .reply_handler import (
    ReplyHandlerService,
    ReplyContext
)
from .sender_manager import SenderManagerService
from .optimizer import CampaignOptimizerService
from .guardrails import GuardrailsService, OutreachLimits

logger = logging.getLogger(__name__)


class OutreachOrchestrator:
    """
    Main orchestrator for the outreach system.
    
    Principles:
    - AI handles intelligence generation
    - System (guardrails) handles constraints
    - Never skip safety checks
    - Always log decisions
    """
    
    def __init__(
        self,
        ai_client: Any,
        limits: Optional[OutreachLimits] = None
    ):
        """
        Initialize the orchestrator with all services.
        
        Args:
            ai_client: AI client for all AI operations (OpenAI client)
            limits: Custom outreach limits
        """
        self.ai_client = ai_client
        
        # Initialize services
        self.intelligence = LeadIntelligenceService(ai_client)
        self.email_generator = EmailGeneratorService(ai_client)
        self.reply_handler = ReplyHandlerService(ai_client)
        self.sender_manager = SenderManagerService(ai_client)
        self.optimizer = CampaignOptimizerService(ai_client)
        self.guardrails = GuardrailsService(limits)
        
        logger.info("OutreachOrchestrator initialized")
    
    def process_new_lead(
        self,
        company_data: CompanyData,
        contact_name: str,
        contact_role: str,
        contact_email: str,
        campaign_positioning: str = "",
        cta_style: str = "soft",
        sender_name: str = "",
        sender_title: str = "",
        sender_company: str = "",
        recipient_timezone: str = "UTC"
    ) -> Dict[str, Any]:
        """
        Full pipeline for processing a new lead.
        
        Steps:
        1. Extract intelligence from company data
        2. Score the lead
        3. Check guardrails (lead score, time, etc.)
        4. Generate email
        5. Check for spam
        6. Assess overall risk
        7. Return result
        
        Returns:
            Dict with success status, email content, scores, and metadata
        """
        logger.info(f"Processing new lead: {contact_email}")
        
        try:
            # Step 1 & 2: Extract and score
            intel, score = self.intelligence.extract_and_score(company_data)
            
            logger.info(f"Lead {contact_email}: score={score.lead_score}, tier={score.priority_tier}")
            
            # Step 3: Check lead guardrails
            can_outreach, reason = self.guardrails.can_outreach_lead(
                lead_score=score.lead_score,
                previous_emails_sent=0,
                last_email_date=None
            )
            
            if not can_outreach:
                return {
                    "success": False,
                    "action": "skip",
                    "lead_score": score.lead_score,
                    "reason": reason
                }
            
            # Check time guardrails
            can_send_now, time_reason = self.guardrails.is_valid_send_time(
                recipient_timezone=recipient_timezone
            )
            
            if not can_send_now:
                return {
                    "success": False,
                    "action": "defer",
                    "lead_score": score.lead_score,
                    "reason": time_reason,
                    "metadata": {"intelligence": intel.model_dump()}
                }
            
            # Step 4: Generate email
            email_request = EmailGenerationRequest(
                contact_name=contact_name,
                contact_role=contact_role,
                company_name=company_data.company_name,
                intelligence=intel,
                trigger_event=company_data.trigger_event,
                campaign_positioning=campaign_positioning,
                cta_style=cta_style,
                sender_name=sender_name,
                sender_title=sender_title,
                sender_company=sender_company
            )
            
            email, spam_check = self.email_generator.generate_and_validate(email_request)
            
            # Step 5: Final risk assessment
            risk = self.guardrails.assess_send_risk(
                sender_id="default",  # Will be assigned later
                sender_bounce_rate=0,
                sender_complaint_rate=0,
                sender_health_score=100,
                lead_score=score.lead_score,
                email_spam_score=spam_check.spam_score,
                is_first_email=True
            )
            
            if not risk.should_proceed:
                return {
                    "success": False,
                    "action": "halt",
                    "email": email.model_dump(),
                    "spam_check": spam_check.model_dump(),
                    "lead_score": score.lead_score,
                    "risk_assessment": risk.model_dump(),
                    "reason": f"Risk too high: {', '.join(risk.reasons)}"
                }
            
            # Success!
            logger.info(f"Email ready for {contact_email}: subject='{email.subject}'")
            
            return {
                "success": True,
                "action": "send",
                "email": email.model_dump(),
                "spam_check": spam_check.model_dump(),
                "lead_score": score.lead_score,
                "risk_assessment": risk.model_dump(),
                "metadata": {
                    "intelligence": intel.model_dump(),
                    "score_details": score.model_dump()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to process lead {contact_email}: {e}")
            return {
                "success": False,
                "action": "error",
                "reason": str(e)
            }
    
    def process_followup(
        self,
        contact_email: str,
        contact_name: str,
        company_name: str,
        original_subject: str,
        original_body: str,
        days_since_sent: int,
        open_count: int,
        click_count: int = 0,
        previous_emails_count: int = 1,
        last_email_date: Optional[datetime] = None,
        intelligence_summary: str = ""
    ) -> Dict[str, Any]:
        """
        Process follow-up email generation.
        
        Returns:
            Dict with success status and follow-up email
        """
        logger.info(f"Processing follow-up for {contact_email}")
        
        # Check guardrails
        can_outreach, reason = self.guardrails.can_outreach_lead(
            lead_score=70,  # Assume qualified if in sequence
            previous_emails_sent=previous_emails_count,
            last_email_date=last_email_date
        )
        
        if not can_outreach:
            return {
                "success": False,
                "action": "skip",
                "reason": reason
            }
        
        try:
            # Generate follow-up
            from .email_generator import GeneratedEmail
            original_email = GeneratedEmail(
                subject=original_subject,
                body=original_body
            )
            
            request = FollowUpRequest(
                original_email=original_email,
                days_since_sent=days_since_sent,
                open_count=open_count,
                click_count=click_count,
                intelligence_summary=intelligence_summary,
                followup_number=previous_emails_count,
                contact_name=contact_name,
                company_name=company_name
            )
            
            followup = self.email_generator.generate_followup(request)
            
            return {
                "success": True,
                "action": "send_followup",
                "email": followup.model_dump()
            }
            
        except Exception as e:
            logger.error(f"Failed to generate follow-up for {contact_email}: {e}")
            return {
                "success": False,
                "action": "error",
                "reason": str(e)
            }
    
    def process_reply(
        self,
        reply_text: str,
        original_email_subject: str,
        original_email_body: str,
        contact_name: str = "",
        company_name: str = "",
        thread_history: list = None
    ) -> Dict[str, Any]:
        """
        Process an incoming reply.
        
        Classifies the reply and generates an auto-response if appropriate.
        
        Returns:
            Dict with classification, auto_response, and action flags
        """
        logger.info(f"Processing reply from {contact_name or 'unknown'}")
        
        context = ReplyContext(
            reply_text=reply_text,
            original_email_subject=original_email_subject,
            original_email_body=original_email_body,
            thread_history=thread_history or [],
            contact_name=contact_name,
            company_name=company_name
        )
        
        # Classify
        classification = self.reply_handler.classify_reply(context)
        
        # Check risk
        is_risk, risk_level, _ = self.guardrails.check_reply_risk(
            classification.classification,
            classification.confidence
        )
        
        # Determine actions
        should_halt = classification.classification in ["Legal Warning", "Spam Complaint Risk"]
        should_remove = classification.classification in [
            "Not Interested", "Legal Warning", "Spam Complaint Risk"
        ]
        needs_review = classification.needs_human_review or is_risk
        
        # Generate auto-response if safe
        auto_response = None
        if not should_halt and not needs_review:
            can_respond, _ = self.guardrails.can_auto_respond(
                classification.classification,
                classification.confidence
            )
            if can_respond:
                auto_response = self.reply_handler.generate_auto_response(
                    classification, context
                )
        
        return {
            "classification": classification.model_dump(),
            "auto_response": auto_response.model_dump() if auto_response else None,
            "should_halt": should_halt,
            "should_remove_from_sequence": should_remove,
            "needs_human_review": needs_review,
            "risk_level": risk_level
        }
    
    def record_send(self, sender_id: str) -> None:
        """Record a successful send."""
        self.sender_manager.record_send(sender_id)
        self.guardrails.record_send()
    
    def record_bounce(self, sender_id: str) -> None:
        """Record a bounce."""
        self.sender_manager.record_bounce(sender_id)
    
    def record_complaint(self, sender_id: str) -> None:
        """Record a complaint - CRITICAL."""
        self.sender_manager.record_complaint(sender_id)
        logger.critical(f"Complaint recorded for sender {sender_id}")
