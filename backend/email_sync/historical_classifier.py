"""
HISTORICAL EMAIL CLASSIFIER
============================

Batch classification system for processing large email repositories.
Designed for one-time bulk classification of 90K+ emails.

Features:
- Batch processing with configurable batch size
- Checkpoint/resume support for long-running jobs
- Rule-based pre-filtering to reduce AI costs
- Confidence-based escalation to premium models
- Progress tracking and statistics
- Cost estimation and budgeting

Usage:
    classifier = HistoricalClassifier(db)
    
    # Estimate costs first
    estimate = classifier.estimate_classification_cost()
    print(f"Estimated cost: ${estimate['estimated_cost_usd']:.2f}")
    
    # Run classification
    result = classifier.run(
        batch_size=100,
        resume=True,  # Resume from last checkpoint
        dry_run=False
    )
"""

import os
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable
from enum import Enum
from pymongo import MongoClient
from bson import ObjectId

from .models import EmailCategory, CategorizationStatus

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

class ClassificationJobStatus(str, Enum):
    """Job status states"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


# B2B-specific email categories (extended from base EmailCategory)
class B2BEmailCategory(str, Enum):
    """Extended B2B email categories"""
    # Inbound lead indicators
    INBOUND_LEAD = "inbound_lead"
    MEETING_REQUEST = "meeting_request"
    DEMO_REQUEST = "demo_request"
    PRICING_INQUIRY = "pricing_inquiry"
    
    # RFQ/Sales cycle
    RFQ_REQUEST = "rfq_request"
    QUOTE_RESPONSE = "quote_response"
    NEGOTIATION = "negotiation"
    CONTRACT_DISCUSSION = "contract_discussion"
    PURCHASE_ORDER = "purchase_order"
    
    # Post-sale
    ONBOARDING = "onboarding"
    SUPPORT_REQUEST = "support_request"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    
    # Finance
    INVOICE = "invoice"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    PAYMENT_REMINDER = "payment_reminder"
    BILLING_DISPUTE = "billing_dispute"
    
    # Reply types
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    UNSUBSCRIBE = "unsubscribe"
    AUTO_REPLY = "auto_reply"
    
    # Operations
    DELIVERY_UPDATE = "delivery_update"
    VENDOR_COMMUNICATION = "vendor_communication"
    INTERNAL = "internal"
    
    # Low priority
    NEWSLETTER = "newsletter"
    PROMOTIONAL = "promotional"
    SPAM = "spam"
    SOCIAL_NOTIFICATION = "social_notification"
    
    # Fallback
    OTHER = "other"
    UNCATEGORIZED = "uncategorized"


# AI Classification prompts
CLASSIFICATION_SYSTEM_PROMPT = """You are an expert B2B email classifier. Analyze emails and categorize them for a sales/operations CRM system.

Output JSON only:
{
    "category": "<category>",
    "sub_category": "<optional sub-category>",
    "confidence": 0.0-1.0,
    "intent": "informational|action_required|response_expected|fyi",
    "priority": "critical|high|medium|low",
    "department": "sales|operations|finance|support|marketing|hr|other",
    "is_reply": true/false,
    "reply_sentiment": "positive|neutral|negative|null",
    "key_entities": {"company": "", "person": "", "amount": "", "date": ""},
    "suggested_action": "<brief action or null>"
}

Categories:
- inbound_lead, meeting_request, demo_request, pricing_inquiry
- rfq_request, quote_response, negotiation, contract_discussion, purchase_order
- onboarding, support_request, complaint, feedback
- invoice, payment_confirmation, payment_reminder, billing_dispute
- interested, not_interested, out_of_office, bounce, unsubscribe, auto_reply
- delivery_update, vendor_communication, internal
- newsletter, promotional, spam, social_notification
- other"""

CLASSIFICATION_USER_PROMPT = """Classify this email:

From: {from_email}
To: {to_email}
Subject: {subject}
Date: {date}

Body:
{body}

Respond with JSON only."""


class HistoricalClassifier:
    """
    Batch classifier for historical emails.
    
    Processes emails in three stages:
    1. Rule-based pre-filter (newsletters, spam, promotions) - FREE
    2. Keyword classification for obvious categories - FREE
    3. AI classification for ambiguous emails - COSTS MONEY
    """
    
    def __init__(
        self,
        db: MongoClient,
        emails_collection: str = "emails",
        jobs_collection: str = "classification_jobs"
    ):
        """
        Initialize historical classifier.
        
        Args:
            db: MongoDB database instance
            emails_collection: Collection containing emails
            jobs_collection: Collection for job tracking/checkpoints
        """
        self.db = db
        self.emails = db[emails_collection]
        self.jobs = db[jobs_collection]
        
        # Ensure indexes
        self._setup_indexes()
        
        # Statistics
        self.stats = {
            "total_processed": 0,
            "rule_based": 0,
            "keyword_based": 0,
            "ai_classified": 0,
            "escalated": 0,
            "failed": 0,
            "total_cost_usd": 0.0
        }
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            self.emails.create_index([("historical_classified", 1)])
            self.emails.create_index([("category", 1)])
            self.emails.create_index([("b2b_category", 1)])
            self.jobs.create_index([("status", 1), ("created_at", -1)])
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
    
    def estimate_classification_cost(self) -> Dict[str, Any]:
        """
        Estimate the cost to classify all unclassified emails.
        
        Returns:
            Dict with counts and cost estimates
        """
        # Count unclassified emails
        total_unclassified = self.emails.count_documents({
            "$or": [
                {"historical_classified": {"$exists": False}},
                {"historical_classified": False}
            ]
        })
        
        # Sample to estimate AI vs rule-based split
        sample = list(self.emails.aggregate([
            {"$match": {
                "$or": [
                    {"historical_classified": {"$exists": False}},
                    {"historical_classified": False}
                ]
            }},
            {"$sample": {"size": min(500, total_unclassified)}},
            {"$project": {"subject": 1, "body_plain": 1, "from_address": 1}}
        ]))
        
        rule_based_count = 0
        keyword_count = 0
        ai_needed_count = 0
        
        for email in sample:
            category, method = self._pre_classify(email)
            if method == "rule":
                rule_based_count += 1
            elif method == "keyword":
                keyword_count += 1
            else:
                ai_needed_count += 1
        
        # Extrapolate to full dataset
        if len(sample) > 0:
            rule_based_ratio = rule_based_count / len(sample)
            keyword_ratio = keyword_count / len(sample)
            ai_ratio = ai_needed_count / len(sample)
        else:
            rule_based_ratio = 0.3
            keyword_ratio = 0.3
            ai_ratio = 0.4
        
        estimated_ai_emails = int(total_unclassified * ai_ratio)
        
        # Cost estimation (gpt-4o-mini pricing)
        avg_input_tokens = 500  # Subject + body preview
        avg_output_tokens = 150  # JSON response
        cost_per_email = (avg_input_tokens * 0.00015 / 1000) + (avg_output_tokens * 0.0006 / 1000)
        
        # Escalation estimate (10-20% to claude-3-5-sonnet)
        escalation_rate = 0.15
        escalation_cost_per_email = (avg_input_tokens * 0.003 / 1000) + (avg_output_tokens * 0.015 / 1000)
        
        estimated_cost = (
            estimated_ai_emails * cost_per_email * (1 - escalation_rate) +
            estimated_ai_emails * escalation_rate * escalation_cost_per_email
        )
        
        return {
            "total_unclassified": total_unclassified,
            "sample_size": len(sample),
            "estimated_rule_based": int(total_unclassified * rule_based_ratio),
            "estimated_keyword": int(total_unclassified * keyword_ratio),
            "estimated_ai_needed": estimated_ai_emails,
            "estimated_escalations": int(estimated_ai_emails * escalation_rate),
            "estimated_cost_usd": round(estimated_cost, 2),
            "estimated_time_hours": round(estimated_ai_emails / 1000, 1)  # ~1000 emails/hour with rate limits
        }
    
    def _pre_classify(self, email: Dict) -> Tuple[Optional[str], str]:
        """
        Pre-classify email using rules and keywords.
        
        Returns:
            Tuple of (category or None, method: "rule"|"keyword"|"ai_needed")
        """
        subject = (email.get("subject") or "").lower()
        body = (email.get("body_plain") or email.get("snippet") or "")[:500].lower()
        from_email = ""
        from_addr = email.get("from_address")
        if isinstance(from_addr, dict):
            from_email = (from_addr.get("email") or "").lower()
        elif isinstance(from_addr, str):
            from_email = from_addr.lower()
        
        content = f"{subject} {body}"
        
        # RULE 1: Newsletter/Marketing by sender pattern
        newsletter_senders = [
            "newsletter@", "news@", "noreply@", "no-reply@", "marketing@",
            "updates@", "info@", "notifications@", "hello@mailchimp",
            "postmaster@", "mailer-daemon@"
        ]
        if any(pattern in from_email for pattern in newsletter_senders):
            if "unsubscribe" in content or "view in browser" in content:
                return B2BEmailCategory.NEWSLETTER.value, "rule"
        
        # RULE 2: Bounce detection
        bounce_indicators = [
            "delivery failed", "undeliverable", "mail delivery failed",
            "returned mail", "delivery status notification", "550 ",
            "recipient rejected", "mailbox unavailable"
        ]
        if any(ind in content for ind in bounce_indicators):
            return B2BEmailCategory.BOUNCE.value, "rule"
        
        # RULE 3: Out of Office
        ooo_indicators = [
            "out of office", "away from office", "automatic reply",
            "on vacation", "out of the office", "currently unavailable",
            "autoresponder", "auto-reply"
        ]
        if any(ind in content for ind in ooo_indicators):
            return B2BEmailCategory.OUT_OF_OFFICE.value, "rule"
        
        # RULE 4: Social notifications
        social_domains = [
            "linkedin.com", "facebook.com", "twitter.com", "x.com",
            "instagram.com", "youtube.com", "tiktok.com"
        ]
        if any(domain in from_email for domain in social_domains):
            return B2BEmailCategory.SOCIAL_NOTIFICATION.value, "rule"
        
        # RULE 5: Unsubscribe requests
        if subject.startswith("unsubscribe") or "unsubscribe" in subject:
            return B2BEmailCategory.UNSUBSCRIBE.value, "rule"
        
        # KEYWORD-BASED CLASSIFICATION
        keyword_categories = {
            B2BEmailCategory.INVOICE.value: [
                "invoice #", "inv-", "payment due", "amount due",
                "please find attached invoice", "invoice attached"
            ],
            B2BEmailCategory.PAYMENT_CONFIRMATION.value: [
                "payment received", "payment confirmed", "thank you for your payment",
                "payment successful", "payment processed"
            ],
            B2BEmailCategory.RFQ_REQUEST.value: [
                "request for quote", "rfq", "request for quotation",
                "requesting a quote", "quote request", "need pricing for"
            ],
            B2BEmailCategory.MEETING_REQUEST.value: [
                "schedule a call", "schedule a meeting", "book a time",
                "calendar invite", "meeting request", "let's set up a call"
            ],
            B2BEmailCategory.DEMO_REQUEST.value: [
                "request a demo", "demo request", "schedule a demo",
                "product demonstration", "would like a demo"
            ],
            B2BEmailCategory.PURCHASE_ORDER.value: [
                "purchase order", "po #", "po-", "order confirmation",
                "we would like to order", "placing an order"
            ],
            B2BEmailCategory.SUPPORT_REQUEST.value: [
                "support ticket", "case #", "ticket #", "need help with",
                "technical issue", "not working", "having trouble"
            ],
            B2BEmailCategory.PROMOTIONAL.value: [
                "limited time offer", "% off", "discount code", "sale ends",
                "exclusive offer", "special promotion", "free trial"
            ]
        }
        
        for category, keywords in keyword_categories.items():
            matches = sum(1 for kw in keywords if kw in content)
            if matches >= 2:  # High confidence keyword match
                return category, "keyword"
        
        # Needs AI classification
        return None, "ai_needed"
    
    def create_job(
        self,
        batch_size: int = 100,
        max_emails: Optional[int] = None,
        use_escalation: bool = True,
        cost_limit_usd: Optional[float] = None
    ) -> str:
        """
        Create a new classification job.
        
        Args:
            batch_size: Emails per batch
            max_emails: Maximum emails to process (None = all)
            use_escalation: Enable confidence-based escalation
            cost_limit_usd: Stop if cost exceeds this
            
        Returns:
            Job ID
        """
        job_doc = {
            "status": ClassificationJobStatus.PENDING.value,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "config": {
                "batch_size": batch_size,
                "max_emails": max_emails,
                "use_escalation": use_escalation,
                "cost_limit_usd": cost_limit_usd
            },
            "progress": {
                "processed": 0,
                "rule_based": 0,
                "keyword_based": 0,
                "ai_classified": 0,
                "escalated": 0,
                "failed": 0,
                "last_email_id": None
            },
            "costs": {
                "total_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0
            },
            "checkpoints": [],
            "errors": []
        }
        
        result = self.jobs.insert_one(job_doc)
        job_id = str(result.inserted_id)
        logger.info(f"Created classification job: {job_id}")
        return job_id
    
    def run(
        self,
        job_id: Optional[str] = None,
        batch_size: int = 100,
        resume: bool = True,
        dry_run: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Run the classification job.
        
        Args:
            job_id: Existing job ID to resume, or None to create new
            batch_size: Emails per batch
            resume: Resume from last checkpoint
            dry_run: Don't make actual AI calls
            progress_callback: Function called with progress updates
            
        Returns:
            Job result statistics
        """
        # Create or load job
        if job_id and resume:
            job = self.jobs.find_one({"_id": ObjectId(job_id)})
            if not job:
                raise ValueError(f"Job {job_id} not found")
        else:
            job_id = self.create_job(batch_size=batch_size)
            job = self.jobs.find_one({"_id": ObjectId(job_id)})
        
        # Mark as running
        self.jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": ClassificationJobStatus.RUNNING.value, "started_at": datetime.utcnow()}}
        )
        
        try:
            return self._run_job(job, dry_run, progress_callback)
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            self.jobs.update_one(
                {"_id": ObjectId(job_id)},
                {
                    "$set": {"status": ClassificationJobStatus.FAILED.value},
                    "$push": {"errors": {"error": str(e), "timestamp": datetime.utcnow()}}
                }
            )
            raise
    
    def _run_job(
        self,
        job: Dict,
        dry_run: bool,
        progress_callback: Optional[Callable]
    ) -> Dict[str, Any]:
        """Internal job execution"""
        job_id = str(job["_id"])
        config = job["config"]
        progress = job["progress"]
        
        batch_size = config["batch_size"]
        max_emails = config.get("max_emails")
        cost_limit = config.get("cost_limit_usd")
        
        # Build query for unprocessed emails
        query = {
            "$or": [
                {"historical_classified": {"$exists": False}},
                {"historical_classified": False}
            ]
        }
        
        # Resume from checkpoint
        if progress.get("last_email_id"):
            query["_id"] = {"$gt": ObjectId(progress["last_email_id"])}
        
        total_to_process = self.emails.count_documents(query)
        if max_emails:
            total_to_process = min(total_to_process, max_emails - progress["processed"])
        
        logger.info(f"Job {job_id}: Processing {total_to_process} emails")
        
        processed = progress["processed"]
        costs = job.get("costs", {"total_usd": 0.0, "input_tokens": 0, "output_tokens": 0})
        
        while True:
            # Fetch batch
            batch = list(self.emails.find(query).sort("_id", 1).limit(batch_size))
            
            if not batch:
                break
            
            if max_emails and processed >= max_emails:
                break
            
            if cost_limit and costs["total_usd"] >= cost_limit:
                logger.warning(f"Cost limit ${cost_limit} reached")
                break
            
            # Process batch
            batch_result = self._process_batch(batch, dry_run, config.get("use_escalation", True))
            
            # Update progress
            processed += len(batch)
            progress["processed"] = processed
            progress["rule_based"] += batch_result["rule_based"]
            progress["keyword_based"] += batch_result["keyword_based"]
            progress["ai_classified"] += batch_result["ai_classified"]
            progress["escalated"] += batch_result["escalated"]
            progress["failed"] += batch_result["failed"]
            progress["last_email_id"] = str(batch[-1]["_id"])
            
            costs["total_usd"] += batch_result["cost_usd"]
            costs["input_tokens"] += batch_result["input_tokens"]
            costs["output_tokens"] += batch_result["output_tokens"]
            
            # Update checkpoint
            self.jobs.update_one(
                {"_id": ObjectId(job_id)},
                {
                    "$set": {
                        "progress": progress,
                        "costs": costs,
                        "updated_at": datetime.utcnow()
                    },
                    "$push": {
                        "checkpoints": {
                            "timestamp": datetime.utcnow(),
                            "processed": processed,
                            "last_email_id": progress["last_email_id"]
                        }
                    }
                }
            )
            
            # Callback
            if progress_callback:
                progress_callback({
                    "job_id": job_id,
                    "processed": processed,
                    "total": total_to_process + progress["processed"],
                    "percent": round(processed / (total_to_process + progress["processed"]) * 100, 1),
                    "cost_usd": costs["total_usd"]
                })
            
            # Update query for next batch
            query["_id"] = {"$gt": ObjectId(progress["last_email_id"])}
            
            # Small delay to avoid overwhelming the system
            time.sleep(0.5)
        
        # Mark complete
        self.jobs.update_one(
            {"_id": ObjectId(job_id)},
            {
                "$set": {
                    "status": ClassificationJobStatus.COMPLETED.value,
                    "completed_at": datetime.utcnow(),
                    "progress": progress,
                    "costs": costs
                }
            }
        )
        
        return {
            "job_id": job_id,
            "status": "completed",
            "total_processed": processed,
            "rule_based": progress["rule_based"],
            "keyword_based": progress["keyword_based"],
            "ai_classified": progress["ai_classified"],
            "escalated": progress["escalated"],
            "failed": progress["failed"],
            "total_cost_usd": round(costs["total_usd"], 4)
        }
    
    def _process_batch(
        self,
        emails: List[Dict],
        dry_run: bool,
        use_escalation: bool
    ) -> Dict[str, Any]:
        """Process a batch of emails"""
        result = {
            "rule_based": 0,
            "keyword_based": 0,
            "ai_classified": 0,
            "escalated": 0,
            "failed": 0,
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0
        }
        
        ai_needed = []
        
        for email in emails:
            email_id = email["_id"]
            
            # Try pre-classification first
            category, method = self._pre_classify(email)
            
            if category:
                # Update email with classification
                self.emails.update_one(
                    {"_id": email_id},
                    {
                        "$set": {
                            "b2b_category": category,
                            "category_confidence": 0.9 if method == "rule" else 0.75,
                            "category_method": method,
                            "historical_classified": True,
                            "classified_at": datetime.utcnow()
                        }
                    }
                )
                
                if method == "rule":
                    result["rule_based"] += 1
                else:
                    result["keyword_based"] += 1
            else:
                ai_needed.append(email)
        
        # Process AI-needed emails
        if ai_needed and not dry_run:
            ai_result = self._classify_with_ai(ai_needed, use_escalation)
            result["ai_classified"] += ai_result["classified"]
            result["escalated"] += ai_result["escalated"]
            result["failed"] += ai_result["failed"]
            result["cost_usd"] += ai_result["cost_usd"]
            result["input_tokens"] += ai_result["input_tokens"]
            result["output_tokens"] += ai_result["output_tokens"]
        elif ai_needed and dry_run:
            # Dry run - mark as needing AI but don't call
            for email in ai_needed:
                self.emails.update_one(
                    {"_id": email["_id"]},
                    {"$set": {"ai_classification_needed": True}}
                )
        
        return result
    
    def _classify_with_ai(
        self,
        emails: List[Dict],
        use_escalation: bool
    ) -> Dict[str, Any]:
        """Classify emails using AI"""
        from ..leads.openai_wrapper import (
            chat_completion,
            chat_completion_with_escalation,
            ANTHROPIC_DEFAULT_MODEL
        )
        
        result = {
            "classified": 0,
            "escalated": 0,
            "failed": 0,
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0
        }
        
        for email in emails:
            try:
                # Build prompt
                from_email = ""
                from_addr = email.get("from_address")
                if isinstance(from_addr, dict):
                    from_email = from_addr.get("email", "")
                elif isinstance(from_addr, str):
                    from_email = from_addr
                
                to_email = ""
                to_addrs = email.get("to_addresses", [])
                if to_addrs:
                    if isinstance(to_addrs[0], dict):
                        to_email = to_addrs[0].get("email", "")
                    elif isinstance(to_addrs[0], str):
                        to_email = to_addrs[0]
                
                body = (email.get("body_plain") or email.get("snippet") or "")[:1500]
                
                user_prompt = CLASSIFICATION_USER_PROMPT.format(
                    from_email=from_email,
                    to_email=to_email,
                    subject=email.get("subject", ""),
                    date=email.get("timestamp", ""),
                    body=body
                )
                
                messages = [
                    {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ]
                
                # Call AI
                if use_escalation:
                    response = chat_completion_with_escalation(
                        messages=messages,
                        source="background",
                        endpoint="historical_classification",
                        max_output_tokens=300,
                        response_format={"type": "json_object"},
                        confidence_key="confidence",
                        confidence_threshold=0.7
                    )
                    if response.get("escalated"):
                        result["escalated"] += 1
                else:
                    response = chat_completion(
                        messages=messages,
                        source="background",
                        endpoint="historical_classification",
                        max_output_tokens=300,
                        response_format={"type": "json_object"}
                    )
                
                if response["success"]:
                    try:
                        parsed = json.loads(response["content"])
                        
                        # Update email
                        self.emails.update_one(
                            {"_id": email["_id"]},
                            {
                                "$set": {
                                    "b2b_category": parsed.get("category", "other"),
                                    "b2b_sub_category": parsed.get("sub_category"),
                                    "category_confidence": parsed.get("confidence", 0.8),
                                    "category_intent": parsed.get("intent"),
                                    "category_priority": parsed.get("priority"),
                                    "category_department": parsed.get("department"),
                                    "is_reply": parsed.get("is_reply", False),
                                    "reply_sentiment": parsed.get("reply_sentiment"),
                                    "key_entities": parsed.get("key_entities", {}),
                                    "suggested_action": parsed.get("suggested_action"),
                                    "category_method": "ai_escalated" if response.get("escalated") else "ai",
                                    "category_model": response.get("model"),
                                    "category_provider": response.get("provider"),
                                    "historical_classified": True,
                                    "classified_at": datetime.utcnow()
                                }
                            }
                        )
                        
                        result["classified"] += 1
                        
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse AI response for email {email['_id']}")
                        result["failed"] += 1
                else:
                    logger.warning(f"AI classification failed for email {email['_id']}: {response.get('error')}")
                    result["failed"] += 1
                
                # Track costs
                usage = response.get("usage", {})
                result["input_tokens"] += usage.get("input_tokens", 0)
                result["output_tokens"] += usage.get("output_tokens", 0)
                
                # Estimate cost (simple approximation)
                model = response.get("model", "gpt-4o-mini")
                if "claude" in model:
                    result["cost_usd"] += (usage.get("input_tokens", 0) * 0.003 / 1000 +
                                          usage.get("output_tokens", 0) * 0.015 / 1000)
                else:
                    result["cost_usd"] += (usage.get("input_tokens", 0) * 0.00015 / 1000 +
                                          usage.get("output_tokens", 0) * 0.0006 / 1000)
                
                # Rate limit protection
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error classifying email {email.get('_id')}: {e}")
                result["failed"] += 1
        
        return result
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a classification job"""
        job = self.jobs.find_one({"_id": ObjectId(job_id)})
        if not job:
            return {"error": "Job not found"}
        
        return {
            "job_id": job_id,
            "status": job.get("status"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "progress": job.get("progress", {}),
            "costs": job.get("costs", {}),
            "errors": job.get("errors", [])[-5:]  # Last 5 errors
        }
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a running job"""
        result = self.jobs.update_one(
            {"_id": ObjectId(job_id), "status": ClassificationJobStatus.RUNNING.value},
            {"$set": {"status": ClassificationJobStatus.PAUSED.value, "paused_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    def get_classification_stats(self) -> Dict[str, Any]:
        """Get overall classification statistics"""
        pipeline = [
            {
                "$group": {
                    "_id": "$b2b_category",
                    "count": {"$sum": 1},
                    "avg_confidence": {"$avg": "$category_confidence"}
                }
            },
            {"$sort": {"count": -1}}
        ]
        
        by_category = list(self.emails.aggregate(pipeline))
        
        total = self.emails.count_documents({})
        classified = self.emails.count_documents({"historical_classified": True})
        
        return {
            "total_emails": total,
            "classified": classified,
            "unclassified": total - classified,
            "by_category": by_category
        }
