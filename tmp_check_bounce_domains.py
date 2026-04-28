import pymongo

db = pymongo.MongoClient()["email_automation"]
leads = db["leads_enriched"]
patterns_coll = db["email_patterns"]

# Get all known pattern domains
pattern_domains = set(p["domain"] for p in patterns_coll.find({}, {"domain": 1}))
print(f"Pattern domains available: {len(pattern_domains)}")

# Get all bounced leads
bounced = list(leads.find(
    {"email_status": {"$regex": "^bounced$", "$options": "i"}},
    {"company_domain": 1, "email": 1, "first_name": 1}
))
print(f"Total bounced leads: {len(bounced)}")

# Count how many bounced leads have a matching pattern domain
with_pattern = [l for l in bounced if l.get("company_domain", "").strip().lower() in pattern_domains]
print(f"Bounced leads with a matching domain pattern: {len(with_pattern)}")

# Show some
for l in with_pattern[:5]:
    domain = l.get("company_domain", "").strip().lower()
    p = patterns_coll.find_one({"domain": domain})
    print(f"  email={l.get('email')}  domain={domain}  pattern={p.get('pattern')}  conf={p.get('confidence'):.0%}")

# Also check what domains the bounced leads are from
from collections import Counter
bounced_domains = Counter(l.get("company_domain","").strip().lower() for l in bounced)
print("\nTop 10 bounced lead domains:")
for d, c in bounced_domains.most_common(10):
    has_pattern = "✓" if d in pattern_domains else "✗"
    print(f"  {has_pattern} {d}: {c}")
