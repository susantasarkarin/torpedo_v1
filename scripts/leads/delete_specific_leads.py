"""
Delete specific leads from the database
"""

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["email_automation"]

# Leads to delete
emails_to_delete = [
    "john.smith@techcorp.com",
    "sarah.jones@innovate.io",
    "mike.chen@startup.com"
]

print("🗑️  Deleting specified leads...\n")

for email in emails_to_delete:
    # Find the lead first
    lead = db.leads_enriched.find_one({"email": email})
    
    if lead:
        # Delete from leads_enriched
        result = db.leads_enriched.delete_one({"email": email})
        if result.deleted_count > 0:
            print(f"✅ Deleted: {lead.get('name', 'Unknown')} ({email})")
        else:
            print(f"❌ Failed to delete: {email}")
    else:
        print(f"⚠️  Not found: {email}")

print(f"\n✨ Deletion complete!")

# Show remaining leads
remaining = db.leads_enriched.count_documents({})
print(f"\n📊 Remaining leads in database: {remaining}")

if remaining > 0:
    print("\nRemaining leads:")
    for lead in db.leads_enriched.find({}, {"name": 1, "email": 1, "title": 1}):
        print(f"  - {lead.get('name')} ({lead.get('email')})")
