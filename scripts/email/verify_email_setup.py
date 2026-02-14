"""
Verification script to check email campaign setup
"""

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["email_automation"]

print("🔍 Checking Email Campaign Setup\n")
print("=" * 50)

# Check templates
templates_count = db.templates.count_documents({})
print(f"\n📧 Email Templates: {templates_count}")
if templates_count > 0:
    templates = list(db.templates.find({}, {"name": 1, "category": 1, "subject": 1}))
    for t in templates:
        print(f"   ✅ {t['name']} ({t['category']})")
        print(f"      Subject: {t['subject']}")
else:
    print("   ⚠️ No templates found!")

# Check user signature
user = db.users.find_one({"email": {"$exists": True}})
print(f"\n👤 User Profile:")
if user:
    print(f"   ✅ Email: {user.get('email')}")
    print(f"   ✅ Name: {user.get('first_name')} {user.get('last_name')}")
    print(f"   ✅ Title: {user.get('job_title')}")
    print(f"   ✅ Company: {user.get('company_name')}")
    if user.get('email_signature'):
        print(f"   ✅ Email Signature: Configured")
    else:
        print(f"   ⚠️ Email Signature: Not configured")
else:
    print("   ⚠️ No user found!")

# Check leads
leads_count = db.leads_enriched.count_documents({})
print(f"\n📊 AI Database Leads: {leads_count}")
if leads_count > 0:
    sample_leads = list(db.leads_enriched.find({}, {"name": 1, "email": 1, "title": 1, "company_name": 1}).limit(3))
    for lead in sample_leads:
        print(f"   ✅ {lead.get('name')} ({lead.get('email')})")
        print(f"      {lead.get('title')} at {lead.get('company_name')}")
else:
    print("   ⚠️ No leads found!")

print("\n" + "=" * 50)
print("\n✨ Setup Status:")
print(f"   {'✅' if templates_count > 0 else '❌'} Email templates configured")
print(f"   {'✅' if user and user.get('email_signature') else '❌'} User signature configured")
print(f"   {'✅' if leads_count > 0 else '❌'} Leads available")

if templates_count > 0 and user and user.get('email_signature') and leads_count > 0:
    print("\n🎉 All systems ready! You can now:")
    print("   1. Go to AI Database page (http://localhost:5173)")
    print("   2. Select leads using checkboxes")
    print("   3. Click '🔄 Create Workflow' button")
    print("   4. Select a template from dropdown")
    print("   5. Click 'Launch Workflow' to send emails")
else:
    print("\n⚠️ Some components missing. Please run setup scripts.")
