"""
INTEGRATION EXAMPLE
===================

Example demonstrating how to use PersonalizationEngine and RulesEngine together
in a campaign workflow.

This shows the complete flow:
1. Personalizing email content for a recipient
2. Sending the email
3. Tracking engagement (opens, clicks, replies)
4. Evaluating rules based on engagement
5. Taking automated actions
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campaigns.personalization_engine import PersonalizationEngine, create_engine_with_ai
from campaigns.rules_engine import RulesEngine
from datetime import datetime, timedelta


def example_personalization_workflow():
    """
    Example: Personalize email content for different leads at different levels.
    """
    print("=" * 80)
    print("PERSONALIZATION ENGINE EXAMPLE")
    print("=" * 80)
    
    # Initialize engine
    engine = PersonalizationEngine()
    
    # Sample email template
    template = """
    Hi {{first_name}},
    
    I noticed that {{company}} is in the {{industry}} space and wanted to reach out.
    
    As a {{title}}, you're probably dealing with {{pain_point}} challenges.
    Our solution helps {{use_case}} by providing {{value_proposition}}.
    
    Would you be open to a quick 15-minute call to discuss how we've helped 
    similar companies in {{location}}?
    
    Best regards,
    Sales Team
    """
    
    # Sample lead data
    lead = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@acme.com",
        "company_name": "Acme Corporation",
        "title": "VP of Sales",
        "industry": "Technology",
        "seniority": "Senior",
        "department": "Sales",
        "pain_point": "inefficient lead qualification",
        "use_case": "streamline sales processes",
        "value_proposition": "30% faster deal cycles",
        "location": "San Francisco, CA",
        "city": "San Francisco",
        "state": "CA"
    }
    
    # Level 1: Light Personalization (name, company, industry only)
    print("\n--- LEVEL 1: Light Personalization ---")
    personalized_l1 = engine.personalize_content(template, lead, level=1)
    print(personalized_l1)
    
    # Level 2: Role-Based Personalization (+ title, seniority, pain points)
    print("\n--- LEVEL 2: Role-Based Personalization ---")
    personalized_l2 = engine.personalize_content(template, lead, level=2)
    print(personalized_l2)
    
    # Level 3: Deep Personalization (all tokens, ready for AI enhancement)
    print("\n--- LEVEL 3: Deep Personalization ---")
    personalized_l3 = engine.personalize_content(template, lead, level=3)
    print(personalized_l3)
    
    # Validate template
    print("\n--- TEMPLATE VALIDATION ---")
    validation = engine.validate_template(template, level=2)
    print(f"Valid: {validation['valid']}")
    print(f"Tokens found: {validation['tokens_found']}")
    print(f"Tokens allowed at level 2: {validation['tokens_allowed']}")
    print(f"Tokens blocked at level 2: {validation['tokens_blocked']}")
    if validation['warnings']:
        print(f"Warnings: {validation['warnings']}")
    
    # Batch personalization
    print("\n--- BATCH PERSONALIZATION ---")
    leads = [
        {"first_name": "Jane", "company_name": "TechCorp", "email": "jane@techcorp.com", "industry": "SaaS"},
        {"first_name": "Bob", "company_name": "DataCo", "email": "bob@dataco.com", "industry": "Analytics"},
        {"first_name": "Alice", "company_name": "StartupXYZ", "email": "alice@startupxyz.com", "industry": "E-commerce"},
    ]
    
    simple_template = "Hi {{first_name}}, I see {{company}} is in {{industry}}..."
    results = engine.batch_personalize(simple_template, leads, level=1)
    
    for result in results:
        print(f"\n{result['email']}:")
        print(f"  Status: {result['status']}")
        print(f"  Content: {result['personalized_content'][:80]}...")
    
    print("\n" + "=" * 80)


def example_rules_engine_workflow():
    """
    Example: Evaluate rules and execute actions based on recipient engagement.
    """
    print("\n" + "=" * 80)
    print("RULES ENGINE EXAMPLE")
    print("=" * 80)
    
    # Initialize engine
    engine = RulesEngine(db=None)  # In production, pass MongoDB database
    
    campaign_data = {
        "campaign_id": "campaign_123",
        "sequence_length": 5,
        "current_step": 3,
        "cadence": "weekly"
    }
    
    # Scenario 1: Recipient bounced
    print("\n--- SCENARIO 1: Email Bounced ---")
    recipient_bounced = {
        "email": "bounced@example.com",
        "status": "in_sequence",
        "email_opens": 0,
        "email_clicks": 0,
        "replied": False,
        "bounced": True,
        "unsubscribed": False,
        "emails_sent": 2,
        "last_sent_at": datetime.utcnow()
    }
    
    actions_bounced = engine.evaluate_rules(recipient_bounced, campaign_data)
    print(f"Actions to take: {len(actions_bounced)}")
    for action in actions_bounced:
        print(f"  - {action['action']}: {action['reason']} (Priority: {action['priority']})")
    
    # Scenario 2: Recipient replied
    print("\n--- SCENARIO 2: Recipient Replied ---")
    recipient_replied = {
        "email": "interested@example.com",
        "status": "in_sequence",
        "email_opens": 2,
        "email_clicks": 1,
        "replied": True,
        "bounced": False,
        "unsubscribed": False,
        "emails_sent": 2,
        "last_sent_at": datetime.utcnow() - timedelta(days=3),
        "last_replied_at": datetime.utcnow()
    }
    
    actions_replied = engine.evaluate_rules(recipient_replied, campaign_data)
    print(f"Actions to take: {len(actions_replied)}")
    for action in actions_replied:
        print(f"  - {action['action']}: {action['reason']} (Priority: {action['priority']})")
    
    # Scenario 3: Warm lead (multiple opens, no reply)
    print("\n--- SCENARIO 3: Warm Lead (Multiple Opens) ---")
    recipient_warm = {
        "email": "warm@example.com",
        "status": "in_sequence",
        "email_opens": 3,
        "email_clicks": 0,
        "replied": False,
        "bounced": False,
        "unsubscribed": False,
        "emails_sent": 3,
        "last_sent_at": datetime.utcnow() - timedelta(days=2),
        "last_opened_at": datetime.utcnow() - timedelta(hours=6)
    }
    
    actions_warm = engine.evaluate_rules(recipient_warm, campaign_data)
    print(f"Actions to take: {len(actions_warm)}")
    for action in actions_warm:
        print(f"  - {action['action']}: {action['reason']} (Priority: {action['priority']})")
    
    # Scenario 4: Cold lead (no engagement)
    print("\n--- SCENARIO 4: Cold Lead (No Opens) ---")
    recipient_cold = {
        "email": "cold@example.com",
        "status": "in_sequence",
        "email_opens": 0,
        "email_clicks": 0,
        "replied": False,
        "bounced": False,
        "unsubscribed": False,
        "emails_sent": 3,
        "last_sent_at": datetime.utcnow() - timedelta(days=7)
    }
    
    actions_cold = engine.evaluate_rules(recipient_cold, campaign_data)
    print(f"Actions to take: {len(actions_cold)}")
    for action in actions_cold:
        print(f"  - {action['action']}: {action['reason']} (Priority: {action['priority']})")
    
    # Scenario 5: Unsubscribe request
    print("\n--- SCENARIO 5: Unsubscribe Request ---")
    recipient_unsub = {
        "email": "unsubscribe@example.com",
        "status": "in_sequence",
        "email_opens": 1,
        "email_clicks": 0,
        "replied": False,
        "bounced": False,
        "unsubscribed": True,
        "emails_sent": 2,
        "last_sent_at": datetime.utcnow() - timedelta(days=1)
    }
    
    actions_unsub = engine.evaluate_rules(recipient_unsub, campaign_data)
    print(f"Actions to take: {len(actions_unsub)}")
    for action in actions_unsub:
        print(f"  - {action['action']}: {action['reason']} (Priority: {action['priority']})")
    
    # Execute actions (dry run - would integrate with CampaignManager in production)
    print("\n--- EXECUTING ACTIONS (Dry Run) ---")
    execution_result = engine.execute_actions(actions_warm, campaign_manager=None)
    print(f"Status: {execution_result['status']}")
    print(f"Actions executed: {execution_result['actions_executed']}")
    print(f"Actions failed: {execution_result['actions_failed']}")
    
    print("\n" + "=" * 80)


def example_integrated_workflow():
    """
    Example: Complete workflow combining both engines.
    """
    print("\n" + "=" * 80)
    print("INTEGRATED WORKFLOW EXAMPLE")
    print("=" * 80)
    
    # Initialize both engines
    personalization = PersonalizationEngine()
    rules = RulesEngine(db=None)
    
    # Campaign setup
    campaign_data = {
        "campaign_id": "integrated_campaign_001",
        "campaign_name": "Q1 Outreach",
        "sequence_length": 4,
        "current_step": 1,
        "cadence": "weekly"
    }
    
    # Lead data
    lead = {
        "first_name": "Sarah",
        "last_name": "Johnson",
        "email": "sarah.johnson@example.com",
        "company_name": "Example Corp",
        "title": "Director of Marketing",
        "industry": "B2B SaaS",
        "seniority": "Director",
        "department": "Marketing",
        "pain_point": "low conversion rates",
        "use_case": "optimize marketing campaigns",
        "value_proposition": "increase ROI by 40%"
    }
    
    # Step 1: Personalize initial outreach email
    print("\n--- STEP 1: Personalize Email ---")
    template = """
    Hi {{first_name}},
    
    I noticed {{company}} is in the {{industry}} space and thought you might be 
    interested in how we help companies solve {{pain_point}}.
    
    As {{title}}, you'd appreciate our approach to {{use_case}} - we've helped 
    similar companies {{value_proposition}}.
    
    Would you be open to a brief call next week?
    
    Best,
    Sales Team
    """
    
    personalized_email = personalization.personalize_content(template, lead, level=2)
    print("Personalized email:")
    print(personalized_email)
    
    # Step 2: Simulate email engagement tracking
    print("\n--- STEP 2: Tracking Engagement ---")
    
    # After email is sent, track recipient behavior
    recipient_data = {
        "email": lead["email"],
        "status": "in_sequence",
        "email_opens": 2,  # Opened twice
        "email_clicks": 1,  # Clicked a link
        "replied": False,
        "bounced": False,
        "unsubscribed": False,
        "emails_sent": 1,
        "last_sent_at": datetime.utcnow(),
        "last_opened_at": datetime.utcnow() - timedelta(hours=2)
    }
    
    print(f"Recipient: {recipient_data['email']}")
    print(f"Opens: {recipient_data['email_opens']}")
    print(f"Clicks: {recipient_data['email_clicks']}")
    print(f"Replied: {recipient_data['replied']}")
    
    # Step 3: Evaluate rules based on engagement
    print("\n--- STEP 3: Evaluate Automation Rules ---")
    actions = rules.evaluate_rules(recipient_data, campaign_data)
    
    print(f"Rules triggered: {len(actions)}")
    for action in actions:
        print(f"\n  Action: {action['action']}")
        print(f"  Reason: {action['reason']}")
        print(f"  Priority: {action['priority']}")
        print(f"  Data: {action['data']}")
    
    # Step 4: Execute actions
    print("\n--- STEP 4: Execute Actions ---")
    execution_result = rules.execute_actions(actions, campaign_manager=None)
    print(f"Execution status: {execution_result['status']}")
    print(f"Successfully executed: {execution_result['actions_executed']} actions")
    
    # Step 5: Prepare follow-up (if sequence continues)
    if not any(a['action'] == 'stop_sequence' for a in actions):
        print("\n--- STEP 5: Prepare Follow-Up ---")
        followup_template = """
        Hi {{first_name}},
        
        Following up on my previous email about {{value_proposition}} for {{company}}.
        
        I saw you checked out our materials - would love to discuss how we can help with {{pain_point}}.
        
        Best,
        Sales Team
        """
        
        followup_personalized = personalization.personalize_content(followup_template, lead, level=2)
        print("Follow-up email ready:")
        print(followup_personalized[:200] + "...")
    else:
        print("\n--- STEP 5: Sequence Stopped ---")
        print("No follow-up needed - recipient engaged or opted out")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    # Run all examples
    example_personalization_workflow()
    example_rules_engine_workflow()
    example_integrated_workflow()
    
    print("\n" + "=" * 80)
    print("EXAMPLES COMPLETED")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Integrate PersonalizationEngine with email sending in campaign_automation.py")
    print("2. Integrate RulesEngine with webhook handlers for tracking opens/clicks/replies")
    print("3. Set up OutreachComposerAgent for Level 3 AI personalization")
    print("4. Configure MongoDB for rules execution and suppression list management")
    print("=" * 80)
