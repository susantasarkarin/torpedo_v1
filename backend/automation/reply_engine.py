"""
Reply Intelligence Engine

Classifies inbound replies and automates sequence decisions.
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from bson import ObjectId
from pymongo.database import Database

logger = logging.getLogger(__name__)


class ReplyIntelligenceEngine:
    """
    AI-based reply classification with compliance logging.
    """

    MIN_CONFIDENCE_THRESHOLD = 0.85
    ALLOWED_CLASSIFICATIONS = {
        "positive_interest",
        "neutral_response",
        "objection",
        "unsubscribe",
        "spam_risk",
    }

    def __init__(self, db: Database, openai_wrapper=None, decision_logger=None):
        self.db = db
        self.reply_decisions = db["reply_decisions"]
        self.campaign_recipients = db["campaign_recipients"]
        self.leads_enriched = db["leads_enriched"]
        self.leads = db["leads"]
        self.openai_wrapper = openai_wrapper
        self.decision_logger = decision_logger
        self._setup_indexes()

    def _setup_indexes(self) -> None:
        try:
            self.reply_decisions.create_index([("lead_id", 1), ("logged_at", -1)])
            self.reply_decisions.create_index([("campaign_id", 1), ("logged_at", -1)])
            self.reply_decisions.create_index([("classification", 1), ("logged_at", -1)])
        except Exception as exc:
            logger.warning(f"Reply decision index creation warning: {exc}")

    def classify_reply(self, lead_id: str, campaign_id: str, reply_text: str) -> Dict[str, Any]:
        reply_text = (reply_text or "").strip()
        if not reply_text:
            return self._build_fallback_result(
                lead_id,
                campaign_id,
                "neutral_response",
                0.0,
                "Empty reply text",
                requires_manual_review=True,
                error="Empty reply_text"
            )

        if not self.openai_wrapper:
            return self._build_fallback_result(
                lead_id,
                campaign_id,
                "neutral_response",
                0.0,
                "OpenAI wrapper not configured",
                requires_manual_review=True,
                error="OpenAI wrapper not configured"
            )

        prompt = (
            "Classify this inbound reply to a B2B outreach email. "
            "Return JSON with keys: classification, confidence_score, reasoning. "
            "Classification must be one of: positive_interest, neutral_response, objection, "
            "unsubscribe, spam_risk. Confidence_score is 0-1. Keep reasoning short."
            f"\n\nReply:\n{reply_text}"
        )

        response = self.openai_wrapper.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You classify inbound B2B replies for outreach automation. Respond only with JSON."
                },
                {"role": "user", "content": prompt}
            ],
            source="api",
            endpoint="reply_classification",
            model="gpt-4o-mini",
            max_output_tokens=200,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        if not response.get("success"):
            return self._build_fallback_result(
                lead_id,
                campaign_id,
                "neutral_response",
                0.0,
                "OpenAI classification failed",
                requires_manual_review=True,
                error=response.get("error")
            )

        try:
            data = json.loads(response.get("content", "{}"))
        except json.JSONDecodeError as exc:
            return self._build_fallback_result(
                lead_id,
                campaign_id,
                "neutral_response",
                0.0,
                "Invalid JSON from model",
                requires_manual_review=True,
                error=str(exc)
            )

        classification = str(data.get("classification", "neutral_response")).strip()
        confidence_score = self._safe_float(data.get("confidence_score"))
        reasoning = str(data.get("reasoning", "")).strip()

        if classification not in self.ALLOWED_CLASSIFICATIONS:
            classification = "neutral_response"
            confidence_score = 0.0
            reasoning = "Invalid classification label"

        requires_manual_review = confidence_score < self.MIN_CONFIDENCE_THRESHOLD
        action_taken = "manual_review" if requires_manual_review else "none"

        if not requires_manual_review:
            if classification == "positive_interest":
                self._stop_sequence(campaign_id, lead_id, "replied", "interested")
                self._update_lead_status(lead_id, "engaged")
                action_taken = "stop_sequence_engaged"
            elif classification == "unsubscribe":
                self._stop_sequence(campaign_id, lead_id, "unsubscribed", "unsubscribe")
                self._update_lead_status(lead_id, "unsubscribed")
                action_taken = "stop_sequence_unsubscribed"

        decision_log_id = None
        if self.decision_logger:
            decision_log_id = self.decision_logger.log_decision(
                decision_type="reply_classification",
                action=action_taken,
                autonomous=True,
                lead_id=lead_id,
                campaign_id=campaign_id,
                confidence_score=confidence_score,
                reasoning={
                    "classification": classification,
                    "reasoning": reasoning,
                    "requires_manual_review": requires_manual_review
                },
                input_context={"reply_text": reply_text},
                decision_params={"action_taken": action_taken}
            )

        self._log_reply_decision(
            lead_id=lead_id,
            campaign_id=campaign_id,
            classification=classification,
            confidence_score=confidence_score,
            reasoning=reasoning,
            requires_manual_review=requires_manual_review,
            action_taken=action_taken,
            decision_log_id=decision_log_id
        )

        return {
            "classification": classification,
            "confidence_score": round(confidence_score, 3),
            "action_taken": action_taken,
            "decision_log_id": decision_log_id
        }

    def _build_fallback_result(
        self,
        lead_id: str,
        campaign_id: str,
        classification: str,
        confidence_score: float,
        reasoning: str,
        requires_manual_review: bool,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        decision_log_id = None
        action_taken = "manual_review"
        if self.decision_logger:
            decision_log_id = self.decision_logger.log_decision(
                decision_type="reply_classification",
                action=action_taken,
                autonomous=True,
                lead_id=lead_id,
                campaign_id=campaign_id,
                confidence_score=confidence_score,
                reasoning={
                    "classification": classification,
                    "reasoning": reasoning,
                    "requires_manual_review": requires_manual_review
                },
                input_context={"error": error},
                decision_params={"action_taken": action_taken}
            )

        self._log_reply_decision(
            lead_id=lead_id,
            campaign_id=campaign_id,
            classification=classification,
            confidence_score=confidence_score,
            reasoning=reasoning,
            requires_manual_review=requires_manual_review,
            action_taken=action_taken,
            decision_log_id=decision_log_id,
            error=error
        )

        return {
            "classification": classification,
            "confidence_score": round(confidence_score, 3),
            "action_taken": action_taken,
            "decision_log_id": decision_log_id
        }

    def _log_reply_decision(
        self,
        lead_id: str,
        campaign_id: str,
        classification: str,
        confidence_score: float,
        reasoning: str,
        requires_manual_review: bool,
        action_taken: str,
        decision_log_id: Optional[str],
        error: Optional[str] = None
    ) -> str:
        decision_id = str(ObjectId())
        logged_at = datetime.utcnow()
        audit_payload = {
            "decision_type": "reply_classification",
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "classification": classification,
            "confidence_score": confidence_score,
            "timestamp": logged_at.isoformat()
        }
        audit_signature = hashlib.sha256(json.dumps(audit_payload, sort_keys=True).encode()).hexdigest()

        doc = {
            "decision_id": decision_id,
            "lead_id": lead_id,
            "campaign_id": campaign_id,
            "classification": classification,
            "confidence_score": confidence_score,
            "reasoning": reasoning,
            "requires_manual_review": requires_manual_review,
            "action_taken": action_taken,
            "decision_log_id": decision_log_id,
            "error": error,
            "audit_signature": audit_signature,
            "logged_at": logged_at
        }

        try:
            self.reply_decisions.insert_one(doc)
        except Exception as exc:
            logger.error(f"Failed to log reply decision: {exc}")

        return decision_id

    def _stop_sequence(self, campaign_id: str, lead_id: str, status: str, reply_type: str) -> None:
        now = datetime.utcnow()
        self.campaign_recipients.update_one(
            {"campaign_id": campaign_id, "lead_id": lead_id},
            {
                "$set": {
                    "status": status,
                    "reply_type": reply_type,
                    "reply_detected_at": now,
                    "updated_at": now
                }
            }
        )

    def _update_lead_status(self, lead_id: str, status: str) -> None:
        now = datetime.utcnow()
        updates = {"lead_status": status, "engagement_status": status, "updated_at": now}
        self.leads_enriched.update_one({"_id": lead_id}, {"$set": updates})
        self.leads.update_one({"_id": lead_id}, {"$set": updates})

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
