"""
Lead Enrichment Module
Provides intelligent lead classification, enrichment, and email processing using OpenAI
"""

import os
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import openai
from .openai_rotator import get_rotator

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


def classify_lead(lead_data: dict, rotator=None) -> dict:
    """
    Classify a lead into categories using Gemini
    
    Args:
        lead_data: Dictionary containing lead information (email, company, title, etc.)
        rotator: Optional GeminiRotator instance (will create if not provided)
        
    Returns:
        {
            "category": str,  # CLIENT, VENDOR, RECRUITER, INTERNAL, SPAM
            "confidence": float,  # 0.0 to 1.0
            "department": str,  # Sales, Marketing, Engineering, HR, etc.
            "seniority": str,  # C-Level, VP, Director, Manager, IC, Entry
            "reasoning": str,  # Why this classification
            "buying_intent": float,  # 0.0 to 1.0
            "priority": str  # HIGH, MEDIUM, LOW
        }
    """
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


def extract_contact_info(email_body: str, rotator=None) -> dict:
    """
    Extract structured contact information from email body
    
    Args:
        email_body: Raw email text
        rotator: Optional GeminiRotator instance
        
    Returns:
        {
            "contacts": [
                {
                    "name": str,
                    "title": str,
                    "email": str,
                    "phone": str,
                    "company": str
                }
            ],
            "primary_contact": {...},  # Most relevant contact
            "signature_extracted": bool
        }
    """
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
