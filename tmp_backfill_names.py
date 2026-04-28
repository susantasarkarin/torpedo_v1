"""
Backfill first_name, last_name, and company_domain for leads that have
a full name but no first_name/last_name split.
Also tries to extract company domain from title or company_name.
"""
import pymongo
import re
from datetime import datetime

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]
patterns_coll = db["email_patterns"]

def split_name(name):
    """Split 'John Smith, PhD' -> ('John', 'Smith')"""
    if not name:
        return "", ""
    # Remove suffixes after comma
    clean = re.sub(r',.*', '', name).strip()
    # Remove common suffixes
    clean = re.sub(r'\b(PhD|MBA|MD|MSc|BSc|CFA|PMP|Jr|Sr|II|III)\b', '', clean, flags=re.IGNORECASE).strip()
    parts = clean.split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    return first, last

def extract_company_from_title(title):
    """Try to extract company name from title strings like:
    'Sr. Analyst @ Randstad India | ...'
    'Manager at Nielsen'
    'Founding Partner, Quipper Research'
    """
    if not title:
        return None
    # Pattern: @ Company Name |
    m = re.search(r'@\s*([^|@\n]+)', title)
    if m:
        return m.group(1).strip()
    # Pattern: at/@ Company Name
    m = re.search(r'\b(?:at|@)\s+([A-Z][^\|,\n]+)', title)
    if m:
        return m.group(1).strip()
    return None

def company_name_to_domain(company_name):
    """Very rough: 'Randstad India' -> 'randstad.com'"""
    if not company_name:
        return None
    # Remove common suffixes
    clean = re.sub(r'\b(India|Global|Group|Limited|Ltd|Inc|Corp|LLC|Pvt|Private|Solutions|Services|Consulting|Research|Analytics|Insights)\b', '', company_name, flags=re.IGNORECASE).strip()
    # Remove non-alpha except spaces
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', clean).strip()
    # Take first significant word(s)
    words = [w.lower() for w in clean.split() if len(w) > 2]
    if not words:
        return None
    # Check if any word matches a known pattern domain
    for word in words:
        guessed = word + ".com"
        if patterns_coll.find_one({"domain": guessed}):
            return guessed
    return None

# Process all leads with email=null and no first_name
cursor = leads.find({
    "email": None,
    "name": {"$exists": True, "$nin": [None, ""]},
    "first_name": None,
})

name_split_count = 0
domain_from_company = 0
domain_from_title = 0

for lead in cursor:
    name = lead.get("name", "")
    first, last = split_name(name)
    if not first:
        continue

    update = {
        "first_name": first,
        "last_name": last,
    }

    # Try company_name if available
    if not lead.get("company_domain"):
        company_name = lead.get("company_name", "")
        if company_name:
            domain = company_name_to_domain(company_name)
            if domain:
                update["company_domain"] = domain
                domain_from_company += 1
        
        # Try title extraction if no domain yet
        if "company_domain" not in update:
            title = lead.get("title", "")
            extracted = extract_company_from_title(title)
            if extracted:
                domain = company_name_to_domain(extracted)
                if domain:
                    update["company_domain"] = domain
                    domain_from_title += 1

    leads.update_one({"_id": lead["_id"]}, {"$set": update})
    name_split_count += 1

print(f"Split names for: {name_split_count} leads")
print(f"  + domain found via company_name: {domain_from_company}")
print(f"  + domain found via title: {domain_from_title}")

# Final check
after = leads.count_documents({
    "email": None,
    "first_name": {"$nin": [None, ""]},
    "company_domain": {"$nin": [None, ""]}
})
print(f"\nLeads now eligible for Apply Patterns (has first_name + company_domain, no email): {after}")
