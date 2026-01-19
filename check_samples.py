from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')
db = client['torpedo_gmail']

# Check RFQ emails
print("=== RFQ EMAILS ===")
emails = list(db.email_metadata.find(
    {'ai_category': 'rfq'},
    {'subject': 1, 'ai_summary': 1, 'ai_urgency': 1, 'ai_is_sales_lead': 1}
).limit(3))

for i, e in enumerate(emails, 1):
    subj = e.get('subject', 'N/A') or 'N/A'
    summary = e.get('ai_summary', 'N/A') or 'N/A'
    print(f"--- RFQ {i} ---")
    print(f"Subject: {subj[:70]}")
    print(f"Is Sales Lead: {e.get('ai_is_sales_lead')}")
    print(f"Urgency: {e.get('ai_urgency')}")
    print(f"Summary: {summary}")
    print()

# Check Client emails  
print("=== CLIENT EMAILS ===")
emails = list(db.email_metadata.find(
    {'ai_category': 'client'},
    {'subject': 1, 'ai_summary': 1, 'ai_urgency': 1}
).limit(3))

for i, e in enumerate(emails, 1):
    subj = e.get('subject', 'N/A') or 'N/A'
    summary = e.get('ai_summary', 'N/A') or 'N/A'
    print(f"--- Client {i} ---")
    print(f"Subject: {subj[:70]}")
    print(f"Urgency: {e.get('ai_urgency')}")
    print(f"Summary: {summary}")
    print()
