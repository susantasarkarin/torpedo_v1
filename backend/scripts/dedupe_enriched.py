"""
Deduplicate leads_enriched collection by email and fix indexes
"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Find duplicate emails using aggregation
pipeline = [
    {"$group": {
        "_id": "$email",
        "count": {"$sum": 1},
        "ids": {"$push": "$_id"}
    }},
    {"$match": {"count": {"$gt": 1}}}
]

print("Finding duplicate emails...")
duplicates = list(db.leads_enriched.aggregate(pipeline))
print(f"Found {len(duplicates)} emails with duplicates")

# Keep the first (oldest) entry, delete the rest
total_deleted = 0
for dup in duplicates:
    email = dup["_id"]
    ids = dup["ids"]
    # Keep first, delete rest
    ids_to_delete = ids[1:]
    result = db.leads_enriched.delete_many({"_id": {"$in": ids_to_delete}})
    total_deleted += result.deleted_count
    if total_deleted % 100 == 0:
        print(f"  Progress: deleted {total_deleted} duplicates...")

print(f"Deleted {total_deleted} duplicate leads")

# Now create the email index
print("Creating unique email index...")
try:
    db.leads_enriched.create_index("email", unique=True, sparse=True)
    print("  Email index created successfully!")
except Exception as e:
    print(f"  Error: {e}")

# Show final indexes
print("\nFinal indexes on leads_enriched:")
for idx_name, idx_info in db.leads_enriched.index_information().items():
    print(f"  {idx_name}: {idx_info}")

print(f"\nTotal leads_enriched count: {db.leads_enriched.count_documents({})}")
