"""
OPENAI EMAIL CLASSIFIER
========================

Two-tier OpenAI-based email classification.

Classification Tiers:
- Tier 1: GPT-4o-mini (cheap, fast) for initial classification
- Tier 2: GPT-4o (better quality) if confidence < 0.7
- On Failure: Mark as "Human Intervention Needed"

Features:
- Automatic classification as emails arrive
- All emails queued to ai_review_queue for human review
- Background batch processing for historic emails
- Cost tracking and rate limiting
- Lead extraction for Client/Vendor emails → Sales > Lead

Usage:
    classifier = OpenAIEmailClassifier(db)
    
    # Classify single email
    result = classifier.classify_email(email_doc)
    
    # Process batch of unclassified emails
    stats = classifier.process_batch(batch_size=500)
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pymongo import MongoClient
from bson import ObjectId

logger = logging.getLogger(__name__)


# ============== CONFIGURATION ==============

# Batch processing configuration
BATCH_SIZE = 500  # Emails per batch for historic processing
BATCH_DELAY_SECONDS = 2  # Delay between batches to avoid rate limits
MAX_RETRIES = 3

# Email classification categories (Tier 1)
EMAIL_CATEGORIES = [
    "client",       # Client/customer communication
    "vendor",       # Vendor/supplier communication
    "internal",     # Internal team emails
    "promotional",  # Marketing, newsletters
    "invoice",      # Invoices, billing
    "banking",      # Bank statements, transactions
    "automated",    # Auto-replies, system notifications
    "spam",         # Spam, unwanted
    "others"        # Uncategorized
]

# Classification prompts
TIER1_SYSTEM_PROMPT = """You are an email classifier for a B2B CRM system. Classify emails into one of these categories:

- client: Customer/client communication, inquiries, requests, feedback
- vendor: Vendor/supplier communication, orders, quotes, negotiations
- internal: Internal team emails, company announcements
- promotional: Marketing emails, newsletters, promotions
- invoice: Invoices, billing statements, payment requests
- banking: Bank statements, transaction notifications
- automated: Auto-replies, system notifications, out-of-office
- spam: Spam, phishing, unwanted solicitation
- others: Emails that don't fit other categories

Respond with JSON only:
{
    "category": "<category>",
    "confidence_score": 0.0-1.0,
    "reasoning": "brief explanation"
}"""

TIER2_SYSTEM_PROMPT = """You are an expert B2B email analyst. Provide deep analysis of client/vendor emails.

Analyze the email and respond with JSON:
{
    "category": "<category>",
    "sub_category": "<specific type>",
    "confidence_score": 0.0-1.0,
    "intent": "new_inquiry|rfq_request|follow_up|meeting_request|complaint|feedback|negotiation|order|invoice|other",
    "urgency": "critical|high|medium|low",
    "sentiment": "positive|neutral|negative",
    "summary": "one-sentence summary",
    "key_points": ["point1", "point2"],
    "action_items": ["action1", "action2"],
    "mentioned_amounts": ["$X", "$Y"],
    "mentioned_dates": ["date1", "date2"],
    "suggested_response": "brief suggested response or null"
}

Sub-categories:
- For client: new_inquiry, support_request, feedback, complaint, meeting_request, rfq_response, order_confirmation
- For vendor: quote_request, rfq, purchase_order, negotiation, delivery_update, invoice_query"""

EMAIL_PROMPT_TEMPLATE = """Classify this email:

From: {from_email}
To: {to_email}
Subject: {subject}
Date: {date}

Body:
{body}

Respond with JSON only."""


class OpenAIEmailClassifier:
    """
    OpenAI-based email classifier with two-tier approach and Gemini fallback.
    """
    
    def __init__(
        self,
        db: MongoClient = None,
        emails_collection: str = "email_metadata",
        emails_db: str = "torpedo_gmail",
        review_queue_collection: str = "ai_review_queue"
    ):
        """
        Initialize classifier.
        
        Args:
            db: MongoDB database instance or None (will connect using MONGO_URI)
            emails_collection: Collection containing emails
            emails_db: Database name for emails
            review_queue_collection: Collection for review queue
        """
        if db is None:
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.emails = client[emails_db][emails_collection]
            self.review_queue = client["email_automation"][review_queue_collection]
        else:
            self.emails = db[emails_collection]
            self.review_queue = db[review_queue_collection]
        
        # Statistics
        self.stats = {
            "total_processed": 0,
            "tier1_only": 0,
            "tier2_escalated": 0,
            "human_intervention_needed": 0,
            "failed": 0,
            "leads_extracted": 0,
            "total_cost_usd": 0.0
        }
        
        # Sales leads collection
        if db is None:
            mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            leads_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.leads_collection = leads_client["torpedo_settings"]["leads"]
        else:
            # When db is provided, use db.client to access other databases
            self.leads_collection = db.client["torpedo_settings"]["leads"]
        
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Create necessary indexes"""
        try:
            self.emails.create_index([("ai_tier1_category", 1)])
            self.emails.create_index([("ai_classified_at", 1)])
            self.emails.create_index([("ai_needs_classification", 1)])
            self.review_queue.create_index([("email_id", 1)])
            self.review_queue.create_index([("status", 1), ("created_at", -1)])
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    def classify_email(
        self,
        email: Dict[str, Any],
        force_tier2: bool = False
    ) -> Dict[str, Any]:
        """
        Classify a single email using two-tier OpenAI approach.
        
        CRITICAL: System emails are short-circuited BEFORE any LLM call.
        This guarantees zero wasted LLM calls on bounce/OOO/auto-reply.
        
        Args:
            email: Email document from MongoDB
            force_tier2: Force Tier 2 deep analysis even for non-client/vendor
            
        Returns:
            Classification result with category, confidence, tier info
        """
        from .system_email_detector import (
            should_skip_llm_classification,
            detect_system_email,
            generate_system_email_summary
        )
        from .models import EmailType, SystemSubtype
        
        # ============================================
        # HARD SHORT-CIRCUIT: System Email Detection
        # ============================================
        # This MUST happen before ANY LLM call to prevent wasted costs
        should_skip, skip_reason = should_skip_llm_classification(email)
        if should_skip:
            logger.info(f"Skipping LLM for email {email.get('_id')}: {skip_reason}")
            
            # Get or detect system subtype
            system_subtype = email.get("system_subtype")
            if not system_subtype:
                detection = detect_system_email(email)
                system_subtype = detection.system_subtype.value if detection.system_subtype else "auto_reply"
            
            # Generate deterministic summary for system emails
            system_summary = email.get("gmail_summary")
            if not system_summary:
                subtype_enum = SystemSubtype(system_subtype) if system_subtype else SystemSubtype.AUTO_REPLY
                system_summary = generate_system_email_summary(email, subtype_enum)
            
            # Return deterministic result (NO LLM CALL)
            system_result = {
                "success": True,
                "email_id": str(email.get("_id")),
                "category": "system",  # Not an AI category, just a marker
                "email_type": EmailType.SYSTEM.value,
                "system_subtype": system_subtype,
                "confidence": 1.0,
                "reasoning": skip_reason,
                "model": None,  # No model used
                "provider": None,  # No provider used
                "escalated": False,
                "human_intervention_needed": False,
                "tier2_analysis": None,
                "gmail_summary": system_summary,
                "classified_at": datetime.utcnow(),
                "llm_skipped": True,  # Explicit flag for audit
                "skip_reason": skip_reason
            }
            
            # Update email in database with system classification
            self._update_system_email_classification(email["_id"], system_result)
            
            # Do NOT add to review queue (system emails don't need human review)
            return system_result
        
        # ============================================
        # Normal Path: LLM Classification
        # ============================================
        from ..leads.openai_wrapper import chat_completion_with_escalation
        
        # Extract email data
        from_email = self._extract_email_address(email.get("from_address"))
        to_email = self._extract_email_address(email.get("to_addresses", [{}])[0] if email.get("to_addresses") else {})
        subject = email.get("subject", "")
        body = (email.get("body_plain") or email.get("snippet") or "")[:2000]
        date = email.get("received_at") or email.get("timestamp") or ""
        
        # Build prompt
        user_prompt = EMAIL_PROMPT_TEMPLATE.format(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            date=str(date),
            body=body
        )
        
        messages = [
            {"role": "system", "content": TIER1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        # Call AI with escalation (GPT-4o-mini → GPT-4o, NO Gemini fallback)
        result = chat_completion_with_escalation(
            messages=messages,
            source="background",
            endpoint="email_classification",
            max_output_tokens=300,
            response_format={"type": "json_object"},
            confidence_key="confidence_score",
            confidence_threshold=0.7,
            fallback_to_gemini=False  # No Gemini fallback
        )
        
        if not result["success"]:
            # Mark as Human Intervention Needed
            logger.warning(f"Classification failed for email {email.get('_id')}: {result.get('error')}")
            self.stats["human_intervention_needed"] += 1
            
            # Mark email as needing human intervention
            human_intervention_result = {
                "success": True,
                "email_id": str(email.get("_id")),
                "category": "human_intervention_needed",
                "confidence": 0.0,
                "reasoning": f"AI classification failed: {result.get('error')}",
                "model": None,
                "provider": None,
                "escalated": False,
                "human_intervention_needed": True,
                "tier2_analysis": None,
                "classified_at": datetime.utcnow()
            }
            
            # Update email in database
            self._update_email_classification(email["_id"], human_intervention_result)
            
            # Queue for human review with high priority
            self._add_to_review_queue(email, human_intervention_result, priority="high")
            
            return human_intervention_result
        
        # Parse result
        try:
            parsed = json.loads(result["content"])
            category = parsed.get("category", "others")
            confidence = parsed.get("confidence_score", 0.5)
            
            # Determine if we need Tier 2 deep analysis
            needs_tier2 = force_tier2 or (category in ["client", "vendor"] and confidence >= 0.7)
            tier2_result = None
            
            if needs_tier2:
                tier2_result = self._tier2_analysis(email, category)
            
            # Update statistics
            self.stats["total_processed"] += 1
            if result.get("escalated"):
                self.stats["tier2_escalated"] += 1
            else:
                self.stats["tier1_only"] += 1
            
            # Build classification result
            classification = {
                "success": True,
                "email_id": str(email.get("_id")),
                "category": category,
                "confidence": confidence,
                "reasoning": parsed.get("reasoning"),
                "model": result.get("model"),
                "provider": result.get("provider"),
                "escalated": result.get("escalated", False),
                "human_intervention_needed": False,
                "tier2_analysis": tier2_result,
                "classified_at": datetime.utcnow()
            }
            
            # Update email in database
            self._update_email_classification(email["_id"], classification)
            
            # Extract and save lead for client/vendor emails
            if category in ["client", "vendor"] and confidence >= 0.5:
                self._extract_and_save_lead(email, classification)
            
            # Queue for human review (ALL emails)
            self._add_to_review_queue(email, classification)
            
            return classification
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse classification for email {email.get('_id')}: {e}")
            self.stats["failed"] += 1
            return {
                "success": False,
                "error": f"JSON parse error: {e}",
                "email_id": str(email.get("_id")),
                "raw_response": result.get("content")
            }
    
    def _tier2_analysis(
        self,
        email: Dict[str, Any],
        category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Perform Tier 2 deep analysis for client/vendor emails.
        Uses GPT-4o only (no Gemini fallback).
        
        Args:
            email: Email document
            category: Tier 1 category
            
        Returns:
            Tier 2 analysis result or None
        """
        from ..leads.openai_wrapper import chat_completion, PREMIUM_MODEL
        
        from_email = self._extract_email_address(email.get("from_address"))
        to_email = self._extract_email_address(email.get("to_addresses", [{}])[0] if email.get("to_addresses") else {})
        subject = email.get("subject", "")
        body = (email.get("body_plain") or email.get("body_html") or email.get("snippet") or "")[:3000]
        date = email.get("received_at") or email.get("timestamp") or ""
        
        user_prompt = EMAIL_PROMPT_TEMPLATE.format(
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            date=str(date),
            body=body
        )
        
        messages = [
            {"role": "system", "content": TIER2_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        # Use GPT-4o only (no Gemini fallback)
        result = chat_completion(
            messages=messages,
            source="background",
            endpoint="email_deep_analysis",
            model=PREMIUM_MODEL,
            max_output_tokens=500,
            response_format={"type": "json_object"},
            allow_premium_model=True,
            provider="openai"
        )
        
        if not result["success"]:
            logger.warning(f"GPT-4o failed for Tier 2 analysis: {result.get('error')}")
            return None
        
        if result["success"]:
            try:
                return json.loads(result["content"])
            except json.JSONDecodeError:
                return None
        
        return None
    
    def _extract_email_address(self, addr: Any) -> str:
        """Extract email string from address object"""
        if isinstance(addr, dict):
            return addr.get("email", "") or addr.get("address", "")
        elif isinstance(addr, str):
            return addr
        return ""
    
    def _update_email_classification(
        self,
        email_id: ObjectId,
        classification: Dict[str, Any]
    ):
        """Update email document with classification"""
        update = {
            "ai_tier1_category": classification.get("category"),
            "ai_confidence": classification.get("confidence"),
            "ai_model": classification.get("model"),
            "ai_provider": classification.get("provider"),
            "ai_escalated": classification.get("escalated", False),
            "ai_human_intervention_needed": classification.get("human_intervention_needed", False),
            "ai_classified_at": classification.get("classified_at"),
            "ai_needs_classification": False
        }
        
        # Add Tier 2 analysis if present
        tier2 = classification.get("tier2_analysis")
        if tier2:
            update.update({
                "ai_sub_category": tier2.get("sub_category"),
                "ai_intent": tier2.get("intent"),
                "ai_urgency": tier2.get("urgency"),
                "ai_sentiment": tier2.get("sentiment"),
                "ai_summary": tier2.get("summary"),
                "ai_key_points": tier2.get("key_points"),
                "ai_action_items": tier2.get("action_items"),
                "ai_mentioned_amounts": tier2.get("mentioned_amounts"),
                "ai_mentioned_dates": tier2.get("mentioned_dates"),
                "ai_suggested_response": tier2.get("suggested_response")
            })
        
        self.emails.update_one(
            {"_id": email_id},
            {"$set": update}
        )
    
    def _update_system_email_classification(
        self,
        email_id: ObjectId,
        result: Dict[str, Any]
    ):
        """
        Update email document for system emails (no LLM was called).
        
        System emails get a deterministic classification and are marked as processed.
        """
        update = {
            "email_type": result.get("email_type"),
            "system_subtype": result.get("system_subtype"),
            "gmail_summary": result.get("gmail_summary"),
            "processed": True,
            "ai_needs_classification": False,
            "ai_classified_at": result.get("classified_at"),
            "ai_llm_skipped": True,
            "ai_skip_reason": result.get("skip_reason"),
            # These are explicitly null to indicate no AI was used
            "ai_tier1_category": None,
            "ai_model": None,
            "ai_provider": None,
            "ai_confidence": None,
        }
        
        self.emails.update_one(
            {"_id": email_id},
            {"$set": update}
        )
        logger.debug(f"System email {email_id} marked as processed (no LLM)")
    
    def _extract_and_save_lead(
        self,
        email: Dict[str, Any],
        classification: Dict[str, Any]
    ):
        """
        Extract lead information from client/vendor emails and save to Sales > Lead.
        
        Extracts: First Name, Last Name, Email ID
        """
        try:
            from_address = email.get("from_address", {})
            
            # Extract email
            if isinstance(from_address, dict):
                email_addr = from_address.get("email", "") or from_address.get("address", "")
                display_name = from_address.get("name", "") or from_address.get("displayName", "")
            elif isinstance(from_address, str):
                email_addr = from_address
                display_name = ""
            else:
                email_addr = ""
                display_name = ""
            
            if not email_addr:
                logger.warning(f"No email address found for lead extraction: {email.get('_id')}")
                return
            
            # Parse name from display_name or email
            first_name, last_name = self._parse_name(display_name, email_addr)
            
            # Check for existing lead by email
            existing_lead = self.leads_collection.find_one({"email": email_addr})
            if existing_lead:
                logger.debug(f"Lead already exists for {email_addr}")
                return
            
            # Create lead document
            lead_doc = {
                "firstName": first_name,
                "lastName": last_name,
                "email": email_addr,
                "source": "email_classification",
                "source_category": classification.get("category"),
                "source_email_id": str(email.get("_id")),
                "source_subject": email.get("subject", "")[:200],
                "created_at": datetime.utcnow(),
                "status": "new",
                "pipeline_stage": "lead_captured",
                "classification_confidence": classification.get("confidence", 0),
                "notes": f"Auto-extracted from {classification.get('category')} email"
            }
            
            # Add company info if we can parse it from domain
            domain = email_addr.split("@")[1] if "@" in email_addr else ""
            if domain and not any(free in domain.lower() for free in ["gmail", "yahoo", "hotmail", "outlook", "aol"]):
                lead_doc["companyDomain"] = domain
                lead_doc["companyName"] = domain.split(".")[0].title()
            
            # Insert lead
            result = self.leads_collection.insert_one(lead_doc)
            self.stats["leads_extracted"] += 1
            logger.info(f"Lead extracted and saved: {email_addr} (ID: {result.inserted_id})")
            
        except Exception as e:
            logger.error(f"Failed to extract lead from email {email.get('_id')}: {e}")
    
    def _parse_name(self, display_name: str, email_addr: str) -> Tuple[str, str]:
        """
        Parse first and last name from display name or email address.
        
        Returns:
            Tuple of (first_name, last_name)
        """
        import re
        
        if display_name and display_name.strip():
            # Clean the display name
            name = display_name.strip()
            # Remove quoted strings and extra characters
            name = re.sub(r'["\']', '', name)
            name = name.strip()
            
            parts = name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
            elif len(parts) == 1:
                first_name = parts[0]
                last_name = ""
            else:
                first_name = ""
                last_name = ""
        else:
            # Try to parse from email address
            local_part = email_addr.split("@")[0] if "@" in email_addr else email_addr
            # Common separators: . _ - 
            parts = re.split(r'[._\-]', local_part)
            if len(parts) >= 2:
                first_name = parts[0].title()
                last_name = parts[1].title()
            elif len(parts) == 1:
                first_name = parts[0].title()
                last_name = ""
            else:
                first_name = ""
                last_name = ""
        
        return first_name, last_name
    
    def _add_to_review_queue(
        self,
        email: Dict[str, Any],
        classification: Dict[str, Any],
        priority: str = "normal"
    ):
        """
        Add classified email to review queue.
        ALL emails are queued for human review regardless of confidence.
        
        Args:
            email: Email document
            classification: Classification result
            priority: Queue priority (normal, high, urgent)
        """
        try:
            review_doc = {
                "email_id": str(email.get("_id")),
                "entity_type": "email",
                "status": "pending",
                "priority": priority,
                "human_intervention_needed": classification.get("human_intervention_needed", False),
                "created_at": datetime.utcnow(),
                "classification": {
                    "category": classification.get("category"),
                    "confidence": classification.get("confidence"),
                    "reasoning": classification.get("reasoning"),
                    "tier2_analysis": classification.get("tier2_analysis")
                },
                "email_summary": {
                    "from": self._extract_email_address(email.get("from_address")),
                    "to": self._extract_email_address(email.get("to_addresses", [{}])[0] if email.get("to_addresses") else {}),
                    "subject": email.get("subject", "")[:200],
                    "snippet": (email.get("snippet") or "")[:300],
                    "received_at": email.get("received_at")
                },
                "model_used": classification.get("model"),
                "provider_used": classification.get("provider"),
                "escalated": classification.get("escalated", False)
            }
            
            # Upsert to avoid duplicates
            self.review_queue.update_one(
                {"email_id": str(email.get("_id"))},
                {"$set": review_doc},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Failed to add email to review queue: {e}")
    
    def process_batch(
        self,
        batch_size: int = BATCH_SIZE,
        max_batches: Optional[int] = None,
        delay_between_batches: float = BATCH_DELAY_SECONDS
    ) -> Dict[str, Any]:
        """
        Process a batch of unclassified emails.
        
        Args:
            batch_size: Number of emails per batch
            max_batches: Maximum batches to process (None = all)
            delay_between_batches: Seconds between batches
            
        Returns:
            Processing statistics
        """
        batches_processed = 0
        total_processed = 0
        start_time = datetime.utcnow()
        
        while True:
            # Get unclassified emails
            unclassified = list(self.emails.find({
                "$or": [
                    {"ai_tier1_category": {"$exists": False}},
                    {"ai_needs_classification": True}
                ]
            }).limit(batch_size))
            
            if not unclassified:
                logger.info("No more unclassified emails")
                break
            
            logger.info(f"Processing batch {batches_processed + 1}: {len(unclassified)} emails")
            
            for email in unclassified:
                try:
                    self.classify_email(email)
                    total_processed += 1
                except Exception as e:
                    logger.error(f"Error classifying email {email.get('_id')}: {e}")
                    self.stats["failed"] += 1
            
            batches_processed += 1
            
            if max_batches and batches_processed >= max_batches:
                logger.info(f"Reached max batches limit: {max_batches}")
                break
            
            # Delay between batches
            if delay_between_batches > 0:
                time.sleep(delay_between_batches)
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        return {
            "batches_processed": batches_processed,
            "total_processed": total_processed,
            "duration_seconds": duration,
            "emails_per_second": total_processed / duration if duration > 0 else 0,
            "stats": self.stats.copy()
        }
    
    def get_unclassified_count(self) -> int:
        """Get count of emails needing classification"""
        return self.emails.count_documents({
            "$or": [
                {"ai_tier1_category": {"$exists": False}},
                {"ai_needs_classification": True}
            ]
        })
    
    def get_classification_stats(self) -> Dict[str, Any]:
        """Get classification statistics"""
        pipeline = [
            {"$group": {
                "_id": "$ai_tier1_category",
                "count": {"$sum": 1},
                "avg_confidence": {"$avg": "$ai_confidence"}
            }},
            {"$sort": {"count": -1}}
        ]
        
        category_stats = list(self.emails.aggregate(pipeline))
        
        return {
            "total_classified": self.emails.count_documents({"ai_tier1_category": {"$exists": True}}),
            "total_unclassified": self.get_unclassified_count(),
            "by_category": category_stats,
            "pending_review": self.review_queue.count_documents({"status": "pending"})
        }


# ============== BACKGROUND WORKER ==============

class OpenAIClassificationWorker:
    """
    Background worker for continuous email classification.
    Processes historic emails in batches and classifies new emails as they arrive.
    """
    
    def __init__(
        self,
        db: MongoClient = None,
        batch_size: int = 500,
        poll_interval: int = 60
    ):
        """
        Initialize worker.
        
        Args:
            db: MongoDB database instance
            batch_size: Emails per batch
            poll_interval: Seconds between polling for new emails
        """
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self._running = False
        self._classifier = OpenAIEmailClassifier(db)
    
    def start(self):
        """Start background classification"""
        import threading
        
        if self._running:
            logger.warning("Classification worker already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="OpenAIClassificationWorker",
            daemon=True
        )
        self._thread.start()
        logger.info("OpenAI Classification Worker started")
    
    def stop(self):
        """Stop background classification"""
        self._running = False
        logger.info("OpenAI Classification Worker stopped")
    
    def _run_loop(self):
        """Main worker loop"""
        while self._running:
            try:
                unclassified_count = self._classifier.get_unclassified_count()
                
                if unclassified_count > 0:
                    logger.info(f"Found {unclassified_count} unclassified emails, processing batch...")
                    result = self._classifier.process_batch(
                        batch_size=self.batch_size,
                        max_batches=1
                    )
                    logger.info(f"Batch complete: {result['total_processed']} processed")
                else:
                    logger.debug("No unclassified emails, waiting...")
                
            except Exception as e:
                logger.error(f"Classification worker error: {e}", exc_info=True)
            
            time.sleep(self.poll_interval)
    
    @property
    def classifier(self) -> OpenAIEmailClassifier:
        """Get the classifier instance"""
        return self._classifier


# ============== CONVENIENCE FUNCTIONS ==============

def classify_single_email(email_id: str, db: MongoClient = None) -> Dict[str, Any]:
    """
    Classify a single email by ID.
    
    Args:
        email_id: Email ObjectId string
        db: MongoDB database instance
        
    Returns:
        Classification result
    """
    classifier = OpenAIEmailClassifier(db)
    
    email = classifier.emails.find_one({"_id": ObjectId(email_id)})
    if not email:
        return {"success": False, "error": "Email not found"}
    
    return classifier.classify_email(email)


def start_background_classification(
    batch_size: int = 500,
    poll_interval: int = 60
) -> OpenAIClassificationWorker:
    """
    Start background classification worker.
    
    Args:
        batch_size: Emails per batch
        poll_interval: Seconds between polls
        
    Returns:
        Worker instance
    """
    worker = OpenAIClassificationWorker(
        batch_size=batch_size,
        poll_interval=poll_interval
    )
    worker.start()
    return worker
