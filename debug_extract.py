#!/usr/bin/env python3
"""Debug Gmail extraction - simulate the extraction logic"""
from pymongo import MongoClient
from datetime import datetime

# Connect to databases
client = MongoClient()
email_automation = client['email_automation']
torpedo_gmail = client['torpedo_gmail']

leads_collection = email_automation['leads_raw']
email_metadata = torpedo_gmail['email_metadata']

# Get 100 inbound emails
emails = list(email_metadata.find({'direction': 'inbound'}).limit(100))
print(f"Found {len(emails)} inbound emails")

skip_patterns = ['noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster', 
                'bounce', 'notifications', 'alert', 'system', 'auto', 'newsletter']
internal_domains = ['surveyfieldwork.com', 'cogentixresearch.com']

extracted = 0
skipped_patterns = 0
skipped_internal = 0
duplicates = 0
inserted = 0
errors = 0
seen = set()

for email_doc in emails:
    email_addr = email_doc.get("from_email", "")
    name = email_doc.get("from_name", "")
    
    if not email_addr or "@" not in email_addr:
        continue
    
    email_addr = email_addr.lower().strip()
    
    if email_addr in seen:
        duplicates += 1
        continue
    seen.add(email_addr)
    
    # Skip system emails
    if any(p in email_addr.lower() for p in skip_patterns):
        skipped_patterns += 1
        continue
    
    # Get domain
    domain = email_addr.split("@")[1] if "@" in email_addr else None
    
    # Skip internal
    if domain in internal_domains:
        skipped_internal += 1
        continue
    
    # Check existing
    existing = leads_collection.find_one({"email": email_addr})
    if existing:
        duplicates += 1
        continue
    
    extracted += 1
    
    # Build lead doc
    lead_doc = {
        "email": email_addr,
        "source": "gmail",
        "source_detail": "email_extraction",
        "created_at": datetime.utcnow(),
        "name": name if name else None,
        "classification_status": "pending",
        "company_domain": domain
    }
    
    try:
        result = leads_collection.insert_one(lead_doc)
        inserted += 1
        print(f"Inserted: {email_addr} -> {result.inserted_id}")
    except Exception as e:
        errors += 1
        print(f"Error inserting {email_addr}: {e}")

print(f"\n=== Summary ===")
print(f"Emails processed: {len(emails)}")
print(f"Skipped (patterns): {skipped_patterns}")
print(f"Skipped (internal): {skipped_internal}")
print(f"Duplicates: {duplicates}")
print(f"Extracted: {extracted}")
print(f"Inserted: {inserted}")
print(f"Errors: {errors}")

# Verify count
final_count = leads_collection.count_documents({'source': 'gmail'})
print(f"\nFinal Gmail leads count: {final_count}")
