"""
Mail Segregation Agent - Uses Gemini AI to intelligently categorize and segregate emails

Purpose:
- Categorizes emails into custom categories using Gemini
- Segregates mail_pool based on business logic
- Supports multiple segregation strategies
- Provides mail summary generation
- Extracts contact information from email bodies
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum

import google.generativeai as genai
from pymongo import MongoClient
from bson import ObjectId
from backend.leads.gemini_rotator import get_rotator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get Gemini rotator instance (manages 7 API keys with automatic rotation)
rotator = get_rotator()

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
mongo_client = MongoClient(MONGO_URI)

# ✅ EXISTING STORAGE (Do NOT create new collections)
# Email source collection - stores all incoming emails from Gmail
torpedo_gmail_db = mongo_client["torpedo_gmail"]
mail_pool_emails = torpedo_gmail_db["email_metadata"]  # Uses existing field: ai_classification_status

# Email automation database - where classification results are stored
email_automation_db = mongo_client["email_automation"]
email_leads = email_automation_db["email_leads"]  # Extract leads from emails
email_conversations = email_automation_db["email_conversations"]  # Email threads
classified_emails = email_automation_db["classified_emails"]  # Classification results

# Leads database - where extracted leads go
# Try to get "leads" database, fallback to "ai_enrichment" if it doesn't exist
try:
    leads_db = mongo_client.get_database("leads")
    # Check if database exists by trying to list collections
    leads_db.list_collection_names()
except Exception:
    leads_db = mongo_client.get_database("ai_enrichment")
leads_collection = leads_db["leads"]  # Main leads collection
lead_extraction_logs = leads_db["lead_extraction_logs"]  # Track extraction activity


class SegmentationStrategy(str, Enum):
    """Available email segmentation strategies"""
    CATEGORY = "category"  # By email category (sales, support, etc.)
    SENDER_DOMAIN = "sender_domain"  # By sender's company domain
    PRIORITY = "priority"  # By priority level
    INTENT = "intent"  # By business intent
    ENGAGEMENT = "engagement"  # By engagement level
    CUSTOM = "custom"  # Custom Gemini-based segmentation


@dataclass
class EmailCategory:
    """Represents an email category"""
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.7


@dataclass
class ExtractedContact:
    """Represents extracted contact information"""
    name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    title: str = ""
    linkedin: str = ""
    website: str = ""
    address: str = ""
    social_handles: Dict[str, str] = field(default_factory=dict)
    source_email_id: str = ""
    extracted_at: str = ""


@dataclass
class ExtractedLead:
    """Extracted lead from email - creates lead document in leads database"""
    name: str
    email: str
    company: str = ""
    title: str = ""
    phone: str = ""
    linkedin: str = ""
    website: str = ""
    location: str = ""
    source_email_id: str = ""
    source_email_from: str = ""
    source_email_subject: str = ""
    extracted_at: str = ""
    confidence: float = 0.8


@dataclass
class MailSegmentSummary:
    """Summary of a mail segment"""
    segment_id: str
    segment_name: str
    total_emails: int
    date_range: Tuple[str, str]
    key_topics: List[str]
    sentiment_distribution: Dict[str, int]
    top_senders: List[Tuple[str, int]]
    action_items: List[str]
    summary_text: str
    created_at: str = ""


class MailSegregationAgent:
    """Main agent for mail segregation using Gemini"""
    
    def __init__(self):
        # Use existing Gemini rotator instead of single API key
        self.rotator = rotator
        self.default_categories = self._initialize_default_categories()
    
    def _initialize_default_categories(self) -> List[EmailCategory]:
        """Initialize default email categories"""
        return [
            EmailCategory(
                name="Sales",
                description="Sales inquiries, pricing questions, demo requests",
                keywords=["sales", "pricing", "demo", "quote", "purchase"]
            ),
            EmailCategory(
                name="Support",
                description="Customer support, bug reports, technical issues",
                keywords=["support", "help", "issue", "bug", "error", "problem"]
            ),
            EmailCategory(
                name="Business Development",
                description="Partnership opportunities, collaborations, strategic initiatives",
                keywords=["partnership", "collaboration", "bd", "joint venture", "strategic"]
            ),
            EmailCategory(
                name="Recruitment",
                description="Job inquiries, hiring, candidate-related",
                keywords=["recruitment", "hiring", "job", "candidate", "interview", "hr"]
            ),
            EmailCategory(
                name="Marketing",
                description="Marketing campaigns, newsletters, promotions",
                keywords=["marketing", "campaign", "newsletter", "promotion", "webinar"]
            ),
            EmailCategory(
                name="Administrative",
                description="Internal admin, compliance, legal matters",
                keywords=["admin", "compliance", "legal", "contract", "policy"]
            ),
            EmailCategory(
                name="Follow-up",
                description="Follow-up messages and reminders",
                keywords=["follow up", "reminder", "check-in", "touching base"]
            ),
            EmailCategory(
                name="Other",
                description="Uncategorized or miscellaneous emails",
                keywords=[]
            ),
        ]
    
    def _call_gemini(self, prompt: str, task_type: str = "segregate") -> str:
        """
        Call Gemini API with automatic key rotation
        
        Args:
            prompt: The prompt to send to Gemini
            task_type: Type of task for quota tracking (segregate, contact_extract, mail_summary)
            
        Returns:
            Response text from Gemini
        """
        # Get available key from rotator
        key_index, api_key = self.rotator.get_available_key()
        
        # Configure genai with the selected key
        self.rotator.configure_genai(key_index)
        
        # Create model and generate response
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content(prompt)
        
        # Log the request for quota tracking
        # Estimate tokens (rough estimate: 1 token ≈ 4 characters)
        estimated_tokens = (len(prompt) + len(response.text)) // 4
        self.rotator.log_request(key_index, estimated_tokens, task_type)
        
        return response.text
    
    async def segregate_all_emails(
        self, 
        strategy: SegmentationStrategy = SegmentationStrategy.CATEGORY,
        batch_size: int = 100,
        force_rescan: bool = False
    ) -> Dict[str, Any]:
        """
        Segregate all emails in mail_pool using specified strategy
        
        Args:
            strategy: Segregation strategy to use
            batch_size: Number of emails to process per batch
            force_rescan: Whether to rescan already processed emails
            
        Returns:
            Dictionary with segregation results
        """
        try:
            logger.info(f"Starting mail segregation with strategy: {strategy}")
            
            # Get total email count
            if force_rescan:
                total_emails = mail_pool_emails.count_documents({})
                mail_pool_emails.update_many({}, {"$unset": {"ai_classification_status": ""}})
            else:
                total_emails = mail_pool_emails.count_documents({"ai_classification_status": {"$exists": False}})
            
            logger.info(f"Found {total_emails} emails to segregate")
            
            # Process in batches
            processed = 0
            failed = 0
            
            for skip in range(0, total_emails, batch_size):
                batch = list(mail_pool_emails.find(
                    {"ai_classification_status": {"$exists": False}} if not force_rescan else {}
                ).limit(batch_size).skip(skip))
                
                for email in batch:
                    try:
                        segment_result = await self._segment_email(email, strategy)
                        
                        # Store in existing ai_classification_status field
                        classification_data = {
                            "status": "classified",
                            "category": segment_result["category"],
                            "segment": segment_result["segment"],
                            "confidence": segment_result["confidence"],
                            "reasoning": segment_result.get("reasoning", ""),
                            "metadata": segment_result.get("metadata", {}),
                            "classified_at": datetime.utcnow(),
                            "classification_method": "gemini_segregation"
                        }
                        
                        # Update email_metadata with classification status
                        mail_pool_emails.update_one(
                            {"_id": email["_id"]},
                            {"$set": {"ai_classification_status": classification_data}}
                        )
                        
                        # Also store in classified_emails collection for tracking
                        classified_emails.update_one(
                            {"email_id": str(email["_id"])},
                            {"$set": {
                                "email_id": str(email["_id"]),
                                "from_email": email.get("from_email", ""),
                                "subject": email.get("subject", ""),
                                "classification": classification_data,
                                "updated_at": datetime.utcnow()
                            }},
                            upsert=True
                        )
                        processed += 1
                    except Exception as e:
                        logger.error(f"Error segregating email {email.get('_id')}: {e}")
                        failed += 1
                
                logger.info(f"Processed {processed} emails, {failed} failed")
            
            # Generate segment summaries
            summaries = await self._generate_segment_summaries()
            
            return {
                "success": True,
                "total_emails": total_emails,
                "processed": processed,
                "failed": failed,
                "strategy": strategy.value,
                "segment_summaries": summaries,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error in segregate_all_emails: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _segment_email(
        self, 
        email: Dict[str, Any], 
        strategy: SegmentationStrategy
    ) -> Dict[str, Any]:
        """
        Segment a single email using Gemini
        
        Args:
            email: Email document from database
            strategy: Segmentation strategy
            
        Returns:
            Dictionary with segment information
        """
        subject = email.get("subject", "")
        body = email.get("body", "")[:2000]  # Limit body size
        
        prompt = f"""
Analyze this email and categorize it. Return JSON only.

Subject: {subject}
Body (first 2000 chars): {body}

Categories to consider:
{json.dumps([asdict(cat) for cat in self.default_categories], indent=2)}

Return JSON with exactly this format:
{{
    "segment": "category_name",
    "category": "primary_category",
    "confidence": 0.95,
    "reasoning": "brief explanation",
    "metadata": {{
        "is_promotional": false,
        "requires_response": true,
        "priority": "medium"
    }}
}}

Only return valid JSON, no other text.
"""
        
        try:
            response_text = self._call_gemini(prompt, task_type="segregate")
            result = json.loads(response_text)
            return result
        except json.JSONDecodeError:
            # Fallback categorization
            return {
                "segment": "Other",
                "category": "uncategorized",
                "confidence": 0.5,
                "reasoning": "Could not parse Gemini response",
                "metadata": {}
            }
    
    async def extract_contact_information(self, email_id: str) -> Optional[ExtractedContact]:
        """
        Extract contact information from an email using Gemini
        
        Args:
            email_id: ID of the email to extract contacts from
            
        Returns:
            ExtractedContact object or None if not found
        """
        email = mail_pool_emails.find_one({"_id": ObjectId(email_id) if isinstance(email_id, str) else email_id})
        if not email:
            return None
        
        body = email.get("body", "")
        sender = email.get("from_email", "")
        sender_name = email.get("from_name", "")
        
        prompt = f"""
Extract contact information from this email. Return JSON only.

From: {sender_name} <{sender}>
Body:
{body}

Extract contact information and return as JSON:
{{
    "name": "Full name if found",
    "email": "Email address",
    "phone": "Phone number if found",
    "company": "Company name if found",
    "title": "Job title if found",
    "linkedin": "LinkedIn URL if found",
    "website": "Website URL if found",
    "address": "Physical address if found",
    "social_handles": {{
        "twitter": "handle if found",
        "instagram": "handle if found"
    }}
}}

Return only valid JSON, no other text. Use empty strings for not found fields.
"""
        
        try:
            response_text = self._call_gemini(prompt, task_type="contact_extract")
            data = json.loads(response_text)
            
            contact = ExtractedContact(
                name=data.get("name", ""),
                email=data.get("email", sender),
                phone=data.get("phone", ""),
                company=data.get("company", ""),
                title=data.get("title", ""),
                linkedin=data.get("linkedin", ""),
                website=data.get("website", ""),
                address=data.get("address", ""),
                social_handles=data.get("social_handles", {}),
                source_email_id=str(email_id),
                extracted_at=datetime.utcnow().isoformat()
            )
            
            # Save to email_leads collection
            email_leads.insert_one(asdict(contact))
            
            return contact
        
        except Exception as e:
            logger.error(f"Error extracting contact info: {e}")
            return None
    
    async def extract_all_contacts(self, batch_size: int = 50) -> Dict[str, Any]:
        """Extract contacts from all emails in pool"""
        try:
            emails = list(mail_pool_emails.find({"from_email": {"$exists": True}}).limit(1000))
            
            extracted = 0
            failed = 0
            
            for email in emails:
                try:
                    contact = await self.extract_contact_information(email["_id"])
                    if contact:
                        extracted += 1
                except Exception as e:
                    logger.error(f"Failed to extract contact: {e}")
                    failed += 1
            
            return {
                "success": True,
                "total_processed": len(emails),
                "extracted": extracted,
                "failed": failed,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error in extract_all_contacts: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_mail_summary(
        self, 
        segment_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Optional[MailSegmentSummary]:
        """
        Generate summary for email segment using Gemini
        
        Args:
            segment_name: Name of segment to summarize (if None, summarize all)
            date_from: Start date for email range
            date_to: End date for email range
            
        Returns:
            MailSegmentSummary object
        """
        try:
            # Build query
            query = {}
            if segment_name:
                query["segment_name"] = segment_name
            
            if date_from or date_to:
                date_query = {}
                if date_from:
                    date_query["$gte"] = datetime.fromisoformat(date_from)
                if date_to:
                    date_query["$lte"] = datetime.fromisoformat(date_to)
                query["date"] = date_query
            
            # Get emails for segment
            emails = list(mail_pool_emails.find(query).limit(100))
            
            if not emails:
                return None
            
            # Extract key data
            subjects = [e.get("subject", "") for e in emails]
            senders = [e.get("from_email", "") for e in emails]
            
            # Generate summary using Gemini
            prompt = f"""
Generate a professional email segment summary. Return JSON only.

Total Emails: {len(emails)}
Subject Lines: {json.dumps(subjects[:10])}  # First 10
Top Senders: {json.dumps(list(set(senders))[:5])}  # Top 5 unique

Return JSON:
{{
    "key_topics": ["topic1", "topic2", "topic3"],
    "action_items": ["action1", "action2"],
    "sentiment_distribution": {{"positive": 10, "neutral": 50, "negative": 40}},
    "summary_text": "2-3 sentence professional summary"
}}

Return only valid JSON, no other text.
"""
            
            response_text = self._call_gemini(prompt, task_type="mail_summary")
            summary_data = json.loads(response_text)
            
            segment_id = str(ObjectId())
            summary = MailSegmentSummary(
                segment_id=segment_id,
                segment_name=segment_name or "All Emails",
                total_emails=len(emails),
                date_range=(
                    emails[0].get("date", "").isoformat() if emails else "",
                    emails[-1].get("date", "").isoformat() if emails else ""
                ),
                key_topics=summary_data.get("key_topics", []),
                sentiment_distribution=summary_data.get("sentiment_distribution", {}),
                top_senders=[(s, senders.count(s)) for s in set(senders)][:5],
                action_items=summary_data.get("action_items", []),
                summary_text=summary_data.get("summary_text", ""),
                created_at=datetime.utcnow().isoformat()
            )
            
            # Save to database (mail summaries stored in email_automation)
            email_automation_db["mail_summaries"].insert_one(asdict(summary))
            
            return summary
        
        except Exception as e:
            logger.error(f"Error generating mail summary: {e}")
            return None
    
    async def _generate_segment_summaries(self) -> List[Dict[str, Any]]:
        """Generate summaries for all segments"""
        try:
            segments = mail_pool_emails.aggregate([
                {"$group": {"_id": "$segment_name", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ])
            
            summaries = []
            for segment in segments:
                segment_name = segment["_id"]
                if segment_name:
                    summary = await self.generate_mail_summary(segment_name)
                    if summary:
                        summaries.append(asdict(summary))
            
            return summaries
        
        except Exception as e:
            logger.error(f"Error generating summaries: {e}")
            return []
    
    async def extract_leads_from_emails(self, batch_size: int = 50) -> Dict[str, Any]:
        """
        Extract leads from all emails and create lead documents in leads database
        
        Args:
            batch_size: Number of emails to process per batch
            
        Returns:
            Dictionary with extraction results
        """
        try:
            logger.info("Starting lead extraction from emails")
            
            # Get all emails that haven't had leads extracted
            total_emails = mail_pool_emails.count_documents({"lead_extracted": {"$ne": True}})
            logger.info(f"Found {total_emails} emails to process for lead extraction")
            
            extracted = 0
            failed = 0
            
            # Process in batches
            for skip in range(0, total_emails, batch_size):
                batch = list(mail_pool_emails.find(
                    {"lead_extracted": {"$ne": True}}
                ).limit(batch_size).skip(skip))
                
                for email in batch:
                    try:
                        lead_data = await self._extract_lead_from_email(email)
                        if lead_data:
                            # Create or update lead in leads database
                            lead_id = await self._create_or_update_lead(lead_data)
                            
                            # Update email metadata
                            mail_pool_emails.update_one(
                                {"_id": email["_id"]},
                                {"$set": {
                                    "lead_extracted": True,
                                    "lead_id": lead_id,
                                    "lead_extraction_date": datetime.utcnow()
                                }}
                            )
                            
                            # Log extraction
                            lead_extraction_logs.insert_one({
                                "email_id": str(email["_id"]),
                                "lead_id": lead_id,
                                "extraction_date": datetime.utcnow(),
                                "status": "success"
                            })
                            
                            extracted += 1
                    except Exception as e:
                        logger.error(f"Error extracting lead from email {email.get('_id')}: {e}")
                        failed += 1
                
                logger.info(f"Batch complete: {extracted} extracted, {failed} failed")
            
            return {
                "success": True,
                "total_emails": total_emails,
                "extracted": extracted,
                "failed": failed,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error in extract_leads_from_emails: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def _extract_lead_from_email(self, email: Dict[str, Any]) -> Optional[ExtractedLead]:
        """
        Extract lead information from email using Gemini
        
        Args:
            email: Email document from database
            
        Returns:
            ExtractedLead object or None if no lead data found
        """
        try:
            email_body = email.get("body", "")
            email_subject = email.get("subject", "")
            from_email = email.get("from_email", "")
            from_name = email.get("from_name", "")
            
            if not email_body:
                return None
            
            # Use Gemini to extract lead information
            prompt = f"""
Extract lead information from this email. Return JSON only.

FROM: {from_email} ({from_name})
SUBJECT: {email_subject}
BODY: {email_body[:2000]}  # First 2000 chars

Extract if present: name, email, company, title, phone, linkedin profile, website, location.
If a field is not found or unclear, omit it from the JSON.

Return JSON format:
{{
    "name": "Full Name",
    "email": "email@example.com",
    "company": "Company Name",
    "title": "Job Title",
    "phone": "+1-234-567-8900",
    "linkedin": "https://linkedin.com/in/profile",
    "website": "https://company.com",
    "location": "City, State, Country",
    "confidence": 0.85
}}

Return ONLY valid JSON, no explanation or other text.
"""
            
            response_text = self._call_gemini(prompt, task_type="lead_extract")
            
            try:
                lead_data = json.loads(response_text)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse lead extraction response: {response_text}")
                return None
            
            # Only create lead if we have at least name and email
            if not (lead_data.get("name") and lead_data.get("email")):
                return None
            
            extracted_lead = ExtractedLead(
                name=lead_data.get("name", ""),
                email=lead_data.get("email", ""),
                company=lead_data.get("company", ""),
                title=lead_data.get("title", ""),
                phone=lead_data.get("phone", ""),
                linkedin=lead_data.get("linkedin", ""),
                website=lead_data.get("website", ""),
                location=lead_data.get("location", ""),
                source_email_id=str(email["_id"]),
                source_email_from=from_email,
                source_email_subject=email_subject,
                extracted_at=datetime.utcnow().isoformat(),
                confidence=float(lead_data.get("confidence", 0.8))
            )
            
            return extracted_lead
        
        except Exception as e:
            logger.error(f"Error extracting lead from email: {e}")
            return None
    
    async def _create_or_update_lead(self, lead_data: ExtractedLead) -> str:
        """
        Create or update lead in leads database
        
        Args:
            lead_data: ExtractedLead object
            
        Returns:
            Lead ID (string)
        """
        try:
            # Check if lead already exists by email
            existing_lead = leads_collection.find_one({"email": lead_data.email})
            
            lead_doc = {
                "name": lead_data.name,
                "email": lead_data.email,
                "company": lead_data.company,
                "title": lead_data.title,
                "phone": lead_data.phone,
                "linkedin": lead_data.linkedin,
                "website": lead_data.website,
                "location": lead_data.location,
                "source_emails": [lead_data.source_email_id],
                "extracted_at": lead_data.extracted_at,
                "confidence": lead_data.confidence,
                "last_updated": datetime.utcnow()
            }
            
            if existing_lead:
                # Update existing lead - add to source_emails if not already there
                source_emails = existing_lead.get("source_emails", [])
                if lead_data.source_email_id not in source_emails:
                    source_emails.append(lead_data.source_email_id)
                
                leads_collection.update_one(
                    {"_id": existing_lead["_id"]},
                    {"$set": {
                        **lead_doc,
                        "source_emails": source_emails,
                        "last_updated": datetime.utcnow()
                    }}
                )
                lead_id = str(existing_lead["_id"])
            else:
                # Create new lead
                result = leads_collection.insert_one(lead_doc)
                lead_id = str(result.inserted_id)
            
            # Also store in email_leads collection for email automation
            email_leads.insert_one({
                "lead_id": lead_id,
                "email_id": lead_data.source_email_id,
                "name": lead_data.name,
                "email": lead_data.email,
                "company": lead_data.company,
                "title": lead_data.title,
                "extracted_at": lead_data.extracted_at,
                "source_email": lead_data.source_email_from,
                "source_subject": lead_data.source_email_subject
            })
            
            logger.info(f"Lead {lead_id} created/updated for {lead_data.email}")
            return lead_id
        
        except Exception as e:
            logger.error(f"Error creating/updating lead: {e}")
            raise
    
    async def mark_email_as_lead_extracted(self, email_id: str, lead_id: str) -> bool:
        """
        Mark email as having lead extracted
        
        Args:
            email_id: Email document ID
            lead_id: Lead document ID
            
        Returns:
            True if successful
        """
        try:
            mail_pool_emails.update_one(
                {"_id": ObjectId(email_id)},
                {"$set": {
                    "lead_extracted": True,
                    "lead_id": lead_id,
                    "lead_extraction_date": datetime.utcnow()
                }}
            )
            return True
        except Exception as e:
            logger.error(f"Error marking email as lead extracted: {e}")
            return False
    
    def get_lead_extraction_stats(self) -> Dict[str, Any]:
        """Get statistics about lead extraction"""
        try:
            total_emails = mail_pool_emails.count_documents({})
            extracted_emails = mail_pool_emails.count_documents({"lead_extracted": True})
            total_leads = leads_collection.count_documents({})
            
            return {
                "total_emails": total_emails,
                "emails_with_leads": extracted_emails,
                "pending_extraction": total_emails - extracted_emails,
                "extraction_percentage": round((extracted_emails / total_emails * 100) if total_emails > 0 else 0, 2),
                "total_leads_created": total_leads,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting lead extraction stats: {e}")
            return {}
    
    def get_segregation_stats(self) -> Dict[str, Any]:
        """Get statistics about segregated emails"""
        try:
            total = mail_pool_emails.count_documents({})
            classified = mail_pool_emails.count_documents({"ai_classification_status": {"$exists": True}})
            
            segment_breakdown = list(mail_pool_emails.aggregate([
                {"$match": {"ai_classification_status": {"$exists": True}}},
                {"$group": {"_id": "$ai_classification_status.segment", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]))
            
            return {
                "total_emails": total,
                "classified_emails": classified,
                "pending_emails": total - classified,
                "classification_percentage": round((classified / total * 100) if total > 0 else 0, 2),
                "segment_breakdown": segment_breakdown,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}


# Singleton instance
_agent_instance: Optional[MailSegregationAgent] = None


def get_mail_segregation_agent() -> MailSegregationAgent:
    """Get or create singleton instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MailSegregationAgent()
    return _agent_instance
