"""
Mail Segregation Agent - GOVERNED VERSION
==========================================
Uses Gemini AI via the ai_governance framework for email classification.

GOVERNANCE ENFORCED:
- Single entry point for Gemini calls via ai_governance.gemini_gateway
- 7,000 daily request limit enforced
- One classification per email (uniqueness constraint)
- No automatic retries
- No infinite loops
- Event-driven, bounded operations

This agent is the ONLY user-facing interface for email classification.
All Gemini calls are routed through the governance framework.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum

from pymongo import MongoClient
from bson import ObjectId

# GOVERNANCE IMPORTS - Single source of truth for Gemini
from backend.ai_governance import (
    classify_email,
    summarize_email,
    extract_leads_from_email,
    check_gemini_daily_limit,
    check_email_classification_status,
    GeminiDailyLimitExceeded,
    EmailAlreadyClassified,
    get_governance_status,
)
from backend.ai_governance.governance_checks import get_gemini_daily_usage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# ✅ EXISTING STORAGE (Do NOT create new collections)
torpedo_gmail_db = mongo_client["torpedo_gmail"]
mail_pool_emails = torpedo_gmail_db["email_metadata"]

email_automation_db = mongo_client["email_automation"]
email_leads = email_automation_db["email_leads"]
classified_emails = email_automation_db["classified_emails"]

# Leads database
try:
    leads_db = mongo_client.get_database("leads")
    leads_db.list_collection_names()
except Exception:
    leads_db = mongo_client.get_database("ai_enrichment")
leads_collection = leads_db["leads"]


@dataclass
class EmailCategory:
    """Represents an email category"""
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    """Result of email classification (from governance gateway)"""
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


class MailSegregationAgent:
    """
    Main agent for mail segregation using GOVERNED Gemini access.
    
    All Gemini calls go through ai_governance.gemini_gateway which enforces:
    - Daily limit (7000)
    - One classification per email
    - No retries
    - Proper logging and auditing
    """
    
    # Maximum emails to process in a single request (bounded operation)
    MAX_BATCH_SIZE = 100
    
    def __init__(self):
        self.default_categories = self._initialize_default_categories()
    
    def _initialize_default_categories(self) -> List[EmailCategory]:
        """Initialize default email categories"""
        return [
            EmailCategory(
                name="client",
                description="From existing customers/clients",
                keywords=["customer", "client", "account"]
            ),
            EmailCategory(
                name="vendor",
                description="From suppliers/vendors",
                keywords=["vendor", "supplier", "invoice"]
            ),
            EmailCategory(
                name="sales_inquiry",
                description="Potential sales leads and inquiries",
                keywords=["interested", "pricing", "demo", "quote"]
            ),
            EmailCategory(
                name="support",
                description="Customer support requests",
                keywords=["support", "help", "issue", "bug"]
            ),
            EmailCategory(
                name="internal",
                description="Internal company communication",
                keywords=["team", "internal", "meeting"]
            ),
            EmailCategory(
                name="promotional",
                description="Marketing and promotional content",
                keywords=["marketing", "promotion", "offer"]
            ),
            EmailCategory(
                name="newsletter",
                description="Subscribed newsletters",
                keywords=["newsletter", "update", "digest"]
            ),
            EmailCategory(
                name="automated",
                description="Auto-generated system emails",
                keywords=["automated", "notification", "alert"]
            ),
            EmailCategory(
                name="spam",
                description="Unwanted or spam emails",
                keywords=["unsubscribe", "spam"]
            ),
            EmailCategory(
                name="other",
                description="Uncategorized emails",
                keywords=[]
            ),
        ]
    
    def get_governance_status(self) -> Dict[str, Any]:
        """
        Get current AI governance status.
        
        Returns:
            Dictionary with Gemini usage, limits, and enforcement status
        """
        return get_governance_status()
    
    def get_daily_usage(self) -> Dict[str, int]:
        """
        Get current Gemini daily usage.
        
        Returns:
            Dictionary with current_usage and remaining
        """
        current, remaining = get_gemini_daily_usage()
        return {
            "current_usage": current,
            "remaining": remaining,
            "daily_limit": 7000
        }
    
    def classify_single_email(
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
        - Email can only be classified ONCE (unique constraint)
        - Daily limit checked before call
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
        try:
            # Call governance-controlled classification
            result = classify_email(
                email_id=email_id,
                subject=subject,
                body=body,
                from_email=from_email,
                source=source
            )
            
            # Convert to our result format
            return ClassificationResult(
                email_id=result.email_id,
                category=result.category,
                confidence=result.confidence,
                summary=result.summary,
                intent=result.intent,
                priority=result.priority,
                action_required=result.action_required,
                classified_at=result.classified_at,
                success=result.success,
                error=result.error
            )
            
        except EmailAlreadyClassified:
            logger.warning(f"Email {email_id} already classified - reclassification forbidden")
            raise
        except GeminiDailyLimitExceeded:
            logger.error("Gemini daily limit reached - no more classifications today")
            raise
        except Exception as e:
            logger.error(f"Classification failed for {email_id}: {e}")
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
    
    def classify_email_by_id(self, email_id: str, source: str = "api") -> ClassificationResult:
        """
        Classify an email by its database ID.
        
        Fetches email from database and classifies it.
        
        Args:
            email_id: MongoDB ObjectId as string
            source: Source of request
            
        Returns:
            ClassificationResult
        """
        # Fetch email from database
        try:
            object_id = ObjectId(email_id)
        except Exception:
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
                error="Invalid email_id format"
            )
        
        email = mail_pool_emails.find_one({"_id": object_id})
        if not email:
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
                error="Email not found in database"
            )
        
        # Check if already classified
        if not check_email_classification_status(email_id):
            raise EmailAlreadyClassified(f"Email {email_id} has already been classified")
        
        return self.classify_single_email(
            email_id=email_id,
            subject=email.get("subject", ""),
            body=email.get("body", "")[:3000],  # Limit body size
            from_email=email.get("from_email", ""),
            source=source
        )
    
    def process_pending_emails(
        self,
        max_count: int = None,
        source: str = "api"
    ) -> Dict[str, Any]:
        """
        Process pending (unclassified) emails.
        
        GOVERNANCE ENFORCED:
        - Bounded operation (max_count enforced)
        - No infinite loops
        - Stops at daily limit
        
        Args:
            max_count: Maximum emails to process (default: MAX_BATCH_SIZE)
            source: Source of request
            
        Returns:
            Dictionary with processing results
        """
        # Enforce bounded operation
        if max_count is None or max_count > self.MAX_BATCH_SIZE:
            max_count = self.MAX_BATCH_SIZE
        
        # Check daily limit before starting
        if not check_gemini_daily_limit():
            return {
                "success": False,
                "error": "Gemini daily limit (7000) reached",
                "processed": 0,
                "failed": 0
            }
        
        # Get pending emails
        pending_emails = list(mail_pool_emails.find(
            {"ai_classification_status": {"$exists": False}},
            {"_id": 1, "subject": 1, "body": 1, "from_email": 1}
        ).limit(max_count))
        
        if not pending_emails:
            return {
                "success": True,
                "message": "No pending emails to classify",
                "processed": 0,
                "failed": 0
            }
        
        results = {
            "success": True,
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "limit_reached": False,
            "details": []
        }
        
        for email in pending_emails:
            email_id = str(email["_id"])
            
            try:
                # Classify email
                classification = self.classify_single_email(
                    email_id=email_id,
                    subject=email.get("subject", ""),
                    body=email.get("body", "")[:3000],
                    from_email=email.get("from_email", ""),
                    source=source
                )
                
                if classification.success:
                    # Update email_metadata with classification
                    mail_pool_emails.update_one(
                        {"_id": email["_id"]},
                        {"$set": {
                            "ai_classification_status": {
                                "status": "classified",
                                "category": classification.category,
                                "confidence": classification.confidence,
                                "summary": classification.summary,
                                "intent": classification.intent,
                                "priority": classification.priority,
                                "action_required": classification.action_required,
                                "classified_at": classification.classified_at,
                                "classification_method": "gemini_governance"
                            }
                        }}
                    )
                    
                    # Also store in classified_emails collection
                    classified_emails.update_one(
                        {"email_id": email_id},
                        {"$set": {
                            "email_id": email_id,
                            "from_email": email.get("from_email", ""),
                            "subject": email.get("subject", ""),
                            "category": classification.category,
                            "confidence": classification.confidence,
                            "classified_at": classification.classified_at,
                            "updated_at": datetime.utcnow()
                        }},
                        upsert=True
                    )
                    
                    results["processed"] += 1
                else:
                    results["failed"] += 1
                    results["details"].append({
                        "email_id": email_id,
                        "error": classification.error
                    })
                    
            except EmailAlreadyClassified:
                results["skipped"] += 1
                
            except GeminiDailyLimitExceeded:
                results["limit_reached"] = True
                logger.warning("Daily limit reached during batch processing")
                break  # Stop processing - no more Gemini calls today
                
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "email_id": email_id,
                    "error": str(e)
                })
        
        results["timestamp"] = datetime.utcnow().isoformat()
        return results
    
    def summarize_email_by_id(self, email_id: str, max_length: int = 200) -> Dict[str, Any]:
        """
        Summarize an email by its database ID.
        
        Args:
            email_id: MongoDB ObjectId as string
            max_length: Maximum summary length
            
        Returns:
            Dictionary with summary
        """
        # Fetch email from database
        try:
            object_id = ObjectId(email_id)
        except Exception:
            return {"success": False, "error": "Invalid email_id format"}
        
        email = mail_pool_emails.find_one({"_id": object_id})
        if not email:
            return {"success": False, "error": "Email not found"}
        
        return summarize_email(
            email_id=email_id,
            subject=email.get("subject", ""),
            body=email.get("body", "")[:3000],
            max_length=max_length
        )
    
    def extract_leads_by_email_id(self, email_id: str) -> Dict[str, Any]:
        """
        Extract leads from an email by its database ID.
        
        Note: This is for leads FROM email content only.
        For external lead discovery, use the OpenAI gateway.
        
        Args:
            email_id: MongoDB ObjectId as string
            
        Returns:
            Dictionary with extracted leads
        """
        # Fetch email from database
        try:
            object_id = ObjectId(email_id)
        except Exception:
            return {"success": False, "error": "Invalid email_id format", "leads": []}
        
        email = mail_pool_emails.find_one({"_id": object_id})
        if not email:
            return {"success": False, "error": "Email not found", "leads": []}
        
        result = extract_leads_from_email(
            email_id=email_id,
            subject=email.get("subject", ""),
            body=email.get("body", "")[:3000],
            from_email=email.get("from_email", "")
        )
        
        # Store extracted leads in database
        if result.success and result.leads:
            for lead in result.leads:
                lead["source_email_id"] = email_id
                lead["extracted_at"] = result.extracted_at
                email_leads.insert_one(lead)
        
        return {
            "email_id": result.email_id,
            "leads": result.leads,
            "extracted_at": result.extracted_at,
            "success": result.success,
            "error": result.error
        }


# ============== SINGLETON ==============

_agent_instance: Optional[MailSegregationAgent] = None


def get_agent() -> MailSegregationAgent:
    """Get singleton MailSegregationAgent instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MailSegregationAgent()
    return _agent_instance


# ============== CONVENIENCE FUNCTIONS ==============

def classify_pending_emails(max_count: int = 100) -> Dict[str, Any]:
    """Convenience function to classify pending emails"""
    return get_agent().process_pending_emails(max_count=max_count)


def get_ai_status() -> Dict[str, Any]:
    """Get AI governance status"""
    return get_agent().get_governance_status()
