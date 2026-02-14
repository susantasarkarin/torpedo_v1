"""
HYBRID CLASSIFIER
=================

Two-stage classification: deterministic rules first, then AI fallback.

Rule Layer (Free + Instant):
- Spam complaint patterns → immediate classification
- Bounce patterns → immediate classification
- OOO patterns → immediate classification
- Unsubscribe patterns → immediate classification

AI Layer (GPT-4o-mini):
- Only invoked when rules don't match
- Returns intent + confidence + extracted data
- Confidence < 0.65 → classify as UNKNOWN
- Max 8 second timeout, 1 retry
- Structured extraction for OOO dates and referrals

Enterprise Rules:
- Spam complaints NEVER go to AI (speed + safety)
- classification_method always set explicitly
- AI failures → classify as UNKNOWN, not error
- Token budget: ~100 tokens response
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from enum import Enum
import asyncio

from .models import (
    ReplyIntent,
    ClassificationMethod,
    ClassificationResult,
    ExtractedData,
    CONFIDENCE_THRESHOLD,
    MAX_AI_TEXT_LENGTH,
)

logger = logging.getLogger(__name__)

# AI Config
AI_MODEL = "gpt-4o-mini"
AI_TIMEOUT_SECONDS = 8
AI_MAX_RETRIES = 1
AI_MAX_TOKENS = 150


# ============== RULE PATTERNS ==============

class RulePatterns:
    """
    Deterministic rule patterns for classification.
    
    Order matters: more specific patterns first.
    """
    
    # SPAM_COMPLAINT - Critical, never send to AI
    # FALSE NEGATIVE HERE IS CATASTROPHIC - be aggressive
    SPAM_COMPLAINT = [
        r"marked?\s*(as\s+)?spam",
        r"reported?\s*(as\s+)?spam",
        r"report(ing|ed)?\s+.*\s+spam",
        r"block(ed|ing)?\s+(your|this)",
        r"abuse\s+report",
        r"will\s+report",
        r"reporting\s+(you|this)",
        r"spam(ming|med)?",
        r"harassment",
        r"legal\s+action",
        r"lawyer|attorney",
        r"cease\s+and\s+desist",
        # Additional regulatory/legal keywords - CRITICAL
        r"\bftc\b",           # Federal Trade Commission
        r"can-?spam",         # CAN-SPAM Act
        r"\bgdpr\b",          # GDPR
        r"\bccpa\b",          # California Consumer Privacy Act
        r"lawsuit",
        r"sue\s+(you|your)",
        r"litigation",
        r"attorney\s+general",
        r"data\s+protection\s+(authority|officer)",
        r"privacy\s+complaint",
        r"unauthorized\s+(email|contact|solicitation)",
        r"illegal\s+(email|spam|solicitation)",
    ]
    
    # BOUNCE - Delivery failures
    BOUNCE = [
        r"delivery\s+(has\s+)?fail(ed|ure)",
        r"undeliverable",
        r"message\s+not\s+delivered",
        r"address\s+(not\s+found|rejected|invalid)",
        r"mailbox\s+(full|unavailable|not\s+found)",
        r"user\s+(unknown|not\s+found|doesn'?t\s+exist)",
        r"no\s+such\s+user",
        r"recipient\s+rejected",
        r"550\s+",  # SMTP rejection
        r"554\s+",  # SMTP rejection
        r"mail\s+delivery\s+subsystem",
        r"mailer-daemon",
    ]
    
    # NOT_INTERESTED - Clear rejections
    NOT_INTERESTED = [
        r"unsubscribe\s+me",
        r"remove\s+(me|my\s+email)",
        r"take\s+me\s+off",
        r"stop\s+(emailing|contacting|sending)",
        r"don'?t\s+(contact|email|send)",
        r"not\s+interested",
        r"no\s+thanks?",
        r"please\s+stop",
        r"wrong\s+person",
        r"not\s+(the\s+)?right\s+(person|contact|fit)",
        r"leave\s+me\s+alone",
        r"do\s+not\s+contact",
        r"never\s+contact",
    ]
    
    # OOO - Out of office
    OOO = [
        r"out\s+of\s+(the\s+)?office",
        r"(i'?m|i\s+am)\s+(currently\s+)?(away|on\s+vacation|on\s+leave|out)",
        r"on\s+(annual\s+)?leave",
        r"on\s+vacation",
        r"on\s+(maternity|paternity|sick)\s+leave",
        r"limited\s+(email\s+)?access",
        r"will\s+(return|be\s+back)\s+(on|after)",
        r"back\s+(on|after|in)\s+",
        r"(i'?ll|i\s+will)\s+respond\s+(when|after)",
        r"auto(matic)?\s*-?\s*reply",
        r"automatic\s+response",
    ]
    
    # REFERRAL indicators (needs AI for extraction)
    REFERRAL_INDICATORS = [
        r"(contact|reach\s+out\s+to|speak\s+(to|with)|email)\s+\w+",
        r"(the\s+)?right\s+person\s+(would\s+be|is|to\s+contact)",
        r"(you\s+)?should\s+(talk|speak)\s+(to|with)",
        r"(try|contact)\s+\w+@",  # Mentions an email
        r"forward(ed|ing)?\s+(this\s+)?(to|along)",
        r"pass(ed|ing)?\s+(this\s+)?on\s+to",
        r"cc'?d\s+",
        r"looping\s+in",
    ]


# ============== RULE CLASSIFIER ==============

class RuleClassifier:
    """
    Deterministic rule-based classification.
    
    Fast, free, and guaranteed consistent.
    """
    
    def __init__(self):
        """Compile all patterns."""
        self._patterns: Dict[ReplyIntent, list] = {
            ReplyIntent.SPAM_COMPLAINT: [
                re.compile(p, re.IGNORECASE) for p in RulePatterns.SPAM_COMPLAINT
            ],
            ReplyIntent.BOUNCE: [
                re.compile(p, re.IGNORECASE) for p in RulePatterns.BOUNCE
            ],
            ReplyIntent.NOT_INTERESTED: [
                re.compile(p, re.IGNORECASE) for p in RulePatterns.NOT_INTERESTED
            ],
            ReplyIntent.OOO: [
                re.compile(p, re.IGNORECASE) for p in RulePatterns.OOO
            ],
        }
        
        self._referral_patterns = [
            re.compile(p, re.IGNORECASE) for p in RulePatterns.REFERRAL_INDICATORS
        ]
    
    def classify(self, text: str) -> Optional[ClassificationResult]:
        """
        Attempt rule-based classification.
        
        Args:
            text: Cleaned reply text
            
        Returns:
            ClassificationResult if rule matched, None otherwise
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        # Check patterns in priority order
        for intent, patterns in self._patterns.items():
            for pattern in patterns:
                match = pattern.search(text_lower)
                if match:
                    return ClassificationResult(
                        intent=intent,
                        confidence=1.0,  # Rules have perfect confidence
                        method=ClassificationMethod.RULE,
                        matched_rule=intent.value,
                        matched_pattern=pattern.pattern,
                        below_confidence_threshold=False
                    )
        
        return None
    
    def has_referral_indicators(self, text: str) -> bool:
        """Check if text has referral-like patterns."""
        text_lower = text.lower()
        for pattern in self._referral_patterns:
            if pattern.search(text_lower):
                return True
        return False


# ============== AI CLASSIFIER ==============

class AIClassifier:
    """
    AI-based classification using GPT-4o-mini.
    
    Features:
    - Structured JSON output
    - Confidence scoring
    - OOO date extraction
    - Referral contact extraction
    - Timeout and retry handling
    """
    
    CLASSIFICATION_PROMPT = """Classify this email reply into ONE of these categories:

- interested: Wants to learn more, schedule meeting, discuss further
- soft_interest: Open but not urgent, "maybe later", "send more info"
- not_now: Bad timing, busy, try again later (with timeframe)
- not_interested: Clear rejection, not a fit, wrong person
- referral: Suggests contacting someone else (includes name/email)
- ooo: Out of office / vacation / away message
- spam_complaint: Angry about receiving email, threatens to report
- bounce: Delivery failure / address invalid

Respond ONLY with valid JSON (no markdown, no explanation):
{
  "intent": "<category>",
  "confidence": <0.0-1.0>,
  "return_date": "<YYYY-MM-DD or null>",
  "referral_name": "<name or null>",
  "referral_email": "<email or null>",
  "timeframe": "<mentioned timeframe or null>"
}

Reply text:
\"\"\"
{text}
\"\"\""""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize AI classifier.
        
        Args:
            api_key: OpenAI API key (falls back to env)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = None
    
    def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                import openai
                openai.api_key = self.api_key
                self._client = openai
            except ImportError:
                logger.error("openai package not installed")
                return None
        return self._client
    
    def classify(self, text: str) -> ClassificationResult:
        """
        Classify text using AI.
        
        Args:
            text: Cleaned reply text
            
        Returns:
            ClassificationResult (UNKNOWN if AI fails)
        """
        # Truncate if needed
        if len(text) > MAX_AI_TEXT_LENGTH:
            text = text[:MAX_AI_TEXT_LENGTH] + "..."
        
        # Build prompt
        prompt = self.CLASSIFICATION_PROMPT.format(text=text)
        
        # Try classification with retry
        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                result = self._call_api(prompt)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"AI classification attempt {attempt + 1} failed: {e}")
                if attempt < AI_MAX_RETRIES:
                    continue
        
        # All attempts failed → return UNKNOWN
        logger.error("AI classification failed, returning UNKNOWN")
        return ClassificationResult(
            intent=ReplyIntent.UNKNOWN,
            confidence=0.0,
            method=ClassificationMethod.AI,
            below_confidence_threshold=True,
            ai_model=AI_MODEL
        )
    
    def _call_api(self, prompt: str) -> Optional[ClassificationResult]:
        """
        Call OpenAI API with timeout.
        
        Returns:
            ClassificationResult or None on error
        """
        client = self._get_client()
        if not client:
            return None
        
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a precise email classifier. Output only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=AI_MAX_TOKENS,
                temperature=0.1,  # Low temp for consistency
                timeout=AI_TIMEOUT_SECONDS
            )
            
            # Parse response
            content = response.choices[0].message.content.strip()
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            return self._parse_response(content, tokens_used)
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
    
    def _parse_response(
        self,
        content: str,
        tokens_used: int
    ) -> Optional[ClassificationResult]:
        """
        Parse AI JSON response.
        
        Returns:
            ClassificationResult or None if parsing fails
        """
        try:
            # Clean potential markdown
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```\w*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            
            data = json.loads(content)
            
            # Extract fields
            intent_str = data.get("intent", "unknown").lower()
            confidence = float(data.get("confidence", 0.5))
            
            # Map to enum
            try:
                intent = ReplyIntent(intent_str)
            except ValueError:
                intent = ReplyIntent.UNKNOWN
            
            # Check confidence threshold
            below_threshold = confidence < CONFIDENCE_THRESHOLD
            if below_threshold:
                intent = ReplyIntent.UNKNOWN
            
            # Build extracted data
            extracted = ExtractedData(
                return_date=data.get("return_date"),
                referral_name=data.get("referral_name"),
                referral_email=data.get("referral_email"),
                mentioned_timeframe=data.get("timeframe")
            )
            
            return ClassificationResult(
                intent=intent,
                confidence=confidence,
                method=ClassificationMethod.AI,
                extracted_data=extracted,
                below_confidence_threshold=below_threshold,
                ai_model=AI_MODEL,
                ai_tokens_used=tokens_used,
                ai_raw_response=content
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}\nContent: {content}")
            return None
        except Exception as e:
            logger.error(f"Error processing AI response: {e}")
            return None


# ============== HYBRID CLASSIFIER ==============

class HybridClassifier:
    """
    Two-stage hybrid classifier.
    
    1. Rules first (free, instant, deterministic)
    2. AI fallback (if rules don't match)
    
    Enterprise features:
    - Spam complaints never go to AI
    - Confidence threshold (0.65)
    - Explicit classification_method tracking
    - Graceful degradation on AI failure
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize hybrid classifier.
        
        Args:
            api_key: OpenAI API key for AI fallback
        """
        self.rule_classifier = RuleClassifier()
        self.ai_classifier = AIClassifier(api_key)
    
    def classify(self, text: str) -> ClassificationResult:
        """
        Classify reply text using hybrid approach.
        
        Args:
            text: Cleaned reply text
            
        Returns:
            ClassificationResult with intent, confidence, method
        """
        if not text or len(text.strip()) < 3:
            return ClassificationResult(
                intent=ReplyIntent.UNKNOWN,
                confidence=0.0,
                method=ClassificationMethod.RULE,
                below_confidence_threshold=True
            )
        
        # Stage 1: Try rules first
        rule_result = self.rule_classifier.classify(text)
        
        if rule_result:
            logger.info(
                f"Rule classification: {rule_result.intent.value} "
                f"(pattern: {rule_result.matched_pattern})"
            )
            return rule_result
        
        # Stage 2: AI classification
        logger.debug("No rule match, falling back to AI")
        ai_result = self.ai_classifier.classify(text)
        
        logger.info(
            f"AI classification: {ai_result.intent.value} "
            f"(confidence: {ai_result.confidence:.2f}, "
            f"below_threshold: {ai_result.below_confidence_threshold})"
        )
        
        return ai_result
    
    def classify_batch(
        self,
        texts: list[Tuple[str, str]]  # (reply_id, text)
    ) -> Dict[str, ClassificationResult]:
        """
        Classify multiple replies.
        
        Args:
            texts: List of (reply_id, text) tuples
            
        Returns:
            Dict mapping reply_id to ClassificationResult
        """
        results = {}
        
        for reply_id, text in texts:
            try:
                results[reply_id] = self.classify(text)
            except Exception as e:
                logger.error(f"Classification error for {reply_id}: {e}")
                results[reply_id] = ClassificationResult(
                    intent=ReplyIntent.UNKNOWN,
                    confidence=0.0,
                    method=ClassificationMethod.AI,
                    below_confidence_threshold=True
                )
        
        return results


# ============== CONVENIENCE FUNCTIONS ==============

def classify_reply(text: str, api_key: Optional[str] = None) -> ClassificationResult:
    """
    Convenience function for single reply classification.
    
    Args:
        text: Cleaned reply text
        api_key: Optional OpenAI API key
        
    Returns:
        ClassificationResult
    """
    classifier = HybridClassifier(api_key)
    return classifier.classify(text)


def get_classification_stats(
    results: list[ClassificationResult]
) -> Dict[str, Any]:
    """
    Calculate classification statistics.
    
    Args:
        results: List of classification results
        
    Returns:
        Stats dict with counts and rates
    """
    if not results:
        return {"total": 0}
    
    stats = {
        "total": len(results),
        "by_intent": {},
        "by_method": {},
        "avg_confidence": 0.0,
        "below_threshold_count": 0,
        "rule_rate": 0.0,
        "ai_rate": 0.0,
    }
    
    confidence_sum = 0.0
    
    for r in results:
        # By intent
        intent = r.intent.value if isinstance(r.intent, Enum) else r.intent
        stats["by_intent"][intent] = stats["by_intent"].get(intent, 0) + 1
        
        # By method
        method = r.method.value if isinstance(r.method, Enum) else r.method
        stats["by_method"][method] = stats["by_method"].get(method, 0) + 1
        
        # Confidence
        confidence_sum += r.confidence
        
        # Below threshold
        if r.below_confidence_threshold:
            stats["below_threshold_count"] += 1
    
    stats["avg_confidence"] = confidence_sum / len(results)
    stats["rule_rate"] = stats["by_method"].get("rule", 0) / len(results)
    stats["ai_rate"] = stats["by_method"].get("ai", 0) / len(results)
    
    return stats
