"""
Setup email templates and user signature in MongoDB
Run this once to configure the email system
"""

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["email_automation"]

# Email templates
templates = [
    {
        "name": "Introductory Mail-1",
        "category": "Outreach",
        "subject": "Quick question about {{contact.company}}",
        "body": """
        <p>Hi {{contact.first_name}},</p>
        
        <p>I noticed you're the {{contact.title}} at {{contact.company}}, and I thought I'd reach out.</p>
        
        <p>We've been helping companies like yours streamline their operations and boost productivity. 
        I'd love to share some insights that might be relevant to your team.</p>
        
        <p>Would you be open to a quick 15-minute call next week?</p>
        
        <p>Best regards,<br>
        {{sender.name}}<br>
        {{sender.title}}<br>
        {{sender.company}}</p>
        """
    },
    {
        "name": "Follow-up Mail",
        "category": "Follow-up",
        "subject": "Following up on my previous email",
        "body": """
        <p>Hi {{contact.first_name}},</p>
        
        <p>I wanted to follow up on my previous email about {{contact.company}}.</p>
        
        <p>I know you're busy, but I genuinely believe we could add value to your operations. 
        Even a brief conversation could be helpful.</p>
        
        <p>Let me know if you'd like to connect!</p>
        
        <p>Best,<br>
        {{sender.name}}<br>
        {{sender.title}}<br>
        {{sender.company}}</p>
        """
    }
]

# Insert templates
print("📧 Setting up email templates...")
db.templates.delete_many({})  # Clear existing
result = db.templates.insert_many(templates)
print(f"✅ Created {len(result.inserted_ids)} templates")

# Add email signature to user profile
print("\n✍️ Setting up user email signature...")
user = db.users.find_one({"email": {"$exists": True}})

if user:
    signature = """
    <br><br>
    <div style="font-family: Arial, sans-serif; color: #333; border-top: 2px solid #0066cc; padding-top: 10px; margin-top: 20px;">
        <strong style="color: #0066cc;">Best regards,</strong><br>
        <strong>{first_name} {last_name}</strong><br>
        <span style="color: #666;">{job_title}</span><br>
        <span style="color: #0066cc; font-weight: bold;">{company_name}</span><br>
        <span style="color: #666;">📧 {email}</span>
    </div>
    """.format(
        first_name=user.get('first_name', 'Admin'),
        last_name=user.get('last_name', 'User'),
        job_title=user.get('job_title', 'Sales Manager'),
        company_name=user.get('company_name', 'Your Company'),
        email=user.get('email', 'admin@company.com')
    )
    
    db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"email_signature": signature}}
    )
    print(f"✅ Added email signature to user: {user.get('email')}")
else:
    print("⚠️ No user found in database. Please create a user first.")

print("\n✨ Email system setup complete!")
print("\n📋 Summary:")
print(f"   - {len(templates)} email templates")
print(f"   - User signature configured")
print("\nYou can now use the Workflow Builder to send emails!")
