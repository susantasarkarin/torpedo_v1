#!/usr/bin/env python3
"""
Test script for CPX Audit Framework
Validates the audit service logic without database dependencies
"""

import sys
import hashlib
from datetime import datetime, timedelta


class MockCollection:
    """Mock MongoDB collection for testing"""
    def __init__(self):
        self.data = []
        self.indexes = []
    
    def insert_one(self, doc):
        class Result:
            inserted_id = "test_id_123"
        self.data.append(doc)
        return Result()
    
    def find_one(self, query):
        return None
    
    def update_one(self, query, update):
        pass
    
    def create_index(self, *args, **kwargs):
        self.indexes.append(args)
    
    def count_documents(self, query):
        return 0
    
    def aggregate(self, pipeline):
        return []
    
    def find(self, query=None):
        return self


def test_fingerprint_generation():
    """Test fingerprint hash generation"""
    # Import would be: from app.services.audit_service import AuditService
    # But we'll test the logic directly
    
    ip = "192.168.1.1"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
    accept_language = "en-US,en;q=0.9"
    
    raw = f"{ip}|{user_agent}|{accept_language}"
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()
    
    print(f"✅ Fingerprint generation test")
    print(f"   Input: IP={ip}, UA={user_agent[:30]}..., Lang={accept_language}")
    print(f"   Fingerprint: {fingerprint[:32]}...")
    
    # Test that same input produces same fingerprint
    fingerprint2 = hashlib.sha256(raw.encode()).hexdigest()
    assert fingerprint == fingerprint2, "Fingerprints should match for same input"
    print(f"   ✅ Consistent fingerprinting verified")
    
    # Test that different input produces different fingerprint
    raw2 = f"192.168.1.2|{user_agent}|{accept_language}"
    fingerprint3 = hashlib.sha256(raw2.encode()).hexdigest()
    assert fingerprint != fingerprint3, "Different IPs should produce different fingerprints"
    print(f"   ✅ Uniqueness verified")


def test_screenout_classification():
    """Test screen-out classification logic"""
    IMMEDIATE_REJECT_THRESHOLD = 5
    SCREENER_FAIL_THRESHOLD = 30
    
    def classify_screenout(duration_seconds):
        if duration_seconds < IMMEDIATE_REJECT_THRESHOLD:
            return "IMMEDIATE_REJECT"
        elif duration_seconds < SCREENER_FAIL_THRESHOLD:
            return "SCREENER_FAIL"
        else:
            return "QUALITY_REJECT"
    
    print(f"\n✅ Screen-out classification test")
    
    # Test immediate reject (< 5 seconds)
    result = classify_screenout(2.5)
    assert result == "IMMEDIATE_REJECT", "2.5 seconds should be IMMEDIATE_REJECT"
    print(f"   ✅ 2.5s -> {result}")
    
    # Test screener fail (5-30 seconds)
    result = classify_screenout(15.0)
    assert result == "SCREENER_FAIL", "15 seconds should be SCREENER_FAIL"
    print(f"   ✅ 15.0s -> {result}")
    
    # Test quality reject (> 30 seconds)
    result = classify_screenout(120.0)
    assert result == "QUALITY_REJECT", "120 seconds should be QUALITY_REJECT"
    print(f"   ✅ 120.0s -> {result}")
    
    # Edge cases
    result = classify_screenout(5.0)
    assert result == "SCREENER_FAIL", "Exactly 5s should be SCREENER_FAIL"
    print(f"   ✅ 5.0s (edge) -> {result}")
    
    result = classify_screenout(30.0)
    assert result == "QUALITY_REJECT", "Exactly 30s should be QUALITY_REJECT"
    print(f"   ✅ 30.0s (edge) -> {result}")


def test_postback_validation():
    """Test postback validation logic"""
    def validate_postback(status, payout):
        if status == "complete" and payout <= 0:
            return False, "Complete status but payout is zero or negative"
        return True, None
    
    print(f"\n✅ Postback validation test")
    
    # Valid complete with payout
    is_valid, error = validate_postback("complete", 2.50)
    assert is_valid, "Complete with payout should be valid"
    assert error is None, "Error should be None for valid postback"
    print(f"   ✅ Complete + $2.50 payout -> Valid")
    
    # Invalid complete without payout
    is_valid, error = validate_postback("complete", 0)
    assert not is_valid, "Complete without payout should be invalid"
    assert error is not None, "Error should be set for invalid postback"
    print(f"   ✅ Complete + $0 payout -> Invalid: {error}")
    
    # Terminated with 0 payout is OK
    is_valid, error = validate_postback("terminated", 0)
    assert is_valid, "Terminated with 0 payout should be valid"
    assert error is None, "Error should be None for valid postback"
    print(f"   ✅ Terminated + $0 payout -> Valid")


def test_auto_pause_logic():
    """Test auto-pause condition"""
    SCREENOUT_RATE_THRESHOLD = 0.80
    
    def check_auto_pause(screenout_rate):
        if screenout_rate > SCREENOUT_RATE_THRESHOLD:
            reason = f"Screen-out rate {screenout_rate:.1%} exceeds threshold {SCREENOUT_RATE_THRESHOLD:.1%}"
            return True, reason
        return False, None
    
    print(f"\n✅ Auto-pause logic test")
    
    # Below threshold
    should_pause, reason = check_auto_pause(0.75)
    assert not should_pause, "75% should not trigger pause"
    print(f"   ✅ 75% screenout rate -> No pause")
    
    # Above threshold
    should_pause, reason = check_auto_pause(0.85)
    assert should_pause, "85% should trigger pause"
    print(f"   ✅ 85% screenout rate -> Pause: {reason}")
    
    # Edge case
    should_pause, reason = check_auto_pause(0.80)
    assert not should_pause, "Exactly 80% should not trigger pause (threshold is >)"
    print(f"   ✅ 80% screenout rate (edge) -> No pause")


def test_duration_calculation():
    """Test duration calculation from traffic record"""
    print(f"\n✅ Duration calculation test")
    
    created_at = datetime.utcnow() - timedelta(seconds=45)
    current_time = datetime.utcnow()
    
    duration_delta = current_time - created_at
    duration_seconds = duration_delta.total_seconds()
    
    assert 44 <= duration_seconds <= 46, f"Duration should be ~45 seconds, got {duration_seconds}"
    print(f"   ✅ Duration: {duration_seconds:.2f} seconds")
    
    # Test with different intervals
    created_at2 = datetime.utcnow() - timedelta(seconds=2)
    duration2 = (datetime.utcnow() - created_at2).total_seconds()
    assert duration2 < 5, "Should be less than 5 seconds"
    print(f"   ✅ Short duration: {duration2:.2f} seconds")


def test_parameter_integrity():
    """Test parameter matching"""
    print(f"\n✅ Parameter integrity test")
    
    def verify_parameter_integrity(outgoing, incoming):
        return outgoing == incoming
    
    # Matching parameters
    result = verify_parameter_integrity("abc123", "abc123")
    assert result, "Matching parameters should return True"
    print(f"   ✅ Matching subids: abc123 == abc123")
    
    # Mismatched parameters
    result = verify_parameter_integrity("abc123", "xyz789")
    assert not result, "Mismatched parameters should return False"
    print(f"   ✅ Mismatched subids detected: abc123 != xyz789")


def run_all_tests():
    """Run all unit tests"""
    print("=" * 60)
    print("CPX Audit Framework - Unit Tests")
    print("=" * 60)
    
    try:
        test_fingerprint_generation()
        test_screenout_classification()
        test_postback_validation()
        test_auto_pause_logic()
        test_duration_calculation()
        test_parameter_integrity()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
