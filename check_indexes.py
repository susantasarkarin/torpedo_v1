from pymongo import MongoClient

c = MongoClient()
db = c.torpedo_gmail

# Check existing indexes
print('=== EXISTING INDEXES ===')
indexes = list(db.email_metadata.list_indexes())
for idx in indexes:
    print(f"  {idx['name']} - {idx.get('key')}")

print()
print('=== EMAIL COUNT ===')
print('Total:', db.email_metadata.count_documents({}))
