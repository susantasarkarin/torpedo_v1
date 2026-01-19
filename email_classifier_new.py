"""
TWO-AGENT EMAIL CLASSIFIER
===========================
Agent 1: Creates comprehensive 500-word summary of email thread (including trail mails) + sender details
Agent 2: Categorizes email based on the AI summary from Agent 1

Categories:
- client: Business inquiries FROM prospects/customers
- vendor: FROM external suppliers/service providers  
- invoice: Bills, payment requests, dues
- banking: Bank statements, transactions, alerts
- internal: Between team members (same company domains)
- newsletter: Marketing newsletters, industry updates
- bounce: Undeliverable, failed delivery notifications
- promotional: Ads, offers, sales pitches
- automated: System notifications, alerts, confirmations
- others: Cannot determine
"""

import os
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

from .openai_wrapper import chat_completion, DEFAULT_MODEL

load_dotenv()
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
torpedo_gmail_db = mongo_client['torpedo_gmail']
email_metadata = torpedo_gmail_db['email_metadata']


# Internal company domains
INTERNAL_DOMAINS = ["surveyfieldwork.com", "cogentixresearch.com"]

# Valid categories
CATEGORIES = [
    "client", "vendor", "invoice", "banking", "internal",
    "newsletter", "bounce", "promotional", "automated", "others"
]


# ============================================================================
# AGENT 1: SUMMARY EXTRACTION (500 words including thread + sender details)
# ============================================================================

AGENT1_SYSTEM_PROMPT = """You are an expert email analyst. Your task is to create a COMPREHENSIVE SUMMARY of the email conversation.

CRITICAL REQUIREMENTS:
1. Create a detailed summary of approximately 500 words (minimum 300, maximum 600)
2. Include ALL emails in the thread/trail - summarize the complete conversation flow
3. Extract and include complete sender information from signatures and headers
4. Capture: purpose, key requests, important details (pricing, dates, specs), action items, relationship status

Your summary MUST include:
- Full context of the conversation (who initiated, what was discussed)
- All key points from every email in the thread
- Specific details: dates, amounts, project names, specifications mentioned
- Names, titles, and companies of all participants
- Any action items or next steps mentioned
- Current status of the conversation (new, ongoing, closed)

SENDER INFORMATION to extract:
- Full name (from signature or headers)
- First name and Last name separately  
- Email address
- Job title/designation
- Company name and domain
- Phone number (from signature)
- LinkedIn URL (if mentioned)
- Location/City (if mentioned)

OUTPUT FORMAT (valid JSON only):
{
  "summary": "Your comprehensive 500-word summary here covering the entire email thread...",
  "thread_summary": {
    "email_count": 1,
    "conversation_started": "date of first email",
    "last_activity": "date of latest email",
    "participants": ["email1@domain.com", "email2@domain.com"],
    "status": "new|active|stale|closed"
  },
  "key_points": ["point1", "point2", "point3"],
  "action_items": ["action1", "action2"],
  "urgency": "critical|high|medium|low|none",
  "sender_info": {
    "name": "Full Name",
    "first_name": "First",
    "last_name": "Last",
    "email": "sender@email.com",
    "title": "Job Title",
    "company_name": "Company Name",
    "company_domain": "company.com",
    "phone": "phone number",
    "linkedin": "linkedin url",
    "location": "City, Country"
  }
}

IMPORTANT: The summary should be detailed enough that someone reading it can understand the ENTIRE conversation without reading the original emails."""


AGENT2_SYSTEM_PROMPT = """You are an email categorization expert for a B2B survey/market research company (Survey Fieldwork / Cogentix Research).

Based on the AI summary provided, categorize this email into ONE of these categories:

CATEGORIES:
- client: Business inquiry FROM prospects/customers seeking OUR research/survey services (RFQ, project inquiry, meeting request)
- vendor: FROM external suppliers/service providers contacting US (sales pitch, partnership, software vendor, vendor following up on THEIR invoice)
- invoice: Invoice/bill attached or referenced, billing statement, payment request WITH specific invoice numbers
- banking: FROM bank domains (axisbank, hdfcbank, icici, sbi, kotak, etc) - statements, transactions, OTPs
- internal: Communications between @surveyfieldwork.com or @cogentixresearch.com team members
- newsletter: Marketing newsletters with "unsubscribe", regular publications, industry digests
- bounce: Delivery failure, "undeliverable", "mailer-daemon", NDR, returned mail
- promotional: One-off marketing/sales email, ads, offers, cold outreach, webinar invites
- automated: System notifications, noreply@, auto-replies, calendar invites, password resets, confirmations
- others: ONLY if absolutely cannot determine

OUTPUT FORMAT (valid JSON only):
{
  "category": "one of the categories above",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why this category was chosen",
  "action_required": true/false,
  "priority": "high|medium|low"
}

CLASSIFICATION HINTS:
- "mailer-daemon", "postmaster", "Undeliverable" = bounce
- Bank domain emails = banking
- Internal company domains communicating = internal
- "Unsubscribe" + regular sender = newsletter
- Vendor asking about THEIR unpaid invoice = vendor (not invoice)
- Invoice WITH numbers for US to pay = invoice
- "noreply@", system-generated = automated"""


def get_thread_emails(thread_id: str, primary_email_id: str) -> List[Dict[str, Any]]:
    """Get all emails in a thread, sorted by date"""
    if not thread_id:
        # No thread, just get the single email
        email = email_metadata.find_one({"_id": ObjectId(primary_email_id)})
        return [email] if email else []
    
    # Get all emails with this thread_id
    emails = list(email_metadata.find(
        {"thread_id": thread_id}
    ).sort("date", 1))  # Oldest first
    
    if not emails:
        # Fallback to single email
        email = email_metadata.find_one({"_id": ObjectId(primary_email_id)})
        return [email] if email else []
    
    return emails


def build_thread_text(emails: List[Dict[str, Any]]) -> str:
    """Build formatted text representation of email thread for Agent 1"""
    if not emails:
        return ""
    
    thread_parts = []
    for i, email_data in enumerate(emails, 1):
        date = email_data.get("date", "Unknown date")
        if hasattr(date, 'isoformat'):
            date = date.isoformat()
        
        from_email = email_data.get("from_email", "Unknown")
        from_name = email_data.get("from_name", "")
        to_emails = email_data.get("to_emails", [])
        to_str = ", ".join(to_emails[:3]) if to_emails else "Unknown"
        subject = email_data.get("subject", "(No subject)")
        body = email_data.get("body_plain", email_data.get("body", ""))[:3000]  # Limit per email
        
        direction = "RECEIVED"
        for internal in INTERNAL_DOMAINS:
            if internal in from_email.lower():
                direction = "SENT"
                break
        
        thread_parts.append(f"""
=== Email {i} of {len(emails)} ({direction}) ===
Date: {date}
From: {from_name} <{from_email}>
To: {to_str}
Subject: {subject}

{body}
""")
    
    return "\n".join(thread_parts)


def extract_sender_name(from_header: str) -> tuple:
    """Extract name parts from email From header"""
    if not from_header:
        return "", "", ""

    match = re.match(r'^"?([^"<]+)"?\s*<?', from_header)
    if match:
        full_name = match.group(1).strip()
        full_name = re.sub(r'<[^>]+>', '', full_name).strip()
        parts = full_name.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:]), full_name
        elif len(parts) == 1:
            return parts[0], "", full_name
    return "", "", ""


def agent1_summarize(
    emails: List[Dict[str, Any]],
    primary_from_email: str,
    primary_from_name: str = "",
    source: str = "background"
) -> Dict[str, Any]:
    """
    AGENT 1: Create comprehensive 500-word summary of email thread with sender extraction
    """
    if not emails:
        return {"success": False, "error": "No emails provided"}
    
    # Build thread text
    thread_text = build_thread_text(emails)
    
    # Extract sender info from header
    first_name, last_name, full_name = extract_sender_name(primary_from_name or primary_from_email)
    from_domain = primary_from_email.split("@")[-1].lower() if "@" in primary_from_email else ""
    
    user_prompt = f"""Analyze this email thread and create a comprehensive summary (approximately 500 words).

Primary Sender: {primary_from_name} <{primary_from_email}>
Company Domain: {from_domain or 'Unknown'}
Number of Emails in Thread: {len(emails)}
Internal Company Domains: {', '.join(INTERNAL_DOMAINS)}

=== EMAIL THREAD START ===
{thread_text}
=== EMAIL THREAD END ===

Create a detailed 500-word summary covering the entire conversation, extract all sender information, and identify key points and action items."""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": AGENT1_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model=DEFAULT_MODEL,
            temperature=0.2,
            max_output_tokens=1500,  # Allow for full 500-word summary + metadata
            response_format={"type": "json_object"},
            source=source
        )
        
        if not response or not response.get("success"):
            logger.warning(f"Agent 1 failed: {response.get('error') if response else 'No response'}")
            return {
                "success": False,
                "error": response.get("error") if response else "No response",
                "summary": "",
                "sender_info": {
                    "name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": primary_from_email,
                    "company_domain": from_domain
                }
            }
        
        content = response.get("content", "")
        if not content:
            return {"success": False, "error": "Empty response"}
        
        # Parse JSON response
        try:
            clean_response = content.strip()
            if clean_response.startswith("```"):
                clean_response = re.sub(r'^```json?\s*', '', clean_response)
                clean_response = re.sub(r'\s*```$', '', clean_response)
            result = json.loads(clean_response)
        except json.JSONDecodeError as e:
            logger.warning(f"Agent 1 JSON error: {e}")
            return {"success": False, "error": f"JSON parse error: {e}"}
        
        # Ensure sender_info has all required fields
        sender_info = result.get("sender_info", {})
        sender_info.setdefault("email", primary_from_email)
        sender_info.setdefault("name", full_name)
        sender_info.setdefault("first_name", first_name)
        sender_info.setdefault("last_name", last_name)
        sender_info.setdefault("company_domain", from_domain)
        
        return {
            "success": True,
            "summary": result.get("summary", ""),
            "thread_summary": result.get("thread_summary", {}),
            "key_points": result.get("key_points", []),
            "action_items": result.get("action_items", []),
            "urgency": result.get("urgency", "none"),
            "sender_info": sender_info,
            "model": DEFAULT_MODEL,
            "agent": "agent1_summary"
        }
        
    except Exception as e:
        logger.error(f"Agent 1 error: {e}")
        return {"success": False, "error": str(e)}


def agent2_categorize(
    summary: str,
    sender_info: Dict[str, Any],
    key_points: List[str] = None,
    source: str = "background"
) -> Dict[str, Any]:
    """
    AGENT 2: Categorize email based on Agent 1's summary
    """
    if not summary:
        return {
            "success": False,
            "error": "No summary provided",
            "category": "others",
            "confidence": 0.0
        }
    
    user_prompt = f"""Based on this AI-generated email summary, categorize the email.

=== AI SUMMARY ===
{summary}

=== SENDER INFO ===
Name: {sender_info.get('name', 'Unknown')}
Email: {sender_info.get('email', 'Unknown')}
Company: {sender_info.get('company_name', sender_info.get('company_domain', 'Unknown'))}
Title: {sender_info.get('title', 'Unknown')}

=== KEY POINTS ===
{chr(10).join(['- ' + p for p in (key_points or [])])}

Determine the most appropriate category for this email."""

    try:
        response = chat_completion(
            messages=[
                {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model=DEFAULT_MODEL,
            temperature=0.1,
            max_output_tokens=300,
            response_format={"type": "json_object"},
            source=source
        )
        
        if not response or not response.get("success"):
            logger.warning(f"Agent 2 failed: {response.get('error') if response else 'No response'}")
            return {
                "success": False,
                "error": response.get("error") if response else "No response",
                "category": "others",
                "confidence": 0.0
            }
        
        content = response.get("content", "")
        if not content:
            return {"success": False, "error": "Empty response", "category": "others", "confidence": 0.0}
        
        # Parse JSON response
        try:
            clean_response = content.strip()
            if clean_response.startswith("```"):
                clean_response = re.sub(r'^```json?\s*', '', clean_response)
                clean_response = re.sub(r'\s*```$', '', clean_response)
            result = json.loads(clean_response)
        except json.JSONDecodeError as e:
            logger.warning(f"Agent 2 JSON error: {e}")
            return {"success": False, "error": f"JSON parse error: {e}", "category": "others", "confidence": 0.0}
        
        # Normalize category
        category = result.get("category", "others").lower().strip()
        if category not in CATEGORIES:
            category = "others"
        
        return {
            "success": True,
            "category": category,
            "confidence": float(result.get("confidence", 0.8)),
            "reasoning": result.get("reasoning", ""),
            "action_required": result.get("action_required", False),
            "priority": result.get("priority", "medium"),
            "model": DEFAULT_MODEL,
            "agent": "agent2_categorize"
        }
        
    except Exception as e:
        logger.error(f"Agent 2 error: {e}")
        return {"success": False, "error": str(e), "category": "others", "confidence": 0.0}


def classify_email_with_agents(
    email_id: str,
    include_thread: bool = True,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Main classification function using the 2-agent system:
    Agent 1: Create 500-word summary (including thread/trail) + sender extraction
    Agent 2: Categorize based on the summary
    """
    # Get the email
    try:
        email_doc = email_metadata.find_one({"_id": ObjectId(email_id)})
    except:
        return {"success": False, "error": "Invalid email ID"}
    
    if not email_doc:
        return {"success": False, "error": "Email not found"}
    
    # Get thread emails if available
    if include_thread:
        thread_id = email_doc.get("thread_id")
        emails = get_thread_emails(thread_id, email_id)
    else:
        emails = [email_doc]
    
    primary_from_email = email_doc.get("from_email", "")
    primary_from_name = email_doc.get("from_name", "")
    
    # AGENT 1: Generate summary
    agent1_result = agent1_summarize(
        emails=emails,
        primary_from_email=primary_from_email,
        primary_from_name=primary_from_name,
        source=source
    )
    
    if not agent1_result.get("success"):
        # Fallback: still try to categorize with basic info
        agent1_result = {
            "success": False,
            "summary": f"Email from {primary_from_email}. Subject: {email_doc.get('subject', '')}",
            "sender_info": {
                "email": primary_from_email,
                "name": primary_from_name,
                "company_domain": primary_from_email.split("@")[-1] if "@" in primary_from_email else ""
            },
            "key_points": [],
            "action_items": [],
            "urgency": "none"
        }
    
    # AGENT 2: Categorize based on summary
    agent2_result = agent2_categorize(
        summary=agent1_result.get("summary", ""),
        sender_info=agent1_result.get("sender_info", {}),
        key_points=agent1_result.get("key_points", []),
        source=source
    )
    
    # Combine results
    final_result = {
        "email_id": email_id,
        "success": agent1_result.get("success", False) and agent2_result.get("success", False),
        # Agent 1 outputs
        "summary": agent1_result.get("summary", ""),
        "thread_summary": agent1_result.get("thread_summary", {}),
        "key_points": agent1_result.get("key_points", []),
        "action_items": agent1_result.get("action_items", []),
        "urgency": agent1_result.get("urgency") or agent2_result.get("priority", "none"),
        "sender_info": agent1_result.get("sender_info", {}),
        # Agent 2 outputs
        "category": agent2_result.get("category", "others"),
        "confidence": agent2_result.get("confidence", 0.0),
        "reasoning": agent2_result.get("reasoning", ""),
        "action_required": agent2_result.get("action_required", False),
        # Metadata
        "classified_at": datetime.utcnow(),
        "method": "two_agent_system",
        "model": DEFAULT_MODEL,
        "thread_email_count": len(emails)
    }
    
    return final_result


def classify_and_summarize(
    email_id: str,
    subject: str,
    body: str,
    from_email: str,
    from_name: str = "",
    to_email: str = "",
    source: str = "background"
) -> Dict[str, Any]:
    """
    Wrapper function for backward compatibility.
    Now uses the 2-agent system.
    """
    return classify_email_with_agents(
        email_id=email_id,
        include_thread=True,
        source=source
    )


def _default_result(email_id: str, from_email: str, first_name: str, last_name: str, full_name: str, from_domain: str = "") -> Dict:
    """Return default result when AI fails"""
    return {
        "email_id": email_id,
        "success": False,
        "summary": "",
        "category": "others",
        "confidence": 0.0,
        "urgency": "none",
        "action_required": False,
        "action_items": [],
        "sender_info": {
            "name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": from_email,
            "email_status": "unknown",
            "title": "",
            "linkedin": "",
            "location": "",
            "company_name": "",
            "company_domain": from_domain,
            "company_linkedin": "",
            "company_industry": "",
            "company_size": "",
            "company_type": "",
            "phone": ""
        },
        "classified_at": datetime.utcnow(),
        "model": DEFAULT_MODEL,
        "method": "fallback"
    }


def clear_all_classifications():
    """Remove all AI classification data from emails"""
    result = email_metadata.update_many(
        {},
        {
            "$unset": {
                "ai_category": "",
                "ai_tier1_category": "",
                "ai_confidence": "",
                "ai_method": "",
                "ai_classified_at": "",
                "ai_summary": "",
                "ai_urgency": "",
                "ai_action_required": "",
                "ai_action_items": "",
                "ai_intent": "",
                "ai_sentiment": "",
                "ai_tier2_result": "",
                "ai_key_points": "",
                "ai_reasoning": "",
                "ai_thread_summary": "",
                "sender_info": ""
            }
        }
    )
    logger.info(f"Cleared classification from {result.modified_count} emails")
    return result.modified_count


def classify_batch(
    batch_size: int = 50,
    source: str = "background",
    delay_between_emails: float = 0.5
) -> Dict[str, Any]:
    """
    Classify a batch of unclassified emails using the 2-agent system.
    """
    # Find unclassified emails
    unclassified = list(email_metadata.find(
        {"ai_category": {"$exists": False}},
        {"_id": 1, "thread_id": 1, "from_email": 1, "from_name": 1}
    ).limit(batch_size))

    if not unclassified:
        return {"processed": 0, "success": 0, "errors": 0, "message": "No unclassified emails"}

    stats = {
        "processed": 0,
        "success": 0,
        "errors": 0,
        "categories": {}
    }

    for email_doc in unclassified:
        email_id = str(email_doc["_id"])

        try:
            result = classify_email_with_agents(
                email_id=email_id,
                include_thread=True,
                source=source
            )

            # Update email in database
            update_fields = {
                "ai_category": result["category"],
                "ai_confidence": result["confidence"],
                "ai_summary": result["summary"],
                "ai_urgency": result["urgency"],
                "ai_action_required": result["action_required"],
                "ai_action_items": result.get("action_items", []),
                "ai_key_points": result.get("key_points", []),
                "ai_reasoning": result.get("reasoning", ""),
                "ai_thread_summary": result.get("thread_summary", {}),
                "ai_classified_at": result["classified_at"],
                "ai_method": result["method"],
                "sender_info": result["sender_info"]
            }
            
            email_metadata.update_one(
                {"_id": email_doc["_id"]},
                {"$set": update_fields}
            )

            stats["processed"] += 1
            if result["success"]:
                stats["success"] += 1
            else:
                stats["errors"] += 1

            cat = result["category"]
            stats["categories"][cat] = stats["categories"].get(cat, 0) + 1

            # Delay between emails (2-agent system makes 2 API calls)
            if delay_between_emails > 0:
                time.sleep(delay_between_emails)

        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}")
            stats["errors"] += 1

    return stats


def classify_all_pending_emails(
    batch_size: int = 50,
    max_batches: Optional[int] = None,
    delay_between_batches: float = 2.0,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Classify ALL unclassified emails in batches using the 2-agent system.
    """
    total_stats = {
        "success": True,
        "total_processed": 0,
        "total_success": 0,
        "total_errors": 0,
        "batches": 0,
        "categories": {},
        "started_at": datetime.utcnow().isoformat(),
        "method": "two_agent_system"
    }

    batch_num = 0
    while True:
        batch_num += 1

        if max_batches and batch_num > max_batches:
            logger.info(f"Reached max batches limit: {max_batches}")
            break

        logger.info(f"Processing batch {batch_num} with {batch_size} emails (2-agent system)")

        batch_stats = classify_batch(
            batch_size=batch_size,
            source=source
        )

        if batch_stats["processed"] == 0:
            logger.info("No more unclassified emails")
            break

        total_stats["total_processed"] += batch_stats["processed"]
        total_stats["total_success"] += batch_stats.get("success", 0)
        total_stats["total_errors"] += batch_stats.get("errors", 0)
        total_stats["batches"] += 1

        for cat, count in batch_stats.get("categories", {}).items():
            total_stats["categories"][cat] = total_stats["categories"].get(cat, 0) + count

        logger.info(f"Batch {batch_num} complete: {batch_stats['processed']} processed, {batch_stats.get('errors', 0)} errors")

        if delay_between_batches > 0:
            time.sleep(delay_between_batches)

    total_stats["completed_at"] = datetime.utcnow().isoformat()
    logger.info(f"Classification complete: {total_stats['total_processed']} emails in {total_stats['batches']} batches")

    return total_stats


def get_classification_stats() -> Dict[str, Any]:
    """Get current classification statistics"""
    pipeline = [
        {"$group": {"_id": "$ai_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]

    results = list(email_metadata.aggregate(pipeline))

    total = email_metadata.count_documents({})
    classified = email_metadata.count_documents({"ai_category": {"$exists": True, "$ne": None}})

    return {
        "total_emails": total,
        "classified": classified,
        "unclassified": total - classified,
        "categories": {r["_id"]: r["count"] for r in results if r["_id"]},
        "method": "two_agent_system"
    }


# Legacy function aliases for backwards compatibility
def classify_email_batch(*args, **kwargs):
    """Legacy wrapper for classify_batch"""
    return {"stats": classify_batch(*args, **kwargs), "results": []}


def get_emails_needing_classification(limit: int = 100) -> List[str]:
    """Get email IDs that haven't been classified yet"""
    emails = email_metadata.find(
        {"ai_category": {"$exists": False}},
        {"_id": 1}
    ).limit(limit)
    return [str(e["_id"]) for e in emails]
