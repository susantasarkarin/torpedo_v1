"""Quick debug: run classify_lead on one real pending lead and print the error."""
import sys
sys.path.insert(0, '/var/www/campaign_platform/backend')

from pymongo import MongoClient

db = MongoClient('mongodb://localhost:27017/')['email_automation']

# Find a lead that should be classifiable
lead_doc = db.leads_raw.find_one({'classification_status': 'pending'})
if not lead_doc:
    # try failed too
    lead_doc = db.leads_raw.find_one({'classification_status': {'$in': ['failed', 'Failed']}})

if not lead_doc:
    print("No pending/failed lead found!")
    sys.exit(1)

print("Lead:", lead_doc.get('name'), '|', lead_doc.get('title'), '|', lead_doc.get('linkedin_url'))
print("attempts:", lead_doc.get('classification_attempts', 0))

from leads.ai_classifier import classify_lead
from leads.models import LeadRaw

try:
    lr = LeadRaw(
        name=lead_doc.get('name') or 'Unknown',
        title=lead_doc.get('title') or '',
        linkedin_url=lead_doc.get('linkedin_url') or '',
        snippet=lead_doc.get('snippet') or '',
        location=lead_doc.get('location') or '',
        company_name=lead_doc.get('company_name') or lead_doc.get('company') or '',
        email=lead_doc.get('email') or '',
    )
    result, log = classify_lead(lr, 'test')
    print("success:", result is not None)
    print("error:", log.error_message)
    if result:
        print("first_name:", result.first_name)
        print("last_name:", result.last_name)
        print("seniority:", result.seniority_level)
        print("department:", result.department)
        print("confidence:", result.confidence_score)
except Exception as e:
    import traceback
    print("EXCEPTION:", e)
    traceback.print_exc()
