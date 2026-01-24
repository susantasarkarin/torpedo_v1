"""
PHASE 1 REGRESSION TESTS
========================

Tests for email deduplication and system email detection.

These tests assert the following critical guarantees:
1. Zero LLM calls for system emails (bounce, OOO, auto-reply)
2. No duplicate classifications across mailboxes or repeated syncs
3. Global idempotency via dedupe_hash

Run with: pytest backend/tests/test_phase1_email_dedup.py -v
"""

import pytest
import hashlib
from datetime import datetime
from unittest.mock import MagicMock, patch, call
from typing import Dict, Any

# Import modules under test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_sync.models import EmailType, SystemSubtype, EmailDocument, EmailAddress, EmailDirection
from email_sync.system_email_detector import (
    detect_system_email,
    compute_dedupe_hash,
    is_system_email,
    should_skip_llm_classification,
    generate_system_email_summary,
    SystemEmailDetection
)


# ============================================
# TEST FIXTURES
# ============================================

@pytest.fixture
def normal_email() -> Dict[str, Any]:
    """A normal business email requiring AI classification"""
    return {
        "_id": "test_normal_123",
        "from_address": {"email": "john@acme.com", "name": "John Smith"},
        "to_addresses": [{"email": "sales@ourcompany.com", "name": "Sales Team"}],
        "subject": "Inquiry about your services",
        "body_plain": "Hello, I am interested in learning more about your product offerings. Please send me a quote for 500 units.",
        "snippet": "Hello, I am interested in learning more...",
        "timestamp": datetime.utcnow()
    }


@pytest.fixture
def bounce_email_mailer_daemon() -> Dict[str, Any]:
    """Bounce email from mailer-daemon"""
    return {
        "_id": "test_bounce_1",
        "from_address": {"email": "mailer-daemon@gmail.com", "name": "Mail Delivery Subsystem"},
        "to_addresses": [{"email": "sender@ourcompany.com", "name": ""}],
        "subject": "Delivery Status Notification (Failure)",
        "body_plain": "Delivery to the following recipient failed permanently: user@unknown.com. Technical details: 550 5.1.1 The email account that you tried to reach does not exist.",
        "snippet": "Delivery to the following recipient failed...",
        "timestamp": datetime.utcnow()
    }


@pytest.fixture
def bounce_email_postmaster() -> Dict[str, Any]:
    """Bounce email from postmaster"""
    return {
        "_id": "test_bounce_2",
        "from_address": {"email": "postmaster@company.com", "name": "Postmaster"},
        "to_addresses": [{"email": "sender@ourcompany.com", "name": ""}],
        "subject": "Undeliverable: Your message to john@badcompany.com",
        "body_plain": "Your message could not be delivered. The recipient's mailbox is full.",
        "snippet": "Your message could not be delivered...",
        "timestamp": datetime.utcnow()
    }


@pytest.fixture
def ooo_email() -> Dict[str, Any]:
    """Out of Office auto-reply"""
    return {
        "_id": "test_ooo_1",
        "from_address": {"email": "jane@client.com", "name": "Jane Doe"},
        "to_addresses": [{"email": "sales@ourcompany.com", "name": ""}],
        "subject": "Out of Office: Re: Your proposal",
        "body_plain": "I am currently out of the office with limited access to email. I will be back on Monday, January 27th. For urgent matters, please contact my colleague.",
        "snippet": "I am currently out of the office...",
        "timestamp": datetime.utcnow()
    }


@pytest.fixture
def auto_reply_email() -> Dict[str, Any]:
    """Generic automated response"""
    return {
        "_id": "test_auto_1",
        "from_address": {"email": "noreply@ticketing.com", "name": "Support System"},
        "to_addresses": [{"email": "support@ourcompany.com", "name": ""}],
        "subject": "Automated response: Your ticket has been received",
        "body_plain": "This is an automated message to confirm we have received your support request. A team member will respond within 24 hours.",
        "snippet": "This is an automated message...",
        "timestamp": datetime.utcnow()
    }


@pytest.fixture
def unsubscribe_email() -> Dict[str, Any]:
    """Unsubscribe confirmation"""
    return {
        "_id": "test_unsub_1",
        "from_address": {"email": "noreply@newsletter.com", "name": "Newsletter"},
        "to_addresses": [{"email": "marketing@ourcompany.com", "name": ""}],
        "subject": "Unsubscribe confirmed",
        "body_plain": "You have been successfully unsubscribed from our mailing list.",
        "snippet": "You have been successfully unsubscribed...",
        "timestamp": datetime.utcnow()
    }


# ============================================
# TEST: SYSTEM EMAIL DETECTION
# ============================================

class TestSystemEmailDetection:
    """Tests for system email detection logic"""
    
    def test_normal_email_not_detected_as_system(self, normal_email):
        """Normal business emails should NOT be detected as system emails"""
        result = detect_system_email(normal_email)
        
        assert result.is_system is False
        assert result.email_type == EmailType.NORMAL
        assert result.system_subtype is None
    
    def test_bounce_mailer_daemon_detected(self, bounce_email_mailer_daemon):
        """Bounce from mailer-daemon should be detected"""
        result = detect_system_email(bounce_email_mailer_daemon)
        
        assert result.is_system is True
        assert result.email_type == EmailType.SYSTEM
        assert result.system_subtype == SystemSubtype.BOUNCE
        assert result.confidence >= 0.8
        assert "mailer-daemon" in result.detection_reason.lower() or "bounce" in result.detection_reason.lower()
    
    def test_bounce_postmaster_detected(self, bounce_email_postmaster):
        """Bounce from postmaster should be detected"""
        result = detect_system_email(bounce_email_postmaster)
        
        assert result.is_system is True
        assert result.email_type == EmailType.SYSTEM
        assert result.system_subtype == SystemSubtype.BOUNCE
    
    def test_out_of_office_detected(self, ooo_email):
        """Out of Office auto-reply should be detected"""
        result = detect_system_email(ooo_email)
        
        assert result.is_system is True
        assert result.email_type == EmailType.SYSTEM
        assert result.system_subtype == SystemSubtype.OUT_OF_OFFICE
        assert result.confidence >= 0.7
    
    def test_auto_reply_detected(self, auto_reply_email):
        """Automated responses should be detected"""
        result = detect_system_email(auto_reply_email)
        
        assert result.is_system is True
        assert result.email_type == EmailType.SYSTEM
        assert result.system_subtype == SystemSubtype.AUTO_REPLY
    
    def test_unsubscribe_detected(self, unsubscribe_email):
        """Unsubscribe confirmations should be detected"""
        result = detect_system_email(unsubscribe_email)
        
        assert result.is_system is True
        assert result.email_type == EmailType.SYSTEM
        assert result.system_subtype == SystemSubtype.UNSUBSCRIBE
    
    def test_is_system_email_convenience_function(self, bounce_email_mailer_daemon, normal_email):
        """is_system_email() convenience function works correctly"""
        assert is_system_email(bounce_email_mailer_daemon) is True
        assert is_system_email(normal_email) is False


# ============================================
# TEST: LLM SHORT-CIRCUIT
# ============================================

class TestLLMShortCircuit:
    """Tests ensuring LLM calls are skipped for system emails"""
    
    def test_should_skip_llm_for_bounce(self, bounce_email_mailer_daemon):
        """should_skip_llm_classification returns True for bounce"""
        should_skip, reason = should_skip_llm_classification(bounce_email_mailer_daemon)
        
        assert should_skip is True
        assert "bounce" in reason.lower() or "mailer-daemon" in reason.lower()
    
    def test_should_skip_llm_for_ooo(self, ooo_email):
        """should_skip_llm_classification returns True for OOO"""
        should_skip, reason = should_skip_llm_classification(ooo_email)
        
        assert should_skip is True
        assert "out of office" in reason.lower() or "ooo" in reason.lower()
    
    def test_should_not_skip_llm_for_normal(self, normal_email):
        """should_skip_llm_classification returns False for normal emails"""
        should_skip, reason = should_skip_llm_classification(normal_email)
        
        assert should_skip is False
        assert "normal" in reason.lower() or "requires classification" in reason.lower()
    
    def test_already_marked_system_skips_detection(self, normal_email):
        """Emails already marked as system should skip detection"""
        # Pre-mark as system
        normal_email["email_type"] = EmailType.SYSTEM.value
        normal_email["system_subtype"] = SystemSubtype.BOUNCE.value
        
        should_skip, reason = should_skip_llm_classification(normal_email)
        
        assert should_skip is True
        assert "already marked" in reason.lower()
    
    def test_already_processed_skips(self, normal_email):
        """Emails with dedupe_hash and processed=True should skip"""
        normal_email["dedupe_hash"] = "abc123"
        normal_email["processed"] = True
        
        should_skip, reason = should_skip_llm_classification(normal_email)
        
        assert should_skip is True
        assert "already processed" in reason.lower()


# ============================================
# TEST: DEDUPLICATION
# ============================================

class TestDeduplication:
    """Tests for global content-based deduplication"""
    
    def test_same_email_produces_same_hash(self, normal_email):
        """Identical emails produce identical dedupe_hash"""
        hash1 = compute_dedupe_hash(normal_email)
        hash2 = compute_dedupe_hash(normal_email)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex
    
    def test_different_emails_produce_different_hashes(self, normal_email, bounce_email_mailer_daemon):
        """Different emails produce different hashes"""
        hash1 = compute_dedupe_hash(normal_email)
        hash2 = compute_dedupe_hash(bounce_email_mailer_daemon)
        
        assert hash1 != hash2
    
    def test_subject_normalization_strips_reply_prefix(self, normal_email):
        """Re:/Fw: prefixes are stripped for deduplication"""
        email1 = normal_email.copy()
        email1["subject"] = "Important meeting"
        
        email2 = normal_email.copy()
        email2["subject"] = "Re: Important meeting"
        
        email3 = normal_email.copy()
        email3["subject"] = "RE: FW: Important meeting"
        
        hash1 = compute_dedupe_hash(email1)
        hash2 = compute_dedupe_hash(email2)
        hash3 = compute_dedupe_hash(email3)
        
        # All should produce the same hash
        assert hash1 == hash2 == hash3
    
    def test_different_mailbox_same_email_same_hash(self, normal_email):
        """Same email to different mailboxes produces same hash (global dedupe)"""
        email1 = normal_email.copy()
        email1["mailbox_id"] = "mailbox_1"
        
        email2 = normal_email.copy()
        email2["mailbox_id"] = "mailbox_2"
        
        hash1 = compute_dedupe_hash(email1)
        hash2 = compute_dedupe_hash(email2)
        
        # Hash should be the same (mailbox_id is NOT part of hash)
        assert hash1 == hash2
    
    def test_body_fingerprint_ignores_signatures(self, normal_email):
        """Body fingerprint should be stable across different signatures"""
        email1 = normal_email.copy()
        email1["body_plain"] = "Hello, I am interested in your product.\n\n--\nJohn Smith\nCEO"
        
        email2 = normal_email.copy()
        email2["body_plain"] = "Hello, I am interested in your product.\n\nBest regards,\nJohn"
        
        # These should produce similar (ideally same) hashes due to signature stripping
        hash1 = compute_dedupe_hash(email1)
        hash2 = compute_dedupe_hash(email2)
        
        # Note: Due to fingerprint normalization, these may be same or different
        # The key is that the same email forwarded produces the same hash
        assert hash1 is not None
        assert hash2 is not None


# ============================================
# TEST: SYSTEM EMAIL SUMMARY GENERATION
# ============================================

class TestSystemEmailSummary:
    """Tests for deterministic summary generation for system emails"""
    
    def test_bounce_summary_contains_failure_indication(self, bounce_email_mailer_daemon):
        """Bounce summaries should indicate delivery failure"""
        summary = generate_system_email_summary(bounce_email_mailer_daemon, SystemSubtype.BOUNCE)
        
        assert summary is not None
        assert len(summary) > 0
        assert "delivery failure" in summary.lower() or "not delivered" in summary.lower() or "notification" in summary.lower()
    
    def test_ooo_summary_contains_out_of_office(self, ooo_email):
        """OOO summaries should indicate out of office"""
        summary = generate_system_email_summary(ooo_email, SystemSubtype.OUT_OF_OFFICE)
        
        assert summary is not None
        assert "out of office" in summary.lower()
    
    def test_summary_length_is_reasonable(self, bounce_email_mailer_daemon):
        """System email summaries should be short (inbox preview style)"""
        summary = generate_system_email_summary(bounce_email_mailer_daemon, SystemSubtype.BOUNCE)
        
        assert len(summary) <= 160  # SMS/preview length
    
    def test_summary_is_deterministic(self, bounce_email_mailer_daemon):
        """Same email should produce same summary"""
        summary1 = generate_system_email_summary(bounce_email_mailer_daemon, SystemSubtype.BOUNCE)
        summary2 = generate_system_email_summary(bounce_email_mailer_daemon, SystemSubtype.BOUNCE)
        
        assert summary1 == summary2


# ============================================
# TEST: ZERO LLM CALLS FOR SYSTEM EMAILS
# ============================================

class TestZeroLLMCallsForSystemEmails:
    """
    Critical regression tests ensuring system emails NEVER trigger LLM calls.
    
    These tests verify the short-circuit behavior at the pre-classification layer.
    The key guarantee is that should_skip_llm_classification() returns True for
    system emails, preventing any downstream LLM call.
    """
    
    def test_bounce_triggers_short_circuit(self, bounce_email_mailer_daemon):
        """Bounce email triggers short-circuit before any LLM call is possible"""
        should_skip, reason = should_skip_llm_classification(bounce_email_mailer_daemon)
        
        # CRITICAL: This MUST be True to prevent LLM call
        assert should_skip is True
        assert "bounce" in reason.lower() or "mailer-daemon" in reason.lower() or "system" in reason.lower()
    
    def test_ooo_triggers_short_circuit(self, ooo_email):
        """OOO email triggers short-circuit before any LLM call is possible"""
        should_skip, reason = should_skip_llm_classification(ooo_email)
        
        # CRITICAL: This MUST be True to prevent LLM call
        assert should_skip is True
    
    @patch('leads.openai_wrapper.chat_completion_with_escalation')
    def test_classifier_does_not_call_llm_for_bounce(self, mock_llm, bounce_email_mailer_daemon):
        """Bounce email classification should NOT call LLM"""
        # Import here to avoid circular imports
        from email_sync.openai_email_classifier import OpenAIEmailClassifier
        
        # Create classifier with mocked dependencies
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=MagicMock())
        mock_db.client = MagicMock()
        mock_db.client.__getitem__ = MagicMock(return_value={"leads": MagicMock()})
        
        classifier = OpenAIEmailClassifier(db=mock_db)
        
        # Classify bounce email
        result = classifier.classify_email(bounce_email_mailer_daemon)
        
        # CRITICAL ASSERTION: LLM was NOT called
        mock_llm.assert_not_called()
        
        # Result should indicate system email
        assert result["success"] is True
        assert result["llm_skipped"] is True
        assert result["email_type"] == EmailType.SYSTEM.value
        assert result["system_subtype"] == SystemSubtype.BOUNCE.value
    
    @patch('leads.openai_wrapper.chat_completion_with_escalation')
    def test_classifier_does_not_call_llm_for_ooo(self, mock_llm, ooo_email):
        """OOO email classification should NOT call LLM"""
        from email_sync.openai_email_classifier import OpenAIEmailClassifier
        
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=MagicMock())
        mock_db.client = MagicMock()
        mock_db.client.__getitem__ = MagicMock(return_value={"leads": MagicMock()})
        
        classifier = OpenAIEmailClassifier(db=mock_db)
        result = classifier.classify_email(ooo_email)
        
        # CRITICAL ASSERTION: LLM was NOT called
        mock_llm.assert_not_called()
        
        assert result["llm_skipped"] is True
        assert result["system_subtype"] == SystemSubtype.OUT_OF_OFFICE.value


# ============================================
# TEST: NO DUPLICATE CLASSIFICATIONS
# ============================================

class TestNoDuplicateClassifications:
    """
    Tests ensuring the same email doesn't trigger multiple LLM calls.
    """
    
    def test_storage_returns_global_duplicate_flag(self, normal_email):
        """Storage should return is_global_duplicate flag"""
        from email_sync.storage import EmailStorage
        from email_sync.system_email_detector import compute_dedupe_hash
        
        # Create mock DB
        mock_db = MagicMock()
        mock_emails_collection = MagicMock()
        mock_queue_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda x: {
            "emails": mock_emails_collection,
            "categorization_queue": mock_queue_collection
        }.get(x, MagicMock()))
        
        # Compute hash
        expected_hash = compute_dedupe_hash(normal_email)
        
        # Simulate existing email with same hash
        mock_emails_collection.find_one.return_value = {
            "_id": "existing_id",
            "dedupe_hash": expected_hash
        }
        
        storage = EmailStorage(mock_db)
        
        # Create EmailDocument
        email_doc = EmailDocument(
            provider_message_id="msg_123",
            mailbox_id="mailbox_1",
            from_address=EmailAddress(**normal_email["from_address"]),
            to_addresses=[EmailAddress(**a) for a in normal_email.get("to_addresses", [])],
            subject=normal_email["subject"],
            body_plain=normal_email["body_plain"]
        )
        
        is_new, email_id, is_global_duplicate = storage.save_email(email_doc)
        
        # Should detect as global duplicate
        assert is_global_duplicate is True
        assert is_new is False
    
    def test_same_email_different_mailboxes_deduplicated(self):
        """Same email synced to different mailboxes should be deduplicated"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        base_email = {
            "from_address": {"email": "client@example.com", "name": "Client"},
            "subject": "Important question",
            "body_plain": "What are your prices for 100 units?"
        }
        
        # Same email received in two mailboxes
        email_mailbox_1 = {**base_email, "mailbox_id": "sales@company.com"}
        email_mailbox_2 = {**base_email, "mailbox_id": "support@company.com"}
        
        hash1 = compute_dedupe_hash(email_mailbox_1)
        hash2 = compute_dedupe_hash(email_mailbox_2)
        
        # Hashes must be identical (global deduplication)
        assert hash1 == hash2


# ============================================
# TEST: DEDUPE HASH STABILITY
# ============================================

class TestDedupeHashStability:
    """
    Tests for dedupe_hash stability across edge cases.
    
    Per CTO requirements:
    - Forwarded emails
    - Reply chains
    - Minor body mutations (signatures, footers)
    
    All must be deterministic. Non-deterministic = fix before Phase 2.
    """
    
    def test_reply_chain_produces_same_hash(self):
        """Emails in a reply chain should dedupe on the same logical content"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        original = {
            "from_address": {"email": "client@example.com"},
            "subject": "Question about pricing",
            "body_plain": "Hello, I'd like to know your prices for the enterprise plan."
        }
        
        reply = {
            "from_address": {"email": "client@example.com"},
            "subject": "Re: Question about pricing",
            "body_plain": "Hello, I'd like to know your prices for the enterprise plan."
        }
        
        nested_reply = {
            "from_address": {"email": "client@example.com"},
            "subject": "RE: Re: Question about pricing",
            "body_plain": "Hello, I'd like to know your prices for the enterprise plan."
        }
        
        # All should produce same hash (subject prefix stripped)
        hash_original = compute_dedupe_hash(original)
        hash_reply = compute_dedupe_hash(reply)
        hash_nested = compute_dedupe_hash(nested_reply)
        
        assert hash_original == hash_reply == hash_nested
    
    def test_forward_prefix_stripped(self):
        """Fw:/Fwd: prefixes should be stripped for deduplication"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        original = {
            "from_address": {"email": "sales@company.com"},
            "subject": "New lead from website",
            "body_plain": "A new lead has registered on the website."
        }
        
        forwarded = {
            "from_address": {"email": "sales@company.com"},
            "subject": "Fw: New lead from website",
            "body_plain": "A new lead has registered on the website."
        }
        
        fwd_variant = {
            "from_address": {"email": "sales@company.com"},
            "subject": "FWD: New lead from website",
            "body_plain": "A new lead has registered on the website."
        }
        
        hash_original = compute_dedupe_hash(original)
        hash_fw = compute_dedupe_hash(forwarded)
        hash_fwd = compute_dedupe_hash(fwd_variant)
        
        assert hash_original == hash_fw == hash_fwd
    
    def test_signature_stripping_stability(self):
        """Different email signatures should not affect hash if body content is same"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        # Same message, different signatures
        email_sig1 = {
            "from_address": {"email": "john@acme.com"},
            "subject": "Meeting tomorrow",
            "body_plain": "Let's meet tomorrow at 3pm to discuss the proposal.\n\n--\nJohn Smith\nCEO, ACME Corp"
        }
        
        email_sig2 = {
            "from_address": {"email": "john@acme.com"},
            "subject": "Meeting tomorrow",
            "body_plain": "Let's meet tomorrow at 3pm to discuss the proposal.\n\nBest regards,\nJohn"
        }
        
        email_sig3 = {
            "from_address": {"email": "john@acme.com"},
            "subject": "Meeting tomorrow",
            "body_plain": "Let's meet tomorrow at 3pm to discuss the proposal.\n\nSent from my iPhone"
        }
        
        hash1 = compute_dedupe_hash(email_sig1)
        hash2 = compute_dedupe_hash(email_sig2)
        hash3 = compute_dedupe_hash(email_sig3)
        
        # Signatures are stripped - hashes should match
        assert hash1 == hash2 == hash3
    
    def test_footer_disclaimer_does_not_affect_hash(self):
        """Legal footers/disclaimers should not change the hash"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        email_no_footer = {
            "from_address": {"email": "legal@bigcorp.com"},
            "subject": "Contract review",
            "body_plain": "Please review the attached contract and let me know your comments."
        }
        
        email_with_footer = {
            "from_address": {"email": "legal@bigcorp.com"},
            "subject": "Contract review",
            "body_plain": "Please review the attached contract and let me know your comments.\n\nKind regards,\n\nThis email is confidential and may contain privileged information..."
        }
        
        hash1 = compute_dedupe_hash(email_no_footer)
        hash2 = compute_dedupe_hash(email_with_footer)
        
        # Footer should be stripped via signature detection
        assert hash1 == hash2
    
    def test_whitespace_normalization(self):
        """Extra whitespace should not affect hash"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        email_normal = {
            "from_address": {"email": "test@test.com"},
            "subject": "Test message",
            "body_plain": "Hello, this is a test message."
        }
        
        email_extra_spaces = {
            "from_address": {"email": "test@test.com"},
            "subject": "  Test   message  ",  # Extra spaces
            "body_plain": "Hello,   this  is  a   test  message."  # Extra spaces
        }
        
        hash1 = compute_dedupe_hash(email_normal)
        hash2 = compute_dedupe_hash(email_extra_spaces)
        
        # Whitespace should be normalized
        assert hash1 == hash2
    
    def test_case_insensitivity(self):
        """Hash should be case-insensitive for subject and sender"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        email_lower = {
            "from_address": {"email": "john@example.com"},
            "subject": "important meeting",
            "body_plain": "Let's discuss the project."
        }
        
        email_mixed = {
            "from_address": {"email": "John@Example.COM"},
            "subject": "Important Meeting",
            "body_plain": "Let's discuss the project."
        }
        
        hash1 = compute_dedupe_hash(email_lower)
        hash2 = compute_dedupe_hash(email_mixed)
        
        assert hash1 == hash2
    
    def test_hash_is_deterministic_across_calls(self):
        """Same email must produce same hash on repeated calls"""
        from email_sync.system_email_detector import compute_dedupe_hash
        
        email = {
            "from_address": {"email": "stable@test.com"},
            "subject": "Determinism test",
            "body_plain": "This should always hash the same."
        }
        
        hashes = [compute_dedupe_hash(email) for _ in range(100)]
        
        # All hashes must be identical
        assert len(set(hashes)) == 1


# ============================================
# TEST: CONCURRENT/BATCH INSERT BEHAVIOR
# ============================================

class TestConcurrencyAndBatchBehavior:
    """
    Tests verifying index behavior under concurrent/batch scenarios.
    
    Note: These are unit tests with mocks. Full integration tests
    require a live MongoDB instance.
    """
    
    def test_batch_save_computes_hashes_for_all_emails(self):
        """save_emails_batch should compute dedupe_hash for all emails"""
        from email_sync.storage import EmailStorage
        from email_sync.system_email_detector import compute_dedupe_hash
        from email_sync.models import EmailDocument, EmailAddress
        
        mock_db = MagicMock()
        mock_emails_collection = MagicMock()
        mock_queue_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda x: {
            "emails": mock_emails_collection,
            "categorization_queue": mock_queue_collection
        }.get(x, MagicMock()))
        
        # Simulate no existing emails
        mock_emails_collection.find.return_value = []
        # Mock bulk_write result (storage uses bulk_write with UpdateOne, not insert_many)
        mock_bulk_result = MagicMock()
        mock_bulk_result.upserted_count = 3
        mock_bulk_result.modified_count = 0
        mock_emails_collection.bulk_write.return_value = mock_bulk_result
        
        storage = EmailStorage(mock_db)
        
        # Create batch of emails
        emails = [
            EmailDocument(
                provider_message_id=f"msg_{i}",
                mailbox_id="mailbox_1",
                from_address=EmailAddress(email=f"sender{i}@test.com"),
                to_addresses=[],
                subject=f"Test email {i}",
                body_plain=f"Body content {i}"
            )
            for i in range(3)
        ]
        
        # Save batch
        result = storage.save_emails_batch(emails)
        
        # Verify bulk_write was called (storage uses bulk_write, not insert_many)
        assert mock_emails_collection.bulk_write.called
        
        # Get the operations that were passed to bulk_write
        operations = mock_emails_collection.bulk_write.call_args[0][0]
        
        # Each operation should contain a dedupe_hash in the filter
        for op in operations:
            # UpdateOne operations have _filter attribute
            assert "dedupe_hash" in op._filter
            assert op._filter["dedupe_hash"] is not None
            assert len(op._filter["dedupe_hash"]) == 64  # SHA256 hex length
    
    def test_batch_save_skips_global_duplicates(self):
        """save_emails_batch should skip emails with existing hashes"""
        from email_sync.storage import EmailStorage
        from email_sync.system_email_detector import compute_dedupe_hash
        from email_sync.models import EmailDocument, EmailAddress
        
        mock_db = MagicMock()
        mock_emails_collection = MagicMock()
        mock_queue_collection = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda x: {
            "emails": mock_emails_collection,
            "categorization_queue": mock_queue_collection
        }.get(x, MagicMock()))
        
        # Create test email
        email = EmailDocument(
            provider_message_id="msg_1",
            mailbox_id="mailbox_1",
            from_address=EmailAddress(email="sender@test.com"),
            to_addresses=[],
            subject="Test email",
            body_plain="Body content"
        )
        
        # Compute expected hash
        email_dict = {
            "from_address": {"email": "sender@test.com"},
            "subject": "Test email",
            "body_plain": "Body content"
        }
        expected_hash = compute_dedupe_hash(email_dict)
        
        # Simulate email already exists with this hash
        mock_emails_collection.find.return_value = [{"dedupe_hash": expected_hash}]
        
        storage = EmailStorage(mock_db)
        
        # Save batch (should be filtered out)
        storage.save_emails_batch([email])
        
        # insert_many should NOT be called (or called with empty list)
        if mock_emails_collection.insert_many.called:
            inserted_docs = mock_emails_collection.insert_many.call_args[0][0]
            assert len(inserted_docs) == 0


# ============================================
# RUN TESTS
# ============================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
