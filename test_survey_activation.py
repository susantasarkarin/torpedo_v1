#!/usr/bin/env python3
"""
Test script to verify survey activation service logic.
This simulates the background_survey_sync function without requiring a database connection.
"""

def test_activation_logic():
    """Test the survey activation logic"""
    
    print("🧪 Testing Survey Activation Logic\n")
    
    # Simulate filter settings
    filters = {
        "max_loi": 20,  # Maximum 20 minutes
        "min_cpi": 1.0,  # Minimum $1.00
        "min_ir": 5     # Minimum 5% incidence rate
    }
    
    print(f"📋 Filter Settings:")
    print(f"   Max LOI: {filters['max_loi']} minutes")
    print(f"   Min CPI: ${filters['min_cpi']}")
    print(f"   Min IR: {filters['min_ir']}%\n")
    
    # Simulate survey samples
    test_surveys = [
        {
            "survey_id": "CPX_001",
            "provider": "CPX",
            "loi": 15,
            "payout": 2.50,
            "conversion_rate": 10,
            "live_link": "https://example.com/survey1",
            "expected": True,
            "reason": "Meets all criteria"
        },
        {
            "survey_id": "CPX_002", 
            "provider": "CPX",
            "loi": 25,
            "payout": 2.00,
            "conversion_rate": 15,
            "live_link": "https://example.com/survey2",
            "expected": False,
            "reason": "LOI too high (25 > 20)"
        },
        {
            "survey_id": "CPX_003",
            "provider": "CPX",
            "loi": 10,
            "payout": 0.50,
            "conversion_rate": 20,
            "live_link": "https://example.com/survey3",
            "expected": False,
            "reason": "Payout too low ($0.50 < $1.00)"
        },
        {
            "survey_id": "CINT_001",
            "provider": "CINT",
            "length_of_interview": 18,
            "payout": 1.50,
            "bid_incidence": 8,
            "is_live": True,
            "expected": True,
            "reason": "Meets all criteria"
        },
        {
            "survey_id": "CINT_002",
            "provider": "CINT",
            "length_of_interview": 12,
            "payout": 1.20,
            "bid_incidence": 3,
            "is_live": True,
            "expected": False,
            "reason": "IR too low (3 < 5)"
        },
        {
            "survey_id": "CINT_003",
            "provider": "CINT",
            "length_of_interview": 15,
            "payout": 2.00,
            "bid_incidence": 10,
            "is_live": False,
            "expected": False,
            "reason": "Not live"
        }
    ]
    
    print("📊 Testing Survey Evaluation:\n")
    
    passed = 0
    failed = 0
    
    for survey in test_surveys:
        # Evaluate survey
        is_eligible = evaluate_survey(survey, filters)
        
        # Check if result matches expectation
        if is_eligible == survey["expected"]:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status} {survey['survey_id']} ({survey['provider']})")
        print(f"   LOI: {survey.get('loi') or survey.get('length_of_interview', 0)} min, "
              f"Payout: ${survey.get('payout', 0)}, "
              f"IR: {survey.get('conversion_rate') or survey.get('bid_incidence', 0)}%")
        print(f"   Expected: {survey['expected']} (Eligible), Got: {is_eligible}")
        print(f"   Reason: {survey['reason']}\n")
    
    print(f"\n{'='*60}")
    print(f"Test Results: {passed} passed, {failed} failed out of {len(test_surveys)} total")
    print(f"{'='*60}")
    
    return failed == 0


def evaluate_survey(survey, filters):
    """
    Simplified version of the evaluation logic from activation_service.py
    """
    provider = survey.get("provider", "").upper()
    
    # Check if survey is live
    if provider == "CINT":
        if not survey.get("is_live", False):
            return False
        if survey.get("message_reason") == "deactivated":
            return False
    elif provider == "CPX":
        if not (survey.get("live_link") or survey.get("entry_link")):
            return False
    
    # Get filter thresholds
    max_loi = filters.get("max_loi", 20)
    min_cpi = filters.get("min_cpi", 1.0)
    min_ir = filters.get("min_ir", 5)
    
    # Filter: LOI (length of interview)
    if provider == "CINT":
        loi = survey.get("length_of_interview") or survey.get("bid_length_of_interview") or survey.get("loi") or 0
    else:
        loi = survey.get("loi") or survey.get("length_of_interview") or 0
    
    try:
        loi = float(loi) if loi else 0
    except (ValueError, TypeError):
        loi = 0
    
    if loi > 0 and loi > max_loi:
        return False
    
    # Filter: Payout / CPI
    payout = survey.get("payout") or survey.get("cpi") or 0
    
    try:
        payout = float(payout) if payout else 0
    except (ValueError, TypeError):
        payout = 0
    
    if payout < min_cpi:
        return False
    
    # Filter: Conversion/Incidence Rate
    if provider == "CINT":
        ir = survey.get("bid_incidence") or survey.get("incidence_rate") or survey.get("conversion_rate") or 0
    else:
        ir = survey.get("conversion_rate") or survey.get("incidence_rate") or 0
    
    try:
        ir = float(ir) if ir else 0
    except (ValueError, TypeError):
        ir = 0
    
    if ir > 0 and ir < min_ir:
        return False
    
    return True


if __name__ == "__main__":
    success = test_activation_logic()
    exit(0 if success else 1)
