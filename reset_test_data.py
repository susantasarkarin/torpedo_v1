from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
db = client['email_automation']

# Reset all transferred flags for fresh testing
result = db['leads_enriched'].update_many(
    {'transferred_to_vendor_leads': True},
    {'$unset': {'transferred_to_vendor_leads': '', 'transferred_at': '', 'vendor_lead_id': ''}}
)

print(f"Reset {result.modified_count} leads")

# Clear vendor_leads collection for fresh testing
vendor_result = db['vendor_leads'].delete_many({'transferred_from_ai_database': True})
print(f"Cleared {vendor_result.deleted_count} transferred leads from vendor_leads")
