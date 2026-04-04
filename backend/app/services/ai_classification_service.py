"""
AI CLASSIFICATION SERVICE
==========================

AI-powered email classification using Gemini (volume) and Claude (complex tasks).

Implements the 2-provider strategy:
- Gemini 2.0 Flash: High-volume classification, extraction, analytics
- Claude 3.5 Sonnet: Cold emails, content writing, agents

Features:
1. Email classification with department routing
2. Lead extraction from emails
3. Priority and urgency detection
4. Entity extraction (company, person, amounts, dates)
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum

import openai

logger = logging.getLogger(__name__)


# =========================================================================
# ENUMS
# =========================================================================

class EmailCategory(str, Enum):
    """Email categories for CRM routing"""
    # Sales
    INBOUND_LEAD = "inbound_lead"
    MEETING_REQUEST = "meeting_request"
    DEMO_REQUEST = "demo_request"
    PRICING_INQUIRY = "pricing_inquiry"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    DISCOVERY = "discovery"
    OUTREACH = "outreach"
    
    # Operations
    RFQ_REQUEST = "rfq_request"
    QUOTE_RESPONSE = "quote_response"
    NEGOTIATION = "negotiation"
    CONTRACT_DISCUSSION = "contract_discussion"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_UPDATE = "delivery_update"
    VENDOR_COMMUNICATION = "vendor_communication"
    
    # Finance
    INVOICE = "invoice"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    PAYMENT_REMINDER = "payment_reminder"
    BILLING_DISPUTE = "billing_dispute"
    BANKING = "banking"
    
    # Support
    SUPPORT_REQUEST = "support_request"
    COMPLAINT = "complaint"
    FEEDBACK = "feedback"
    ONBOARDING = "onboarding"
    
    # Low priority
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    UNSUBSCRIBE = "unsubscribe"
    AUTO_REPLY = "auto_reply"
    NEWSLETTER = "newsletter"
    PROMOTIONAL = "promotional"
    SPAM = "spam"
    SOCIAL_NOTIFICATION = "social_notification"
    INTERNAL = "internal"
    OTHER = "other"
    UNCATEGORIZED = "uncategorized"


class Department(str, Enum):
    """Department routing"""
    SALES = "sales"
    OPERATIONS = "operations"
    FINANCE = "finance"
    SUPPORT = "support"
    NONE = "none"


class Priority(str, Enum):
    """Email priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Category to department mapping
CATEGORY_TO_DEPARTMENT = {
    # Sales
    EmailCategory.INBOUND_LEAD: Department.SALES,
    EmailCategory.MEETING_REQUEST: Department.SALES,
    EmailCategory.DEMO_REQUEST: Department.SALES,
    EmailCategory.PRICING_INQUIRY: Department.SALES,
    EmailCategory.INTERESTED: Department.SALES,
    EmailCategory.DISCOVERY: Department.SALES,
    EmailCategory.OUTREACH: Department.SALES,
    
    # Operations
    EmailCategory.RFQ_REQUEST: Department.OPERATIONS,
    EmailCategory.QUOTE_RESPONSE: Department.OPERATIONS,
    EmailCategory.NEGOTIATION: Department.OPERATIONS,
    EmailCategory.CONTRACT_DISCUSSION: Department.OPERATIONS,
    EmailCategory.PURCHASE_ORDER: Department.OPERATIONS,
    EmailCategory.DELIVERY_UPDATE: Department.OPERATIONS,
    EmailCategory.VENDOR_COMMUNICATION: Department.OPERATIONS,
    
    # Finance
    EmailCategory.INVOICE: Department.FINANCE,
    EmailCategory.PAYMENT_CONFIRMATION: Department.FINANCE,
    EmailCategory.PAYMENT_REMINDER: Department.FINANCE,
    EmailCategory.BILLING_DISPUTE: Department.FINANCE,
    EmailCategory.BANKING: Department.FINANCE,
    
    # Support
    EmailCategory.SUPPORT_REQUEST: Department.SUPPORT,
    EmailCategory.COMPLAINT: Department.SUPPORT,
    EmailCategory.FEEDBACK: Department.SUPPORT,
    EmailCategory.ONBOARDING: Department.SUPPORT,
    
    # No routing
    EmailCategory.NOT_INTERESTED: Department.NONE,
    EmailCategory.OUT_OF_OFFICE: Department.NONE,
    EmailCategory.BOUNCE: Department.NONE,
    EmailCategory.UNSUBSCRIBE: Department.NONE,
    EmailCategory.AUTO_REPLY: Department.NONE,
    EmailCategory.NEWSLETTER: Department.NONE,
    EmailCategory.PROMOTIONAL: Department.NONE,
    EmailCategory.SPAM: Department.NONE,
    EmailCategory.SOCIAL_NOTIFICATION: Department.NONE,
    EmailCategory.INTERNAL: Department.NONE,
    EmailCategory.OTHER: Department.NONE,
    EmailCategory.UNCATEGORIZED: Department.NONE,
}


@dataclass
class ClassificationResult:
    """Email classification result"""
    category: str
    confidence: float
    department: str
    priority: str
    intent: str
    is_reply: bool
    reply_sentiment: Optional[str]
    key_entities: Dict[str, Any]
    suggested_action: Optional[str]
    summary: str


@dataclass
class LeadExtractionResult:
    """Extracted lead information from email"""
    has_lead: bool
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    company: Optional[str]
    title: Optional[str]
    phone: Optional[str]
    pain_points: List[str]
    services_interested: List[str]
    urgency: str
    confidence: float


class AIClassificationService:
    """
    AI service for email classification and analysis.
    
    Uses:
    - Gemini 2.0 Flash for high-volume classification
    - Claude 3.5 Sonnet for complex analysis (optional)
    """
    
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None
    ):
        """Initialize AI service with API keys"""
        # OpenAI setup (backward compat: accepts gemini_api_key param name)
        api_key = gemini_api_key or os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai_client = openai.OpenAI(api_key=api_key)
            self.model_name = "gpt-4o-mini"
        else:
            self.openai_client = None
            logger.warning("OpenAI API key not configured")
        
        # Keep backward compat attributes
        self.gemini_model = self.openai_client  # truthy check compat
        self.anthropic_client = None
    
    # =========================================================================
    # EMAIL CLASSIFICATION
    # =========================================================================
    
    def classify_email(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        body: str,
        snippet: Optional[str] = None
    ) -> ClassificationResult:
        """
        Classify an email using Gemini.
        
        Returns:
            ClassificationResult with category, department, priority, etc.
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI API not configured")
        
        prompt = self._build_classification_prompt(from_email, to_email, subject, body)
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Map category to department
            category = result.get("category", "uncategorized")
            try:
                category_enum = EmailCategory(category)
                department = CATEGORY_TO_DEPARTMENT.get(category_enum, Department.NONE).value
            except ValueError:
                department = "none"
            
            return ClassificationResult(
                category=category,
                confidence=result.get("confidence", 0.5),
                department=department,
                priority=result.get("priority", "medium"),
                intent=result.get("intent", "informational"),
                is_reply=result.get("is_reply", False),
                reply_sentiment=result.get("reply_sentiment"),
                key_entities=result.get("key_entities", {}),
                suggested_action=result.get("suggested_action"),
                summary=result.get("summary", "")
            )
            
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return ClassificationResult(
                category="uncategorized",
                confidence=0.0,
                department="none",
                priority="medium",
                intent="informational",
                is_reply=False,
                reply_sentiment=None,
                key_entities={},
                suggested_action=None,
                summary=""
            )
    
    def _build_classification_prompt(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        body: str
    ) -> str:
        """Build classification prompt for Gemini"""
        # Truncate body if too long
        max_body_length = 3000
        if len(body) > max_body_length:
            body = body[:max_body_length] + "..."
        
        return f'''You are an email classifier for Torpedo, a B2B survey panel operations and sample supplier company.

CONTEXT:
- We supply respondents to survey panels (CPX Research, Cint, Lucid)
- Our clients are market research agencies and insights teams (Buyers)
- We work with panel vendors who provide traffic

TASK: Classify the email and extract metadata for CRM routing.

CATEGORIES (pick exactly one):
SALES DEPARTMENT:
- inbound_lead: New prospect reaching out
- meeting_request: Requesting a call/meeting
- demo_request: Wants to see platform/services
- pricing_inquiry: Asking about rates/CPI/costs
- interested: Positive reply to outreach
- discovery: Early stage conversation
- outreach: Our cold outreach (sent mail)

OPERATIONS DEPARTMENT:
- rfq_request: Request for quotation on a project
- quote_response: Reply to our quote
- negotiation: Discussing terms/pricing/scope
- contract_discussion: Contract/legal matters
- purchase_order: PO or order confirmation
- delivery_update: Project status/fieldwork update
- vendor_communication: Panel vendor correspondence (CPX, Cint, Lucid)

FINANCE DEPARTMENT:
- invoice: Invoice sent or received
- payment_confirmation: Payment made/received
- payment_reminder: Payment due/overdue notice
- billing_dispute: Billing issue or discrepancy
- banking: Bank statements, wire details

SUPPORT:
- support_request: Technical help needed
- complaint: Client complaint or escalation
- feedback: Client feedback (positive or negative)
- onboarding: New client setup

LOW PRIORITY / NO ROUTING:
- not_interested: Negative reply to outreach
- out_of_office: Auto OOO reply
- bounce: Delivery failure
- unsubscribe: Opt-out request
- auto_reply: Automated response
- newsletter: Marketing newsletter
- promotional: Promo/sales email from others
- spam: Irrelevant spam
- social_notification: LinkedIn, Twitter, etc.
- internal: Team/company internal
- other: Doesn't fit above
- uncategorized: Cannot determine

INPUT EMAIL:
From: {from_email}
To: {to_email}
Subject: {subject}
Body:
{body}

OUTPUT FORMAT (JSON only, no explanation):
{{
  "category": "<category_from_list>",
  "confidence": <0.0-1.0>,
  "priority": "<critical|high|medium|low>",
  "intent": "<action_required|response_expected|informational|fyi>",
  "is_reply": <true|false>,
  "reply_sentiment": "<positive|neutral|negative|null>",
  "key_entities": {{
    "company_name": "<extracted or null>",
    "person_name": "<extracted or null>",
    "project_name": "<extracted or null>",
    "amount_mentioned": "<USD amount or null>",
    "deadline_mentioned": "<date or null>",
    "survey_count": "<number of completes/surveys mentioned or null>"
  }},
  "suggested_action": "<brief next step or null>",
  "summary": "<one sentence, max 120 chars>"
}}'''
    
    # =========================================================================
    # LEAD EXTRACTION
    # =========================================================================
    
    def extract_lead(
        self,
        from_email: str,
        from_name: Optional[str],
        subject: str,
        body: str
    ) -> LeadExtractionResult:
        """
        Extract lead information from an email.
        
        Returns:
            LeadExtractionResult with contact details and intent
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI API not configured")
        
        prompt = self._build_lead_extraction_prompt(from_email, from_name, subject, body)
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            return LeadExtractionResult(
                has_lead=result.get("has_lead", False),
                first_name=result.get("first_name"),
                last_name=result.get("last_name"),
                email=result.get("email") or from_email,
                company=result.get("company"),
                title=result.get("title"),
                phone=result.get("phone"),
                pain_points=result.get("pain_points", []),
                services_interested=result.get("services_interested", []),
                urgency=result.get("urgency", "medium"),
                confidence=result.get("confidence", 0.5)
            )
            
        except Exception as e:
            logger.error(f"Lead extraction error: {e}")
            return LeadExtractionResult(
                has_lead=False,
                first_name=None,
                last_name=None,
                email=from_email,
                company=None,
                title=None,
                phone=None,
                pain_points=[],
                services_interested=[],
                urgency="medium",
                confidence=0.0
            )
    
    def _build_lead_extraction_prompt(
        self,
        from_email: str,
        from_name: Optional[str],
        subject: str,
        body: str
    ) -> str:
        """Build lead extraction prompt"""
        max_body_length = 2000
        if len(body) > max_body_length:
            body = body[:max_body_length] + "..."
        
        return f'''You are a lead extraction specialist for Torpedo, a B2B survey panel company.

TASK: Extract potential lead information from this email.

OUR SERVICES:
- Online survey panel access (consumer + B2B)
- Survey programming & hosting
- Fieldwork management
- Data processing & cleaning
- Multi-country studies

INPUT EMAIL:
From: {from_name or ""} <{from_email}>
Subject: {subject}
Body:
{body}

Determine if this is a potential sales lead and extract relevant information.

OUTPUT FORMAT (JSON only):
{{
  "has_lead": <true if this is a potential sales lead, false otherwise>,
  "first_name": "<first name or null>",
  "last_name": "<last name or null>",
  "email": "<email address>",
  "company": "<company name or null>",
  "title": "<job title or null>",
  "phone": "<phone number or null>",
  "pain_points": ["<pain point mentioned>"],
  "services_interested": ["<specific service they might need>"],
  "urgency": "<high|medium|low>",
  "confidence": <0.0-1.0>
}}'''
    
    # =========================================================================
    # BATCH CLASSIFICATION
    # =========================================================================
    
    def classify_batch(
        self,
        emails: List[Dict]
    ) -> List[Tuple[str, ClassificationResult]]:
        """
        Classify a batch of emails.
        
        Args:
            emails: List of dicts with keys: id, from_email, to_emails, subject, snippet
            
        Returns:
            List of (email_id, ClassificationResult) tuples
        """
        results = []
        
        for email in emails:
            try:
                result = self.classify_email(
                    from_email=email.get("from_email", ""),
                    to_email=email.get("to_emails", [""])[0] if email.get("to_emails") else "",
                    subject=email.get("subject", ""),
                    body=email.get("snippet", "")  # Use snippet for batch classification
                )
                results.append((email.get("_id"), result))
            except Exception as e:
                logger.error(f"Error classifying email {email.get('_id')}: {e}")
                results.append((email.get("_id"), ClassificationResult(
                    category="uncategorized",
                    confidence=0.0,
                    department="none",
                    priority="medium",
                    intent="informational",
                    is_reply=False,
                    reply_sentiment=None,
                    key_entities={},
                    suggested_action=None,
                    summary=""
                )))
        
        return results
    
    # =========================================================================
    # COLD EMAIL WRITING (CLAUDE)
    # =========================================================================
    
    def write_cold_email(
        self,
        prospect_name: str,
        prospect_title: str,
        prospect_company: str,
        prospect_industry: str,
        personalization_hooks: List[str],
        pain_points: List[str],
        sender_name: str
    ) -> Dict[str, str]:
        """
        Generate a personalized cold email sequence using Claude.
        
        Returns:
            Dict with keys: email_1, email_2, email_3, subject_1, subject_2, subject_3
        """
        # DISABLED: Claude removed. Cold email generation via cold_outreach_router (Gemini).
        raise RuntimeError("write_cold_email is disabled. Use the campaign AI generation endpoint (cold_outreach_router) which uses Gemini.")
    
    def _build_cold_email_prompt(
        self,
        name: str,
        title: str,
        company: str,
        industry: str,
        hooks: List[str],
        pain_points: List[str],
        sender_name: str
    ) -> str:
        """Build cold email prompt for Claude"""
        return f'''You are a B2B cold email expert writing for Torpedo, a survey panel and sample supplier.

ABOUT TORPEDO:
- We provide online survey panel access, fieldwork, and data collection
- We work with market research agencies, consulting firms, and enterprise insights teams
- Differentiators: Fast turnaround (24-48hr starts), quality respondents, competitive CPI, dedicated project managers
- We cover 50+ countries, consumer and B2B panels
- Typical project: 500-5,000 completes, $3-15 CPI depending on audience

TASK: Write a personalized cold email sequence.

PROSPECT:
Name: {name}
Title: {title}
Company: {company}
Industry: {industry}
Personalization Hooks: {", ".join(hooks)}
Pain Points: {", ".join(pain_points)}

EMAIL 1 REQUIREMENTS (Initial Outreach):
- Subject: 4-7 words, lowercase except first word, no spam words
- Opening: Personalized reference (their company, role, or recent news)
- Problem: One pain point research teams face (vendor reliability, speed, quality, cost)
- Solution: Position Torpedo subtly (not a pitch, a resource)
- Proof: One specific result ("cut fieldwork time by 40%" or "10K completes across 12 markets")
- CTA: Soft, low friction ("open to a quick chat?" or "worth exploring?")
- Length: 60-90 words
- Tone: Peer-to-peer, helpful, not salesy

EMAIL 2 (Follow-up, 3 days later):
- Subject: Re: [original subject] OR new angle
- Add value: Share insight, ask question, or reference something timely
- Shorter: 40-60 words
- Different angle from Email 1

EMAIL 3 (Breakup, 5 days after Email 2):
- Subject: Should I close your file?
- Acknowledge busy schedule
- Leave door open
- Very short: 30-50 words

AVOID:
- "I hope this finds you well"
- "I wanted to reach out"  
- "We are a leading provider"
- "Best-in-class"
- Multiple CTAs
- Exclamation marks
- Links or attachments
- Asking for 30 minutes (ask for "quick" or "15 min")

OUTPUT FORMAT:

**EMAIL 1**
Subject: <subject>

<body>

Best,
{sender_name}

---

**EMAIL 2**
Subject: <subject>

<body>

{sender_name}

---

**EMAIL 3**
Subject: <subject>

<body>

{sender_name}'''
    
    def _parse_cold_email_response(self, content: str) -> Dict[str, str]:
        """Parse Claude's cold email response into structured dict"""
        result = {
            "email_1": "",
            "email_2": "",
            "email_3": "",
            "subject_1": "",
            "subject_2": "",
            "subject_3": ""
        }
        
        # Split by email markers
        parts = content.split("**EMAIL")
        
        for i, part in enumerate(parts[1:4], 1):  # Skip first empty part
            lines = part.strip().split("\n")
            
            # Find subject
            for j, line in enumerate(lines):
                if line.lower().startswith("subject:"):
                    result[f"subject_{i}"] = line.split(":", 1)[1].strip()
                    # Body starts after subject
                    body_lines = []
                    for body_line in lines[j+1:]:
                        if body_line.strip() == "---":
                            break
                        body_lines.append(body_line)
                    result[f"email_{i}"] = "\n".join(body_lines).strip()
                    break
        
        return result
    
    # =========================================================================
    # THREAD ANALYSIS
    # =========================================================================
    
    def summarize_thread(self, thread_messages: List[Dict]) -> Dict:
        """
        Summarize an email thread using Gemini.
        
        Args:
            thread_messages: List of messages with keys: from, to, subject, body, timestamp
            
        Returns:
            Thread summary with key points, actions, sentiment
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI API not configured")
        
        # Build thread content
        thread_content = "\n\n---\n\n".join([
            f"From: {m.get('from', '')}\nTo: {m.get('to', '')}\nDate: {m.get('timestamp', '')}\nSubject: {m.get('subject', '')}\n\n{m.get('body', '')[:1000]}"
            for m in thread_messages[:10]  # Limit to 10 messages
        ])
        
        prompt = f'''You are an email analyst for Torpedo, a survey panel company.

TASK: Summarize this email thread for quick review.

EMAIL THREAD:
{thread_content}

OUTPUT FORMAT (JSON only):
{{
  "thread_subject": "<subject>",
  "participants": ["<email1>", "<email2>"],
  "message_count": <number>,
  "summary": "<4-6 sentence summary>",
  "current_status": "<where things stand>",
  "pending_actions": [
    {{"owner": "<who>", "action": "<what>", "deadline": "<when or null>"}}
  ],
  "key_decisions": ["<decision1>"],
  "sentiment": "<positive|neutral|negative|mixed>",
  "urgency": "<critical|high|medium|low>",
  "next_step": "<recommended action>"
}}'''
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            logger.error(f"Thread summarization error: {e}")
            return {
                "summary": "Unable to summarize thread",
                "sentiment": "neutral",
                "urgency": "medium"
            }
