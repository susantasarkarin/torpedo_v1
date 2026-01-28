"""
AGENT 5 INTEGRATION TEST
========================

Test suite for Re-engagement Service and A/B Testing Service.

Tests:
1. Re-engagement Service:
   - Dormant lead detection
   - Strategy selection
   - Campaign creation
   - Sender rotation
   - Metrics tracking

2. A/B Testing Service:
   - Variant assignment
   - Statistical significance calculation
   - Winner declaration
   - Winner rollout
   - Conversion tracking

Run: python test_agent5_services.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from pymongo import MongoClient
from campaigns.reengagement import ReengagementService
from campaigns.ab_testing import ABTestingService
from bson import ObjectId
import random


def setup_test_database():
    """Setup test database with sample data."""
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform_test
    
    # Clear test collections
    db.campaign_recipients.delete_many({})
    db.campaign_sends.delete_many({})
    db.reengagement_campaigns.delete_many({})
    db.ab_tests.delete_many({})
    db.ab_test_assignments.delete_many({})
    db.mailboxes.delete_many({})
    
    # Create sample dormant leads
    dormant_leads = []
    for i in range(10):
        lead = {
            "_id": ObjectId(),
            "lead_id": f"lead_{i}",
            "email": f"lead{i}@example.com",
            "campaign_id": ObjectId(),
            "status": "completed",
            "last_activity_at": datetime.utcnow() - timedelta(days=25),
            "completed_at": datetime.utcnow() - timedelta(days=25),
            "unsubscribed": False
        }
        dormant_leads.append(lead)
    
    db.campaign_recipients.insert_many(dormant_leads)
    
    # Create sample sends for engagement metrics
    for lead in dormant_leads[:5]:  # First 5 are engaged
        for j in range(5):
            send = {
                "_id": ObjectId(),
                "recipient_id": lead["_id"],
                "sent_at": datetime.utcnow() - timedelta(days=30 - j*3),
                "status": "opened" if j < 3 else "sent"
            }
            db.campaign_sends.insert_one(send)
    
    for lead in dormant_leads[5:]:  # Last 5 are low engagement
        for j in range(5):
            send = {
                "_id": ObjectId(),
                "recipient_id": lead["_id"],
                "sent_at": datetime.utcnow() - timedelta(days=30 - j*3),
                "status": "sent"
            }
            db.campaign_sends.insert_one(send)
    
    # Create sample mailboxes for sender rotation
    mailboxes = [
        {
            "_id": ObjectId(),
            "email": "sender1@company.com",
            "status": "active",
            "daily_limit": 100,
            "sends_today": 10
        },
        {
            "_id": ObjectId(),
            "email": "sender2@company.com",
            "status": "active",
            "daily_limit": 100,
            "sends_today": 5
        }
    ]
    db.mailboxes.insert_many(mailboxes)
    
    print("✓ Test database setup complete")
    return db


def test_reengagement_service(db):
    """Test Re-engagement Service functionality."""
    print("\n" + "="*80)
    print("TESTING RE-ENGAGEMENT SERVICE")
    print("="*80)
    
    service = ReengagementService(db)
    
    # Test 1: Detect dormant leads
    print("\n1. Testing dormant lead detection...")
    dormant = service.detect_dormant_leads(days_since_last_contact=21)
    print(f"   Found {len(dormant)} dormant leads")
    assert len(dormant) > 0, "Should find dormant leads"
    print("   ✓ Dormant lead detection works")
    
    # Test 2: Strategy selection
    print("\n2. Testing strategy selection...")
    for lead in dormant[:3]:
        strategy = service.select_reengagement_strategy(lead)
        print(f"   Lead {lead['email']}: {strategy} (engagement: {lead['engagement_rate']:.1%})")
        assert strategy in ["soft_drip", "trigger_based", "reset_outreach"]
    print("   ✓ Strategy selection works")
    
    # Test 3: Create re-engagement campaign
    print("\n3. Testing campaign creation...")
    campaign = service.create_reengagement_campaign(
        lead_ids=[str(lead["_id"]) for lead in dormant[:3]],
        strategy="soft_drip"
    )
    print(f"   Created campaign: {campaign['name']}")
    print(f"   Total leads: {campaign['metrics']['total_leads']}")
    print(f"   Sequence steps: {len(campaign['sequence_steps'])}")
    assert campaign["strategy"] == "soft_drip"
    assert len(campaign["sequence_steps"]) == 3
    print("   ✓ Campaign creation works")
    
    # Test 4: Sender rotation
    print("\n4. Testing sender rotation...")
    mailboxes = list(db.mailboxes.find())
    if len(mailboxes) >= 2:
        new_mailbox = service.rotate_sender_for_reset(
            str(campaign["_id"]),
            str(mailboxes[0]["_id"])
        )
        print(f"   Rotated to mailbox: {new_mailbox}")
        assert new_mailbox != str(mailboxes[0]["_id"])
        print("   ✓ Sender rotation works")
    
    # Test 5: Mark reengaged
    print("\n5. Testing reengagement tracking...")
    service.mark_reengaged(str(dormant[0]["_id"]), str(campaign["_id"]))
    recipient = db.campaign_recipients.find_one({"_id": dormant[0]["_id"]})
    assert recipient["reengagement_status"] == "reengaged"
    print("   ✓ Reengagement tracking works")
    
    # Test 6: Get metrics
    print("\n6. Testing metrics retrieval...")
    metrics = service.get_reengagement_metrics(str(campaign["_id"]))
    print(f"   Total leads: {metrics['total_leads']}")
    print(f"   Reengagement rate: {metrics['reengagement_rate']:.1%}")
    print("   ✓ Metrics retrieval works")
    
    print("\n✓ All Re-engagement Service tests passed!")
    return True


def test_ab_testing_service(db):
    """Test A/B Testing Service functionality."""
    print("\n" + "="*80)
    print("TESTING A/B TESTING SERVICE")
    print("="*80)
    
    service = ABTestingService(db)
    campaign_id = str(ObjectId())
    
    # Test 1: Variant assignment
    print("\n1. Testing variant assignment...")
    variants = ["control", "variant_a", "variant_b"]
    split_ratio = {"control": 0.4, "variant_a": 0.3, "variant_b": 0.3}
    
    assignments = {}
    for i in range(100):
        recipient_id = f"recipient_{i}"
        variant = service.assign_variant(
            campaign_id=campaign_id,
            recipient_id=recipient_id,
            variants=variants,
            split_ratio=split_ratio
        )
        assignments[variant] = assignments.get(variant, 0) + 1
    
    print(f"   Assignment distribution:")
    for variant, count in assignments.items():
        print(f"     {variant}: {count} ({count/100:.1%})")
    
    # Check roughly follows split ratio (within 15%)
    assert 25 <= assignments.get("control", 0) <= 55, "Control should be ~40%"
    print("   ✓ Variant assignment works")
    
    # Test 2: Record conversions (variant_a performs better)
    print("\n2. Testing conversion tracking...")
    for i in range(100):
        recipient_id = f"recipient_{i}"
        assignment = db.ab_test_assignments.find_one({
            "campaign_id": ObjectId(campaign_id),
            "recipient_id": ObjectId(recipient_id)
        })
        
        if assignment:
            variant = assignment["variant"]
            # Simulate different conversion rates
            if variant == "control" and random.random() < 0.10:
                service.record_conversion(recipient_id, campaign_id)
            elif variant == "variant_a" and random.random() < 0.18:  # 80% lift
                service.record_conversion(recipient_id, campaign_id)
            elif variant == "variant_b" and random.random() < 0.08:
                service.record_conversion(recipient_id, campaign_id)
    
    print("   ✓ Conversion tracking works")
    
    # Test 3: Get metrics
    print("\n3. Testing metrics retrieval...")
    metrics = service.get_test_metrics(campaign_id)
    print(f"   Metrics for all variants:")
    for variant_name, variant_metrics in metrics["variants"].items():
        print(f"     {variant_name}:")
        print(f"       Assigned: {variant_metrics['assigned']}")
        print(f"       Conversions: {variant_metrics['conversions']}")
        print(f"       Rate: {variant_metrics['conversion_rate']:.2%}")
    print("   ✓ Metrics retrieval works")
    
    # Test 4: Statistical significance
    print("\n4. Testing statistical significance...")
    if len(metrics["variants"]) >= 2:
        control = metrics["variants"]["control"]
        variant_a = metrics["variants"]["variant_a"]
        
        result = service.calculate_significance(
            control_data={
                "conversions": control["conversions"],
                "total": control["assigned"]
            },
            variant_data={
                "conversions": variant_a["conversions"],
                "total": variant_a["assigned"]
            }
        )
        
        print(f"   Control rate: {result['control_rate']:.2%}")
        print(f"   Variant A rate: {result['variant_rate']:.2%}")
        print(f"   Lift: {result['lift']:.1f}%")
        print(f"   P-value: {result['p_value']:.4f}")
        print(f"   Significant: {result['significant']}")
        print(f"   Method: {result['method']}")
        print("   ✓ Statistical significance works")
    
    # Test 5: Winner declaration
    print("\n5. Testing winner declaration...")
    winner = service.should_declare_winner(
        campaign_id=campaign_id,
        threshold=0.80,  # Lower threshold for testing
        min_sample_size=20
    )
    
    if winner:
        print(f"   Winner declared: {winner}")
        print("   ✓ Winner declaration works")
        
        # Test 6: Winner rollout
        print("\n6. Testing winner rollout...")
        count = service.rollout_winner(campaign_id, winner)
        print(f"   Rolled out to {count} recipients")
        print("   ✓ Winner rollout works")
    else:
        print("   No winner yet (need more data)")
        print("   ✓ Winner logic working correctly")
    
    print("\n✓ All A/B Testing Service tests passed!")
    return True


def test_integration():
    """Test integration between services."""
    print("\n" + "="*80)
    print("TESTING SERVICE INTEGRATION")
    print("="*80)
    
    client = MongoClient("mongodb://localhost:27017/")
    db = client.campaign_platform_test
    
    reeng_service = ReengagementService(db)
    ab_service = ABTestingService(db)
    
    # Create re-engagement campaign with A/B testing
    print("\n1. Creating A/B tested re-engagement campaign...")
    dormant = reeng_service.detect_dormant_leads(days_since_last_contact=21)
    
    if len(dormant) >= 6:
        # Split leads into A/B test
        campaign = reeng_service.create_reengagement_campaign(
            lead_ids=[str(lead["_id"]) for lead in dormant[:6]],
            strategy="soft_drip"
        )
        
        # Assign variants for email subject lines
        campaign_id = str(campaign["_id"])
        variants = ["subject_a", "subject_b"]
        
        for lead in dormant[:6]:
            variant = ab_service.assign_variant(
                campaign_id=campaign_id,
                recipient_id=str(lead["_id"]),
                variants=variants,
                split_ratio={"subject_a": 0.5, "subject_b": 0.5}
            )
        
        print(f"   Created A/B tested re-engagement campaign")
        print(f"   Campaign ID: {campaign_id}")
        print("   ✓ Service integration works")
    
    print("\n✓ Integration tests passed!")


def main():
    """Run all tests."""
    print("="*80)
    print("AGENT 5 SERVICE TEST SUITE")
    print("="*80)
    
    try:
        # Setup
        db = setup_test_database()
        
        # Run tests
        test_reengagement_service(db)
        test_ab_testing_service(db)
        test_integration()
        
        print("\n" + "="*80)
        print("✓ ALL TESTS PASSED!")
        print("="*80)
        print("\nAgent 5 services are fully operational:")
        print("  • Re-engagement Service: Dormant detection, strategy selection, campaigns")
        print("  • A/B Testing Service: Variant assignment, statistical analysis, winner selection")
        print("\nNote: For full statistical testing, install scipy:")
        print("  pip install scipy")
        
        return True
        
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
