#!/usr/bin/env python3
"""Fix closed survey 73255503 - mark as inactive"""
from pymongo import MongoClient

c = MongoClient()

# Check current state
s = c.cint_research.cint_surveys.find_one({"survey_id": 73255503})
if s:
    print(f"Survey 73255503 current is_active: {s.get('is_active')}")
    
    # Mark as inactive
    result = c.cint_research.cint_surveys.update_one(
        {"survey_id": 73255503},
        {"$set": {"is_active": False, "survey_status_code": "Closed"}}
    )
    print(f"Updated: modified_count={result.modified_count}")
else:
    print("Survey 73255503 not found")

# Also clear any cached entry link
result2 = c.cint_research.cint_entry_links.delete_one({"survey_id": 73255503})
print(f"Deleted entry link cache: deleted_count={result2.deleted_count}")
