"""
PREVIEW RESOLVER
================

Backend-defined preview resolution for email previews.

Phase 2 Requirement: Backend defines the preview resolution contract.
Frontend MUST NOT implement resolution logic - use resolved_preview field.

Resolution Priority:
1. gmail_summary - Native Gmail summary (highest quality, most context-aware)
2. ai_summary - AI-generated summary (for classified emails)
3. system_summary - Deterministic summary for system emails (bounce/OOO/etc)
4. snippet - Truncated body preview (fallback for unprocessed emails)

Usage:
    from email_sync.preview_resolver import resolve_preview, build_sender_metadata
    
    # Resolve preview for an email document
    preview, source = resolve_preview(email_dict)
    
    # Build sender metadata with confidence
    sender = build_sender_metadata(from_address, crm_match=contact)
"""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime

from .models import PreviewSource, SenderMetadata, SenderSource, EmailType, SystemSubtype


# ============== CONSTANTS ==============

MAX_PREVIEW_LENGTH = 160  # SMS/inbox preview standard length
SNIPPET_FALLBACK_LENGTH = 200


# ============== PREVIEW RESOLUTION ==============

def resolve_preview(
    email: Dict[str, Any],
    max_length: int = MAX_PREVIEW_LENGTH
) -> Tuple[str, PreviewSource]:
    """
    Resolve the best available preview for an email.
    
    Priority:
    1. gmail_summary (native Gmail, highest quality)
    2. ai_summary (AI-generated for classified emails)
    3. snippet (truncated body, fallback)
    
    For system emails, generates deterministic summary if not already set.
    
    Args:
        email: Email document dict
        max_length: Maximum preview length (default 160)
        
    Returns:
        Tuple of (preview_text, source_enum)
    """
    # Already resolved? Return it
    if email.get("resolved_preview"):
        source = email.get("preview_source", PreviewSource.SNIPPET.value)
        if isinstance(source, str):
            try:
                source = PreviewSource(source)
            except ValueError:
                source = PreviewSource.SNIPPET
        return email["resolved_preview"], source
    
    # Priority 1: Gmail summary (native, highest quality)
    gmail_summary = email.get("gmail_summary")
    if gmail_summary and gmail_summary.strip():
        preview = _truncate_preview(gmail_summary, max_length)
        return preview, PreviewSource.GMAIL_SUMMARY
    
    # Priority 2: AI summary (for classified emails)
    ai_summary = email.get("ai_summary")
    if ai_summary and ai_summary.strip():
        preview = _truncate_preview(ai_summary, max_length)
        return preview, PreviewSource.AI_SUMMARY
    
    # Priority 3: System email summary (deterministic)
    if email.get("email_type") == EmailType.SYSTEM.value:
        system_summary = _generate_system_preview(email)
        return system_summary, PreviewSource.SYSTEM_SUMMARY
    
    # Priority 4: Snippet (fallback)
    snippet = email.get("snippet", "")
    if snippet and snippet.strip():
        preview = _truncate_preview(snippet, max_length)
        return preview, PreviewSource.SNIPPET
    
    # No preview available
    return "", PreviewSource.NONE


def resolve_and_update_preview(email: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve preview and update the email dict in-place.
    
    Returns the updated email dict with resolved_preview and preview_source set.
    """
    preview, source = resolve_preview(email)
    email["resolved_preview"] = preview
    email["preview_source"] = source.value
    return email


def _truncate_preview(text: str, max_length: int) -> str:
    """Truncate preview to max length with ellipsis."""
    text = text.strip()
    if len(text) <= max_length:
        return text
    return text[:max_length - 3].rstrip() + "..."


def _generate_system_preview(email: Dict[str, Any]) -> str:
    """
    Generate deterministic preview for system emails.
    
    This is a lightweight version that doesn't need full detection.
    Full summaries should already be set during ingestion.
    """
    system_subtype = email.get("system_subtype")
    subject = email.get("subject", "")
    
    if system_subtype == SystemSubtype.BOUNCE.value:
        return "📧 Delivery failure notification"
    elif system_subtype == SystemSubtype.OUT_OF_OFFICE.value:
        return "🏖️ Out of office auto-reply"
    elif system_subtype == SystemSubtype.AUTO_REPLY.value:
        return "🤖 Automated response"
    elif system_subtype == SystemSubtype.UNSUBSCRIBE.value:
        return "📭 Unsubscribe confirmation"
    else:
        # Fallback to subject truncation
        return _truncate_preview(subject, MAX_PREVIEW_LENGTH) if subject else "System email"


# ============== SENDER METADATA ==============

def build_sender_metadata(
    from_address: Dict[str, Any],
    crm_contact: Optional[Dict[str, Any]] = None,
    ai_extraction: Optional[Dict[str, Any]] = None,
    email_history: Optional[Dict[str, Any]] = None
) -> SenderMetadata:
    """
    Build rich sender metadata with confidence scoring.
    
    Args:
        from_address: Parsed email From: header (email, name)
        crm_contact: Matched CRM contact if found
        ai_extraction: AI-extracted info from signature/body
        email_history: Historical email stats for this sender
        
    Returns:
        SenderMetadata with appropriate source and confidence
    """
    email = _extract_email_string(from_address)
    name = from_address.get("name", "") if isinstance(from_address, dict) else ""
    domain = email.split("@")[1] if "@" in email else None
    
    # Start with header data (baseline confidence)
    metadata = SenderMetadata(
        email=email,
        name=name or None,
        domain=domain,
        source=SenderSource.EMAIL_HEADER,
        confidence=0.5  # Header-only baseline
    )
    
    # Enhance with CRM match (highest confidence)
    if crm_contact:
        metadata.crm_contact_id = str(crm_contact.get("_id", crm_contact.get("id")))
        metadata.crm_company_id = crm_contact.get("company_id")
        if crm_contact.get("name"):
            metadata.name = crm_contact["name"]
        metadata.source = SenderSource.CRM_CONTACT
        metadata.confidence = 0.95  # CRM match is highly reliable
    
    # Enhance with AI extraction (medium-high confidence)
    if ai_extraction:
        metadata.extracted_name = ai_extraction.get("name")
        metadata.extracted_title = ai_extraction.get("title")
        metadata.extracted_company = ai_extraction.get("company")
        metadata.extracted_phone = ai_extraction.get("phone")
        
        # If no CRM match, AI extraction is our best source
        if not crm_contact:
            metadata.source = SenderSource.AI_EXTRACTION
            metadata.confidence = 0.75
    
    # Add historical context
    if email_history:
        metadata.first_seen_at = email_history.get("first_seen_at")
        metadata.last_email_at = email_history.get("last_email_at")
        metadata.email_count = email_history.get("count", 0)
    
    return metadata


def update_sender_from_crm(
    existing: SenderMetadata,
    crm_contact: Dict[str, Any]
) -> SenderMetadata:
    """
    Update existing sender metadata with CRM contact match.
    
    Called when a CRM contact is later linked to an email.
    """
    existing.crm_contact_id = str(crm_contact.get("_id", crm_contact.get("id")))
    existing.crm_company_id = crm_contact.get("company_id")
    if crm_contact.get("name"):
        existing.name = crm_contact["name"]
    existing.source = SenderSource.CRM_CONTACT
    existing.confidence = 0.95
    return existing


def _extract_email_string(from_address: Any) -> str:
    """Extract email string from various formats."""
    if isinstance(from_address, dict):
        return from_address.get("email", "") or from_address.get("address", "")
    elif isinstance(from_address, str):
        # Handle "Name <email>" format
        import re
        match = re.search(r"<([^>]+)>", from_address)
        if match:
            return match.group(1)
        return from_address
    return ""


# ============== BATCH OPERATIONS ==============

def resolve_previews_batch(emails: list) -> list:
    """
    Resolve previews for a batch of emails.
    
    Used during sync and API responses.
    """
    for email in emails:
        resolve_and_update_preview(email)
    return emails


def enrich_sender_metadata_batch(
    emails: list,
    crm_contacts_by_email: Dict[str, Dict[str, Any]]
) -> list:
    """
    Enrich sender metadata for a batch of emails with CRM matches.
    
    Args:
        emails: List of email dicts
        crm_contacts_by_email: Dict mapping email addresses to CRM contacts
        
    Returns:
        Updated emails list
    """
    for email in emails:
        from_address = email.get("from_address", {})
        sender_email = _extract_email_string(from_address)
        
        crm_contact = crm_contacts_by_email.get(sender_email.lower())
        
        metadata = build_sender_metadata(
            from_address=from_address,
            crm_contact=crm_contact
        )
        
        email["sender_metadata"] = metadata.model_dump()
    
    return emails
