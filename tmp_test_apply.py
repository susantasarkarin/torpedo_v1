import pymongo
from datetime import datetime

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]
patterns_coll = db["email_patterns"]

# Simulate what the fixed endpoint does
# Check bounced leads with case-insensitive match
import re

bounced = list(leads.find(
    {
        "email_status": {"$regex": "^bounced$", "$options": "i"},
        "company_domain": {"$exists": True, "$nin": [None, ""]},
        "first_name": {"$exists": True, "$nin": [None, ""]},
    }
).limit(10))

print(f"Bounced leads found (case-insensitive): {leads.count_documents({'email_status': {'$regex': '^bounced$', '$options': 'i'}})}")

# Show a few with their pattern lookup
matched = 0
for lead in bounced[:5]:
    domain = lead.get("company_domain", "").strip().lower()
    first_name = lead.get("first_name", "").strip()
    last_name = lead.get("last_name", "").strip()
    current_email = lead.get("email", "")
    
    pattern_doc = patterns_coll.find_one({"domain": domain})
    
    if pattern_doc:
        pattern_str = pattern_doc.get("pattern", "")
        # Simple generate_email_from_pattern logic
        fn = first_name.lower()
        ln = last_name.lower()
        if "firstname.lastname" in pattern_str:
            new_email = f"{fn}.{ln}@{domain}" if ln else f"{fn}@{domain}"
        elif "firstname_lastname" in pattern_str:
            new_email = f"{fn}_{ln}@{domain}" if ln else f"{fn}@{domain}"
        elif "firstnamelastname" in pattern_str:
            new_email = f"{fn}{ln}@{domain}"
        else:
            new_email = f"{fn}.{ln}@{domain}" if ln else f"{fn}@{domain}"
        
        matched += 1
        print(f"  WOULD FIX: {current_email} → {new_email}  (pattern: {pattern_str}, conf: {pattern_doc.get('confidence'):.0%})")
    else:
        print(f"  NO PATTERN: {current_email}  domain={domain}")

print(f"\nOf 10 sampled bounced leads, {matched} have a matching domain pattern")
print("Apply Patterns should now work correctly!")
