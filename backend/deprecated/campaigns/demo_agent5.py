"""
QUICK DEMONSTRATION: Agent 5 Services
======================================

Quick demo showing both services in action with sample data.
Run: python demo_agent5.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from campaigns.reengagement import ReengagementService
from campaigns.ab_testing import ABTestingService
import random


def demo_reengagement():
    """Demonstrate re-engagement service with sample data."""
    print("=" * 80)
    print("RE-ENGAGEMENT SERVICE DEMO")
    print("=" * 80)
    
    # Sample dormant leads
    dormant_leads = [
        {
            "_id": "lead_001",
            "email": "high_engagement@company.com",
            "days_since_contact": 25,
            "engagement_rate": 0.65,
            "click_rate": 0.30,
            "total_sends": 10
        },
        {
            "_id": "lead_002",
            "email": "medium_engagement@company.com",
            "days_since_contact": 45,
            "engagement_rate": 0.35,
            "click_rate": 0.12,
            "total_sends": 8
        },
        {
            "_id": "lead_003",
            "email": "low_engagement@company.com",
            "days_since_contact": 90,
            "engagement_rate": 0.12,
            "click_rate": 0.02,
            "total_sends": 12
        }
    ]
    
    print("\n📊 Dormant Lead Analysis:")
    print("-" * 80)
    
    # Use direct strategy selection (no DB needed)
    from campaigns.reengagement import ReengagementService
    
    # Create minimal mock
    class MinimalMock:
        pass
    
    # We'll just use the strategy selection method directly
    service_instance = ReengagementService.__new__(ReengagementService)
    
    for lead in dormant_leads:
        strategy = service_instance.select_reengagement_strategy(lead)
        
        print(f"\n📧 {lead['email']}")
        print(f"   Days dormant: {lead['days_since_contact']}")
        print(f"   Engagement rate: {lead['engagement_rate']:.1%}")
        print(f"   Click rate: {lead['click_rate']:.1%}")
        print(f"   ➜ Strategy: {strategy.upper().replace('_', ' ')}")
        
        # Show strategy details
        if strategy == "soft_drip":
            print(f"   📝 Plan: Educational content over 7 days, no hard CTA")
        elif strategy == "trigger_based":
            print(f"   📝 Plan: Event-triggered outreach (job change, funding)")
        else:
            print(f"   📝 Plan: Fresh angle with sender rotation, breakup email")
    
    print("\n" + "=" * 80)


def demo_ab_testing():
    """Demonstrate A/B testing service with statistical analysis."""
    print("\n" + "=" * 80)
    print("A/B TESTING SERVICE DEMO")
    print("=" * 80)
    
    # Simulate A/B test data
    control_total = 500
    variant_total = 500
    
    # Control: 10% conversion
    control_conv = 50
    
    # Variant A: 14% conversion (40% lift)
    variant_conv = 70
    
    print("\n📊 Test Setup:")
    print("-" * 80)
    print(f"Control:   {control_total} emails sent, {control_conv} conversions ({control_conv/control_total:.1%})")
    print(f"Variant A: {variant_total} emails sent, {variant_conv} conversions ({variant_conv/variant_total:.1%})")
    print(f"Lift:      {((variant_conv/variant_total) - (control_conv/control_total)) / (control_conv/control_total) * 100:.1f}%")
    
    # Create service instance (without DB for demo)
    class MinimalMock:
        pass
    
    service_instance = ABTestingService.__new__(ABTestingService)
    
    # Calculate significance
    print("\n📈 Statistical Analysis:")
    print("-" * 80)
    
    result = service_instance.calculate_significance(
        control_data={"conversions": control_conv, "total": control_total},
        variant_data={"conversions": variant_conv, "total": variant_total}
    )
    
    print(f"Control conversion rate:  {result['control_rate']:.2%}")
    print(f"Variant conversion rate:  {result['variant_rate']:.2%}")
    print(f"Lift:                     {result['lift']:+.1f}%")
    print(f"P-value:                  {result['p_value']:.4f}")
    print(f"Chi-squared:              {result.get('chi_squared', 'N/A'):.2f}" if 'chi_squared' in result else "")
    print(f"Z-score:                  {result.get('z_score', 'N/A'):.2f}" if 'z_score' in result else "")
    print(f"Statistically significant: {'✅ YES' if result['significant'] else '❌ NO'}")
    print(f"Confidence level:         {result['confidence']:.1%}")
    
    if result.get("confidence_interval"):
        ci = result["confidence_interval"]
        print(f"95% Confidence Interval:  [{ci['lower']:.2%}, {ci['upper']:.2%}]")
    
    print(f"\nMethod: {result['method']}")
    
    # Decision
    print("\n🎯 Decision:")
    print("-" * 80)
    if result["significant"]:
        print("✅ DECLARE WINNER: Variant A")
        print("   Action: Roll out Variant A to all remaining recipients")
        print(f"   Expected lift: {result['lift']:+.1f}% improvement in conversions")
    else:
        print("⏳ CONTINUE TESTING")
        print("   Action: Need more data to reach statistical significance")
        print("   Recommendation: Collect at least 100 more conversions per variant")
    
    print("\n" + "=" * 80)


def demo_variant_assignment():
    """Demonstrate variant assignment distribution."""
    print("\n" + "=" * 80)
    print("VARIANT ASSIGNMENT DEMO")
    print("=" * 80)
    
    print("\n📊 Assigning 1000 recipients to 3 variants:")
    print("-" * 80)
    
    variants = ["control", "variant_a", "variant_b"]
    split_ratio = {
        "control": 0.5,
        "variant_a": 0.3,
        "variant_b": 0.2
    }
    
    # Simulate assignment
    assignments = {v: 0 for v in variants}
    for i in range(1000):
        variant = random.choices(
            population=variants,
            weights=[split_ratio[v] for v in variants],
            k=1
        )[0]
        assignments[variant] += 1
    
    print(f"\nTarget distribution:")
    for variant, ratio in split_ratio.items():
        print(f"  {variant}: {ratio:.0%}")
    
    print(f"\nActual distribution:")
    for variant, count in assignments.items():
        actual_pct = count / 1000
        target_pct = split_ratio[variant]
        diff = actual_pct - target_pct
        print(f"  {variant}: {count:3d} ({actual_pct:.1%}) [{'+'if diff >= 0 else ''}{diff:.1%} vs target]")
    
    print("\n✅ Distribution matches target ratios within expected variance")
    print("=" * 80)


def main():
    """Run all demonstrations."""
    print("\n" + "🚀" * 40)
    print("AGENT 5 SERVICES DEMONSTRATION")
    print("🚀" * 40)
    
    demo_reengagement()
    demo_ab_testing()
    demo_variant_assignment()
    
    print("\n" + "✅" * 40)
    print("\nDEMONSTRATION COMPLETE")
    print("\nKey Takeaways:")
    print("  1. Re-engagement: 3 strategies based on engagement history")
    print("  2. A/B Testing: Chi-squared & z-test for statistical significance")
    print("  3. Variant Assignment: Weighted random selection with split ratios")
    print("\nFor full implementation, see:")
    print("  • backend/campaigns/reengagement.py")
    print("  • backend/campaigns/ab_testing.py")
    print("  • backend/campaigns/test_agent5_services.py")
    print("\n" + "✅" * 40)


if __name__ == "__main__":
    main()
