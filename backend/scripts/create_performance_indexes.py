#!/usr/bin/env python3
"""
Create missing indexes for Mail Pool performance optimization.
These indexes are critical for fast count_documents() and aggregation queries.
"""

from pymongo import MongoClient, ASCENDING, DESCENDING

c = MongoClient()
db = c.torpedo_gmail

print("Creating performance indexes for Mail Pool...")

# Indexes for Mail Pool stats endpoint
indexes_to_create = [
    # For direction filtering (inbox/outbox counts)
    {"keys": [("direction", ASCENDING)], "name": "direction_1"},
    
    # For labels filtering (drafts, starred)
    {"keys": [("labels", ASCENDING)], "name": "labels_1"},
    
    # For category aggregation
    {"keys": [("category", ASCENDING)], "name": "category_1"},
    
    # For timestamp sorting (most common query)
    {"keys": [("timestamp", DESCENDING)], "name": "timestamp_-1"},
    
    # Compound index for email listing with filters
    {"keys": [("direction", ASCENDING), ("timestamp", DESCENDING)], "name": "direction_1_timestamp_-1"},
    
    # For AI classification queries  
    {"keys": [("ai_category", ASCENDING), ("timestamp", DESCENDING)], "name": "ai_category_1_timestamp_-1"},
    
    # For unclassified emails (classification script)
    {"keys": [("ai_category", ASCENDING)], "name": "ai_category_exists", "partialFilterExpression": {"ai_category": {"$exists": False}}},
    
    # For search queries
    {"keys": [("subject", "text"), ("from_email", "text"), ("snippet", "text")], "name": "text_search"},
]

for idx in indexes_to_create:
    name = idx["name"]
    keys = idx["keys"]
    partial = idx.get("partialFilterExpression")
    
    try:
        # Check if index exists
        existing = list(db.email_metadata.list_indexes())
        existing_names = [i["name"] for i in existing]
        
        if name in existing_names:
            print(f"  ✓ Index '{name}' already exists")
            continue
        
        # Create index
        if partial:
            db.email_metadata.create_index(keys, name=name, partialFilterExpression=partial, background=True)
        else:
            db.email_metadata.create_index(keys, name=name, background=True)
        print(f"  ✓ Created index '{name}'")
    except Exception as e:
        print(f"  ✗ Error creating index '{name}': {e}")

print()
print("Done! Indexes are being created in background.")
print()

# Show all indexes
print("=== ALL INDEXES ===")
for idx in db.email_metadata.list_indexes():
    print(f"  {idx['name']}")
