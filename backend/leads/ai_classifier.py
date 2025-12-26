"""
AGENT 3 — AI CLASSIFICATION ENGINE
ChatGPT API integration with strict JSON schema enforcement
"""

import os
import json
import time
import hashlib
from datetime import datetime
from typing import Optional, Tuple
from openai import OpenAI
from pymongo import MongoClient
from dotenv import load_dotenv

from .models import (
    LeadRaw, AIClassificationOutput, AIClassificationLog,
    SeniorityLevel, Department, Persona, CompanySize, Region
)

load_dotenv()


# ============== CONFIGURATION ==============

MODEL = "gpt-4o-mini"
TEMPERATURE = 0.1  # Low temperature for deterministic output
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Cost per 1K tokens (approximate for gpt-4o-mini)
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006


def get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from database settings first, fallback to env var.
    """
    try:
        MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        settings_db = client["torpedo_settings"]
        app_settings = settings_db["app_settings"]
        
        stored = app_settings.find_one({"_id": "app_config"})
        if stored and stored.get("openai_api_key"):
            return stored["openai_api_key"]
    except Exception as e:
        print(f"Warning: Could not fetch OpenAI key from DB: {e}")
    
    # Fallback to environment variable
    return os.getenv("OPENAI_API_KEY")


# ============== PROMPT TEMPLATE ==============

SYSTEM_PROMPT = """You are a B2B lead classification expert. Your task is to analyze LinkedIn profile information and classify leads into structured categories.

You MUST respond with valid JSON only. No explanations, no markdown, just pure JSON.

Output Schema (STRICT - follow exactly):
{
  "seniority_level": "C-Level" | "VP" | "Director" | "Manager" | "IC" | "Unknown",
  "department": "Sales" | "Marketing" | "Engineering" | "Operations" | "Finance" | "HR" | "Product" | "Other",
  "persona": "Decision Maker" | "Influencer" | "Gatekeeper" | "Practitioner",
  "company_size": "Startup" | "SMB" | "Mid-Market" | "Enterprise",
  "industry": "<string - specific industry name>",
  "region": "US" | "EU" | "APAC" | "LATAM" | "Other",
  "confidence_score": <float between 0.0 and 1.0>
}

Classification Rules:
- C-Level: CEO, CTO, CFO, COO, CMO, CRO, Chief titles
- VP: Vice President, SVP, EVP titles
- Director: Director, Head of titles
- Manager: Manager, Team Lead titles
- IC: Individual Contributor, Analyst, Specialist, Engineer (non-lead)

- Decision Maker: C-Level, VP with budget authority
- Influencer: Directors, Senior Managers who influence decisions
- Gatekeeper: Managers, Coordinators who control access
- Practitioner: ICs, hands-on workers

- Confidence score: How certain you are about the classification (0.0-1.0)
  - 0.9+: Very clear title and context
  - 0.7-0.9: Clear title, some inference needed
  - 0.5-0.7: Moderate inference required
  - <0.5: Significant guessing involved"""


USER_PROMPT_TEMPLATE = """Classify this LinkedIn lead:

Name: {name}
Title: {title}
LinkedIn URL: {linkedin_url}
Additional Context: {snippet}

Respond with JSON only."""


# ============== CLASSIFICATION CACHE ==============

_classification_cache = {}


def get_cache_key(lead: LeadRaw) -> str:
    """Generate cache key based on title (main classification factor)"""
    content = f"{lead.title.lower().strip()}"
    return hashlib.md5(content.encode()).hexdigest()


def get_cached_classification(lead: LeadRaw) -> Optional[AIClassificationOutput]:
    """Check if we have a cached classification for similar lead"""
    key = get_cache_key(lead)
    if key in _classification_cache:
        cached = _classification_cache[key]
        # Return cached result (copy with updated confidence to reflect it's cached)
        return cached
    return None


def cache_classification(lead: LeadRaw, result: AIClassificationOutput):
    """Cache classification result"""
    key = get_cache_key(lead)
    _classification_cache[key] = result


# ============== OPENAI CLIENT ==============

def get_openai_client() -> OpenAI:
    api_key = get_openai_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in settings or environment")
    return OpenAI(api_key=api_key)


# ============== CLASSIFICATION FUNCTION ==============

def classify_lead(lead: LeadRaw) -> Tuple[Optional[AIClassificationOutput], AIClassificationLog]:
    """
    Classify a single lead using ChatGPT.
    Returns: (classification_result, classification_log)
    """
    start_time = time.time()
    
    # Check cache first
    cached = get_cached_classification(lead)
    if cached:
        log = AIClassificationLog(
            raw_lead_id=str(lead.linkedin_url),
            linkedin_url=lead.linkedin_url,
            prompt_used="[CACHED]",
            model_used="cache",
            raw_response=cached.model_dump_json(),
            parsed_output=cached.model_dump(),
            success=True,
            confidence_score=cached.confidence_score,
            tokens_used=0,
            latency_ms=0,
            cost_usd=0.0
        )
        return cached, log
    
    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        name=lead.name,
        title=lead.title,
        linkedin_url=lead.linkedin_url,
        snippet=lead.snippet
    )
    
    # Initialize log
    log = AIClassificationLog(
        raw_lead_id=str(lead.linkedin_url),
        linkedin_url=lead.linkedin_url,
        prompt_used=user_prompt,
        model_used=MODEL,
        temperature=TEMPERATURE,
        success=False
    )
    
    try:
        client = get_openai_client()
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        # Calculate metrics
        latency_ms = int((time.time() - start_time) * 1000)
        tokens_used = response.usage.total_tokens if response.usage else 0
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cost_usd = (input_tokens / 1000 * INPUT_COST_PER_1K) + (output_tokens / 1000 * OUTPUT_COST_PER_1K)
        
        # Parse response
        raw_content = response.choices[0].message.content
        log.raw_response = raw_content
        log.tokens_used = tokens_used
        log.latency_ms = latency_ms
        log.cost_usd = cost_usd
        
        # Parse and validate JSON
        parsed = json.loads(raw_content)
        
        # Validate and create output
        result = AIClassificationOutput(
            seniority_level=SeniorityLevel(parsed.get("seniority_level", "Unknown")),
            department=Department(parsed.get("department", "Other")),
            persona=Persona(parsed.get("persona", "Practitioner")),
            company_size=CompanySize(parsed.get("company_size", "SMB")),
            industry=parsed.get("industry", "Other"),
            region=Region(parsed.get("region", "Other")),
            confidence_score=float(parsed.get("confidence_score", 0.5))
        )
        
        log.parsed_output = result.model_dump()
        log.success = True
        log.confidence_score = result.confidence_score
        
        # Cache the result
        cache_classification(lead, result)
        
        return result, log
        
    except json.JSONDecodeError as e:
        log.error_message = f"JSON parse error: {str(e)}"
        return None, log
        
    except ValueError as e:
        log.error_message = f"Validation error: {str(e)}"
        return None, log
        
    except Exception as e:
        log.error_message = f"API error: {str(e)}"
        log.latency_ms = int((time.time() - start_time) * 1000)
        return None, log


# ============== BATCH CLASSIFICATION ==============

async def classify_leads_batch(leads: list[LeadRaw], batch_size: int = 5) -> list[Tuple[LeadRaw, Optional[AIClassificationOutput], AIClassificationLog]]:
    """
    Classify multiple leads with rate limiting and batching.
    """
    results = []
    
    for i, lead in enumerate(leads):
        result, log = classify_lead(lead)
        results.append((lead, result, log))
        
        # Rate limiting: pause every batch_size requests
        if (i + 1) % batch_size == 0 and i < len(leads) - 1:
            time.sleep(1.0)  # 1 second pause between batches
    
    return results
