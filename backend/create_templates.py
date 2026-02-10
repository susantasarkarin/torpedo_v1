"""Create email templates in MongoDB"""
from pymongo import MongoClient
from datetime import datetime

client = MongoClient('mongodb://localhost:27017/')
db = client['email_automation']

# Clear existing templates
db.templates.delete_many({})

templates = [
    {
        "name": "Introductory Mail-1",
        "category": "Outreach",
        "subject": "Quick question about {{contact.company}}",
        "body": """<p>Hi {{contact.first_name}},</p>

<p>I noticed your work at {{contact.company}} and was impressed by your approach to {{contact.title}}.</p>

<p>I wanted to reach out because I believe we could help you achieve even better results with our solutions.</p>

<p>Would you be open to a quick 15-minute chat next week?</p>

<p>Best regards,<br>
{{sender.name}}<br>
{{sender.title}}<br>
{{sender.company}}</p>""",
        "created_at": datetime.utcnow()
    },
    {
        "name": "Follow-up Mail",
        "category": "Follow-up",
        "subject": "Following up - {{contact.company}}",
        "body": """<p>Hi {{contact.first_name}},</p>

<p>I wanted to follow up on my previous email about helping {{contact.company}}.</p>

<p>I understand you're busy, but I thought this might be valuable for your team.</p>

<p>If you're interested, I'd love to schedule a brief call. What does your calendar look like?</p>

<p>Thanks,<br>
{{sender.name}}<br>
{{sender.title}}<br>
{{sender.company}}</p>""",
        "created_at": datetime.utcnow()
    }
]

result = db.templates.insert_many(templates)
print(f"✅ Created {len(result.inserted_ids)} templates:")
for idx, template in enumerate(templates):
    print(f"  {idx+1}. {template['name']} - {template['category']}")
    print(f"     ID: {result.inserted_ids[idx]}")

print("\n✅ Templates created successfully!")
