"""
Create admin user with email signature
"""

from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client["email_automation"]

# Check if user exists
existing_user = db.users.find_one({"email": {"$exists": True}})

if existing_user:
    print(f"✅ User already exists: {existing_user.get('email')}")
    # Update with signature
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
        first_name=existing_user.get('first_name', 'Admin'),
        last_name=existing_user.get('last_name', 'User'),
        job_title=existing_user.get('job_title', 'Sales Manager'),
        company_name=existing_user.get('company_name', 'Your Company'),
        email=existing_user.get('email', 'admin@company.com')
    )
    
    db.users.update_one(
        {"_id": existing_user["_id"]},
        {"$set": {"email_signature": signature}}
    )
    print(f"✅ Updated email signature for: {existing_user.get('email')}")
else:
    # Create new admin user
    user_data = {
        "email": "admin@company.com",
        "first_name": "Admin",
        "last_name": "User",
        "job_title": "Sales Manager",
        "company_name": "Your Company",
        "created_at": datetime.utcnow(),
        "role": "admin"
    }
    
    signature = """
    <br><br>
    <div style="font-family: Arial, sans-serif; color: #333; border-top: 2px solid #0066cc; padding-top: 10px; margin-top: 20px;">
        <strong style="color: #0066cc;">Best regards,</strong><br>
        <strong>Admin User</strong><br>
        <span style="color: #666;">Sales Manager</span><br>
        <span style="color: #0066cc; font-weight: bold;">Your Company</span><br>
        <span style="color: #666;">📧 admin@company.com</span>
    </div>
    """
    
    user_data["email_signature"] = signature
    
    result = db.users.insert_one(user_data)
    print(f"✅ Created admin user: admin@company.com")
    print(f"✅ User ID: {result.inserted_id}")

print("\n✨ User setup complete!")
