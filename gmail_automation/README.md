# Gmail Automation

A comprehensive, modular Python application for Gmail automation with OAuth 2.0 authentication, AI-powered email analysis, and intelligent response generation.

## Features

- 🔐 **OAuth 2.0 Authentication** - Secure Gmail API access with token management
- 📧 **Email Fetching** - Fetch and parse emails with advanced filtering
- 🏷️ **Smart Categorization** - Rule-based email categorization with custom rules
- 🧠 **AI Sentiment Analysis** - Analyze tone, urgency, and intent of emails
- ✍️ **Automated Responses** - Generate personalized replies using templates or AI
- 👥 **Multi-Account Support** - Manage multiple Gmail accounts and aliases
- 🔌 **Modular Architecture** - Easy to extend and customize

## Installation

### 1. Install Dependencies

```bash
cd gmail_automation
pip install -r requirements.txt
```

### 2. Download TextBlob Data (for offline sentiment analysis)

```bash
python -m textblob.download_corpora
```

### 3. Set Up Google Cloud Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **Gmail API**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Choose **Desktop Application**
6. Download the credentials JSON file
7. Save it as `credentials.json` in your working directory

## Quick Start

### Python API

```python
from gmail_automation import GmailAutomation

# Initialize
gmail = GmailAutomation()

# Authenticate (opens browser for OAuth)
gmail.authenticate()

# Fetch and analyze unread emails
results = gmail.fetch_and_analyze(query="is:unread", max_emails=20)

# Print summary
print(f"Analyzed {results['email_count']} emails")
print(f"Categories: {results['categorization_stats']}")
print(f"Sentiment: {results['sentiment_summary']}")

# Compose a response
response = gmail.compose_response(
    email_id="some_email_id",
    template="acknowledgment",
    custom_content="I'll review this and get back to you shortly."
)

# Send the response
result = gmail.send_email(response)
print(f"Sent: {result['message_id']}")
```

### Command Line Interface

```bash
# Check status
python -m gmail_automation status

# Fetch unread emails
python -m gmail_automation fetch --query "is:unread" --max 20

# Analyze emails with full report
python -m gmail_automation analyze --query "is:unread" --output report.json

# Compose and send an email
python -m gmail_automation compose --to "recipient@example.com" \
    --subject "Hello" --body "Test message" --send
```

## Module Overview

### Authentication (`auth.py`)

```python
from gmail_automation.auth import GmailAuthenticator

auth = GmailAuthenticator(credentials_path="credentials.json")
service = auth.authenticate()
email = auth.get_user_email()
```

### Email Fetcher (`email_fetcher.py`)

```python
from gmail_automation.email_fetcher import EmailFetcher

fetcher = EmailFetcher(service)

# Fetch with various filters
emails = fetcher.fetch_emails(query="is:unread", max_results=50)
unread = fetcher.fetch_unread()
starred = fetcher.fetch_starred()
from_sender = fetcher.fetch_from_sender("boss@company.com")

# Get full thread
thread = fetcher.get_thread(email.thread_id)
```

### Categorizer (`categorizer.py`)

```python
from gmail_automation.categorizer import EmailCategorizer, CategorizationRule

categorizer = EmailCategorizer()

# Add custom rules
categorizer.add_simple_rule(
    category="client",
    keywords=["project", "deliverable"],
    sender_patterns=[r"@clientcompany\.com$"]
)

# Add VIP senders
categorizer.add_vip_sender("ceo@company.com")

# Categorize emails
results = categorizer.categorize_batch(emails)
```

### Sentiment Analyzer (`sentiment_analyzer.py`)

```python
from gmail_automation.sentiment_analyzer import SentimentAnalyzer

# Basic analysis (TextBlob - no API needed)
analyzer = SentimentAnalyzer()
result = analyzer.analyze(email)

print(f"Sentiment: {result.sentiment}")  # positive, negative, neutral
print(f"Tone: {result.tone}")            # professional, urgent, friendly
print(f"Urgency: {result.urgency}")      # critical, high, medium, low
print(f"Intent: {result.intent}")        # request, complaint, inquiry

# Advanced analysis with OpenAI
analyzer = SentimentAnalyzer(use_openai=True, openai_api_key="sk-...")
```

### Email Composer (`email_composer.py`)

```python
from gmail_automation.email_composer import EmailComposer

composer = EmailComposer(
    service=service,
    default_name="John Smith",
    company_name="Acme Corp"
)

# Compose response using template
response = composer.compose_response(
    original_email=email,
    sentiment_result=sentiment,
    template_name="acknowledgment"
)

# Compose new email
email = composer.compose_new(
    to=["recipient@example.com"],
    subject="Hello",
    body="Your message here",
    cc=["cc@example.com"]
)

# Send or save as draft
composer.send_email(email)
composer.save_draft(email)
```

### Account Manager (`account_manager.py`)

```python
from gmail_automation.account_manager import AccountManager

manager = AccountManager()

# Add multiple accounts
manager.add_account("work", "work_credentials.json")
manager.add_account("personal", "personal_credentials.json")

# Add aliases
manager.add_alias("work", "sales@company.com", "Sales Team")

# Set routing rules
from gmail_automation.account_manager import RoutingRule

manager.add_routing_rule(RoutingRule(
    name="sales_emails",
    account_id="work",
    alias_email="sales@company.com",
    category_match=["sales", "inquiry"]
))

# Get appropriate sending address
account, alias = manager.get_sending_address(category="sales")
```

## Configuration

Edit `config.json` to customize behavior:

```json
{
    "categorization": {
        "custom_rules": [
            {
                "name": "urgent_clients",
                "category": "urgent",
                "keywords": ["urgent", "asap"],
                "sender_patterns": ["@importantclient.com"]
            }
        ],
        "vip_senders": ["ceo@company.com", "vip@partner.com"]
    },
    "sentiment_analysis": {
        "use_openai": true
    }
}
```

## Templates

Built-in email templates:

| Template | Use Case |
|----------|----------|
| `acknowledgment` | Simple receipt acknowledgment |
| `urgent_response` | Response to urgent emails |
| `support_response` | Customer support replies |
| `complaint_response` | Handling complaints |
| `follow_up` | Follow-up messages |
| `thank_you` | Appreciation responses |
| `introduction` | Outreach/introduction emails |

Add custom templates:

```python
from gmail_automation.email_composer import EmailTemplate

composer.add_template(EmailTemplate(
    name="my_template",
    subject="Re: {{original_subject}}",
    body="""Hi {{sender_name}},

{{custom_content}}

Best,
{{my_name}}"""
))
```

## Project Structure

```
gmail_automation/
├── __init__.py          # Package exports
├── auth.py              # OAuth 2.0 authentication
├── email_fetcher.py     # Email fetching and parsing
├── categorizer.py       # Email categorization rules
├── sentiment_analyzer.py # AI sentiment analysis
├── email_composer.py    # Email composition and sending
├── account_manager.py   # Multi-account management
├── main.py              # Main application and CLI
├── config.json          # Configuration file
├── requirements.txt     # Dependencies
└── README.md           # This file
```

## Security Notes

- **Credentials**: Never commit `credentials.json` or `token.pickle` to version control
- **API Keys**: Use environment variables for OpenAI API keys
- **Scopes**: Request only necessary Gmail API scopes
- **Tokens**: Tokens are stored securely in `~/.gmail_automation/`

## Requirements

- Python 3.9+
- Google Cloud Project with Gmail API enabled
- OAuth 2.0 credentials (Desktop App)
- (Optional) OpenAI API key for advanced analysis

## License

MIT License

## Contributing

Contributions welcome! Please read the contributing guidelines before submitting PRs.
