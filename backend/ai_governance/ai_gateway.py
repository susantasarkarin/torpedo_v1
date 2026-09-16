"""
AI GATEWAY - Single Entry Point for All AI Operations (AWS Bedrock Mantle)
============================================================================
Task-specific LLM operations live here; generic generation and web search
live in claude_gateway.py. AWS Bedrock Mantle (OpenAI-compatible, serverless,
per-token billed) is the AI provider in this codebase.

Qwen-only policy: uses qwen.qwen3-32b-v1:0 for high-volume classification /
summarization / extraction tasks — the same model leads/bedrock_client.py
uses for its "cheap" role. No other model should be substituted here.

Constraints (MANDATORY):
- Hard limit: 50,000 requests per day (configurable safeguard)
- One classification per email (unique constraint)
- No automatic retries on failure
- No parallel processing for same email
- Event-driven, bounded, deterministic
"""

import os
import logging
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

import openai
from pymongo import MongoClient

# Load backend environment variables from the backend/.env file
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from .governance_checks import (
    check_ai_daily_limit,
    increment_ai_daily_usage,
    acquire_classification_lock,
    complete_classification,
    fail_classification,
    AIDailyLimitExceeded,
    EmailAlreadyClassified,
)

logger = logging.getLogger(__name__)


def _strip_markdown_json(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences from an LLM response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ============== CONFIGURATION ==============
#
# Primary provider is AWS Bedrock Mantle — a serverless, per-token-billed
# OpenAI-compatible endpoint that fronts open-weight models (GLM, DeepSeek,
# Kimi, etc). Billed through the AWS account already used for SES, no
# separate prepaid wallet. Auth is a Bedrock API key (bearer token).

BEDROCK_BASE_URL = os.getenv("BEDROCK_MANTLE_BASE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1")
# Qwen-only policy: same model, same env var, as leads/bedrock_client.py's
# "cheap" role — this module must never default to a different provider.
# The default model for gateway calls. Named ANTHROPIC_MODEL historically; it
# has held a BEDROCK model id for as long as it has had this value, and there
# is no Anthropic model in the path. Renamed; the old name is kept as an alias
# because other modules import it.
DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_CHEAP", "qwen.qwen3-32b-v1:0")
ANTHROPIC_MODEL = DEFAULT_MODEL  # deprecated alias

_mongo_client: Optional[MongoClient] = None


def _get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return _mongo_client


def _get_bedrock_bearer_token() -> str:
    """
    Bearer token for the OpenAI-compatible Bedrock gateway endpoint.

    Only used when AI_GATEWAY_USE_BEARER_TOKEN=true. The default path is boto3
    Converse (see _call_llm), which authenticates with the standard AWS
    credential chain and needs none of this.

    NOTE the trap this function used to spring: its last fallback is
    ANTHROPIC_API_KEY, so on a host with an Anthropic key but no Bedrock
    bearer token it returned an `sk-ant-...` key and presented it to an AWS
    endpoint, which answered 401 "Invalid bearer token". That is what broke
    lead classification for months.
    """
    try:
        client = _get_mongo_client()
        settings = client['torpedo_settings']['app_settings'].find_one({'_id': 'app_config'})
        if settings:
            key = settings.get('bedrock_api_key', '') or settings.get('anthropic_api_key', '')
            if key:
                return key
    except Exception as e:
        logger.warning(f"Could not read Bedrock key from MongoDB: {e}")
    env_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "") or os.getenv("ANTHROPIC_API_KEY", "")
    if env_key:
        return env_key
    raise ValueError("No Bedrock API key configured — save it in Settings or set AWS_BEARER_TOKEN_BEDROCK env var")


# Deprecated alias: the name says Anthropic, the value is a Bedrock token.
_get_anthropic_api_key = _get_bedrock_bearer_token


# ============== DATA CLASSES ==============

@dataclass
class ClassificationResult:
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


@dataclass
class LeadExtractionResult:
    email_id: str
    leads: List[Dict[str, Any]]
    extracted_at: str
    success: bool
    error: Optional[str] = None


# ============== AI GATEWAY ==============

class AIGateway:
    """
    SINGLE ENTRY POINT for all LLM operations.
    Backed by Anthropic Claude. Drop-in replacement for the old OpenAI/Gemini gateway.
    """

    def __init__(self):
        self._client: Optional[openai.OpenAI] = None

    def _get_client(self) -> openai.OpenAI:
        api_key = _get_bedrock_bearer_token()
        self._client = openai.OpenAI(api_key=api_key, base_url=BEDROCK_BASE_URL)
        return self._client

    def _call_llm(self, prompt: str, model: str = None, max_tokens: int = 1024,
                  temperature: float = 0.3, role: str = "cheap") -> str:
        """
        Internal method — one governed model call. Enforces the daily limit.

        Routed through leads.bedrock_client (boto3 `bedrock-runtime.Converse`),
        which is the path that actually authenticates on this deployment and
        the one the runbook designates as the only permitted Bedrock client.

        WHY THIS CHANGED (2026-09-01)
        -----------------------------
        This used to build an `openai.OpenAI` client pointed at
        BEDROCK_MANTLE_BASE_URL and authenticate with a bearer token resolved
        from settings/env. On production that token resolution fell through to
        ANTHROPIC_API_KEY — a genuine `sk-ant-...` Anthropic key — which was
        then presented to an AWS endpoint. AWS rejected it:

            401 invalid_api_key: "Invalid bearer token"

        Every gateway call failed, which is why lead classification had been
        writing classification_status="Failed" for months while mail
        segregation (which uses leads.bedrock_client directly) worked fine.
        The two paths were never the same "Bedrock".

        Using boto3 needs no new secret: AWS_ACCESS_KEY_ID/SECRET are already
        present and verified working against bedrock-runtime in ap-south-1.

        The bearer-token path is kept below as an explicit opt-in for anyone
        who does have a real AWS Bedrock API key (AWS_BEARER_TOKEN_BEDROCK).
        """
        if not check_ai_daily_limit():
            raise AIDailyLimitExceeded(
                "AI daily limit reached. No more calls allowed today."
            )
        increment_ai_daily_usage()

        if os.getenv("AI_GATEWAY_USE_BEARER_TOKEN", "false").lower() in ("1", "true", "yes"):
            try:
                client = self._get_client()
                response = client.chat.completions.create(
                    model=model or DEFAULT_MODEL,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Bedrock (bearer-token path) failed: {e}. NO AUTOMATIC RETRY.")
                raise

        try:
            from leads.bedrock_client import converse
        except ImportError:  # pragma: no cover
            from backend.leads.bedrock_client import converse
        try:
            # The gateway's callers put everything in one prompt; Converse wants
            # a system/user split, so the instruction goes in system and the
            # payload in user.
            return converse(
                role,
                "You are a precise assistant. Follow the user's instructions exactly.",
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            ).strip()
        except Exception as e:
            logger.error(f"Bedrock Converse call failed: {e}. NO AUTOMATIC RETRY.")
            raise

    def complete(self, prompt: str, model: str = None, max_tokens: int = 1024,
                 temperature: float = 0.3) -> str:
        """
        Generic governed completion — the public path for callers whose task
        does not match one of the typed methods below.

        This exists so "my use case isn't covered" stops being a reason to
        construct a client directly (TOR-22). Everything that goes through here
        is subject to the daily limit and lands in the usage counters; a
        directly-constructed client is invisible to both, which is why cost was
        unattributable and a model deprecation meant grepping the tree.
        """
        return self._call_llm(prompt, model=model, max_tokens=max_tokens,
                              temperature=temperature)

    # ------------------------------------------------------------------
    # classify_email
    # ------------------------------------------------------------------

    def classify_email(self, email_id: str, subject: str, body: str,
                       from_email: str, source: str = "api") -> ClassificationResult:
        acquire_classification_lock(email_id, source)
        try:
            prompt = self._build_classification_prompt(subject, body, from_email)
            response_text = self._call_llm(prompt)
            result = self._parse_classification_response(email_id, response_text)
            complete_classification(email_id, asdict(result))
            return result
        except (AIDailyLimitExceeded, EmailAlreadyClassified):
            raise
        except Exception as e:
            fail_classification(email_id, str(e))
            return ClassificationResult(
                email_id=email_id, category="error", confidence=0.0,
                summary="", intent="", priority="low", action_required=False,
                classified_at=datetime.utcnow().isoformat(), success=False,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # summarize_email
    # ------------------------------------------------------------------

    def summarize_email(self, email_id: str, subject: str, body: str,
                        max_length: int = 200) -> Dict[str, Any]:
        prompt = f"""Summarize this email concisely in {max_length} characters or less.

Subject: {subject}
Body: {body[:2000]}

Return JSON only:
{{"summary": "...", "key_points": ["...", "..."], "sentiment": "positive|neutral|negative"}}"""
        try:
            response_text = self._call_llm(prompt)
            parsed = json.loads(_strip_markdown_json(response_text))
            return {"email_id": email_id, "summary": parsed.get("summary", ""),
                    "key_points": parsed.get("key_points", []),
                    "sentiment": parsed.get("sentiment", "neutral"),
                    "summarized_at": datetime.utcnow().isoformat(), "success": True}
        except Exception as e:
            logger.error(f"Email summarization failed for {email_id}: {e}. NO RETRY.")
            return {"email_id": email_id, "summary": "", "error": str(e), "success": False}

    # ------------------------------------------------------------------
    # extract_leads_from_email
    # ------------------------------------------------------------------

    def extract_leads_from_email(self, email_id: str, subject: str, body: str,
                                 from_email: str) -> LeadExtractionResult:
        prompt = f"""Extract lead/contact information from this email.

From: {from_email}
Subject: {subject}
Body: {body[:3000]}

Return JSON only:
{{
  "leads": [
    {{
      "name": "Full Name",
      "email": "email@example.com",
      "phone": "+1234567890 or null",
      "company": "Company Name or null",
      "title": "Job Title or null",
      "source": "email_signature|body|footer"
    }}
  ]
}}

If no leads found, return {{"leads": []}}"""
        try:
            response_text = self._call_llm(prompt)
            parsed = json.loads(_strip_markdown_json(response_text))
            return LeadExtractionResult(
                email_id=email_id, leads=parsed.get("leads", []),
                extracted_at=datetime.utcnow().isoformat(), success=True)
        except Exception as e:
            logger.error(f"Lead extraction failed for {email_id}: {e}. NO RETRY.")
            return LeadExtractionResult(
                email_id=email_id, leads=[],
                extracted_at=datetime.utcnow().isoformat(), success=False, error=str(e))

    # ------------------------------------------------------------------
    # enrich_lead_data
    # ------------------------------------------------------------------

    def enrich_lead_data(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        prompt = f"""You are a B2B sales analyst and email research specialist. Analyse the company data below and return ONLY valid JSON.

Company data:
{json.dumps(context, indent=2)}

Return JSON with exactly these fields:
{{
  "role_match_score": <integer 0-100>,
  "company_size_bucket": "1-10" | "11-50" | "51-200" | "201-1000" | "1000+",
  "industry": "<primary industry string>",
  "seniority_hint": "<likely decision-maker title>",
  "top_pain_points": ["<pain point 1>", "<pain point 2>"],
  "personalisation_hook": "<one sentence specific to this company, no generic filler>",
  "email_address": "<most likely professional email for this contact at domain>",
  "email_confidence": <integer 0-100>
}}

Rules for email_address:
- Use ONLY the domain provided in company data — never invent a different domain
- Prefer firstname.lastname@domain, then firstname@domain, then f.lastname@domain
- Always return a syntactically valid email — never return null or empty string

No preamble. No markdown. Only JSON."""
        try:
            response_text = self._call_llm(prompt)
            clean = _strip_markdown_json(response_text)
            return json.loads(clean)
        except Exception as e:
            logger.error(f"Lead enrichment failed: {e}. NO RETRY.")
            return None

    # ------------------------------------------------------------------
    # generate_email_draft
    # ------------------------------------------------------------------

    def generate_email_draft(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, str]]:
        try:
            # Routed through _call_llm (bedrock_client.converse), same as every
            # other method below — this used to build its own openai.OpenAI
            # client pointed straight at BEDROCK_BASE_URL, which bypassed the
            # local:/self-hosted provider seam entirely. role="smart" since this
            # is human/client-facing content, matching mail_pool_ai's writer role.
            raw = self._call_llm(f"{system_prompt}\n\n{user_prompt}",
                                  max_tokens=600, temperature=0.7, role="smart")
            clean = _strip_markdown_json(raw)
            result = json.loads(clean)
            if "subject" in result and "body" in result:
                return result
            logger.error("Draft response missing 'subject' or 'body' keys.")
            return None
        except Exception as e:
            logger.error(f"Email draft generation failed: {e}. NO RETRY.")
            return None

    # ------------------------------------------------------------------
    # classify_senders
    # ------------------------------------------------------------------

    def classify_senders(self, sender_summaries: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        prompt = f"""Classify each email sender as one of: client | vendor | promotional | transactional | unknown.

Senders:
{json.dumps(sender_summaries, indent=2)}

Return JSON only:
{{
  "results": [
    {{"email": "<email>", "classification": "<label>", "confidence": 0.0-1.0}}
  ]
}}

No preamble. No markdown."""
        try:
            response_text = self._call_llm(prompt)
            clean = _strip_markdown_json(response_text)
            return json.loads(clean).get("results", [])
        except Exception as e:
            logger.error(f"Sender classification failed: {e}. NO RETRY.")
            return None

    # ------------------------------------------------------------------
    # analyze_reply_sentiment
    # ------------------------------------------------------------------

    def analyze_reply_sentiment(self, email_id: str, reply_body: str,
                                lead_name: str) -> Dict[str, Any]:
        prompt = f"""Analyse the sentiment and intent of this reply email from a B2B sales prospect.

Prospect name: {lead_name}
Reply body:
{reply_body[:3000]}

Return JSON only:
{{
  "sentiment": "positive" | "negative" | "neutral",
  "confidence": 0.0-1.0,
  "summary": "<one sentence summary>",
  "intent": "<what the prospect wants>",
  "recommended_action": "move_to_crm" | "archive_and_flag" | "flag_for_manual_review"
}}

No preamble. No markdown."""
        try:
            response_text = self._call_llm(prompt)
            clean = _strip_markdown_json(response_text)
            result = json.loads(clean)
            result.update({"email_id": email_id,
                           "analyzed_at": datetime.utcnow().isoformat(), "success": True})
            return result
        except Exception as e:
            logger.error(f"Reply sentiment analysis failed for {email_id}: {e}. NO RETRY.")
            return {"email_id": email_id, "sentiment": "neutral", "confidence": 0.0,
                    "summary": "", "intent": "",
                    "recommended_action": "flag_for_manual_review",
                    "analyzed_at": datetime.utcnow().isoformat(),
                    "success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # route_to_business_unit
    # ------------------------------------------------------------------

    def route_to_business_unit(self, lead_context: Dict[str, Any],
                               business_units: List[Dict[str, str]]) -> Dict[str, Any]:
        bu_block = "\n\n".join([
            f"BU SLUG: {bu['slug']}\nBU NAME: {bu['name']}\n{bu['description']}"
            for bu in business_units
        ])
        prompt = f"""You are a senior B2B sales strategist. Your task is to:
1. Analyse the enriched lead data below.
2. Review the business unit descriptions.
3. Identify the gap between what the lead needs and what we offer.
4. Pick the single best-fit business unit.

LEAD DATA:
{json.dumps(lead_context, indent=2)}

OUR BUSINESS UNITS:
{bu_block}

Return JSON only:
{{
  "slug": "<chosen bu slug>",
  "bu_name": "<chosen bu name>",
  "gap_analysis": "<2-3 sentences>",
  "sender": "<SENDER field from chosen BU description>"
}}

No preamble. No markdown. Only JSON."""
        try:
            response_text = self._call_llm(prompt, temperature=0.4)
            clean = _strip_markdown_json(response_text)
            result = json.loads(clean)
            result.update({"routed_at": datetime.utcnow().isoformat(), "success": True})
            return result
        except Exception as e:
            logger.error(f"BU routing failed: {e}. NO RETRY.")
            return {"slug": None, "bu_name": None, "gap_analysis": "", "sender": "",
                    "routed_at": datetime.utcnow().isoformat(), "success": False,
                    "error": str(e)}

    # ------------------------------------------------------------------
    # draft_outreach_email (replaces the old draft_outreach_email_openai)
    # ------------------------------------------------------------------

    def draft_outreach_email(self, lead_context: Dict[str, Any],
                             bu_description: str, gap_analysis: str,
                             sender: str) -> Dict[str, str]:
        first_name = (lead_context.get("name") or "").split()[0] or "there"
        system_prompt = f"""You are a senior B2B sales copywriter. You write short, human,
non-salesy outreach emails on behalf of market research and data companies.
Your emails are under 150 words in the body, addressed by first name, and end with
a single soft call to action (a 15-minute call or a reply).

BUSINESS UNIT CONTEXT:
{bu_description}

SENDER: {sender}"""
        user_prompt = f"""Write a cold outreach email for the following lead.

LEAD:
{json.dumps(lead_context, indent=2)}

GAP ANALYSIS (why this BU fits):
{gap_analysis}

Rules:
- Address the lead as {first_name}
- Reference one specific pain point from lead data
- Keep body under 150 words
- Sign off with sender name and title
- Subject line: short, specific, no clickbait

Return JSON only:
{{"subject": "<subject line>", "body": "<full plain-text email body>"}}

No preamble. No markdown. Only JSON."""
        try:
            # Same seam as generate_email_draft above — was a direct
            # openai.OpenAI(base_url=BEDROCK_BASE_URL) client, now routed
            # through _call_llm so it respects the local:/self-hosted chain.
            raw = self._call_llm(f"{system_prompt}\n\n{user_prompt}",
                                  max_tokens=600, temperature=0.7, role="smart")
            clean = _strip_markdown_json(raw)
            return json.loads(clean)
        except Exception as e:
            logger.error(f"Outreach email draft failed: {e}")
            return {"subject": "", "body": ""}

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_classification_prompt(self, subject: str, body: str, from_email: str) -> str:
        return f"""Classify this email into one of these categories:
- client: From existing customers/clients
- vendor: From suppliers/vendors
- internal: Internal company communication
- promotional: Marketing/promotional content
- invoice: Bills, invoices, payment requests
- banking: Bank statements, financial notifications
- automated: Auto-generated system emails
- spam: Unwanted/spam emails
- newsletter: Subscribed newsletters
- bounce: Email delivery failures
- sales_inquiry: Potential sales leads
- support: Support requests/tickets
- recruitment: Job applications, hiring
- partnership: Business partnerships, collaborations
- other: Doesn't fit other categories

Email Details:
From: {from_email}
Subject: {subject}
Body: {body[:2000]}

Return JSON only:
{{
  "category": "category_name",
  "confidence": 0.0-1.0,
  "summary": "One sentence summary",
  "intent": "What the sender wants",
  "priority": "high|medium|low",
  "action_required": true|false
}}"""

    def _parse_classification_response(self, email_id: str, response_text: str) -> ClassificationResult:
        try:
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```(?:json)?\s*", "", clean)
                clean = re.sub(r"\s*```$", "", clean)
                clean = clean.strip()
            parsed = json.loads(clean)
            return ClassificationResult(
                email_id=email_id, category=parsed.get("category", "other"),
                confidence=float(parsed.get("confidence", 0.5)),
                summary=parsed.get("summary", ""), intent=parsed.get("intent", ""),
                priority=parsed.get("priority", "medium"),
                action_required=parsed.get("action_required", False),
                classified_at=datetime.utcnow().isoformat(), success=True)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse classification response: {e}")
            return ClassificationResult(
                email_id=email_id, category="other", confidence=0.3,
                summary="Classification parsing failed", intent="unknown",
                priority="low", action_required=False,
                classified_at=datetime.utcnow().isoformat(), success=True,
                error=f"Parse error: {e}")


# ============== SINGLETON ==============

_gateway_instance: Optional[AIGateway] = None


def get_ai_gateway() -> AIGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = AIGateway()
    return _gateway_instance

# Backward-compatible alias
get_gemini_gateway = get_ai_gateway


# ============== CONVENIENCE FUNCTIONS ==============

def classify_email(email_id: str, subject: str, body: str, from_email: str,
                   source: str = "api") -> ClassificationResult:
    return get_ai_gateway().classify_email(email_id, subject, body, from_email, source)

def summarize_email(email_id: str, subject: str, body: str,
                    max_length: int = 200) -> Dict[str, Any]:
    return get_ai_gateway().summarize_email(email_id, subject, body, max_length)

def extract_leads_from_email(email_id: str, subject: str, body: str,
                             from_email: str) -> LeadExtractionResult:
    return get_ai_gateway().extract_leads_from_email(email_id, subject, body, from_email)

def enrich_lead_data(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_ai_gateway().enrich_lead_data(context)

def generate_email_draft(system_prompt: str, user_prompt: str) -> Optional[Dict[str, str]]:
    return get_ai_gateway().generate_email_draft(system_prompt, user_prompt)

def classify_senders(sender_summaries: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    return get_ai_gateway().classify_senders(sender_summaries)

def analyze_reply_sentiment(email_id: str, reply_body: str,
                            lead_name: str) -> Dict[str, Any]:
    return get_ai_gateway().analyze_reply_sentiment(email_id, reply_body, lead_name)

def route_to_business_unit(lead_context: Dict[str, Any],
                           business_units: List[Dict[str, str]]) -> Dict[str, Any]:
    return get_ai_gateway().route_to_business_unit(lead_context, business_units)
