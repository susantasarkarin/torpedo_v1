#!/usr/bin/env python3
"""Check lead detail and related emails"""

from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv
load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
leads_db = client["email_automation"]
torpedo_db = client["torpedo_gmail"]

leads_enriched = leads_db["leads_enriched"]
email_metadata = torpedo_db["email_metadata"]

lead_id = "696e32822cc37ab3836523b5"

print("=" * 50)
print("CHECKING LEAD:", lead_id)
print("=" * 50)

# Get lead
lead = leads_enriched.find_one({"_id": ObjectId(lead_id)})
if lead:
    print("\n=== LEAD DATA ===")
    for k in sorted(lead.keys()):
        val = str(lead[k])
        if len(val) > 80:
            val = val[:77] + "..."
        print(f"  {k}: {val}")
    
    lead_email = lead.get("email")
    print(f"\nLead Email: {lead_email}")
    
    if lead_email:
        # Find emails in email_metadata where this email is in from_email or to_emails
        print("\n=== EMAILS FROM/TO THIS LEAD ===")
        
        # Check from_email
        from_count = email_metadata.count_documents({"from_email": {"$regex": lead_email, "$options": "i"}})
        print(f"Emails from {lead_email}: {from_count}")
        
        # Check to_emails
        to_count = email_metadata.count_documents({"to_emails": {"$regex": lead_email, "$options": "i"}})
        print(f"Emails to {lead_email}: {to_count}")
        
        # Get sample emails
        sample_emails = list(email_metadata.find({
            "$or": [
                {"from_email": {"$regex": lead_email, "$options": "i"}},
                {"to_emails": {"$regex": lead_email, "$options": "i"}}
            ]
        }).sort("timestamp", -1).limit(5))
        
        if sample_emails:
            print(f"\nSample emails ({len(sample_emails)}):")
            for e in sample_emails:
                print(f"  - Subject: {e.get('subject', 'N/A')}")
                print(f"    From: {e.get('from_email')} | To: {e.get('to_emails')}")
                print(f"    Date: {e.get('timestamp')}")
                print(f"    Direction: {e.get('direction')}")
                print()
else:
    print("Lead not found")
