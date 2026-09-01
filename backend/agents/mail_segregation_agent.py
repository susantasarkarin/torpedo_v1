"""
Mail Segregation Agent - Rule-based email categorization and segregation

Purpose:
- Categorizes emails into business categories using keyword/domain/pattern rules
- Segregates mail_pool based on deterministic business logic (zero AI dependency)
- Extracts contact information via regex patterns
- Generates programmatic mail summaries via MongoDB aggregation

Categories: internal, client, vendor, promotion, transactional, bank, gst_it_govt, others
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum

from pymongo import MongoClient, UpdateOne
from bson import ObjectId


def _get_pooled_client():
    """The process-wide pooled MongoClient (backend/database.py)."""
    try:
        from ..database import get_client
    except ImportError:
        from database import get_client
    return get_client()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
# Shared pooled client (TOR-12): this module built its own
# MongoClient at import time. 101 modules did, each with a pool of
# up to 100 connections on a 2 GB box shared with mongod.
mongo_client = _get_pooled_client()

# Email source collection - stores all incoming emails from Gmail
torpedo_gmail_db = mongo_client["torpedo_gmail"]
mail_pool_emails = torpedo_gmail_db["email_metadata"]

# HONEST NAMING: this layer is rule-based, not AI. Its per-email verdict is
# stored under `rule_classification_status`. The old field name
# `ai_classification_status` was misleading (nothing here is a model) and is
# read as a fallback during migration — writes go only to the new field, and
# `backfill_mail_segments.py` / a one-off copy can retire the legacy field.
RULE_STATUS_FIELD = "rule_classification_status"
LEGACY_RULE_STATUS_FIELD = "ai_classification_status"


def _classified_filter(exists: bool = True) -> Dict[str, Any]:
    """Match docs already (or not yet) rule-classified under either field name."""
    if exists:
        return {"$or": [{RULE_STATUS_FIELD: {"$exists": True}},
                        {LEGACY_RULE_STATUS_FIELD: {"$exists": True}}]}
    return {RULE_STATUS_FIELD: {"$exists": False},
            LEGACY_RULE_STATUS_FIELD: {"$exists": False}}


def _segment_expr():
    """Aggregation expression for the segment across both field names (new wins)."""
    return {"$ifNull": [f"${RULE_STATUS_FIELD}.segment",
                        f"${LEGACY_RULE_STATUS_FIELD}.segment"]}

# Email automation database - where classification results are stored
email_automation_db = mongo_client["email_automation"]
email_leads = email_automation_db["email_leads"]
email_conversations = email_automation_db["email_conversations"]
classified_emails = email_automation_db["classified_emails"]

# Leads database
try:
    leads_db = mongo_client.get_database("leads")
    leads_db.list_collection_names()
except Exception:
    leads_db = mongo_client.get_database("ai_enrichment")
leads_collection = leads_db["leads"]
lead_extraction_logs = leads_db["lead_extraction_logs"]

# Settings database (for internal domains lookup)
settings_db = mongo_client["torpedo_settings"]


# ============================================================
# Enums & Data Classes (kept for backward compatibility)
# ============================================================

class SegmentationStrategy(str, Enum):
    CATEGORY = "category"
    SENDER_DOMAIN = "sender_domain"
    PRIORITY = "priority"
    INTENT = "intent"
    ENGAGEMENT = "engagement"
    CUSTOM = "custom"


@dataclass
class EmailCategory:
    name: str
    description: str
    keywords: List[str] = field(default_factory=list)
    confidence_threshold: float = 0.7


@dataclass
class ExtractedContact:
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


# ============================================================
# Classification Rules — priority-ordered category definitions
# ============================================================

# Free email providers — excluded from company extraction
FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "mail.com", "protonmail.com",
    "zoho.com", "yandex.com", "gmx.com", "rediffmail.com",
}

# Internal domains — loaded once from app_settings or env, cached
_internal_domains_cache: Optional[List[str]] = None


def _get_internal_domains() -> List[str]:
    """Load internal/company domains from app_settings or env."""
    global _internal_domains_cache
    if _internal_domains_cache is not None:
        return _internal_domains_cache

    domains: List[str] = []
    try:
        settings = settings_db["app_settings"].find_one()
        if settings:
            raw = settings.get("internal_domains", [])
            if isinstance(raw, list):
                domains = [d.lower().strip() for d in raw if d]
            elif isinstance(raw, str):
                domains = [d.lower().strip() for d in raw.split(",") if d.strip()]
    except Exception:
        pass

    # Also check env
    env_domains = os.getenv("INTERNAL_DOMAINS", "")
    if env_domains:
        domains.extend([d.lower().strip() for d in env_domains.split(",") if d.strip()])

    # Dedupe
    _internal_domains_cache = list(set(domains)) if domains else ["cogentixresearch.com"]
    return _internal_domains_cache


# ---------- Bank ----------
BANK_SENDER_DOMAINS = [
    "sbi", "hdfc", "icici", "axis", "kotak", "yesbank", "indusind",
    "bankofbaroda", "pnb", "canara", "unionbank", "idbi", "rbl",
    "federalbank", "bandhan", "citi", "hsbc", "standardchartered",
    "dbs", "barclays", "jpmorgan", "chase", "wellsfargo", "bankofamerica",
    "capitalone", "amex", "americanexpress", "mastercard", "visa",
    "razorpay", "paytm", "phonepe", "gpay", "bharatpe",
]

BANK_SUBJECT_PATTERNS = [
    r"\b(?:bank|banking)\b",
    r"\b(?:statement|account\s+summary)\b",
    r"\b(?:transaction\s+alert|txn\s+alert)\b",
    r"\b(?:debit|credit)\s+(?:alert|notification|of)\b",
    r"\b(?:NEFT|RTGS|IMPS|UPI|wire\s+transfer)\b",
    r"\b(?:EMI|loan|mortgage)\s+(?:due|payment|reminder)\b",
    r"\b(?:credit\s+card|debit\s+card)\b",
    r"\b(?:SWIFT|IBAN)\b",
    r"\b(?:balance|withdrawal|deposit)\b",
    r"\bKYC\b",
]

# ---------- GST / IT / Govt ----------
GOVT_SENDER_DOMAINS = [
    "incometax.gov.in", "gst.gov.in", "incometaxindia.gov.in",
    "nic.in", "gov.in", "eci.gov.in", "epfindia.gov.in",
    "mca.gov.in", "rbi.org.in", "sebi.gov.in",
]

GOVT_SUBJECT_PATTERNS = [
    r"\bGST(?:IN|R|-)?\b",
    r"\b(?:income\s+tax|ITR|I\.T\.)\b",
    r"\b(?:Form\s+(?:16|26AS|10E))\b",
    r"\b(?:TDS|TCS)\b",
    r"\bPAN\b",
    r"\b(?:assessment|scrutiny|notice\s+u/s)\b",
    r"\b(?:challan|e-?filing|e-?verify)\b",
    r"\b(?:provident\s+fund|EPF|EPFO)\b",
    r"\b(?:ROC|MCA|annual\s+return)\b",
    r"\b(?:DGFT|customs|excise)\b",
]

# ---------- Transactional ----------
TRANSACTIONAL_SENDER_PATTERNS = [
    r"^noreply@", r"^no-reply@", r"^donotreply@", r"^do-not-reply@",
    r"^notification@", r"^alerts?@", r"^confirm", r"^verify",
    r"^support@", r"^billing@", r"^orders?@", r"^receipts?@",
    r"^shipping@", r"^tracking@",
]

TRANSACTIONAL_SUBJECT_PATTERNS = [
    r"\b(?:invoice|receipt|bill)\b",
    r"\b(?:order\s+confirm|shipment|shipping|tracking)\b",
    r"\b(?:payment\s+(?:received|confirmed|successful|failed))\b",
    r"\bOTP\b",
    r"\b(?:verification\s+code|verify\s+your|confirm\s+your)\b",
    r"\b(?:password\s+reset|reset\s+your\s+password)\b",
    r"\b(?:subscription\s+(?:confirm|renew|cancel))\b",
    r"\b(?:welcome\s+to|account\s+created|sign[- ]?up)\b",
    r"\b(?:two[- ]?factor|2FA|MFA)\b",
]

# ---------- Promotion ----------
PROMOTION_SUBJECT_PATTERNS = [
    r"\b(?:offer|discount|deal|sale|coupon|promo(?:tion|code)?)\b",
    r"\b(?:newsletter|digest|weekly\s+update)\b",
    r"\b(?:webinar|event|workshop|conference|summit)\b",
    r"\b(?:limited\s+time|exclusive|special|flash\s+sale)\b",
    r"\b(?:free\s+trial|get\s+started|sign\s+up\s+now)\b",
    r"\bunsubscribe\b",
    r"\b(?:black\s+friday|cyber\s+monday|festive|diwali|christmas)\b",
    r"\b(?:earn\s+rewards|loyalty|cashback)\b",
]

PROMOTION_BODY_PATTERNS = [
    r"unsubscribe",
    r"view\s+in\s+browser",
    r"email\s+preferences",
    r"opt[- ]?out",
    r"manage\s+subscriptions?",
    r"you\s+are\s+receiving\s+this\s+(?:email|because)",
]

# ---------- Client ----------
CLIENT_SUBJECT_PATTERNS = [
    r"\b(?:inquiry|enquiry|RFP|RFQ|request\s+for)\b",
    r"\b(?:proposal|quotation|quote)\b",
    r"\b(?:meeting\s+request|schedule\s+(?:a\s+)?call|set\s+up\s+a\s+meeting)\b",
    r"\b(?:interested\s+in|looking\s+for|need\s+help\s+with)\b",
    r"\b(?:collaboration|project\s+(?:brief|requirement))\b",
    r"\b(?:demo\s+request|product\s+inquiry)\b",
]

CLIENT_BODY_PATTERNS = [
    r"(?:we\s+are\s+(?:interested|looking)|I(?:'m|\s+am)\s+(?:interested|looking))",
    r"(?:could\s+you\s+(?:send|share|provide)|please\s+(?:send|share|provide))",
    r"(?:can\s+we\s+(?:schedule|set\s+up|arrange))",
    r"(?:would\s+like\s+(?:to\s+discuss|a\s+(?:demo|quote|proposal)))",
]

# ---------- Vendor ----------
VENDOR_SUBJECT_PATTERNS = [
    r"\b(?:we\s+offer|our\s+(?:product|service|solution))\b",
    r"\b(?:partnership\s+(?:proposal|opportunity))\b",
    r"\b(?:reseller|distributor|supplier)\b",
    r"\b(?:introducing|announcement|launch(?:ing)?)\b",
]

VENDOR_BODY_PATTERNS = [
    r"(?:we\s+(?:offer|provide|specialize|are\s+a))",
    r"(?:our\s+(?:company|team|platform|solution))",
    r"(?:I(?:'d|\s+would)\s+like\s+to\s+(?:introduce|present|offer))",
    r"(?:exclusive\s+(?:partner|dealer|distributor))",
    r"(?:competitive\s+(?:pricing|rates))",
    r"(?:free\s+(?:consultation|assessment|audit))",
]

# ---------- Contact extraction patterns ----------
PHONE_PATTERNS = [
    r'(?:phone|tel|mobile|cell|direct|office|fax)\s*[:\-]?\s*(\+?[\d\s\-\(\)\.]{7,20})',
    r'(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4})',
    r'(\+91[\s\-]?\d{5}[\s\-]?\d{5})',           # India +91
    r'(\+91[\s\-]?\d{10})',                        # India +91 no spaces
    r'(\b0\d{2,4}[\s\-]?\d{6,8}\b)',              # India STD codes (0xx-xxxxxxxx)
    r'[\+]?[(]?[0-9]{1,3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}',
    r'\(\d{3}\)\s?\d{3}[-\s]?\d{4}',
]

LINKEDIN_PATTERN = r'(?:https?://)?(?:www\.)?linkedin\.com/(?:in|company)/([a-zA-Z0-9\-]+)'
WEBSITE_PATTERN = r'(?:https?://)?(?:www\.)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})(?:/[^\s]*)?'
EMAIL_PATTERN = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

TITLE_KEYWORDS = [
    'CEO', 'CTO', 'CFO', 'COO', 'CMO', 'CRO', 'CIO', 'CHRO',
    'VP', 'Vice President', 'Director', 'Manager', 'Head of',
    'Founder', 'Co-Founder', 'President', 'Partner',
    'Engineer', 'Developer', 'Designer', 'Analyst',
    'Consultant', 'Associate', 'Specialist', 'Coordinator',
    'Lead', 'Senior', 'Principal', 'Architect',
]

SIGN_OFF_PATTERNS = [
    r'(?:best|kind|warm)\s+regards',
    r'regards',
    r'sincerely',
    r'thanks?\s*(?:&|and)?\s*regards',
    r'thank(?:s|\s+you)',
    r'cheers',
    r'respectfully',
    r'yours\s+(?:truly|faithfully)',
]

STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'need', 'dare', 'ought',
    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
    'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'between', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
    'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each',
    'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
    'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
    'just', 'because', 'but', 'and', 'or', 'if', 'while', 'about', 'up',
    'this', 'that', 'these', 'those', 'it', 'its', 'i', 'me', 'my', 'we',
    'our', 'you', 'your', 'he', 'she', 'they', 'them', 'his', 'her',
    'what', 'which', 'who', 'whom', 're', 'fwd', 'fw',
}


# ============================================================
# Main Agent Class
# ============================================================

class MailSegregationAgent:
    """Rule-based mail segregation agent — zero AI dependency."""

    def __init__(self):
        self.internal_domains = _get_internal_domains()

    # ----------------------------------------------------------
    # Core: Rule-based email classification
    # ----------------------------------------------------------

    def _classify_email(self, email: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify a single email using deterministic keyword/domain/pattern rules.

        Priority order: internal -> bank -> gst_it_govt -> transactional -> promotion -> client -> vendor -> others

        Returns dict with: segment, category, confidence, reasoning, metadata
        """
        from_email = (email.get("from_email") or email.get("from_address", {}).get("email", "") or "").lower()
        from_name = (email.get("from_name") or email.get("from_address", {}).get("name", "") or "").lower()
        subject = (email.get("subject") or "").lower()
        body_raw = email.get("body_plain") or email.get("body") or email.get("snippet") or ""
        body = body_raw[:2000].lower()
        direction = (email.get("direction") or "").lower()
        labels = [lbl.lower() for lbl in (email.get("labels") or [])]

        domain = from_email.split("@")[-1] if "@" in from_email else ""
        text = f"{subject} {body}"

        def _count_pattern_hits(patterns: List[str], target: str) -> int:
            return sum(1 for p in patterns if re.search(p, target, re.IGNORECASE))

        # ---- 1. Internal ----
        if domain and any(domain.endswith(d) for d in self.internal_domains):
            return self._result("internal", "Internal", 0.95,
                                f"Sender domain '{domain}' is an internal domain",
                                is_promotional=False, requires_response=True, priority="medium")

        # ---- 2. Bank ----
        bank_domain_hit = any(bd in domain for bd in BANK_SENDER_DOMAINS)
        bank_subj_hits = _count_pattern_hits(BANK_SUBJECT_PATTERNS, subject)
        bank_score = (0.5 if bank_domain_hit else 0) + min(bank_subj_hits * 0.2, 0.5)
        if bank_score >= 0.5:
            return self._result("bank", "Bank", min(bank_score, 1.0),
                                f"Bank domain={bank_domain_hit}, subject hits={bank_subj_hits}",
                                is_promotional=False, requires_response=False, priority="low")

        # ---- 3. GST / IT / Govt ----
        govt_domain_hit = any(domain.endswith(gd) for gd in GOVT_SENDER_DOMAINS)
        govt_subj_hits = _count_pattern_hits(GOVT_SUBJECT_PATTERNS, text)
        govt_score = (0.5 if govt_domain_hit else 0) + min(govt_subj_hits * 0.15, 0.5)
        if govt_score >= 0.5:
            return self._result("gst_it_govt", "GST/IT/Govt", min(govt_score, 1.0),
                                f"Govt domain={govt_domain_hit}, keyword hits={govt_subj_hits}",
                                is_promotional=False, requires_response=True, priority="high")

        # ---- 4. Transactional ----
        txn_sender_hit = any(re.search(p, from_email, re.I) for p in TRANSACTIONAL_SENDER_PATTERNS)
        txn_subj_hits = _count_pattern_hits(TRANSACTIONAL_SUBJECT_PATTERNS, subject)
        txn_score = (0.3 if txn_sender_hit else 0) + min(txn_subj_hits * 0.25, 0.7)
        if txn_score >= 0.5:
            return self._result("transactional", "Transactional", min(txn_score, 1.0),
                                f"Transactional sender={txn_sender_hit}, subject hits={txn_subj_hits}",
                                is_promotional=False, requires_response=False, priority="low")

        # ---- 5. Promotion ----
        promo_subj_hits = _count_pattern_hits(PROMOTION_SUBJECT_PATTERNS, subject)
        promo_body_hits = _count_pattern_hits(PROMOTION_BODY_PATTERNS, body)
        promo_score = min(promo_subj_hits * 0.2, 0.5) + min(promo_body_hits * 0.15, 0.5)
        if promo_score >= 0.4:
            return self._result("promotion", "Promotion", min(promo_score, 1.0),
                                f"Promo subject hits={promo_subj_hits}, body hits={promo_body_hits}",
                                is_promotional=True, requires_response=False, priority="low")

        # ---- 6. Client (inbound) ----
        is_inbound = direction == "inbound" or "inbox" in labels
        client_subj_hits = _count_pattern_hits(CLIENT_SUBJECT_PATTERNS, subject)
        client_body_hits = _count_pattern_hits(CLIENT_BODY_PATTERNS, body)
        client_score = min(client_subj_hits * 0.25, 0.5) + min(client_body_hits * 0.2, 0.5)
        if is_inbound:
            client_score += 0.1
        if client_score >= 0.4:
            return self._result("client", "Client", min(client_score, 1.0),
                                f"Client subject hits={client_subj_hits}, body hits={client_body_hits}, inbound={is_inbound}",
                                is_promotional=False, requires_response=True, priority="high")

        # ---- 7. Vendor ----
        vendor_subj_hits = _count_pattern_hits(VENDOR_SUBJECT_PATTERNS, subject)
        vendor_body_hits = _count_pattern_hits(VENDOR_BODY_PATTERNS, body)
        vendor_score = min(vendor_subj_hits * 0.25, 0.5) + min(vendor_body_hits * 0.15, 0.5)
        if vendor_score >= 0.4:
            return self._result("vendor", "Vendor", min(vendor_score, 1.0),
                                f"Vendor subject hits={vendor_subj_hits}, body hits={vendor_body_hits}",
                                is_promotional=False, requires_response=False, priority="medium")

        # ---- 8. Others (fallback) ----
        return self._result("others", "Others", 0.3,
                            "No category rules matched",
                            is_promotional=False, requires_response=False, priority="low")

    def classify(self, email: Dict[str, Any]) -> Dict[str, Any]:
        """
        Public rule-based classification (wraps _classify_email). Used as the
        Stage-1 prefilter by the AI mail-desk (sales/mail_pool_ai.py): its
        cheap, deterministic segment decides whether an email is worth a paid
        Bedrock call. Returns {segment, category, confidence, reasoning,
        metadata}.

        NOTE: there is deliberately no RFQ rule here. RFQ detection is semantic
        and lives ONLY in the AI layer — do not add keyword RFQ rules, they
        would silently disagree with the model's classification.
        """
        return self._classify_email(email)

    @staticmethod
    def _result(segment: str, category: str, confidence: float, reasoning: str,
                is_promotional: bool, requires_response: bool, priority: str) -> Dict[str, Any]:
        return {
            "segment": segment,
            "category": category,
            "confidence": round(confidence, 2),
            "reasoning": reasoning,
            "metadata": {
                "is_promotional": is_promotional,
                "requires_response": requires_response,
                "priority": priority,
            }
        }

    # ----------------------------------------------------------
    # Segregate all emails
    # ----------------------------------------------------------

    def segregate_all_emails(
        self,
        strategy: SegmentationStrategy = SegmentationStrategy.CATEGORY,
        batch_size: int = 100,
        force_rescan: bool = False
    ) -> Dict[str, Any]:
        """
        Segregate all unclassified emails using rule-based classification.
        """
        try:
            logger.info(f"Starting rule-based mail segregation (strategy={strategy})")

            if force_rescan:
                total_emails = mail_pool_emails.count_documents({})
                # Clear BOTH the new and legacy fields on a forced rescan.
                mail_pool_emails.update_many(
                    {}, {"$unset": {RULE_STATUS_FIELD: "", LEGACY_RULE_STATUS_FIELD: ""}})
            else:
                total_emails = mail_pool_emails.count_documents(_classified_filter(exists=False))

            logger.info(f"Found {total_emails} emails to segregate")

            processed = 0
            failed = 0

            while True:
                batch = list(mail_pool_emails.find(
                    _classified_filter(exists=False) if not force_rescan else {}
                ).limit(batch_size))

                if not batch:
                    break

                pool_ops = []
                classified_ops = []

                for email in batch:
                    try:
                        segment_result = self._classify_email(email)

                        classification_data = {
                            "status": "classified",
                            "category": segment_result["category"],
                            "segment": segment_result["segment"],
                            "confidence": segment_result["confidence"],
                            "reasoning": segment_result.get("reasoning", ""),
                            "metadata": segment_result.get("metadata", {}),
                            "classified_at": datetime.utcnow(),
                            "classification_method": "rule_based"
                        }

                        pool_ops.append(UpdateOne(
                            {"_id": email["_id"]},
                            {"$set": {RULE_STATUS_FIELD: classification_data}}
                        ))

                        classified_ops.append(UpdateOne(
                            {"email_id": str(email["_id"])},
                            {"$set": {
                                "email_id": str(email["_id"]),
                                "from_email": email.get("from_email", ""),
                                "subject": email.get("subject", ""),
                                "classification": classification_data,
                                "updated_at": datetime.utcnow()
                            }},
                            upsert=True
                        ))
                        processed += 1
                    except Exception as e:
                        logger.error(f"Error classifying email {email.get('_id')}: {e}")
                        failed += 1

                if pool_ops:
                    mail_pool_emails.bulk_write(pool_ops, ordered=False)
                if classified_ops:
                    classified_emails.bulk_write(classified_ops, ordered=False)

                logger.info(f"Processed {processed} emails, {failed} failed")

            summaries = self._generate_segment_summaries()

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

    # ----------------------------------------------------------
    # Contact extraction (regex-based)
    # ----------------------------------------------------------

    def extract_contact_information(self, email_id: str) -> Optional[ExtractedContact]:
        """Extract contact information from an email using regex patterns (with upsert dedup)."""
        email = mail_pool_emails.find_one({"_id": ObjectId(email_id) if isinstance(email_id, str) else email_id})
        if not email:
            return None

        body = email.get("body_plain") or email.get("body") or ""
        sender = email.get("from_email", "")
        sender_name = email.get("from_name", "")
        domain = sender.split("@")[-1] if "@" in sender else ""

        sig_info = self._parse_signature(body)

        # Phone
        phone = sig_info.get("phone", "")
        if not phone:
            for pattern in PHONE_PATTERNS:
                match = re.search(pattern, body)
                if match:
                    phone = match.group(1) if match.lastindex else match.group(0)
                    phone = phone.strip()
                    if sum(c.isdigit() for c in phone) >= 7:
                        break
                    phone = ""

        # LinkedIn
        linkedin = sig_info.get("linkedin", "")
        if not linkedin:
            lk_match = re.search(LINKEDIN_PATTERN, body, re.I)
            if lk_match:
                prefix = "company" if "/company/" in (lk_match.group(0) or "") else "in"
                linkedin = f"https://linkedin.com/{prefix}/{lk_match.group(1)}"

        # Company
        company = sig_info.get("company", "")
        if not company and domain and domain not in FREE_EMAIL_PROVIDERS:
            company = domain.split(".")[0].title()

        # Title
        title = sig_info.get("title", "")

        # Website
        website = ""
        if domain and domain not in FREE_EMAIL_PROVIDERS:
            website = f"https://{domain}"

        name = sig_info.get("name", "") or sender_name

        # Weighted confidence scoring
        weights = {"email": 0.3, "name": 0.25, "company": 0.2, "title": 0.1, "phone": 0.1, "linkedin": 0.05}
        confidence = sum(w for field, w in weights.items() if locals().get(field) or (field == "email" and sender))
        confidence = round(min(confidence, 1.0), 2)

        contact = ExtractedContact(
            name=name,
            email=sender,
            phone=phone,
            company=company,
            title=title,
            linkedin=linkedin,
            website=website,
            address="",
            social_handles={},
            source_email_id=str(email_id),
            extracted_at=datetime.utcnow().isoformat()
        )

        # Upsert to deduplicate by email
        email_leads.update_one(
            {"email": sender},
            {"$set": asdict(contact), "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return contact

    def extract_all_contacts(self, batch_size: int = 50) -> Dict[str, Any]:
        """Extract contacts from all emails in pool using cursor-based pagination."""
        try:
            extracted = 0
            failed = 0
            total = 0
            cursor = mail_pool_emails.find(
                {"from_email": {"$exists": True}},
                no_cursor_timeout=True,
                batch_size=batch_size,
            )
            try:
                for email in cursor:
                    total += 1
                    try:
                        contact = self.extract_contact_information(email["_id"])
                        if contact:
                            extracted += 1
                    except Exception as e:
                        logger.error(f"Failed to extract contact: {e}")
                        failed += 1
            finally:
                cursor.close()

            return {
                "success": True,
                "total_processed": total,
                "extracted": extracted,
                "failed": failed,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in extract_all_contacts: {e}")
            return {"success": False, "error": str(e)}

    # ----------------------------------------------------------
    # Mail summary (programmatic, no AI)
    # ----------------------------------------------------------

    def generate_mail_summary(
        self,
        segment_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Optional[MailSegmentSummary]:
        """Generate summary for email segment using aggregation — no AI."""
        try:
            query: Dict[str, Any] = {}
            if segment_name:
                # Read-compat: match the segment under either field name.
                query["$or"] = [
                    {f"{RULE_STATUS_FIELD}.segment": segment_name},
                    {f"{LEGACY_RULE_STATUS_FIELD}.segment": segment_name},
                ]

            if date_from or date_to:
                date_query: Dict[str, Any] = {}
                if date_from:
                    date_query["$gte"] = datetime.fromisoformat(date_from)
                if date_to:
                    date_query["$lte"] = datetime.fromisoformat(date_to)
                query["timestamp"] = date_query

            emails = list(mail_pool_emails.find(query).sort("timestamp", -1).limit(200))
            if not emails:
                return None

            # Key topics — most frequent words from subjects (stop-word filtered)
            word_counter: Counter = Counter()
            for e in emails:
                subj = e.get("subject", "")
                words = re.findall(r'[a-zA-Z]{3,}', subj.lower())
                word_counter.update(w for w in words if w not in STOP_WORDS)
            key_topics = [w for w, _ in word_counter.most_common(10)]

            # Top senders
            sender_counter: Counter = Counter(e.get("from_email", "") for e in emails)
            top_senders = sender_counter.most_common(5)

            # Date range
            dates = [e.get("timestamp") for e in emails if e.get("timestamp")]
            date_start = min(dates).isoformat() if dates else ""
            date_end = max(dates).isoformat() if dates else ""

            # Template summary
            sender_names = ", ".join(s[0] for s in top_senders[:3])
            topic_str = ", ".join(key_topics[:5]) if key_topics else "various"
            summary_text = (
                f"Segment '{segment_name or 'All'}' contains {len(emails)} emails. "
                f"Top senders: {sender_names}. "
                f"Most discussed topics: {topic_str}."
            )

            segment_id = str(ObjectId())
            summary = MailSegmentSummary(
                segment_id=segment_id,
                segment_name=segment_name or "All Emails",
                total_emails=len(emails),
                date_range=(date_start, date_end),
                key_topics=key_topics,
                sentiment_distribution={},
                top_senders=top_senders,
                action_items=[],
                summary_text=summary_text,
                created_at=datetime.utcnow().isoformat()
            )

            email_automation_db["mail_summaries"].insert_one(asdict(summary))
            return summary

        except Exception as e:
            logger.error(f"Error generating mail summary: {e}")
            return None

    def _generate_segment_summaries(self) -> List[Dict[str, Any]]:
        """Generate summaries for all classified segments."""
        try:
            segments = mail_pool_emails.aggregate([
                {"$match": _classified_filter(exists=True)},
                {"$group": {"_id": _segment_expr(), "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ])

            summaries = []
            for segment in segments:
                seg_name = segment["_id"]
                if seg_name:
                    summary = self.generate_mail_summary(seg_name)
                    if summary:
                        summaries.append(asdict(summary))
            return summaries

        except Exception as e:
            logger.error(f"Error generating summaries: {e}")
            return []

    # ----------------------------------------------------------
    # Lead extraction (regex-based)
    # ----------------------------------------------------------

    def extract_leads_from_emails(self, batch_size: int = 50) -> Dict[str, Any]:
        """Extract leads from all emails and create lead documents."""
        try:
            logger.info("Starting lead extraction from emails")
            total_emails = mail_pool_emails.count_documents({"lead_extracted": {"$ne": True}})
            logger.info(f"Found {total_emails} emails to process for lead extraction")

            extracted = 0
            failed = 0

            while True:
                batch = list(mail_pool_emails.find(
                    {"lead_extracted": {"$ne": True}}
                ).limit(batch_size))

                for email in batch:
                    try:
                        lead_data = self._extract_lead_from_email(email)
                        if lead_data:
                            lead_id = self._create_or_update_lead(lead_data)

                            mail_pool_emails.update_one(
                                {"_id": email["_id"]},
                                {"$set": {
                                    "lead_extracted": True,
                                    "lead_id": lead_id,
                                    "lead_extraction_date": datetime.utcnow()
                                }}
                            )
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

                if not batch or len(batch) == 0:
                    break

            return {
                "success": True,
                "total_emails": total_emails,
                "extracted": extracted,
                "failed": failed,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in extract_leads_from_emails: {e}")
            return {"success": False, "error": str(e), "timestamp": datetime.utcnow().isoformat()}

    def _extract_lead_from_email(self, email: Dict[str, Any]) -> Optional[ExtractedLead]:
        """Extract lead information from email using regex patterns."""
        try:
            body = email.get("body_plain") or email.get("body") or ""
            from_email = email.get("from_email", "")
            from_name = email.get("from_name", "")
            subject = email.get("subject", "")

            if not from_email:
                return None

            domain = from_email.split("@")[-1] if "@" in from_email else ""

            # Company from domain (skip free providers)
            company = ""
            if domain and domain not in FREE_EMAIL_PROVIDERS:
                company = domain.split(".")[0].title()

            # Name from from_name or parse from email prefix
            name = from_name.strip()
            if not name:
                prefix = from_email.split("@")[0]
                name = re.sub(r'[._]', ' ', prefix).title()

            # Parse signature for additional info
            sig_info = self._parse_signature(body)

            # Prefer signature-extracted name over header if it looks like a real name
            sig_name = sig_info.get("name", "")
            if sig_name and " " in sig_name and len(sig_name) < 50:
                name = sig_name

            phone = sig_info.get("phone", "")
            linkedin = sig_info.get("linkedin", "")
            title = sig_info.get("title", "")
            location = sig_info.get("location", "")

            # Website
            website = ""
            if domain and domain not in FREE_EMAIL_PROVIDERS:
                website = f"https://{domain}"

            if not name:
                return None

            # Confidence: weighted scoring per field
            weights = {"name": 0.25, "email": 0.3, "company": 0.2, "title": 0.1, "phone": 0.1, "linkedin": 0.05}
            fields = {"name": name, "email": from_email, "company": company, "title": title, "phone": phone, "linkedin": linkedin}
            confidence = sum(w for f, w in weights.items() if fields.get(f))
            confidence = round(min(confidence, 1.0), 2)

            return ExtractedLead(
                name=name,
                email=from_email,
                company=company,
                title=title,
                phone=phone,
                linkedin=linkedin,
                website=website,
                location=location,
                source_email_id=str(email["_id"]),
                source_email_from=from_email,
                source_email_subject=subject,
                extracted_at=datetime.utcnow().isoformat(),
                confidence=round(confidence, 2)
            )
        except Exception as e:
            logger.error(f"Error extracting lead from email: {e}")
            return None

    def _create_or_update_lead(self, lead_data: ExtractedLead) -> str:
        """Create or update lead in leads database."""
        try:
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
                source_emails = existing_lead.get("source_emails", [])
                if lead_data.source_email_id not in source_emails:
                    source_emails.append(lead_data.source_email_id)

                leads_collection.update_one(
                    {"_id": existing_lead["_id"]},
                    {"$set": {**lead_doc, "source_emails": source_emails, "last_updated": datetime.utcnow()}}
                )
                lead_id = str(existing_lead["_id"])
            else:
                result = leads_collection.insert_one(lead_doc)
                lead_id = str(result.inserted_id)

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

    # ----------------------------------------------------------
    # Utility: mark email
    # ----------------------------------------------------------

    def mark_email_as_lead_extracted(self, email_id: str, lead_id: str) -> bool:
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

    # ----------------------------------------------------------
    # Stats
    # ----------------------------------------------------------

    def get_lead_extraction_stats(self) -> Dict[str, Any]:
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
        try:
            total = mail_pool_emails.count_documents({})
            classified = mail_pool_emails.count_documents(_classified_filter(exists=True))

            segment_breakdown = list(mail_pool_emails.aggregate([
                {"$match": _classified_filter(exists=True)},
                {"$group": {"_id": _segment_expr(), "count": {"$sum": 1}}},
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

    # ----------------------------------------------------------
    # Signature parsing helper
    # ----------------------------------------------------------

    def _parse_signature(self, body: str) -> Dict[str, str]:
        """
        Parse email signature from last ~40 lines of the body.
        Handles quoted replies and common signature separators.
        Returns dict with: name, title, company, phone, linkedin, location
        """
        info: Dict[str, str] = {"name": "", "title": "", "company": "", "phone": "", "linkedin": "", "location": ""}

        if not body:
            return info

        lines = body.strip().split("\n")

        # Strip quoted replies (lines starting with > or "On ... wrote:")
        clean_lines = []
        for line in lines:
            if re.match(r'^>', line):
                continue
            if re.match(r'^On .+ wrote:', line, re.I):
                break
            clean_lines.append(line)

        # Look for signature separators: "-- ", "___", "---"
        sig_start = -1
        for i, line in enumerate(clean_lines):
            stripped = line.strip()
            if stripped in ("--", "-- ") or re.match(r'^[_\-]{3,}$', stripped):
                sig_start = i
                break

        if sig_start >= 0:
            sig_lines = clean_lines[sig_start:]
        else:
            sig_lines = clean_lines[-40:] if len(clean_lines) > 40 else clean_lines

        sig_text = "\n".join(sig_lines)

        # Find sign-off line to narrow signature
        sign_off_idx = -1
        for i, line in enumerate(sig_lines):
            for pattern in SIGN_OFF_PATTERNS:
                if re.search(pattern, line, re.I):
                    sign_off_idx = i
                    break
            if sign_off_idx >= 0:
                break

        if sign_off_idx >= 0:
            sig_lines = sig_lines[sign_off_idx:]

        # Name — usually first non-empty line after sign-off
        for line in sig_lines:
            clean = line.strip().rstrip(",")
            if not clean or len(clean) > 60 or "@" in clean or "http" in clean.lower():
                continue
            if any(re.search(p, clean, re.I) for p in SIGN_OFF_PATTERNS):
                continue
            words = clean.split()
            if 1 <= len(words) <= 4 and all(re.match(r'^[A-Za-z\.\-\']+$', w) for w in words):
                info["name"] = clean.title()
                break

        # Title + company extraction (title line often has " at Company" or " | Company")
        for line in sig_lines:
            clean = line.strip()
            for kw in TITLE_KEYWORDS:
                if re.search(r'\b' + re.escape(kw) + r'\b', clean, re.I):
                    # Check for "Title at Company" or "Title | Company"
                    split_match = re.search(r'(.+?)(?:\s+at\s+|\s*[\|,]\s*)(.+)', clean, re.I)
                    if split_match:
                        info["title"] = split_match.group(1).strip()[:100]
                        info["company"] = split_match.group(2).strip()[:100]
                    else:
                        info["title"] = clean[:100]
                    break
            if info["title"]:
                break

        # Phone
        for pattern in PHONE_PATTERNS:
            match = re.search(pattern, sig_text)
            if match:
                phone_val = match.group(1) if match.lastindex else match.group(0)
                phone_val = phone_val.strip()
                if sum(c.isdigit() for c in phone_val) >= 7:
                    info["phone"] = phone_val
                    break

        # LinkedIn
        lk_match = re.search(LINKEDIN_PATTERN, sig_text, re.I)
        if lk_match:
            prefix = "company" if "/company/" in (lk_match.group(0) or "") else "in"
            info["linkedin"] = f"https://linkedin.com/{prefix}/{lk_match.group(1)}"

        # Location — look for common patterns
        loc_match = re.search(r'(?:location|based\s+in|from)\s*[:\-]?\s*([A-Z][a-zA-Z\s,]+)', sig_text)
        if loc_match:
            info["location"] = loc_match.group(1).strip()[:100]

        return info


# Singleton instance
_agent_instance: Optional[MailSegregationAgent] = None


def get_mail_segregation_agent() -> MailSegregationAgent:
    """Get or create singleton instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MailSegregationAgent()
    return _agent_instance

