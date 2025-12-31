"""Update IMAP server settings for Google Workspace accounts"""
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
gmail_db = client['torpedo_gmail']

# Update the IMAP server settings
result = gmail_db['imap_accounts'].update_one(
    {'email': 'susanta@surveyfieldwork.com'},
    {'$set': {
        'imap_server': 'imap.gmail.com',
        'smtp_server': 'smtp.gmail.com',
        'imap_port': 993,
        'smtp_port': 587
    }}
)

print(f"Updated {result.modified_count} account(s)")

# Verify the update
account = gmail_db['imap_accounts'].find_one({'email': 'susanta@surveyfieldwork.com'})
if account:
    print(f"\nUpdated settings:")
    print(f"  IMAP Server: {account.get('imap_server')}")
    print(f"  IMAP Port: {account.get('imap_port')}")
    print(f"  SMTP Server: {account.get('smtp_server')}")
    print(f"  SMTP Port: {account.get('smtp_port')}")
