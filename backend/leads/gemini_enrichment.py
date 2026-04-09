"""
Lead Enrichment Module
Provides intelligent lead classification, enrichment, and email processing using OpenAI
"""

import os
import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import openai
from .openai_rotator import get_rotator

logger = logging.getLogger(__name__)

# Constants
MODEL_NAME = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.7
CLASSIFY_TEMPERATURE = 0.3  # Lower for consistent classification
EXTRACT_TEMPERATURE = 0.5  # Medium for structured extraction

# Token estimation (rough)
TOKENS_PER_CHAR = 0.25


def estimate_tokens(text: str) -> int:
    """Estimate token count for text"""
    return int(len(text) * TOKENS_PER_CHAR)


def _classify_lead_rule_based(lead_data: dict) -> dict:
    """
    Rule-based lead classification using keywords and patterns — NO AI.
    """
    title = (lead_data.get("title") or "").lower()
    email_addr = (lead_data.get("email") or "").lower()
    subject = (lead_data.get("email_subject") or "").lower()
    body = (lead_data.get("email_body") or "")[:2000].lower()
    company = (lead_data.get("company") or "").lower()
    content = f"{subject} {body}"
    
    # Seniority from title
    seniority = "Unknown"
    seniority_tiers = {
        "C-Level": ["ceo", "cto", "cfo", "coo", "cmo", "cro", "chief", "founder", "co-founder"],
        "VP": ["vp", "vice president", "evp", "svp"],
        "Director": ["director", "head of"],
        "Manager": ["manager", "lead", "senior manager"],
        "IC": ["analyst", "specialist", "coordinator", "associate", "engineer", "developer"],
        "Entry": ["intern", "trainee", "assistant", "junior"],
    }
    for level, keywords in seniority_tiers.items():
        if any(kw in title for kw in keywords):
            seniority = level
            break
    
    # Department from title
    department = "Other"
    dept_map = {
        "Sales": ["sales", "business development", "account executive", "revenue"],
        "Marketing": ["marketing", "growth", "brand", "content", "seo"],
        "Engineering": ["engineering", "developer", "software", "devops", "tech lead"],
        "HR": ["hr", "human resources", "people", "talent", "recruiting"],
        "Finance": ["finance", "accounting", "controller"],
        "Operations": ["operations", "ops", "supply chain"],
        "Product": ["product", "ux", "design"],
        "Legal": ["legal", "counsel", "compliance"],
    }
    for dept, keywords in dept_map.items():
        if any(kw in title for kw in keywords):
            department = dept
            break
    
    # Category detection
    category = "CLIENT"  # Default assumption
    confidence = 0.4
    reasoning = "Default classification"
    buying_intent = 0.3
    
    # VENDOR indicators (someone offering services TO us)
    vendor_keywords = [
        "we offer", "our services", "our solution", "our platform",
        "i'd like to introduce", "reaching out on behalf of", "partnership",
        "schedule a demo", "free trial", "special offer", "our company",
    ]
    vendor_score = sum(1 for kw in vendor_keywords if kw in content)
    
    # CLIENT indicators (someone interested in OUR services)
    client_keywords = [
        "interested in", "looking for", "need help", "rfp", "rfq",
        "quote", "pricing", "how much", "do you offer", "can you",
        "we need", "project", "requirement", "budget",
    ]
    client_score = sum(1 for kw in client_keywords if kw in content)
    
    # RECRUITER indicators
    recruiter_keywords = [
        "job opportunity", "open position", "hiring", "career",
        "recruitment", "candidate", "resume", "cv", "talent acquisition",
    ]
    recruiter_score = sum(1 for kw in recruiter_keywords if kw in content)
    
    # SPAM indicators
    spam_keywords = [
        "unsubscribe", "click here", "act now", "free", "winner",
        "congratulations", "limited time", "million dollars",
    ]
    spam_score = sum(1 for kw in spam_keywords if kw in content)
    
    # Pick highest
    scores = {
        "CLIENT": client_score,
        "VENDOR": vendor_score,
        "RECRUITER": recruiter_score,
        "SPAM": spam_score,
    }
    top = max(scores, key=scores.get)
    top_score = scores[top]
    
    if top_score >= 3:
        category = top
        confidence = min(0.9, 0.5 + top_score * 0.1)
        reasoning = f"Keyword match: {top_score} indicators for {top}"
    elif top_score >= 1:
        category = top
        confidence = 0.4 + top_score * 0.1
        reasoning = f"Weak keyword match: {top_score} indicators for {top}"
    else:
        # No strong signals in content — use title/email heuristics
        if seniority in ["C-Level", "VP", "Director"]:
            buying_intent = 0.5
            category = "CLIENT"
            confidence = 0.5
            reasoning = "Senior title, assumed potential client"
        else:
            category = "CLIENT"
            confidence = 0.35
            reasoning = "No strong signals, default to CLIENT"
    
    # Buying intent based on seniority + category
    if category == "CLIENT":
        intent_map = {"C-Level": 0.8, "VP": 0.7, "Director": 0.6, "Manager": 0.5, "IC": 0.3}
        buying_intent = intent_map.get(seniority, 0.3)
        if client_score >= 3:
            buying_intent = min(1.0, buying_intent + 0.2)
    else:
        buying_intent = 0.1
    
    # Priority
    if buying_intent >= 0.7:
        priority = "HIGH"
    elif buying_intent >= 0.4:
        priority = "MEDIUM"
    else:
        priority = "LOW"
    
    return {
        "category": category,
        "confidence": round(confidence, 2),
        "department": department,
        "seniority": seniority,
        "reasoning": reasoning,
        "buying_intent": round(buying_intent, 2),
        "priority": priority,
        "method": "rule_based",
    }


def classify_lead(lead_data: dict, rotator=None) -> dict:
    """
    Classify a lead into categories using Gemini.
    
    HYBRID: Tries rule-based classification first. Falls back to AI if confidence < 0.7.
    
    Args:
        lead_data: Dictionary containing lead information (email, company, title, etc.)
        rotator: Optional GeminiRotator instance (will create if not provided)
        
    Returns:
        {
            "category": str,  # CLIENT, VENDOR, RECRUITER, INTERNAL, SPAM
            "confidence": float,  # 0.0 to 1.0
            "department": str,
            "seniority": str,
            "reasoning": str,
            "buying_intent": float,
            "priority": str
        }
    """
    # Try rule-based classification first
    rule_result = _classify_lead_rule_based(lead_data)
    if rule_result["confidence"] >= 0.7:
        logger.info(f"Rule-based lead classification: {rule_result['category']} (confidence={rule_result['confidence']})")
        return rule_result
    
    logger.info(f"Rule-based low confidence ({rule_result['confidence']}), falling back to AI")
    if rotator is None:
        rotator = get_rotator()
    
    # Get available key
    key_index, api_key = rotator.get_available_key()
    
    # Build context from lead_data
    context = []
    if lead_data.get("email"):
        context.append(f"Email: {lead_data['email']}")
    if lead_data.get("full_name"):
        context.append(f"Name: {lead_data['full_name']}")
    if lead_data.get("title"):
        context.append(f"Title: {lead_data['title']}")
    if lead_data.get("company"):
        context.append(f"Company: {lead_data['company']}")
    if lead_data.get("email_subject"):
        context.append(f"Email Subject: {lead_data['email_subject']}")
    if lead_data.get("email_body"):
        # Truncate long email bodies
        body = lead_data['email_body'][:2000]
        context.append(f"Email Body: {body}")
    
    context_text = "\n".join(context)
    
    prompt = f"""Analyze this lead and classify it into appropriate categories.

LEAD INFORMATION:
{context_text}

Provide classification in this JSON format:
{{
  "category": "<CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM>",
  "confidence": <0.0 to 1.0>,
  "department": "<Sales|Marketing|Engineering|HR|Finance|Operations|Legal|Other>",
  "seniority": "<C-Level|VP|Director|Manager|IC|Entry|Unknown>",
  "reasoning": "<brief explanation>",
  "buying_intent": <0.0 to 1.0>,
  "priority": "<HIGH|MEDIUM|LOW>"
}}

Classification Guidelines:
- CLIENT: Potential customer, shows buying intent or interest in services
- VENDOR: Offering services/products to us
- RECRUITER: Job opportunities, recruitment outreach
- INTERNAL: Company communications, team emails
- SPAM: Unsolicited marketing, low-value content

Confidence: How certain are you of the category?
Buying Intent: Likelihood they want to purchase (0=no intent, 1=ready to buy)
Priority: Based on role seniority, buying intent, and urgency
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=CLASSIFY_TEMPERATURE,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="classify",
            success=True,
            metadata={
                "category": result.get("category"),
                "confidence": result.get("confidence"),
                "priority": result.get("priority")
            }
        )
        
        return result
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="classify",
            success=False,
            error=str(e)
        )
        
        return {
            "category": "UNKNOWN",
            "confidence": 0.0,
            "department": "Unknown",
            "seniority": "Unknown",
            "reasoning": f"Error during classification: {str(e)}",
            "buying_intent": 0.5,
            "priority": "MEDIUM"
        }


def enrich_lead(lead_data: dict, rotator=None) -> dict:
    """
    Enrich lead with additional inferred details
    
    Args:
        lead_data: Dictionary with partial lead information
        rotator: Optional GeminiRotator instance
        
    Returns:
        {
            "title_variations": List[str],  # Alternative job titles
            "inferred_skills": List[str],  # Likely skills based on title
            "industry_vertical": str,  # Industry classification
            "company_size_estimate": str,  # Startup, SMB, Enterprise
            "likely_pain_points": List[str],  # Business challenges
            "engagement_angle": str  # How to approach this lead
        }
    """
    if rotator is None:
        rotator = get_rotator()
    
    key_index, api_key = rotator.get_available_key()
    
    # Build context
    context = []
    if lead_data.get("title"):
        context.append(f"Title: {lead_data['title']}")
    if lead_data.get("company"):
        context.append(f"Company: {lead_data['company']}")
    if lead_data.get("linkedin_url"):
        context.append(f"LinkedIn: {lead_data['linkedin_url']}")
    if lead_data.get("company_website"):
        context.append(f"Website: {lead_data['company_website']}")
    
    context_text = "\n".join(context)
    
    prompt = f"""Enrich this lead with additional inferred details.

LEAD INFORMATION:
{context_text}

Provide enrichment in JSON format:
{{
  "title_variations": ["<alternative title 1>", "<alternative title 2>"],
  "inferred_skills": ["<skill 1>", "<skill 2>", "<skill 3>"],
  "industry_vertical": "<industry name>",
  "company_size_estimate": "<Startup|SMB|Mid-Market|Enterprise>",
  "likely_pain_points": ["<pain point 1>", "<pain point 2>"],
  "engagement_angle": "<how to approach this lead>"
}}

Be specific and actionable. Base inferences on typical patterns for this role/company type.
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=700,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="enrich",
            success=True,
            metadata={"industry": result.get("industry_vertical")}
        )
        
        return result
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="enrich",
            success=False,
            error=str(e)
        )
        
        return {
            "title_variations": [],
            "inferred_skills": [],
            "industry_vertical": "Unknown",
            "company_size_estimate": "Unknown",
            "likely_pain_points": [],
            "engagement_angle": "Research required"
        }


def extract_contact_info(email_body: str, from_email: str = "", from_name: str = "", rotator=None) -> dict:
    """
    Extract structured contact information from email body.
    
    HYBRID: Tries regex first. Falls back to AI only if regex extraction is poor.
    
    Args:
        email_body: Raw email text
        from_email: Sender email address (from header)
        from_name: Sender display name (from header)
        rotator: Optional GeminiRotator instance
        
    Returns:
        {
            "contacts": [{name, title, email, phone, company}],
            "primary_contact": {...},
            "signature_extracted": bool
        }
    """
    # Try regex extraction first
    try:
        from .imap_leads_service import extract_contact_info_regex
        regex_result = extract_contact_info_regex(email_body, from_email, from_name)
        
        primary = regex_result.get("primary_contact", {})
        has_name = bool(primary.get("name"))
        has_phone = bool(primary.get("phone"))
        has_company = bool(primary.get("company"))
        has_linkedin = bool(primary.get("linkedin"))
        
        # If regex got enough data, skip AI
        fields_found = sum([has_name, has_phone, has_company, has_linkedin])
        if fields_found >= 2:
            logger.info(f"Regex extraction sufficient ({fields_found} fields), skipping AI")
            return regex_result
        
        logger.info(f"Regex extraction found {fields_found} fields, falling back to AI")
    except Exception as e:
        logger.warning(f"Regex extraction failed: {e}, falling back to AI")
    if rotator is None:
        rotator = get_rotator()
    
    key_index, api_key = rotator.get_available_key()
    
    # Truncate very long emails
    email_body = email_body[:5000]
    
    prompt = f"""Extract all contact information from this email.

EMAIL:
{email_body}

Provide extracted contacts in JSON format:
{{
  "contacts": [
    {{
      "name": "<full name>",
      "title": "<job title>",
      "email": "<email address>",
      "phone": "<phone number>",
      "company": "<company name>"
    }}
  ],
  "primary_contact": {{...}},
  "signature_extracted": true/false
}}

Extract from:
- Email signature
- Body content
- CC/BCC mentions
- Contact cards

Mark primary_contact as the most senior or relevant person.
Leave fields empty if not found.
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=EXTRACT_TEMPERATURE,
            max_tokens=1000,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="extract",
            success=True,
            metadata={"contacts_found": len(result.get("contacts", []))}
        )
        
        return result
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="extract",
            success=False,
            error=str(e)
        )
        
        return {
            "contacts": [],
            "primary_contact": None,
            "signature_extracted": False
        }


def summarize_email(email_body: str, subject: str = None, rotator=None) -> dict:
    """
    Generate intelligent summary of email content
    
    Args:
        email_body: Email content
        subject: Optional email subject line
        rotator: Optional GeminiRotator instance
        
    Returns:
        {
            "summary": str,  # 2-3 sentence overview
            "key_points": List[str],  # Bullet points of main items
            "action_items": List[str],  # Required actions
            "sentiment": str,  # POSITIVE, NEUTRAL, NEGATIVE
            "urgency": str,  # HIGH, MEDIUM, LOW
            "contains_offer": bool,  # Is there a business offer?
            "next_steps": str  # Recommended response/action
        }
    """
    if rotator is None:
        rotator = get_rotator()
    
    key_index, api_key = rotator.get_available_key()
    
    email_body = email_body[:5000]
    
    subject_line = f"Subject: {subject}\n" if subject else ""
    
    prompt = f"""Summarize this email and extract key information.

{subject_line}EMAIL:
{email_body}

Provide analysis in JSON format:
{{
  "summary": "<2-3 sentence overview>",
  "key_points": ["<point 1>", "<point 2>"],
  "action_items": ["<action 1>", "<action 2>"],
  "sentiment": "<POSITIVE|NEUTRAL|NEGATIVE>",
  "urgency": "<HIGH|MEDIUM|LOW>",
  "contains_offer": true/false,
  "next_steps": "<recommended response>"
}}

Focus on business relevance and actionable insights.
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=800,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="summarize",
            success=True,
            metadata={
                "sentiment": result.get("sentiment"),
                "urgency": result.get("urgency")
            }
        )
        
        return result
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="summarize",
            success=False,
            error=str(e)
        )
        
        return {
            "summary": "Unable to summarize",
            "key_points": [],
            "action_items": [],
            "sentiment": "NEUTRAL",
            "urgency": "MEDIUM",
            "contains_offer": False,
            "next_steps": "Review manually"
        }


def segment_email(subject: str, body: str, sender_email: str = None, rotator=None) -> dict:
    """
    Segment email into type (CLIENT, VENDOR, INTERNAL, SPAM)
    Faster than full classify_lead - just categorization
    
    Args:
        subject: Email subject line
        body: Email body (can be truncated)
        sender_email: Sender email address
        rotator: Optional GeminiRotator instance
        
    Returns:
        {
            "segment": str,  # CLIENT, VENDOR, RECRUITER, INTERNAL, SPAM
            "confidence": float,
            "reasoning": str
        }
    """
    if rotator is None:
        rotator = get_rotator()
    
    key_index, api_key = rotator.get_available_key()
    
    body = body[:1500]  # Shorter for quick segmentation
    
    sender_line = f"From: {sender_email}\n" if sender_email else ""
    
    prompt = f"""Quickly segment this email into the most appropriate category.

{sender_line}Subject: {subject}
Body: {body}

Provide segmentation in JSON format:
{{
  "segment": "<CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence explanation>"
}}

Definitions:
- CLIENT: Potential customer, inquiry about services, business opportunity
- VENDOR: Offering products/services to us, partnership proposals
- RECRUITER: Job opportunities, hiring outreach
- INTERNAL: Company communications, team updates
- SPAM: Unsolicited marketing, irrelevant content, mass emails
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=CLASSIFY_TEMPERATURE,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="segment",
            success=True,
            metadata={"segment": result.get("segment")}
        )
        
        return result
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="segment",
            success=False,
            error=str(e)
        )
        
        return {
            "segment": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"Error: {str(e)}"
        }


def batch_categorize(leads: List[dict], rotator=None) -> List[dict]:
    """
    Categorize multiple leads in a single batch (more efficient for large volumes)
    
    Args:
        leads: List of lead dictionaries (each with email, name, title, company)
        rotator: Optional GeminiRotator instance
        
    Returns:
        List of dictionaries with categorization results
    """
    if rotator is None:
        rotator = get_rotator()
    
    key_index, api_key = rotator.get_available_key()
    
    # Build batch input
    lead_entries = []
    for i, lead in enumerate(leads[:50]):  # Max 50 per batch
        entry = f"""
Lead {i+1}:
- Email: {lead.get('email', 'N/A')}
- Name: {lead.get('full_name', 'N/A')}
- Title: {lead.get('title', 'N/A')}
- Company: {lead.get('company', 'N/A')}
"""
        lead_entries.append(entry)
    
    batch_text = "\n".join(lead_entries)
    
    prompt = f"""Categorize these leads into segments.

LEADS:
{batch_text}

Provide categorization for each lead in JSON format:
{{
  "results": [
    {{
      "lead_index": 1,
      "segment": "<CLIENT|VENDOR|RECRUITER|INTERNAL|SPAM>",
      "confidence": <0.0 to 1.0>,
      "priority": "<HIGH|MEDIUM|LOW>"
    }}
  ]
}}

Focus on quick, accurate categorization.
"""
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=CLASSIFY_TEMPERATURE,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        tokens_used = response.usage.total_tokens if response.usage else estimate_tokens(prompt + text)
        
        rotator.log_request(
            key_index=key_index,
            tokens_used=tokens_used,
            task_type="batch",
            success=True,
            metadata={"batch_size": len(leads)}
        )
        
        return result.get("results", [])
        
    except Exception as e:
        rotator.log_request(
            key_index=key_index,
            tokens_used=estimate_tokens(prompt),
            task_type="batch",
            success=False,
            error=str(e)
        )
        
        # Return empty results on error
        return [
            {
                "lead_index": i+1,
                "segment": "UNKNOWN",
                "confidence": 0.0,
                "priority": "MEDIUM"
            }
            for i in range(len(leads))
        ]


if __name__ == "__main__":
    # Test the enrichment functions
    print("=== Lead Enrichment Test ===\n")
    
    # Sample lead data
    test_lead = {
        "email": "john.smith@techcorp.com",
        "full_name": "John Smith",
        "title": "VP of Engineering",
        "company": "TechCorp Inc",
        "email_subject": "Interested in your automation platform",
        "email_body": """Hi team,

I came across your campaign automation platform and I'm very interested in learning more. 
We're currently using a combination of tools but looking to consolidate.

Our team of 50 engineers is growing fast and we need better lead management.

Can we schedule a demo this week?

Best regards,
John Smith
VP of Engineering, TechCorp Inc
john.smith@techcorp.com
+1 (555) 123-4567
"""
    }
    
    try:
        rotator = get_rotator()
        
        print("1. Testing classify_lead():")
        classification = classify_lead(test_lead, rotator)
        print(f"   Category: {classification['category']}")
        print(f"   Confidence: {classification['confidence']}")
        print(f"   Priority: {classification['priority']}")
        print(f"   Buying Intent: {classification['buying_intent']}\n")
        
        print("2. Testing enrich_lead():")
        enrichment = enrich_lead(test_lead, rotator)
        print(f"   Industry: {enrichment['industry_vertical']}")
        print(f"   Company Size: {enrichment['company_size_estimate']}")
        print(f"   Title Variations: {', '.join(enrichment['title_variations'][:3])}\n")
        
        print("3. Testing extract_contact_info():")
        contacts = extract_contact_info(test_lead['email_body'], rotator)
        print(f"   Contacts Found: {len(contacts['contacts'])}")
        if contacts['primary_contact']:
            print(f"   Primary: {contacts['primary_contact'].get('name', 'N/A')}\n")
        
        print("4. Testing summarize_email():")
        summary = summarize_email(
            test_lead['email_body'],
            test_lead['email_subject'],
            rotator
        )
        print(f"   Summary: {summary['summary']}")
        print(f"   Sentiment: {summary['sentiment']}")
        print(f"   Urgency: {summary['urgency']}\n")
        
        print("5. Testing segment_email():")
        segment = segment_email(
            test_lead['email_subject'],
            test_lead['email_body'],
            test_lead['email'],
            rotator
        )
        print(f"   Segment: {segment['segment']}")
        print(f"   Confidence: {segment['confidence']}\n")
        
        print("✅ All tests completed!")
        
        # Show quota usage
        print("\n6. Quota Usage:")
        quota = rotator.check_quota()
        print(f"   Total requests: {quota['total_requests_today']}")
        print(f"   Total tokens: {quota['total_tokens_used']}")
        print(f"   Percentage used: {quota['percentage_used']}%")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
