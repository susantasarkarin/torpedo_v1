"""
Gmail Automation - Example Usage Scripts

This file demonstrates various use cases for the Gmail Automation package.
"""

import json
from datetime import datetime, timedelta


def example_basic_usage():
    """Basic email fetching and analysis."""
    from gmail_automation import GmailAutomation
    
    # Initialize the automation
    gmail = GmailAutomation()
    
    # Authenticate (will open browser on first run)
    if not gmail.authenticate():
        print("Authentication failed!")
        return
    
    # Fetch unread emails
    emails = gmail.fetch_emails(query="is:unread", max_results=10)
    
    print(f"\n📧 Found {len(emails)} unread emails:\n")
    for email in emails:
        print(f"  From: {email.sender}")
        print(f"  Subject: {email.subject}")
        print(f"  Date: {email.date}")
        print(f"  Preview: {email.snippet[:100]}...")
        print("-" * 50)


def example_sentiment_analysis():
    """Analyze sentiment of emails."""
    from gmail_automation import GmailAutomation
    
    gmail = GmailAutomation()
    gmail.authenticate()
    
    # Fetch and analyze
    results = gmail.fetch_and_analyze(
        query="is:unread",
        max_emails=20
    )
    
    print(f"\n📊 Analysis Results for {results['email_count']} emails:\n")
    
    # Sentiment distribution
    print("Sentiment Distribution:")
    for sentiment, count in results['sentiment_summary']['sentiment_distribution'].items():
        print(f"  {sentiment}: {count}")
    
    # Emails requiring attention
    attention_needed = results.get('requires_attention', [])
    if attention_needed:
        print(f"\n⚠️ {len(attention_needed)} emails require attention:")
        for item in attention_needed[:5]:
            email = item['email']
            print(f"  - {email['subject'][:50]}...")


def example_categorization():
    """Custom email categorization."""
    from gmail_automation import GmailAutomation
    from gmail_automation.categorizer import CategoryPriority
    
    gmail = GmailAutomation()
    gmail.authenticate()
    
    # Add custom categorization rules
    gmail.add_categorization_rule(
        category="clients",
        keywords=["project", "invoice", "payment"],
        sender_patterns=[r"@clientcompany\.com$"]
    )
    
    gmail.add_categorization_rule(
        category="team",
        sender_patterns=[r"@mycompany\.com$"]
    )
    
    # Add VIP senders
    gmail.add_vip_sender("boss@company.com")
    gmail.add_vip_sender("important-client@example.com")
    
    # Fetch and categorize
    emails = gmail.fetch_emails(max_results=50)
    categories = gmail.categorize_emails(emails)
    
    print("\n🏷️ Email Categories:\n")
    for category, results in categories.items():
        print(f"  {category}: {len(results)} emails")


def example_compose_response():
    """Compose automated responses."""
    from gmail_automation import GmailAutomation
    
    gmail = GmailAutomation()
    gmail.authenticate()
    
    # Set up composer with defaults
    gmail._composer.default_name = "John Smith"
    gmail._composer.company_name = "Acme Corporation"
    
    # Fetch an email to respond to
    emails = gmail.fetch_emails(query="is:unread", max_results=1)
    
    if not emails:
        print("No emails to respond to")
        return
    
    email = emails[0]
    
    # Analyze the email
    gmail.analyze_sentiment([email])
    
    # Compose response
    response = gmail.compose_response(
        email_id=email.id,
        template="acknowledgment",
        custom_content="I've reviewed your request and will get back to you by end of day."
    )
    
    print("\n✉️ Composed Response:\n")
    print(f"  To: {response.to}")
    print(f"  Subject: {response.subject}")
    print(f"  Body:\n{response.body_text}")
    
    # Optionally send (uncomment to actually send)
    # result = gmail.send_email(response)
    # print(f"Sent: {result['message_id']}")


def example_multi_account():
    """Working with multiple Gmail accounts."""
    from gmail_automation import GmailAutomation
    
    # Enable multi-account mode
    gmail = GmailAutomation(multi_account=True)
    
    # Get account manager
    manager = gmail.get_account_manager()
    
    # Add accounts (each needs its own credentials file)
    # manager.add_account("work", "work_credentials.json")
    # manager.add_account("personal", "personal_credentials.json")
    
    # List accounts
    print("\n👥 Accounts:\n")
    for account in manager.list_accounts():
        print(f"  {account['id']}: {account['email']}")
        print(f"    Aliases: {len(account['aliases'])}")
        print(f"    Sent today: {account['sent_today']}/{account['daily_limit']}")
    
    # Get usage stats
    stats = manager.get_usage_stats()
    print(f"\n📈 Total sent today: {stats['total_sent_today']}")


def example_openai_analysis():
    """Advanced AI analysis with OpenAI."""
    import os
    from gmail_automation import GmailAutomation
    
    # Requires OPENAI_API_KEY environment variable
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("Set OPENAI_API_KEY environment variable to use this example")
        return
    
    gmail = GmailAutomation(
        use_openai=True,
        openai_api_key=api_key
    )
    gmail.authenticate()
    
    # Fetch emails
    emails = gmail.fetch_emails(query="is:unread", max_results=5)
    
    # Analyze with AI
    sentiments = gmail.analyze_sentiment(emails)
    
    print("\n🤖 AI Analysis Results:\n")
    for email, sentiment in zip(emails, sentiments):
        print(f"Email: {email.subject[:40]}...")
        print(f"  Sentiment: {sentiment.sentiment.value}")
        print(f"  Summary: {sentiment.summary}")
        print(f"  Key Phrases: {sentiment.key_phrases}")
        print("-" * 50)


def example_export_results():
    """Export analysis results to file."""
    from gmail_automation import GmailAutomation
    
    gmail = GmailAutomation()
    gmail.authenticate()
    
    # Full analysis
    results = gmail.fetch_and_analyze(
        query="newer_than:7d",  # Last 7 days
        max_emails=100
    )
    
    # Export to JSON
    output_file = f"email_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    gmail.export_results(output_file)
    
    print(f"\n💾 Results exported to {output_file}")
    print(f"  Emails analyzed: {results['email_count']}")


def example_scheduled_processing():
    """Example of processing emails on a schedule."""
    from gmail_automation import GmailAutomation
    import time
    
    gmail = GmailAutomation()
    gmail.authenticate()
    
    def process_emails():
        """Process unread emails and generate report."""
        results = gmail.fetch_and_analyze(query="is:unread")
        
        # Log results
        print(f"[{datetime.now()}] Processed {results['email_count']} emails")
        
        # Handle urgent emails
        for email_data in results.get('requires_attention', []):
            email = email_data['email']
            print(f"  ⚠️ Urgent: {email['subject']}")
            
            # Could auto-compose acknowledgment here
            # response = gmail.compose_response(email['id'], template='urgent_response')
            # gmail.send_email(response)
        
        return results
    
    # Run once
    process_emails()
    
    # For continuous processing, use a scheduler like APScheduler
    # from apscheduler.schedulers.blocking import BlockingScheduler
    # scheduler = BlockingScheduler()
    # scheduler.add_job(process_emails, 'interval', minutes=5)
    # scheduler.start()


if __name__ == "__main__":
    print("Gmail Automation Examples")
    print("=" * 50)
    print("\nAvailable examples:")
    print("  1. example_basic_usage()")
    print("  2. example_sentiment_analysis()")
    print("  3. example_categorization()")
    print("  4. example_compose_response()")
    print("  5. example_multi_account()")
    print("  6. example_openai_analysis()")
    print("  7. example_export_results()")
    print("  8. example_scheduled_processing()")
    print("\nRun the examples interactively or uncomment the one you want to run.")
    
    # Uncomment to run an example:
    # example_basic_usage()
