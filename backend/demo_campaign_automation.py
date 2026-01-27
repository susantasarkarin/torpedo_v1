"""
DEMO SCRIPT FOR CAMPAIGN AUTOMATION
====================================

This script demonstrates the campaign automation features.
Run: python -m backend.demo_campaign_automation
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campaigns.services_config import get_company_config, list_all_services
from campaigns.email_templates import get_template_config, render_template


def demo_services():
    """Demonstrate service listing"""
    print("\n" + "="*80)
    print("DEMO 1: SERVICES OFFERED BY BOTH COMPANIES")
    print("="*80)
    
    services = list_all_services()
    
    print("\n📋 SURVEY FIELDWORK SERVICES:")
    print("-" * 80)
    for service in services["surveyfieldwork"]:
        print(f"  • {service['name']}")
        print(f"    {service['description']}")
        print()
    
    print("\n📋 COGENTIX RESEARCH SERVICES:")
    print("-" * 80)
    for service in services["cogentixresearch"]:
        print(f"  • {service['name']}")
        print(f"    {service['description']}")
        print()


def demo_email_personalization():
    """Demonstrate personalized email generation"""
    print("\n" + "="*80)
    print("DEMO 2: PERSONALIZED EMAIL GENERATION")
    print("="*80)
    
    # Survey Fieldwork example
    print("\n📧 SURVEY FIELDWORK - Initial Outreach")
    print("-" * 80)
    
    sf_config = get_company_config("surveyfieldwork")
    print(f"From: {sf_config['sender_name']} <{sf_config['sender_email']}>")
    print(f"Company: {sf_config['company_name']}")
    print()
    
    sf_template = get_template_config("surveyfieldwork", "initial_outreach")
    sf_email = render_template(sf_template, {
        "first_name": "Sarah",
        "company": "Global Research Agency"
    })
    
    print(f"Subject: {sf_email['subject']}")
    print(f"\nBody Preview (first 500 chars):")
    print("-" * 80)
    # Remove HTML tags for preview
    import re
    preview = re.sub(r'<[^>]+>', '', sf_email['body_html'])[:500]
    print(preview + "...")
    
    # Cogentix Research example
    print("\n\n📧 COGENTIX RESEARCH - Initial Outreach")
    print("-" * 80)
    
    cr_config = get_company_config("cogentixresearch")
    print(f"From: {cr_config['sender_name']} <{cr_config['sender_email']}>")
    print(f"Company: {cr_config['company_name']}")
    print()
    
    cr_template = get_template_config("cogentixresearch", "initial_outreach")
    cr_email = render_template(cr_template, {
        "first_name": "Michael",
        "company": "TechCorp Solutions"
    })
    
    print(f"Subject: {cr_email['subject']}")
    print(f"\nBody Preview (first 500 chars):")
    print("-" * 80)
    preview = re.sub(r'<[^>]+>', '', cr_email['body_html'])[:500]
    print(preview + "...")


def demo_email_sequence():
    """Demonstrate weekly follow-up sequence"""
    print("\n" + "="*80)
    print("DEMO 3: WEEKLY FOLLOW-UP SEQUENCE")
    print("="*80)
    
    sequence = [
        ("initial_outreach", "Day 0"),
        ("follow_up_week1", "Day 7"),
        ("follow_up_week2", "Day 14"),
        ("follow_up_week3", "Day 21")
    ]
    
    print("\n📅 SURVEY FIELDWORK - 4-Step Outreach Sequence")
    print("-" * 80)
    
    for template_name, day in sequence:
        template = get_template_config("surveyfieldwork", template_name)
        email = render_template(template, {
            "first_name": "John",
            "company": "Acme Corp",
            "industry": "Technology"
        })
        print(f"\n{day}: {template['name']}")
        print(f"Subject: {email['subject']}")
        print(f"Condition: Sent if no reply received" if "follow_up" in template_name else "Condition: Always sent")


def demo_email_signatures():
    """Demonstrate email signatures"""
    print("\n" + "="*80)
    print("DEMO 4: EMAIL SIGNATURES")
    print("="*80)
    
    print("\n✉️ SURVEY FIELDWORK SIGNATURE:")
    print("-" * 80)
    sf_config = get_company_config("surveyfieldwork")
    # Strip HTML for display
    import re
    signature = re.sub(r'<[^>]+>', '\n', sf_config['email_signature'])
    signature = re.sub(r'\n\n+', '\n', signature)
    print(signature.strip())
    
    print("\n\n✉️ COGENTIX RESEARCH SIGNATURE:")
    print("-" * 80)
    cr_config = get_company_config("cogentixresearch")
    signature = re.sub(r'<[^>]+>', '\n', cr_config['email_signature'])
    signature = re.sub(r'\n\n+', '\n', signature)
    print(signature.strip())


def demo_tracking_features():
    """Demonstrate tracking capabilities"""
    print("\n" + "="*80)
    print("DEMO 5: EMAIL TRACKING FEATURES")
    print("="*80)
    
    print("\n📊 TRACKING CAPABILITIES:")
    print("-" * 80)
    print("  ✓ OPENED - Email was opened by recipient")
    print("  ✓ CLICKED - Links in email were clicked")
    print("  ✓ BOUNCED - Email bounced (automatically stops sequence)")
    print("  ✓ NOT_OPENED - Email sent but not opened")
    print("  ✓ REPLIED - Recipient replied (automatically stops sequence)")
    print("  ✓ UNSUBSCRIBED - Recipient unsubscribed (stops sequence)")
    
    print("\n🔄 AUTOMATIC BOUNCE HANDLING:")
    print("-" * 80)
    print("  1. Email bounces detected via tracking webhook")
    print("  2. Recipient status automatically updated to 'BOUNCED'")
    print("  3. Campaign sequence stopped for that recipient")
    print("  4. Send status updated with bounce timestamp")
    
    print("\n📈 METRICS TRACKED:")
    print("-" * 80)
    print("  • Open Rate: % of emails opened")
    print("  • Click Rate: % of emails with clicks")
    print("  • Bounce Rate: % of emails that bounced")
    print("  • Reply Rate: % of recipients who replied")
    print("  • Not Opened: Count of emails sent but not opened")


def demo_api_usage():
    """Demonstrate API usage examples"""
    print("\n" + "="*80)
    print("DEMO 6: API USAGE EXAMPLES")
    print("="*80)
    
    print("\n🔌 CREATE AUTOMATED CAMPAIGN:")
    print("-" * 80)
    print("""
POST /api/campaigns/automation/campaigns

{
  "company": "surveyfieldwork",
  "campaign_name": "Q1 2024 Outreach",
  "recipients": [
    {
      "email": "director@research-agency.com",
      "first_name": "Sarah",
      "company": "Global Research Agency"
    }
  ],
  "start_immediately": true
}
    """)
    
    print("\n🔌 TRACK EMAIL EVENTS:")
    print("-" * 80)
    print("""
POST /api/campaigns/automation/tracking/events

{
  "events": [
    {
      "email": "director@research-agency.com",
      "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
      "event": "opened"
    },
    {
      "email": "bounce@example.com",
      "campaign_id": "60f7b3c9e4b0c8a5d8f9e1a2",
      "event": "bounced"
    }
  ]
}
    """)
    
    print("\n🔌 GET CAMPAIGN REPORT:")
    print("-" * 80)
    print("""
GET /api/campaigns/automation/campaigns/{campaign_id}/report

Response includes:
- Recipient status breakdown (bounced, replied, etc.)
- Send status breakdown (opened, not_opened, etc.)
- Engagement rates (open rate, bounce rate, etc.)
    """)


def run_demo():
    """Run all demonstrations"""
    print("\n" + "="*80)
    print("🚀 CAMPAIGN AUTOMATION SYSTEM DEMO")
    print("="*80)
    print("\nThis demo showcases the automated email campaign system for:")
    print("  • Survey Fieldwork (indira@surveyfieldwork.com)")
    print("  • Cogentix Research (meera@cogentixresearch.com)")
    
    demo_services()
    demo_email_personalization()
    demo_email_sequence()
    demo_email_signatures()
    demo_tracking_features()
    demo_api_usage()
    
    print("\n" + "="*80)
    print("✅ DEMO COMPLETE")
    print("="*80)
    print("\nKey Features Demonstrated:")
    print("  ✓ Service identification for both companies")
    print("  ✓ Personalized emails with appropriate sender")
    print("  ✓ Weekly follow-up sequences (4 emails)")
    print("  ✓ Professional email signatures")
    print("  ✓ Email tracking (opens, bounces, clicks)")
    print("  ✓ Automatic bounce status updates")
    print("\nFor full documentation, see: CAMPAIGN_AUTOMATION_DOCS.md")


if __name__ == "__main__":
    run_demo()
