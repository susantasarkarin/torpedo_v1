
import sys
import os

# Add the current directory to path
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), 'backend')))

from leads.imap_leads_service import extract_name_from_email, parse_email_signature

test_emails = [
    "John Doe <john.doe@example.com>",
    "\"Doe, John\" <john.doe@example.com>",
    "john.doe@example.com",
    "jane_smith@comp.org",
    "Support Staff <support@company.com>",
    "info@domain.com"
]

print("--- Testing extract_name_from_email ---")
for email in test_emails:
    name, first, last = extract_name_from_email(email)
    print(f"Input: {email}")
    print(f"Result: Name='{name}', First='{first}', Last='{last}'")
    print("-" * 20)

test_bodies = [
    "Hi there,\n\nBest regards,\n\nJohn Smith\nCEO | Company Inc.\nPhone: +1 234 567 890\nLinkedIn: linkedin.com/in/johnsmith",
    "Hello,\n\nThanks,\nJane Doe\nMarketing Manager",
    "Sent from my iPhone"
]

print("\n--- Testing parse_email_signature ---")
for body in test_bodies:
    info = parse_email_signature(body)
    print(f"Body snippet: {body.replace('\\n', ' ')[:50]}...")
    print(f"Extracted info: {info}")
    print("-" * 20)
