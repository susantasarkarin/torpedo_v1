"""
AI EMAIL AGENTS
================

Two specialized AI agents for email processing:

AGENT 1 - Email Summary & Contact Extraction
- Creates AI summary (max 500 words)
- Considers full email thread (trail mails)
- Extracts: first name, last name, email, company domain
- Processes individual emails

AGENT 2 - Bulk Categorization Agent  
- Takes batches of ~500 AI summaries
- Categorizes into dynamic buckets
- AI determines optimal category structure
- Returns categorized leads with bucket assignments

Both agents use Gemini API with multi-key rotation for cost efficiency.
"""

import os
import json
import logging
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from pymongo import MongoClient
from dotenv import load_dotenv

# Import OpenAI wrapper for API calls (replaced Gemini)
from .openai_wrapper import (
    chat_completion,
    DEFAULT_MODEL,
    token_logger
)

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
email_db = client['email_automation']
gmail_db = client['torpedo_gmail']

# Collections
email_leads_collection = email_db['email_leads']
ai_summaries_collection = gmail_db['ai_summaries']
ai_categories_collection = gmail_db['ai_categories']
categorization_runs_collection = gmail_db['categorization_runs']


# ============================================================================
# AGENT 1: EMAIL SUMMARY & CONTACT EXTRACTION
# ============================================================================

AGENT1_SYSTEM_PROMPT = """You are an expert email analyst specializing in B2B communications. Your task is to:

1. Create a comprehensive summary of the email conversation (entire thread/trail)
2. Extract contact information from the emails

IMPORTANT GUIDELINES:
- Consider ALL emails in the thread (trail mails included)
- Create a summary that captures the full context and progression of the conversation
- Maximum 500 words for the summary
- Focus on: purpose, key requests, important details (pricing, dates, specifications), action items, relationship status
- Extract contact info from signatures, email addresses, and context clues

OUTPUT FORMAT (JSON):
{
    "summary": "Comprehensive summary of the email conversation (max 500 words)",
    "conversation_status": "active|stale|closed|new",
    "intent": "inquiry|rfq|follow_up|negotiation|support|internal|promotional|other",
    "urgency": "high|medium|low",
    "key_points": ["point1", "point2", "point3"],
    "action_items": ["action1", "action2"],
    "contact": {
        "first_name": "string",
        "last_name": "string", 
        "full_name": "string",
        "email": "email@domain.com",
        "company_domain": "domain.com",
        "company_name": "Company Name if found",
        "title": "Job title if found",
        "phone": "Phone if found",
        "linkedin_url": "LinkedIn URL if found"
    },
    "confidence_score": 0.0-1.0
}"""


def _build_thread_text(emails: List[Dict[str, Any]]) -> str:
    """Build a formatted text representation of email thread"""
    if not emails:
        return ""
    
    # Sort emails by date (oldest first for context flow)
    sorted_emails = sorted(
        emails, 
        key=lambda x: x.get("date", "") if isinstance(x.get("date"), str) else x.get("date", datetime.min).isoformat()
    )
    
    thread_parts = []
    for i, email_data in enumerate(sorted_emails, 1):
        direction = "SENT" if email_data.get("direction") == "sent" else "RECEIVED"
        date = email_data.get("date", "Unknown date")
        from_email = email_data.get("from_email", "Unknown")
        to_email = email_data.get("to", "Unknown")
        subject = email_data.get("subject", "(No subject)")
        body = email_data.get("body", "")[:2000]  # Limit body per email
        
        thread_parts.append(f"""
--- Email {i} ({direction}) ---
Date: {date}
From: {from_email}
To: {to_email}
Subject: {subject}
Body:
{body}
""")
    
    return "\n".join(thread_parts)


def extract_domain_from_email(email_addr: str) -> str:
    """Extract domain from email address"""
    if "@" in email_addr:
        domain = email_addr.split("@")[-1].lower()
        # Skip generic email providers
        generic = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'aol.com', 'live.com']
        if domain not in generic:
            return domain
    return ""


def agent1_process_email_thread(
    emails: List[Dict[str, Any]],
    contact_email: str,
    source: str = "background"
) -> Dict[str, Any]:
    """
    AGENT 1: Process an email thread to generate summary and extract contact info.
    
    Args:
        emails: List of email dictionaries (the full thread/trail)
        contact_email: Primary contact email for this thread
        source: Request source for rate limiting
        
    Returns:
        Dict with summary, contact extraction, and metadata
    """
    if not emails:
        return {
            "success": False,
            "error": "No emails provided",
            "contact_email": contact_email
        }
    
    # Build thread text
    thread_text = _build_thread_text(emails)
    
    # Determine the primary contact from the thread
    domain = extract_domain_from_email(contact_email)
    
    user_prompt = f"""Analyze this email thread and provide a comprehensive summary with contact extraction.

Contact Email: {contact_email}
Company Domain: {domain or 'Unknown'}
Number of Emails in Thread: {len(emails)}

=== EMAIL THREAD ===
{thread_text}
=== END THREAD ===

Provide a thorough summary (max 500 words) covering the entire conversation flow, key points, and extract all contact information you can find."""

    try:
        # Build messages for chat_completion
        messages = [
            {"role": "system", "content": AGENT1_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        result = chat_completion(
            messages=messages,
            source=source,
            endpoint="email_thread_summary",
            model="gpt-4o-mini",  # OpenAI
            provider="openai",
            max_output_tokens=800,  # Allow for full 500-word summary + contact info
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "contact_email": contact_email
            }
        
        # Parse the JSON response
        try:
            parsed = json.loads(result.get("content", "{}"))
        except json.JSONDecodeError:
            parsed = {}
        
        # Ensure contact has the email we're tracking
        if parsed.get("contact"):
            if not parsed["contact"].get("email"):
                parsed["contact"]["email"] = contact_email
            if not parsed["contact"].get("company_domain"):
                parsed["contact"]["company_domain"] = domain
        else:
            parsed["contact"] = {
                "email": contact_email,
                "company_domain": domain,
                "first_name": "",
                "last_name": "",
                "full_name": ""
            }
        
        # Store summary in database
        summary_doc = {
            "contact_email": contact_email,
            "summary": parsed.get("summary", ""),
            "conversation_status": parsed.get("conversation_status", "new"),
            "intent": parsed.get("intent", "other"),
            "urgency": parsed.get("urgency", "medium"),
            "key_points": parsed.get("key_points", []),
            "action_items": parsed.get("action_items", []),
            "contact": parsed.get("contact", {}),
            "confidence_score": parsed.get("confidence_score", 0.5),
            "email_count": len(emails),
            "created_at": datetime.utcnow(),
            "tokens_used": result.get("usage", {}),
            "model": result.get("model", DEFAULT_MODEL)
        }
        
        # Upsert to avoid duplicates
        ai_summaries_collection.update_one(
            {"contact_email": contact_email},
            {"$set": summary_doc},
            upsert=True
        )
        
        return {
            "success": True,
            "contact_email": contact_email,
            **parsed
        }
        
    except Exception as e:
        logger.error(f"Agent 1 error for {contact_email}: {e}")
        return {
            "success": False,
            "error": str(e),
            "contact_email": contact_email
        }


def agent1_batch_process(
    leads_with_emails: List[Dict[str, Any]],
    max_parallel: int = 3,
    delay_between_calls: float = 4.0
) -> List[Dict[str, Any]]:
    """
    Process multiple leads with Agent 1 (with rate limiting).
    
    Args:
        leads_with_emails: List of dicts with 'contact_email' and 'emails' keys
        max_parallel: Maximum parallel API calls (keep low for rate limits)
        delay_between_calls: Seconds between calls per thread
        
    Returns:
        List of processing results
    """
    import time
    
    results = []
    
    for i, lead in enumerate(leads_with_emails):
        contact_email = lead.get("contact_email", "")
        emails = lead.get("emails", [])
        
        if not contact_email or not emails:
            results.append({
                "success": False,
                "error": "Missing contact_email or emails",
                "contact_email": contact_email
            })
            continue
        
        result = agent1_process_email_thread(
            emails=emails,
            contact_email=contact_email,
            source="background"
        )
        results.append(result)
        
        # Rate limiting
        if i < len(leads_with_emails) - 1:
            time.sleep(delay_between_calls)
        
        if (i + 1) % 10 == 0:
            logger.info(f"Agent 1 progress: {i + 1}/{len(leads_with_emails)} leads processed")
    
    return results


# ============================================================================
# AGENT 2: BULK CATEGORIZATION
# ============================================================================

AGENT2_SYSTEM_PROMPT = """You are an expert at categorizing B2B email leads into meaningful business segments. 

Your task is to analyze a batch of lead summaries and:
1. Determine the optimal categories based on the data (you decide the categories)
2. Assign each lead to the most appropriate category
3. Provide reasoning for the categorization

CATEGORY GUIDELINES:
- Create 5-15 categories based on the data patterns
- Categories should be actionable for sales/marketing teams
- Consider: intent, company size, industry, urgency, conversation stage
- Each category should have a clear business meaning

SUGGESTED CATEGORY TYPES (adapt as needed):
- Hot Leads (immediate opportunity)
- Warm Leads (interested but not urgent)
- RFQ/Pricing Requests
- Technical Inquiries
- Partnership Proposals
- Vendor Outreach (companies trying to sell to us)
- Support/Existing Customer
- Dormant/Stale Leads
- Low Quality/Spam
- Internal Communications

OUTPUT FORMAT (JSON):
{
    "categories": [
        {
            "id": "category_id",
            "name": "Category Name",
            "description": "What this category represents",
            "priority": "high|medium|low",
            "suggested_action": "What to do with leads in this category"
        }
    ],
    "categorized_leads": [
        {
            "contact_email": "email@domain.com",
            "category_id": "category_id",
            "confidence": 0.0-1.0,
            "reasoning": "Brief reason for this categorization"
        }
    ],
    "summary": {
        "total_leads": 0,
        "category_distribution": {"category_id": count},
        "insights": "Key observations about this batch of leads"
    }
}"""


def _prepare_summaries_for_categorization(summaries: List[Dict[str, Any]]) -> str:
    """Prepare lead summaries for categorization prompt"""
    summary_parts = []
    
    for i, summary in enumerate(summaries, 1):
        contact = summary.get("contact", {})
        summary_parts.append(f"""
Lead {i}:
- Email: {summary.get('contact_email', 'Unknown')}
- Company: {contact.get('company_name', contact.get('company_domain', 'Unknown'))}
- Intent: {summary.get('intent', 'Unknown')}
- Status: {summary.get('conversation_status', 'Unknown')}
- Urgency: {summary.get('urgency', 'Unknown')}
- Summary: {summary.get('summary', 'No summary')[:300]}...
- Key Points: {', '.join(summary.get('key_points', [])[:3])}
""")
    
    return "\n".join(summary_parts)


def agent2_categorize_batch(
    summaries: List[Dict[str, Any]],
    batch_id: Optional[str] = None,
    source: str = "background"
) -> Dict[str, Any]:
    """
    AGENT 2: Categorize a batch of lead summaries into dynamic categories.
    
    Args:
        summaries: List of AI summaries from Agent 1 (ideally ~500 at a time)
        batch_id: Optional identifier for this categorization run
        source: Request source for rate limiting
        
    Returns:
        Categorization results with categories and lead assignments
    """
    if not summaries:
        return {
            "success": False,
            "error": "No summaries provided"
        }
    
    # Generate batch ID if not provided
    if not batch_id:
        batch_id = f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    # For very large batches, we need to chunk
    MAX_SUMMARIES_PER_CALL = 100  # Limit to avoid context length issues
    
    if len(summaries) > MAX_SUMMARIES_PER_CALL:
        return _agent2_categorize_large_batch(summaries, batch_id, source)
    
    # Prepare summaries text
    summaries_text = _prepare_summaries_for_categorization(summaries)
    
    user_prompt = f"""Analyze and categorize these {len(summaries)} leads:

{summaries_text}

Create appropriate categories based on the data patterns and assign each lead to a category. 
Focus on actionable segmentation that helps sales and marketing teams prioritize their efforts."""

    try:
        # Build messages for chat_completion
        messages = [
            {"role": "system", "content": AGENT2_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        
        result = chat_completion(
            messages=messages,
            source=source,
            endpoint="bulk_categorization",
            model="gpt-4o-mini",  # OpenAI
            provider="openai",
            max_output_tokens=2000,  # Need more tokens for batch categorization
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "batch_id": batch_id
            }
        
        # Parse the JSON response
        try:
            parsed = json.loads(result.get("content", "{}"))
        except json.JSONDecodeError:
            parsed = {}
        
        # Store categorization run
        run_doc = {
            "batch_id": batch_id,
            "categories": parsed.get("categories", []),
            "categorized_leads": parsed.get("categorized_leads", []),
            "summary": parsed.get("summary", {}),
            "lead_count": len(summaries),
            "created_at": datetime.utcnow(),
            "tokens_used": result.get("usage", {}),
            "model": result.get("model", DEFAULT_MODEL)
        }
        
        categorization_runs_collection.insert_one(run_doc)
        
        # Update individual leads with their categories
        for lead_cat in parsed.get("categorized_leads", []):
            email_leads_collection.update_one(
                {"email": lead_cat.get("contact_email")},
                {
                    "$set": {
                        "ai_category_id": lead_cat.get("category_id"),
                        "ai_category_confidence": lead_cat.get("confidence"),
                        "ai_category_reasoning": lead_cat.get("reasoning"),
                        "categorized_at": datetime.utcnow(),
                        "categorization_batch_id": batch_id
                    }
                }
            )
        
        # Store categories for future reference
        for category in parsed.get("categories", []):
            ai_categories_collection.update_one(
                {"id": category.get("id")},
                {"$set": {**category, "batch_id": batch_id, "updated_at": datetime.utcnow()}},
                upsert=True
            )
        
        return {
            "success": True,
            "batch_id": batch_id,
            **parsed
        }
        
    except Exception as e:
        logger.error(f"Agent 2 error for batch {batch_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "batch_id": batch_id
        }


def _agent2_categorize_large_batch(
    summaries: List[Dict[str, Any]],
    batch_id: str,
    source: str = "background"
) -> Dict[str, Any]:
    """
    Handle large batches by chunking and merging results.
    """
    import time
    
    CHUNK_SIZE = 100
    chunks = [summaries[i:i + CHUNK_SIZE] for i in range(0, len(summaries), CHUNK_SIZE)]
    
    logger.info(f"Processing large batch of {len(summaries)} summaries in {len(chunks)} chunks")
    
    all_categories = {}
    all_categorized_leads = []
    
    for i, chunk in enumerate(chunks):
        chunk_id = f"{batch_id}_chunk{i+1}"
        
        result = agent2_categorize_batch(
            summaries=chunk,
            batch_id=chunk_id,
            source=source
        )
        
        if result.get("success"):
            # Merge categories (deduplicate by ID)
            for cat in result.get("categories", []):
                cat_id = cat.get("id")
                if cat_id not in all_categories:
                    all_categories[cat_id] = cat
            
            # Collect all categorized leads
            all_categorized_leads.extend(result.get("categorized_leads", []))
        
        # Rate limiting between chunks
        if i < len(chunks) - 1:
            time.sleep(5.0)
        
        logger.info(f"Completed chunk {i+1}/{len(chunks)}")
    
    # Build final result
    category_distribution = {}
    for lead in all_categorized_leads:
        cat_id = lead.get("category_id", "unknown")
        category_distribution[cat_id] = category_distribution.get(cat_id, 0) + 1
    
    # Store merged categorization run
    merged_run = {
        "batch_id": batch_id,
        "categories": list(all_categories.values()),
        "categorized_leads": all_categorized_leads,
        "summary": {
            "total_leads": len(summaries),
            "category_distribution": category_distribution,
            "insights": f"Large batch processed in {len(chunks)} chunks"
        },
        "lead_count": len(summaries),
        "chunks_processed": len(chunks),
        "created_at": datetime.utcnow()
    }
    
    categorization_runs_collection.insert_one(merged_run)
    
    return {
        "success": True,
        "batch_id": batch_id,
        "categories": list(all_categories.values()),
        "categorized_leads": all_categorized_leads,
        "summary": merged_run["summary"]
    }


def get_uncategorized_leads(limit: int = 500) -> List[Dict[str, Any]]:
    """Get leads that have AI summaries but haven't been categorized yet"""
    # Find leads with summaries but no category
    leads = list(email_leads_collection.find(
        {
            "conversation_summary": {"$exists": True, "$ne": ""},
            "$or": [
                {"ai_category_id": {"$exists": False}},
                {"ai_category_id": None}
            ]
        },
        {"email": 1, "conversation_summary": 1, "email_segment": 1, "company_domain": 1}
    ).limit(limit))
    
    # Get full summaries from ai_summaries_collection
    summaries = []
    for lead in leads:
        summary_doc = ai_summaries_collection.find_one({"contact_email": lead.get("email")})
        if summary_doc:
            summaries.append(summary_doc)
        else:
            # Use basic info if no full summary exists
            summaries.append({
                "contact_email": lead.get("email"),
                "summary": lead.get("conversation_summary", ""),
                "intent": lead.get("email_segment", "other"),
                "conversation_status": "unknown",
                "urgency": "medium",
                "contact": {"company_domain": lead.get("company_domain", "")}
            })
    
    return summaries


def run_batch_categorization(limit: int = 500) -> Dict[str, Any]:
    """
    Run Agent 2 categorization on uncategorized leads.
    
    Args:
        limit: Maximum number of leads to categorize
        
    Returns:
        Categorization results
    """
    # Get uncategorized leads
    summaries = get_uncategorized_leads(limit)
    
    if not summaries:
        return {
            "success": True,
            "message": "No uncategorized leads found",
            "categorized": 0
        }
    
    logger.info(f"Running batch categorization on {len(summaries)} leads")
    
    result = agent2_categorize_batch(summaries)
    
    if result.get("success"):
        categorized_count = len(result.get("categorized_leads", []))
        logger.info(f"Successfully categorized {categorized_count} leads into {len(result.get('categories', []))} categories")
    
    return result


def get_category_statistics() -> Dict[str, Any]:
    """Get statistics about lead categories"""
    pipeline = [
        {"$match": {"ai_category_id": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$ai_category_id", "count": {"$sum": 1}}}
    ]
    
    category_counts = list(email_leads_collection.aggregate(pipeline))
    
    # Get category details
    categories = list(ai_categories_collection.find({}))
    category_map = {c["id"]: c for c in categories}
    
    stats = []
    for cc in category_counts:
        cat_id = cc["_id"]
        cat_info = category_map.get(cat_id, {"name": cat_id, "description": ""})
        stats.append({
            "id": cat_id,
            "name": cat_info.get("name", cat_id),
            "description": cat_info.get("description", ""),
            "priority": cat_info.get("priority", "medium"),
            "count": cc["count"]
        })
    
    # Sort by count descending
    stats.sort(key=lambda x: x["count"], reverse=True)
    
    total_categorized = sum(s["count"] for s in stats)
    total_leads = email_leads_collection.count_documents({})
    
    return {
        "categories": stats,
        "total_categorized": total_categorized,
        "total_leads": total_leads,
        "categorization_rate": round(total_categorized / total_leads * 100, 2) if total_leads > 0 else 0
    }


# ============================================================================
# COMBINED PIPELINE
# ============================================================================

def process_new_emails_pipeline(
    emails_by_contact: Dict[str, List[Dict[str, Any]]],
    run_categorization: bool = True,
    categorization_threshold: int = 50
) -> Dict[str, Any]:
    """
    Full pipeline: Agent 1 for summaries, then Agent 2 for categorization.
    
    Args:
        emails_by_contact: Dict mapping contact_email -> list of emails
        run_categorization: Whether to run Agent 2 after Agent 1
        categorization_threshold: Run Agent 2 only if this many new summaries created
        
    Returns:
        Pipeline results
    """
    pipeline_results = {
        "agent1_results": [],
        "agent2_result": None,
        "total_processed": 0,
        "new_summaries": 0,
        "categorized": 0
    }
    
    # Step 1: Run Agent 1 on all leads
    leads_to_process = [
        {"contact_email": email, "emails": email_list}
        for email, email_list in emails_by_contact.items()
    ]
    
    if leads_to_process:
        logger.info(f"Running Agent 1 on {len(leads_to_process)} leads")
        agent1_results = agent1_batch_process(leads_to_process)
        pipeline_results["agent1_results"] = agent1_results
        pipeline_results["total_processed"] = len(agent1_results)
        pipeline_results["new_summaries"] = sum(1 for r in agent1_results if r.get("success"))
    
    # Step 2: Run Agent 2 if enough new summaries
    if run_categorization and pipeline_results["new_summaries"] >= categorization_threshold:
        logger.info(f"Running Agent 2 categorization on {pipeline_results['new_summaries']} summaries")
        
        # Get fresh summaries for categorization
        summaries = get_uncategorized_leads(500)
        
        if summaries:
            agent2_result = agent2_categorize_batch(summaries)
            pipeline_results["agent2_result"] = agent2_result
            pipeline_results["categorized"] = len(agent2_result.get("categorized_leads", []))
    
    return pipeline_results


# ============================================================================
# STATUS & UTILITY FUNCTIONS
# ============================================================================

def get_agents_status() -> Dict[str, Any]:
    """Get status of both AI agents"""
    gemini_status = get_gemini_status()
    
    # Count summaries and categories
    total_summaries = ai_summaries_collection.count_documents({})
    total_categories = ai_categories_collection.count_documents({})
    total_categorized = email_leads_collection.count_documents({"ai_category_id": {"$exists": True, "$ne": None}})
    
    return {
        "gemini_status": gemini_status,
        "agent1": {
            "name": "Email Summary & Contact Extraction",
            "total_summaries_generated": total_summaries,
            "description": "Processes email threads to create 500-word summaries and extract contact info"
        },
        "agent2": {
            "name": "Bulk Categorization",
            "total_categories": total_categories,
            "total_leads_categorized": total_categorized,
            "description": "Categorizes batches of leads into AI-determined categories"
        }
    }
