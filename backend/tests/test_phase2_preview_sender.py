"""
PHASE 2 TESTS: PREVIEW RESOLUTION AND SENDER METADATA
======================================================

Tests for:
1. Preview resolution priority (gmail_summary → ai_summary → snippet)
2. Sender metadata persistence with confidence and source
3. Backend-defined preview contract enforcement

Run with: pytest backend/tests/test_phase2_preview_sender.py -v
"""

import pytest
from datetime import datetime
from typing import Dict, Any

# Import modules under test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_sync.models import (
    PreviewSource, SenderSource, SenderMetadata, 
    EmailType, SystemSubtype
)
from email_sync.preview_resolver import (
    resolve_preview,
    resolve_and_update_preview,
    build_sender_metadata,
    update_sender_from_crm,
    resolve_previews_batch,
    enrich_sender_metadata_batch
)


# ============================================
# TEST FIXTURES
# ============================================

@pytest.fixture
def email_with_gmail_summary() -> Dict[str, Any]:
    """Email with native Gmail summary (highest priority)"""
    return {
        "from_address": {"email": "john@acme.com", "name": "John Smith"},
        "subject": "Quarterly Report",
        "body_plain": "Please find attached the quarterly financial report for Q4 2025. Key highlights include revenue growth of 15% and...",
        "snippet": "Please find attached...",
        "gmail_summary": "John shared Q4 financial report with 15% revenue growth highlights",
        "ai_summary": None
    }


@pytest.fixture
def email_with_ai_summary() -> Dict[str, Any]:
    """Email with AI summary but no Gmail summary"""
    return {
        "from_address": {"email": "vendor@supplies.com", "name": "Vendor Team"},
        "subject": "Price Update",
        "body_plain": "We are writing to inform you that effective January 1, our prices will increase by 5% due to supply chain costs...",
        "snippet": "We are writing to inform...",
        "gmail_summary": None,
        "ai_summary": "Vendor announcing 5% price increase effective Jan 1 due to supply chain costs"
    }


@pytest.fixture
def email_with_snippet_only() -> Dict[str, Any]:
    """Email with only snippet (fallback)"""
    return {
        "from_address": {"email": "new@contact.com", "name": "New Contact"},
        "subject": "Introduction",
        "body_plain": "Hi, I found your company online and wanted to reach out about potential partnership opportunities.",
        "snippet": "Hi, I found your company online...",
        "gmail_summary": None,
        "ai_summary": None
    }


@pytest.fixture
def system_email_bounce() -> Dict[str, Any]:
    """System email (bounce) without any summary"""
    return {
        "from_address": {"email": "mailer-daemon@gmail.com", "name": "Mail Delivery Subsystem"},
        "subject": "Delivery Status Notification (Failure)",
        "body_plain": "Delivery to the following recipient failed permanently...",
        "snippet": "Delivery to the following...",
        "gmail_summary": None,
        "ai_summary": None,
        "email_type": EmailType.SYSTEM.value,
        "system_subtype": SystemSubtype.BOUNCE.value
    }


@pytest.fixture
def crm_contact() -> Dict[str, Any]:
    """CRM contact for sender matching"""
    return {
        "_id": "contact_123",
        "company_id": "company_456",
        "name": "John Smith",
        "email": "john@acme.com",
        "title": "VP of Sales",
        "company": "ACME Corporation"
    }


# ============================================
# TEST: PREVIEW RESOLUTION PRIORITY
# ============================================

class TestPreviewResolutionPriority:
    """Tests for preview resolution priority chain"""
    
    def test_gmail_summary_has_highest_priority(self, email_with_gmail_summary):
        """Gmail summary should be used when available"""
        preview, source = resolve_preview(email_with_gmail_summary)
        
        assert source == PreviewSource.GMAIL_SUMMARY
        assert "Q4 financial report" in preview
        assert "15% revenue growth" in preview
    
    def test_ai_summary_used_when_no_gmail(self, email_with_ai_summary):
        """AI summary should be used when Gmail summary unavailable"""
        preview, source = resolve_preview(email_with_ai_summary)
        
        assert source == PreviewSource.AI_SUMMARY
        assert "5% price increase" in preview
    
    def test_snippet_used_as_fallback(self, email_with_snippet_only):
        """Snippet should be used when no summaries available"""
        preview, source = resolve_preview(email_with_snippet_only)
        
        assert source == PreviewSource.SNIPPET
        assert "company online" in preview
    
    def test_system_email_gets_system_summary(self, system_email_bounce):
        """System emails should get deterministic system summary"""
        preview, source = resolve_preview(system_email_bounce)
        
        assert source == PreviewSource.SYSTEM_SUMMARY
        assert "delivery failure" in preview.lower() or "📧" in preview
    
    def test_empty_email_returns_none_source(self):
        """Email with no content returns NONE source"""
        empty_email = {
            "from_address": {"email": "test@test.com"},
            "subject": "",
            "body_plain": "",
            "snippet": "",
            "gmail_summary": None,
            "ai_summary": None
        }
        
        preview, source = resolve_preview(empty_email)
        
        assert source == PreviewSource.NONE
        assert preview == ""
    
    def test_gmail_summary_preferred_over_ai_summary(self):
        """When both summaries exist, Gmail summary wins"""
        email = {
            "from_address": {"email": "test@test.com"},
            "subject": "Test",
            "body_plain": "Test body",
            "snippet": "Test...",
            "gmail_summary": "Gmail version of summary",
            "ai_summary": "AI version of summary"
        }
        
        preview, source = resolve_preview(email)
        
        assert source == PreviewSource.GMAIL_SUMMARY
        assert "Gmail version" in preview


class TestPreviewResolutionBehavior:
    """Tests for preview resolution edge cases and behavior"""
    
    def test_preview_truncated_to_max_length(self):
        """Long summaries should be truncated with ellipsis"""
        email = {
            "from_address": {"email": "test@test.com"},
            "subject": "Test",
            "gmail_summary": "A" * 500  # 500 characters
        }
        
        preview, source = resolve_preview(email, max_length=160)
        
        assert len(preview) <= 160
        assert preview.endswith("...")
    
    def test_resolve_and_update_modifies_dict(self, email_with_gmail_summary):
        """resolve_and_update_preview should modify dict in place"""
        assert "resolved_preview" not in email_with_gmail_summary
        
        result = resolve_and_update_preview(email_with_gmail_summary)
        
        assert "resolved_preview" in result
        assert result["preview_source"] == PreviewSource.GMAIL_SUMMARY.value
    
    def test_already_resolved_returns_cached(self):
        """If resolved_preview exists, return it without re-resolving"""
        email = {
            "resolved_preview": "Cached preview",
            "preview_source": PreviewSource.AI_SUMMARY.value,
            "gmail_summary": "New Gmail summary"  # Should be ignored
        }
        
        preview, source = resolve_preview(email)
        
        assert preview == "Cached preview"
        assert source == PreviewSource.AI_SUMMARY
    
    def test_batch_resolution(self, email_with_gmail_summary, email_with_ai_summary, email_with_snippet_only):
        """Batch resolution should work for multiple emails"""
        emails = [
            email_with_gmail_summary.copy(),
            email_with_ai_summary.copy(),
            email_with_snippet_only.copy()
        ]
        
        result = resolve_previews_batch(emails)
        
        assert len(result) == 3
        assert result[0]["preview_source"] == PreviewSource.GMAIL_SUMMARY.value
        assert result[1]["preview_source"] == PreviewSource.AI_SUMMARY.value
        assert result[2]["preview_source"] == PreviewSource.SNIPPET.value


# ============================================
# TEST: SENDER METADATA
# ============================================

class TestSenderMetadata:
    """Tests for sender metadata building with confidence"""
    
    def test_build_from_header_only(self):
        """Sender from header should have baseline confidence"""
        from_address = {"email": "unknown@newcompany.com", "name": "Unknown Person"}
        
        metadata = build_sender_metadata(from_address)
        
        assert metadata.email == "unknown@newcompany.com"
        assert metadata.name == "Unknown Person"
        assert metadata.domain == "newcompany.com"
        assert metadata.source == SenderSource.EMAIL_HEADER
        assert metadata.confidence == 0.5  # Baseline
    
    def test_crm_match_increases_confidence(self, crm_contact):
        """CRM match should give highest confidence"""
        from_address = {"email": "john@acme.com", "name": "J Smith"}
        
        metadata = build_sender_metadata(from_address, crm_contact=crm_contact)
        
        assert metadata.source == SenderSource.CRM_CONTACT
        assert metadata.confidence == 0.95
        assert metadata.crm_contact_id == "contact_123"
        assert metadata.crm_company_id == "company_456"
        assert metadata.name == "John Smith"  # CRM name overrides header
    
    def test_ai_extraction_medium_confidence(self):
        """AI extraction without CRM should have medium confidence"""
        from_address = {"email": "new@company.com", "name": ""}
        ai_extraction = {
            "name": "Sarah Johnson",
            "title": "Marketing Director",
            "company": "TechCorp Inc",
            "phone": "+1-555-123-4567"
        }
        
        metadata = build_sender_metadata(from_address, ai_extraction=ai_extraction)
        
        assert metadata.source == SenderSource.AI_EXTRACTION
        assert metadata.confidence == 0.75
        assert metadata.extracted_name == "Sarah Johnson"
        assert metadata.extracted_title == "Marketing Director"
        assert metadata.extracted_company == "TechCorp Inc"
        assert metadata.extracted_phone == "+1-555-123-4567"
    
    def test_crm_overrides_ai_extraction(self, crm_contact):
        """CRM match should override AI extraction for source/confidence"""
        from_address = {"email": "john@acme.com", "name": ""}
        ai_extraction = {
            "name": "John S.",
            "title": "Salesperson"
        }
        
        metadata = build_sender_metadata(
            from_address, 
            crm_contact=crm_contact,
            ai_extraction=ai_extraction
        )
        
        assert metadata.source == SenderSource.CRM_CONTACT
        assert metadata.confidence == 0.95
        # AI extraction should still be preserved
        assert metadata.extracted_name == "John S."
    
    def test_historical_context_added(self):
        """Email history should be included in metadata"""
        from_address = {"email": "repeat@customer.com", "name": "Repeat Customer"}
        history = {
            "first_seen_at": datetime(2024, 1, 1),
            "last_email_at": datetime(2026, 1, 20),
            "count": 47
        }
        
        metadata = build_sender_metadata(from_address, email_history=history)
        
        assert metadata.email_count == 47
        assert metadata.first_seen_at == datetime(2024, 1, 1)
        assert metadata.last_email_at == datetime(2026, 1, 20)
    
    def test_update_sender_from_crm(self, crm_contact):
        """Existing sender metadata should be updatable with CRM match"""
        existing = SenderMetadata(
            email="john@acme.com",
            name="J. Smith",
            source=SenderSource.EMAIL_HEADER,
            confidence=0.5
        )
        
        updated = update_sender_from_crm(existing, crm_contact)
        
        assert updated.source == SenderSource.CRM_CONTACT
        assert updated.confidence == 0.95
        assert updated.crm_contact_id == "contact_123"
        assert updated.name == "John Smith"


class TestSenderMetadataBatch:
    """Tests for batch sender metadata enrichment"""
    
    def test_batch_enrichment_with_crm_matches(self):
        """Batch enrichment should match emails to CRM contacts"""
        emails = [
            {"from_address": {"email": "john@acme.com", "name": "John"}},
            {"from_address": {"email": "unknown@random.com", "name": "Unknown"}},
            {"from_address": {"email": "jane@partner.com", "name": "Jane"}}
        ]
        
        crm_contacts = {
            "john@acme.com": {"_id": "c1", "name": "John Smith", "company_id": "co1"},
            "jane@partner.com": {"_id": "c2", "name": "Jane Doe", "company_id": "co2"}
        }
        
        result = enrich_sender_metadata_batch(emails, crm_contacts)
        
        # John should have CRM match
        assert result[0]["sender_metadata"]["source"] == SenderSource.CRM_CONTACT.value
        assert result[0]["sender_metadata"]["confidence"] == 0.95
        
        # Unknown should have header only
        assert result[1]["sender_metadata"]["source"] == SenderSource.EMAIL_HEADER.value
        assert result[1]["sender_metadata"]["confidence"] == 0.5
        
        # Jane should have CRM match
        assert result[2]["sender_metadata"]["source"] == SenderSource.CRM_CONTACT.value


# ============================================
# TEST: BACKEND CONTRACT ENFORCEMENT
# ============================================

class TestBackendContract:
    """Tests ensuring backend-defined contract is enforced"""
    
    def test_preview_source_always_set(self):
        """Preview source should always be set after resolution"""
        emails = [
            {"from_address": {"email": "a@a.com"}, "gmail_summary": "Summary"},
            {"from_address": {"email": "b@b.com"}, "ai_summary": "Summary"},
            {"from_address": {"email": "c@c.com"}, "snippet": "Snippet"},
            {"from_address": {"email": "d@d.com"}}  # Empty
        ]
        
        for email in emails:
            resolve_and_update_preview(email)
            assert "preview_source" in email
            assert email["preview_source"] in [s.value for s in PreviewSource]
    
    def test_sender_metadata_always_has_confidence(self):
        """Sender metadata should always have confidence score"""
        test_cases = [
            {"email": "test@test.com"},
            {"email": "test@test.com", "name": "Test"},
        ]
        
        for from_address in test_cases:
            metadata = build_sender_metadata(from_address)
            assert 0.0 <= metadata.confidence <= 1.0
    
    def test_sender_metadata_always_has_source(self):
        """Sender metadata should always have source"""
        metadata = build_sender_metadata({"email": "any@email.com"})
        assert metadata.source in list(SenderSource)


# ============================================
# RUN TESTS
# ============================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
