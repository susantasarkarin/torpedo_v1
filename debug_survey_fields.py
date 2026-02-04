#!/usr/bin/env python3
from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017')
db = client['cint_research']
survey = db.cint_surveys.find_one({"is_active_in_pool": True})
if survey:
    print("Sample survey fields:")
    for key in sorted(survey.keys()):
        val = survey[key]
        val_str = str(val)
        if len(val_str) > 50:
            val_str = val_str[:50] + "..."
        print(f"  {key}: {val_str}")
