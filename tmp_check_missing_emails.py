import pymongo
from collections import Counter

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]
patterns_coll = db["email_patterns"]

total = leads.count_documents({})
print(f"Total leads_enriched: {total}")

# Check all possible "no email" states
no_email_exists = leads.count_documents({"email": {"$exists": False}})
email_is_null = leads.count_documents({"email": None})
email_is_empty = leads.count_documents({"email": ""})
email_has_value = leads.count_documents({"email": {"$exists": True, "$nin": [None, ""]}})

print(f"email field missing: {no_email_exists}")
print(f"email is null: {email_is_null}")
print(f"email is empty string: {email_is_empty}")
print(f"email has a value: {email_has_value}")

# How many have no email at all (any form)
no_email_total = total - email_has_value
print(f"\nLeads with NO email (any form): {no_email_total}")

# Of those with no email, how many have company_domain + first_name?
# Check each case
for label, query in [
    ("email missing", {"email": {"$exists": False}}),
    ("email null", {"email": None}),
    ("email empty", {"email": ""}),
]:
    q = dict(query)
    q["company_domain"] = {"$exists": True, "$nin": [None, ""]}
    q["first_name"] = {"$exists": True, "$nin": [None, ""]}
    c = leads.count_documents(q)
    print(f"  '{label}' + has domain + has first_name: {c}")

# Sample a lead with no email to see its fields
sample = leads.find_one({"email": {"$in": [None, ""]}})
if not sample:
    sample = leads.find_one({"email": {"$exists": False}})
if sample:
    print(f"\nSample no-email lead:")
    print(f"  email: {repr(sample.get('email'))}")
    print(f"  first_name: {sample.get('first_name')}")
    print(f"  last_name: {sample.get('last_name')}")
    print(f"  company_domain: {sample.get('company_domain')}")
    domain = (sample.get("company_domain") or "").strip().lower()
    p = patterns_coll.find_one({"domain": domain}) if domain else None
    print(f"  pattern found: {p.get('pattern') if p else 'None'}")
