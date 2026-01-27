"""
TEST SUITE FOR CAMPAIGN AUTOMATION
===================================

Tests all functionality of the campaign automation system.
Run: python -m backend.test_campaign_automation
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campaigns.services_config import (
    get_company_config, 
    get_service_by_id, 
    list_all_services
)
from campaigns.email_templates import (
    get_template_config, 
    render_template, 
    list_templates
)


def test_services():
    """Test service configuration"""
    print("\n" + "="*80)
    print("TEST 1: SERVICE CONFIGURATION")
    print("="*80)
    
    # Test listing services
    services = list_all_services()
    assert "surveyfieldwork" in services
    assert "cogentixresearch" in services
    assert len(services["surveyfieldwork"]) == 6
    assert len(services["cogentixresearch"]) == 6
    print("✓ Service listing works")
    
    # Test Survey Fieldwork config
    sf_config = get_company_config("surveyfieldwork")
    assert sf_config["sender_email"] == "indira@surveyfieldwork.com"
    assert sf_config["sender_name"] == "Indira"
    assert sf_config["company_name"] == "Survey Fieldwork"
    assert len(sf_config["email_signature"]) > 0
    print("✓ Survey Fieldwork config correct")
    
    # Test Cogentix Research config
    cr_config = get_company_config("cogentixresearch")
    assert cr_config["sender_email"] == "meera@cogentixresearch.com"
    assert cr_config["sender_name"] == "Meera"
    assert cr_config["company_name"] == "Cogentix Research"
    assert len(cr_config["email_signature"]) > 0
    print("✓ Cogentix Research config correct")
    
    # Test service details
    service = get_service_by_id("surveyfieldwork", "audience_sampling")
    assert service["name"] == "Audience Sampling"
    assert "features" in service
    assert "use_cases" in service
    print("✓ Service details retrieval works")
    
    print("\n✅ All service configuration tests passed!")


def test_email_templates():
    """Test email templates"""
    print("\n" + "="*80)
    print("TEST 2: EMAIL TEMPLATES")
    print("="*80)
    
    # Test template listing
    templates = list_templates()
    assert "surveyfieldwork" in templates
    assert "cogentixresearch" in templates
    assert len(templates["surveyfieldwork"]) == 4
    assert len(templates["cogentixresearch"]) == 4
    print("✓ Template listing works")
    
    # Test Survey Fieldwork templates
    for template_name in ["initial_outreach", "follow_up_week1", "follow_up_week2", "follow_up_week3"]:
        template = get_template_config("surveyfieldwork", template_name)
        assert "subject" in template
        assert "body_html" in template
        assert "body_html_with_signature" in template
        assert "indira@surveyfieldwork.com" in template["body_html_with_signature"]
    print("✓ Survey Fieldwork templates work")
    
    # Test Cogentix Research templates
    for template_name in ["initial_outreach", "follow_up_week1", "follow_up_week2", "follow_up_week3"]:
        template = get_template_config("cogentixresearch", template_name)
        assert "subject" in template
        assert "body_html" in template
        assert "body_html_with_signature" in template
        assert "meera@cogentixresearch.com" in template["body_html_with_signature"]
    print("✓ Cogentix Research templates work")
    
    print("\n✅ All email template tests passed!")


def test_template_rendering():
    """Test template rendering with variables"""
    print("\n" + "="*80)
    print("TEST 3: TEMPLATE RENDERING")
    print("="*80)
    
    # Test Survey Fieldwork rendering
    sf_template = get_template_config("surveyfieldwork", "initial_outreach")
    sf_rendered = render_template(sf_template, {
        "first_name": "John",
        "company": "Acme Corp"
    })
    
    assert "John" in sf_rendered["subject"]
    assert "John" in sf_rendered["body_html"]
    assert "Acme Corp" in sf_rendered["body_html"]
    assert "indira@surveyfieldwork.com" in sf_rendered["body_html"]
    assert "{{" not in sf_rendered["subject"]  # No unrendered placeholders
    print("✓ Survey Fieldwork rendering works")
    
    # Test Cogentix Research rendering
    cr_template = get_template_config("cogentixresearch", "initial_outreach")
    cr_rendered = render_template(cr_template, {
        "first_name": "Jane",
        "company": "Global Inc",
        "industry": "Technology"
    })
    
    assert "Jane" in cr_rendered["subject"]
    assert "Jane" in cr_rendered["body_html"]
    assert "Global Inc" in cr_rendered["body_html"]
    assert "meera@cogentixresearch.com" in cr_rendered["body_html"]
    print("✓ Cogentix Research rendering works")
    
    # Test all follow-up templates
    for i, template_name in enumerate(["follow_up_week1", "follow_up_week2", "follow_up_week3"]):
        template = get_template_config("surveyfieldwork", template_name)
        rendered = render_template(template, {
            "first_name": "Test",
            "company": "Test Corp",
            "industry": "Testing"
        })
        assert len(rendered["body_html"]) > 1000  # Should have content
        assert "Test" in rendered["body_html"]
    print("✓ Follow-up templates render correctly")
    
    print("\n✅ All template rendering tests passed!")


def test_email_signatures():
    """Test that email signatures are properly included"""
    print("\n" + "="*80)
    print("TEST 4: EMAIL SIGNATURES")
    print("="*80)
    
    # Survey Fieldwork signature
    sf_config = get_company_config("surveyfieldwork")
    sf_signature = sf_config["email_signature"]
    
    assert "Indira" in sf_signature
    assert "indira@surveyfieldwork.com" in sf_signature
    assert "surveyfieldwork.com" in sf_signature
    assert "Business Development Manager" in sf_signature
    assert "Survey Fieldwork" in sf_signature
    print("✓ Survey Fieldwork signature correct")
    
    # Cogentix Research signature
    cr_config = get_company_config("cogentixresearch")
    cr_signature = cr_config["email_signature"]
    
    assert "Meera" in cr_signature
    assert "meera@cogentixresearch.com" in cr_signature
    assert "cogentixresearch.com" in cr_signature
    assert "Senior Research Consultant" in cr_signature
    assert "Cogentix Research" in cr_signature
    print("✓ Cogentix Research signature correct")
    
    # Check signatures are in rendered templates
    sf_template = get_template_config("surveyfieldwork", "initial_outreach")
    sf_rendered = render_template(sf_template, {"first_name": "Test", "company": "Test"})
    assert "Indira" in sf_rendered["body_html"]
    assert "indira@surveyfieldwork.com" in sf_rendered["body_html"]
    print("✓ Signatures properly included in rendered emails")
    
    print("\n✅ All email signature tests passed!")


def test_personalization_variables():
    """Test that personalization variables work correctly"""
    print("\n" + "="*80)
    print("TEST 5: PERSONALIZATION VARIABLES")
    print("="*80)
    
    # Test with multiple variables
    template = get_template_config("surveyfieldwork", "initial_outreach")
    variables = {
        "first_name": "Sarah",
        "last_name": "Johnson",
        "company": "Research Inc",
        "title": "Director",
        "industry": "Market Research"
    }
    
    rendered = render_template(template, variables)
    
    assert "Sarah" in rendered["subject"]
    assert "Sarah" in rendered["body_html"]
    assert "Research Inc" in rendered["body_html"]
    print("✓ Multiple variables render correctly")
    
    # Test missing optional variables (should not crash)
    rendered2 = render_template(template, {
        "first_name": "John",
        "company": "Acme"
    })
    assert "John" in rendered2["subject"]
    print("✓ Optional variables handled correctly")
    
    print("\n✅ All personalization tests passed!")


def test_weekly_sequence():
    """Test that all 4 emails in sequence exist"""
    print("\n" + "="*80)
    print("TEST 6: WEEKLY FOLLOW-UP SEQUENCE")
    print("="*80)
    
    sequence = ["initial_outreach", "follow_up_week1", "follow_up_week2", "follow_up_week3"]
    
    for company in ["surveyfieldwork", "cogentixresearch"]:
        for i, template_name in enumerate(sequence):
            template = get_template_config(company, template_name)
            assert template is not None
            assert len(template["subject"]) > 0
            assert len(template["body_html"]) > 0
        
        company_name = "Survey Fieldwork" if company == "surveyfieldwork" else "Cogentix Research"
        print(f"✓ {company_name}: 4-step sequence complete")
    
    print("\n✅ All weekly sequence tests passed!")


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*80)
    print("CAMPAIGN AUTOMATION TEST SUITE")
    print("="*80)
    
    try:
        test_services()
        test_email_templates()
        test_template_rendering()
        test_email_signatures()
        test_personalization_variables()
        test_weekly_sequence()
        
        print("\n" + "="*80)
        print("🎉 ALL TESTS PASSED!")
        print("="*80)
        print("\nSummary:")
        print("  ✓ Service configuration working")
        print("  ✓ Email templates loading correctly")
        print("  ✓ Template rendering with variables")
        print("  ✓ Email signatures properly included")
        print("  ✓ Personalization variables working")
        print("  ✓ Weekly follow-up sequences complete")
        print("\nThe campaign automation system is ready to use!")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
