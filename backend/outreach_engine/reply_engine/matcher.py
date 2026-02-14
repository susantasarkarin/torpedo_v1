"""
REPLY MATCHER
=============

Multi-layer thread matching to link incoming replies to outbound sends.

Match Order (4 fallback levels):
1. In-Reply-To header → exact message_id match (confidence: 1.0)
2. References array → any ID matches our sends (confidence: 0.95)
3. thread_id → Gmail thread ID match (confidence: 0.85)
4. subject + sender → fallback match (confidence: 0.60)

Enterprise Rules:
- Match confidence < 0.65 → mark as unmatched
- Never silently trust weak matches
- Store match method for debugging
- Unmatched replies logged for manual review
"""

import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pymongo.database import Database

from .models import MatchResult, MatchMethod

logger = logging.getLogger(__name__)


# ============== CONFIDENCE MAP ==============

MATCH_CONFIDENCE = {
    MatchMethod.IN_REPLY_TO: 1.0,
    MatchMethod.REFERENCES: 0.95,
    MatchMethod.THREAD_ID: 0.85,
    MatchMethod.SUBJECT_SENDER: 0.60,
    MatchMethod.UNMATCHED: 0.0,
}

# Minimum confidence to consider a match valid
MIN_MATCH_CONFIDENCE = 0.65


class ReplyMatcher:
    """
    Multi-layer reply-to-outbound matching.
    
    Uses 4 fallback levels to maximize match rate while
    maintaining confidence tracking.
    """
    
    def __init__(self, db: Database):
        """
        Initialize matcher.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.sends_collection = db["outreach_sends_v2"]
        self.leads_collection = db["outreach_leads_v2"]
    
    def match_reply(
        self,
        in_reply_to: Optional[str],
        references: List[str],
        thread_id: Optional[str],
        subject: Optional[str],
        from_email: str,
        mailbox_id: str
    ) -> MatchResult:
        """
        Match incoming reply to outbound send using 4-layer fallback.
        
        Args:
            in_reply_to: In-Reply-To header value
            references: References header values
            thread_id: Gmail thread ID
            subject: Email subject
            from_email: Sender email address
            mailbox_id: Receiving mailbox ID
            
        Returns:
            MatchResult with confidence and matched entities
        """
        # Layer 1: In-Reply-To (highest confidence)
        if in_reply_to:
            result = self._match_by_in_reply_to(in_reply_to)
            if result.matched:
                logger.info(f"Matched reply via In-Reply-To: {in_reply_to[:50]}")
                return result
        
        # Layer 2: References (high confidence)
        if references:
            result = self._match_by_references(references)
            if result.matched:
                logger.info(f"Matched reply via References: {references[0][:50] if references else 'none'}")
                return result
        
        # Layer 3: Thread ID (medium-high confidence)
        if thread_id:
            result = self._match_by_thread_id(thread_id, from_email)
            if result.matched:
                logger.info(f"Matched reply via thread_id: {thread_id}")
                return result
        
        # Layer 4: Subject + Sender (low confidence fallback)
        if subject and from_email:
            result = self._match_by_subject_sender(subject, from_email, mailbox_id)
            if result.matched:
                # Check confidence threshold
                if result.confidence < MIN_MATCH_CONFIDENCE:
                    logger.warning(
                        f"Subject/sender match below threshold ({result.confidence}), "
                        f"storing as candidate for manual review"
                    )
                    # PRESERVE candidate info for manual review
                    # Don't silently discard - store for debugging
                    return MatchResult(
                        matched=False,
                        method=MatchMethod.SUBJECT_SENDER,  # Keep method for tracking
                        confidence=result.confidence,
                        matched_subject=subject,
                        matched_sender=from_email,
                        # Store candidates for manual review
                        lead_id_candidate=result.lead_id,
                        campaign_id_candidate=result.campaign_id,
                        flag_for_manual_review=True
                    )
                logger.info(f"Matched reply via subject/sender: {from_email}")
                return result
        
        # No match found
        logger.debug(f"No match found for reply from {from_email}")
        return MatchResult(
            matched=False,
            method=MatchMethod.UNMATCHED,
            confidence=0.0
        )
    
    # ============== LAYER 1: IN-REPLY-TO ==============
    
    def _match_by_in_reply_to(self, in_reply_to: str) -> MatchResult:
        """
        Match by In-Reply-To header (exact message_id match).
        
        Confidence: 1.0
        """
        # Clean the message ID
        message_id = self._normalize_message_id(in_reply_to)
        
        # Find send with this message_id
        send = self.sends_collection.find_one({
            "message_id": message_id
        })
        
        if not send:
            # Try without angle brackets
            send = self.sends_collection.find_one({
                "message_id": {"$regex": re.escape(message_id.strip("<>"))}
            })
        
        if send:
            return MatchResult(
                matched=True,
                method=MatchMethod.IN_REPLY_TO,
                confidence=MATCH_CONFIDENCE[MatchMethod.IN_REPLY_TO],
                lead_id=send.get("lead_id"),
                campaign_id=send.get("campaign_id"),
                mailbox_id=send.get("mailbox_id"),
                original_send_id=send.get("send_id"),
                workflow_step=send.get("workflow_step"),
                matched_message_id=message_id
            )
        
        return MatchResult(
            matched=False,
            method=MatchMethod.IN_REPLY_TO,
            confidence=0.0
        )
    
    # ============== LAYER 2: REFERENCES ==============
    
    def _match_by_references(self, references: List[str]) -> MatchResult:
        """
        Match by References header (any ID matches our sends).
        
        Confidence: 0.95
        """
        # Normalize all references
        normalized_refs = [self._normalize_message_id(ref) for ref in references]
        
        # Find any send matching these references
        send = self.sends_collection.find_one({
            "message_id": {"$in": normalized_refs}
        })
        
        if not send:
            # Try with stripped angle brackets
            stripped_refs = [ref.strip("<>") for ref in normalized_refs]
            pipeline = [
                {"$match": {
                    "$or": [
                        {"message_id": {"$in": normalized_refs}},
                        {"message_id": {"$regex": f"({'|'.join(map(re.escape, stripped_refs))})"}}
                    ]
                }},
                {"$limit": 1}
            ]
            results = list(self.sends_collection.aggregate(pipeline))
            send = results[0] if results else None
        
        if send:
            return MatchResult(
                matched=True,
                method=MatchMethod.REFERENCES,
                confidence=MATCH_CONFIDENCE[MatchMethod.REFERENCES],
                lead_id=send.get("lead_id"),
                campaign_id=send.get("campaign_id"),
                mailbox_id=send.get("mailbox_id"),
                original_send_id=send.get("send_id"),
                workflow_step=send.get("workflow_step"),
                matched_message_id=send.get("message_id")
            )
        
        return MatchResult(
            matched=False,
            method=MatchMethod.REFERENCES,
            confidence=0.0
        )
    
    # ============== LAYER 3: THREAD ID ==============
    
    def _match_by_thread_id(
        self,
        thread_id: str,
        from_email: str
    ) -> MatchResult:
        """
        Match by Gmail thread_id.
        
        Additional validation: sender email must match a lead.
        
        Confidence: 0.85
        """
        # Find lead with this thread_id
        lead = self.leads_collection.find_one({
            "thread_id": thread_id,
            "email": from_email.lower()
        })
        
        if lead:
            # Get the most recent send for this lead
            send = self.sends_collection.find_one(
                {"lead_id": lead.get("lead_id")},
                sort=[("sent_at", -1)]
            )
            
            return MatchResult(
                matched=True,
                method=MatchMethod.THREAD_ID,
                confidence=MATCH_CONFIDENCE[MatchMethod.THREAD_ID],
                lead_id=lead.get("lead_id"),
                campaign_id=lead.get("campaign_id"),
                mailbox_id=lead.get("assigned_mailbox_id"),
                original_send_id=send.get("send_id") if send else None,
                workflow_step=lead.get("current_step"),
                matched_thread_id=thread_id
            )
        
        return MatchResult(
            matched=False,
            method=MatchMethod.THREAD_ID,
            confidence=0.0
        )
    
    # ============== LAYER 4: SUBJECT + SENDER ==============
    
    def _match_by_subject_sender(
        self,
        subject: str,
        from_email: str,
        mailbox_id: str
    ) -> MatchResult:
        """
        Fallback match by normalized subject + sender email.
        
        Confidence: 0.60 (BELOW threshold - will be marked unmatched)
        """
        # Normalize subject (strip Re:, Fwd:, etc.)
        normalized_subject = self._normalize_subject(subject)
        
        # Find lead by email
        lead = self.leads_collection.find_one({
            "email": from_email.lower()
        })
        
        if not lead:
            return MatchResult(
                matched=False,
                method=MatchMethod.SUBJECT_SENDER,
                confidence=0.0
            )
        
        # Verify we sent to this lead from this mailbox
        send = self.sends_collection.find_one({
            "lead_id": lead.get("lead_id"),
            "mailbox_id": mailbox_id
        }, sort=[("sent_at", -1)])
        
        if send:
            # Verify subject similarity
            sent_subject = self._normalize_subject(send.get("subject", ""))
            if self._subjects_match(normalized_subject, sent_subject):
                return MatchResult(
                    matched=True,
                    method=MatchMethod.SUBJECT_SENDER,
                    confidence=MATCH_CONFIDENCE[MatchMethod.SUBJECT_SENDER],
                    lead_id=lead.get("lead_id"),
                    campaign_id=send.get("campaign_id"),
                    mailbox_id=mailbox_id,
                    original_send_id=send.get("send_id"),
                    workflow_step=send.get("workflow_step"),
                    matched_subject=normalized_subject,
                    matched_sender=from_email
                )
        
        return MatchResult(
            matched=False,
            method=MatchMethod.SUBJECT_SENDER,
            confidence=0.0
        )
    
    # ============== UTILITIES ==============
    
    def _normalize_message_id(self, message_id: str) -> str:
        """Normalize message ID format."""
        if not message_id:
            return ""
        # Ensure angle brackets
        message_id = message_id.strip()
        if not message_id.startswith("<"):
            message_id = f"<{message_id}"
        if not message_id.endswith(">"):
            message_id = f"{message_id}>"
        return message_id
    
    def _normalize_subject(self, subject: str) -> str:
        """
        Normalize subject for comparison.
        
        Removes: Re:, Fwd:, FW:, RE:, etc.
        """
        if not subject:
            return ""
        
        # Remove common prefixes
        patterns = [
            r"^(re|fwd|fw|aw|antw|vs|sv|ref):\s*",  # Common reply/forward prefixes
            r"^\[.*?\]\s*",  # Bracketed prefixes
        ]
        
        normalized = subject.strip().lower()
        for pattern in patterns:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        
        return normalized
    
    def _subjects_match(self, subject1: str, subject2: str) -> bool:
        """
        Check if two normalized subjects match.
        
        Uses fuzzy matching for slight variations.
        """
        if not subject1 or not subject2:
            return False
        
        # Exact match
        if subject1 == subject2:
            return True
        
        # One contains the other
        if subject1 in subject2 or subject2 in subject1:
            return True
        
        # Word overlap > 70%
        words1 = set(subject1.split())
        words2 = set(subject2.split())
        
        if not words1 or not words2:
            return False
        
        overlap = len(words1 & words2)
        max_words = max(len(words1), len(words2))
        
        return (overlap / max_words) > 0.7
    
    # ============== BULK OPERATIONS ==============
    
    def get_unmatched_replies(
        self,
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get unmatched replies for manual review.
        
        Args:
            limit: Max replies to return
            since: Only get replies after this time
            
        Returns:
            List of unmatched reply logs
        """
        query = {"match_method": MatchMethod.UNMATCHED.value}
        
        if since:
            query["received_at"] = {"$gte": since}
        
        return list(
            self.db["outreach_reply_logs"]
            .find(query)
            .sort("received_at", -1)
            .limit(limit)
        )
