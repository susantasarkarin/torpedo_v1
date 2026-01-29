"""
GEMINI GATEWAY - Single Entry Point for All Gemini Operations
==============================================================
This is the ONLY file that may invoke Gemini API calls.

Gemini is ONLY allowed for:
- Email classification
- Email summarization  
- Lead extraction FROM EXISTING EMAIL THREADS

Gemini MUST NOT be used for:
- Web search
- External lead discovery
- Prospect enrichment outside email context

Constraints (MANDATORY):
- Hard limit: 7,000 requests per day
- One classification per email (unique constraint)
- No automatic retries on failure
- No parallel processing for same email
- No infinite loops or batch processing
- Event-driven, bounded, deterministic
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
import json

# Try new SDK first, fallback to old SDK
try:
    from google import genai
    NEW_GENAI_SDK = True
except ImportError:
    import google.generativeai as genai
    NEW_GENAI_SDK = False

from pymongo import MongoClient

from .governance_checks import (
    check_gemini_daily_limit,
    increment_gemini_daily_usage,
    acquire_classification_lock,
    complete_classification,
    fail_classification,
    GeminiDailyLimitExceeded,
    EmailAlreadyClassified,
)

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

GEMINI_MODEL = "gemini-2.0-flash"

# MongoDB for API keys
_mongo_client: Optional[MongoClient] = None


def _get_mongo_client() -> MongoClient:
    """Get singleton MongoDB client"""
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _mongo_client


def _get_gemini_api_key() -> str:
    """
    Get a Gemini API key from database (rotated keys 1-7).
    Uses simple round-robin based on current usage.
    """
    try:
        client = _get_mongo_client()
        settings = client['torpedo_settings']['app_settings'].find_one()
        
        if settings:
            # Get all available keys
            keys = []
            for i in range(1, 8):  # Keys 1-7
                key = settings.get(f'gemini_api_key_{i}')
                if key:
                    keys.append(key)
            
            if keys:
                # Simple rotation based on time
                index = int(datetime.utcnow().timestamp()) % len(keys)
                return keys[index]
        
        # Fallback to environment variable
        env_key = os.getenv('GEMINI_API_KEY')
        if env_key:
            return env_key
            
    except Exception as e:
        logger.warning(f"Error loading Gemini API key from DB: {e}")
        env_key = os.getenv('GEMINI_API_KEY')
        if env_key:
            return env_key
    
    raise ValueError("No Gemini API key configured in database or environment")


# ============== DATA CLASSES ==============

@dataclass
class ClassificationResult:
    """Result of email classification"""
    email_id: str
    category: str
    confidence: float
    summary: str
    intent: str
    priority: str
    action_required: bool
    classified_at: str
    success: bool
    error: Optional[str] = None


@dataclass
class LeadExtractionResult:
    """Result of lead extraction from email"""
    email_id: str
    leads: List[Dict[str, Any]]
    extracted_at: str
    success: bool
    error: Optional[str] = None


# ============== GEMINI GATEWAY ==============

class GeminiGateway:
    """
    SINGLE ENTRY POINT for all Gemini API operations.
    
    This class enforces all governance rules:
    - Daily limit check before each call
    - One classification per email
    - No retries on failure
    - Logging of all calls
    """
    
    def __init__(self):
        self._client = None
        self._model = None
        self._api_key = None
    
    def _get_client(self):
        """Get configured Gemini client (handles both SDK versions)"""
        if self._client is None:
            self._api_key = _get_gemini_api_key()
            if NEW_GENAI_SDK:
                self._client = genai.Client(api_key=self._api_key)
            else:
                genai.configure(api_key=self._api_key)
                self._model = genai.GenerativeModel(GEMINI_MODEL)
                self._client = self._model
        return self._client
    
    def _call_gemini(self, prompt: str) -> str:
        """
        Internal method to call Gemini API.
        MUST NOT be called directly - use the public methods.
        
        Enforces:
        - Daily limit check
        - Single call (no retries)
        - Error logging
        """
        # MANDATORY: Check daily limit BEFORE incrementing
        if not check_gemini_daily_limit():
            raise GeminiDailyLimitExceeded(
                "Gemini daily limit (7000) reached. No more calls allowed today."
            )
        
        # MANDATORY: Increment counter BEFORE making call
        increment_gemini_daily_usage()
        
        try:
            client = self._get_client()
            
            if NEW_GENAI_SDK:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                return response.text
            else:
                # Old SDK
                response = client.generate_content(prompt)
                return response.text
            
        except Exception as e:
            # Log error ONCE - no retry
            logger.error(f"Gemini API call failed: {e}. NO AUTOMATIC RETRY.")
            raise
    
    def classify_email(
        self,
        email_id: str,
        subject: str,
        body: str,
        from_email: str,
        source: str = "api"
    ) -> ClassificationResult:
        """
        Classify a single email using Gemini.
        
        GOVERNANCE ENFORCED:
        - Email can only be classified ONCE
        - Daily limit checked
        - No retries on failure
        
        Args:
            email_id: Unique email identifier
            subject: Email subject
            body: Email body content
            from_email: Sender email address
            source: Source of request (for audit)
            
        Returns:
            ClassificationResult with category, confidence, etc.
            
        Raises:
            EmailAlreadyClassified: If email was already classified
            GeminiDailyLimitExceeded: If daily limit reached
        """
        # MANDATORY: Acquire classification lock (one-time only)
        acquire_classification_lock(email_id, source)
        
        try:
            prompt = self._build_classification_prompt(subject, body, from_email)
            response_text = self._call_gemini(prompt)
            
            # Parse response
            result = self._parse_classification_response(email_id, response_text)
            
            # Mark classification complete
            complete_classification(email_id, asdict(result))
            
            return result
            
        except (GeminiDailyLimitExceeded, EmailAlreadyClassified):
            raise
            
        except Exception as e:
            # Mark as failed - NO RETRY
            fail_classification(email_id, str(e))
            return ClassificationResult(
                email_id=email_id,
                category="error",
                confidence=0.0,
                summary="",
                intent="",
                priority="low",
                action_required=False,
                classified_at=datetime.utcnow().isoformat(),
                success=False,
                error=str(e)
            )
    
    def summarize_email(
        self,
        email_id: str,
        subject: str,
        body: str,
        max_length: int = 200
    ) -> Dict[str, Any]:
        """
        Summarize an email using Gemini.
        
        Note: Summarization is separate from classification.
        Each email can be summarized once.
        
        Args:
            email_id: Unique email identifier
            subject: Email subject
            body: Email body content
            max_length: Maximum summary length
            
        Returns:
            Dictionary with summary and metadata
        """
        prompt = f"""Summarize this email concisely in {max_length} characters or less.
        
Subject: {subject}
Body: {body[:2000]}

Return JSON only:
{{"summary": "...", "key_points": ["...", "..."], "sentiment": "positive|neutral|negative"}}"""

        try:
            response_text = self._call_gemini(prompt)
            parsed = json.loads(response_text.strip().strip('```json').strip('```'))
            
            return {
                "email_id": email_id,
                "summary": parsed.get("summary", ""),
                "key_points": parsed.get("key_points", []),
                "sentiment": parsed.get("sentiment", "neutral"),
                "summarized_at": datetime.utcnow().isoformat(),
                "success": True
            }
            
        except Exception as e:
            logger.error(f"Email summarization failed for {email_id}: {e}. NO RETRY.")
            return {
                "email_id": email_id,
                "summary": "",
                "error": str(e),
                "success": False
            }
    
    def extract_leads_from_email(
        self,
        email_id: str,
        subject: str,
        body: str,
        from_email: str
    ) -> LeadExtractionResult:
        """
        Extract lead information from an existing email.
        
        GOVERNANCE: This is for leads FROM EMAIL THREADS only.
        For external lead discovery, use OpenAI web search.
        
        Args:
            email_id: Unique email identifier
            subject: Email subject
            body: Email body content
            from_email: Sender email address
            
        Returns:
            LeadExtractionResult with extracted leads
        """
        prompt = f"""Extract lead/contact information from this email.

From: {from_email}
Subject: {subject}
Body: {body[:3000]}

Return JSON only:
{{
  "leads": [
    {{
      "name": "Full Name",
      "email": "email@example.com",
      "phone": "+1234567890 or null",
      "company": "Company Name or null",
      "title": "Job Title or null",
      "source": "email_signature|body|footer"
    }}
  ]
}}

If no leads found, return {{"leads": []}}"""

        try:
            response_text = self._call_gemini(prompt)
            parsed = json.loads(response_text.strip().strip('```json').strip('```'))
            
            return LeadExtractionResult(
                email_id=email_id,
                leads=parsed.get("leads", []),
                extracted_at=datetime.utcnow().isoformat(),
                success=True
            )
            
        except Exception as e:
            logger.error(f"Lead extraction failed for {email_id}: {e}. NO RETRY.")
            return LeadExtractionResult(
                email_id=email_id,
                leads=[],
                extracted_at=datetime.utcnow().isoformat(),
                success=False,
                error=str(e)
            )
    
    def _build_classification_prompt(self, subject: str, body: str, from_email: str) -> str:
        """Build the classification prompt"""
        return f"""Classify this email into one of these categories:
- client: From existing customers/clients
- vendor: From suppliers/vendors
- internal: Internal company communication
- promotional: Marketing/promotional content
- invoice: Bills, invoices, payment requests
- banking: Bank statements, financial notifications
- automated: Auto-generated system emails
- spam: Unwanted/spam emails
- newsletter: Subscribed newsletters
- bounce: Email delivery failures
- sales_inquiry: Potential sales leads
- support: Support requests/tickets
- recruitment: Job applications, hiring
- partnership: Business partnerships, collaborations
- other: Doesn't fit other categories

Email Details:
From: {from_email}
Subject: {subject}
Body: {body[:2000]}

Return JSON only:
{{
  "category": "category_name",
  "confidence": 0.0-1.0,
  "summary": "One sentence summary",
  "intent": "What the sender wants",
  "priority": "high|medium|low",
  "action_required": true|false
}}"""

    def _parse_classification_response(self, email_id: str, response_text: str) -> ClassificationResult:
        """Parse the classification response from Gemini"""
        try:
            # Clean up response text
            clean_text = response_text.strip()
            if clean_text.startswith('```'):
                clean_text = clean_text.strip('```json').strip('```')
            
            parsed = json.loads(clean_text)
            
            return ClassificationResult(
                email_id=email_id,
                category=parsed.get("category", "other"),
                confidence=float(parsed.get("confidence", 0.5)),
                summary=parsed.get("summary", ""),
                intent=parsed.get("intent", ""),
                priority=parsed.get("priority", "medium"),
                action_required=parsed.get("action_required", False),
                classified_at=datetime.utcnow().isoformat(),
                success=True
            )
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse classification response: {e}")
            return ClassificationResult(
                email_id=email_id,
                category="other",
                confidence=0.3,
                summary="Classification parsing failed",
                intent="unknown",
                priority="low",
                action_required=False,
                classified_at=datetime.utcnow().isoformat(),
                success=True,  # API call succeeded, parsing had issues
                error=f"Parse error: {e}"
            )


# ============== SINGLETON ==============

_gateway_instance: Optional[GeminiGateway] = None


def get_gemini_gateway() -> GeminiGateway:
    """Get singleton GeminiGateway instance"""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = GeminiGateway()
    return _gateway_instance


# ============== CONVENIENCE FUNCTIONS ==============

def classify_email(
    email_id: str,
    subject: str,
    body: str,
    from_email: str,
    source: str = "api"
) -> ClassificationResult:
    """Convenience function to classify an email"""
    return get_gemini_gateway().classify_email(email_id, subject, body, from_email, source)


def summarize_email(
    email_id: str,
    subject: str,
    body: str,
    max_length: int = 200
) -> Dict[str, Any]:
    """Convenience function to summarize an email"""
    return get_gemini_gateway().summarize_email(email_id, subject, body, max_length)


def extract_leads_from_email(
    email_id: str,
    subject: str,
    body: str,
    from_email: str
) -> LeadExtractionResult:
    """Convenience function to extract leads from an email"""
    return get_gemini_gateway().extract_leads_from_email(email_id, subject, body, from_email)
