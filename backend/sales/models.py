"""
Sales Data Models
Pydantic models for the unified leads collection, company_domains, and email_events.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr


# ============== ENUMS ==============

class LeadSource(str, Enum):
    FORM = "form"
    MAIL_POOL = "mail_pool"
    GOOGLE_SEARCH = "google_search"
    CSV = "csv"
    MANUAL = "manual"


class LeadStage(str, Enum):
    NEW = "new"
    EMAIL_CONSTRUCTION = "email_construction"
    VERIFIED = "verified"
    ENRICHED = "enriched"
    OUTREACH_SENT = "outreach_sent"
    REPLIED = "replied"
    DISCOVERY = "discovery"
    RFQ = "rfq"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"


class EmailStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    INVALID = "invalid"
    BOUNCED = "bounced"


class LeadTrack(str, Enum):
    INBOUND = "inbound"
    REENGAGEMENT = "reengagement"
    COLD = "cold"


class EnrichmentStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class DraftStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    DISCARDED = "discarded"


class EventType(str, Enum):
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"


class DomainPatternSource(str, Enum):
    GEMINI = "gemini"
    CACHE = "cache"
    MANUAL = "manual"


class RFQStatus(str, Enum):
    PENDING = "pending"
    QUOTED = "quoted"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"


# ============== EMBEDDED MODELS ==============

class Enrichment(BaseModel):
    role: Optional[str] = None
    company_size: Optional[str] = None
    pain_points: List[str] = Field(default_factory=list)
    news: Optional[str] = None
    hook: Optional[str] = None
    status: EnrichmentStatus = EnrichmentStatus.PENDING


class EmailDraft(BaseModel):
    subject: str
    body: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    status: DraftStatus = DraftStatus.PENDING_REVIEW


class EventMetadata(BaseModel):
    clicked_url: Optional[str] = None
    bounce_reason: Optional[str] = None
    reply_snippet: Optional[str] = None


class RFQVersion(BaseModel):
    version_number: int
    amount: float
    currency: str = "USD"
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============== LEAD MODELS ==============

class LeadCreate(BaseModel):
    source: LeadSource
    name: str
    email: Optional[str] = None
    company: Optional[str] = None
    domain: Optional[str] = None
    track: LeadTrack = LeadTrack.COLD
    contactus_message: Optional[str] = None
    mail_thread_ids: List[str] = Field(default_factory=list)


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    domain: Optional[str] = None
    track: Optional[LeadTrack] = None
    intent_score: Optional[int] = None
    enrichment: Optional[Enrichment] = None
    email_draft: Optional[EmailDraft] = None
    rfq_id: Optional[str] = None
    archived: Optional[bool] = None
    icp_tags: Optional[List[str]] = None


class StageTransition(BaseModel):
    new_stage: LeadStage
    reason: Optional[str] = None


class DraftApproval(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None


class DraftRegenerate(BaseModel):
    instruction: Optional[str] = None
    icp_slug: Optional[str] = None  # Override which ICP's outreach config to use


# ============== INBOUND FORM ==============

class InboundLeadPayload(BaseModel):
    name: str
    email: EmailStr
    company: str
    message: str


# ============== GOOGLE SEARCH PROSPECTING ==============

class ProspectRequest(BaseModel):
    industry: str
    job_title: str
    location: str
    company_size: Optional[str] = None
    max_results: int = Field(default=10, ge=1, le=100)


# ============== EMAIL EVENTS ==============

class EmailEventCreate(BaseModel):
    lead_id: str
    event_type: EventType
    metadata: Optional[EventMetadata] = None
    campaign_id: Optional[str] = None


# ============== COMPANY DOMAINS ==============

class CompanyDomainCreate(BaseModel):
    domain: str
    pattern: str
    source: DomainPatternSource = DomainPatternSource.MANUAL


# ============== ICP MODELS ==============

class ICPSegmentCreate(BaseModel):
    slug: str  # machine-readable key, e.g. "bimwave"
    name: str  # display name, e.g. "BIMwave"
    description: Optional[str] = None
    criteria: Optional[dict] = None  # {industries: [], company_sizes: [], keywords: []}
    color: Optional[str] = None  # hex or tailwind colour for badges


class LeadICPUpdate(BaseModel):
    """Set (replace) the full icp_tags list for a lead."""
    icp_tags: List[str]


class BulkICPTag(BaseModel):
    """Add a single ICP tag to multiple leads (append — preserves other tags)."""
    lead_ids: List[str]
    icp_segment: str  # slug of the ICP to add


# ============== RFQ MODELS ==============

class RFQCreate(BaseModel):
    lead_id: str
    title: str
    description: Optional[str] = None
    manual_value: Optional[float] = None
    currency: str = "USD"
    priority: str = "medium"
    due_date: Optional[str] = None


class RFQUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    manual_value: Optional[float] = None
    currency: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None


class RFQStatusUpdate(BaseModel):
    status: RFQStatus
    notes: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None


# ============== MAIL POOL ==============

class MailPoolImportRequest(BaseModel):
    """Trigger mail pool categorisation job"""
    pass


class MailSenderClassification(str, Enum):
    CLIENT = "client"
    VENDOR = "vendor"
    PROMOTIONAL = "promotional"
    TRANSACTIONAL = "transactional"
    UNKNOWN = "unknown"
