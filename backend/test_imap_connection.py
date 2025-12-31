"""Test IMAP connection and email fetching directly"""
import os
import imaplib
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
gmail_db = client['torpedo_gmail']

# Get the account
account = gmail_db['imap_accounts'].find_one({"email": "susanta@surveyfieldwork.com"})
if not account:
    print("Account not found!")
    exit(1)

print(f"Testing IMAP connection for: {account['email']}")
print(f"IMAP Server: {account.get('imap_server', 'imap.gmail.com')}")
print(f"IMAP Port: {account.get('imap_port', 993)}")

try:
    # Connect to IMAP
    imap_server = account.get('imap_server', 'imap.gmail.com')
    imap_port = account.get('imap_port', 993)
    password = account.get('password', '')
    
    print(f"\n📧 Connecting to {imap_server}:{imap_port}...")
    imap = imaplib.IMAP4_SSL(imap_server, imap_port)
    
    print(f"📝 Logging in as {account['email']}...")
    imap.login(account['email'], password)
    print("✅ Login successful!")
    
    # List folders
    print("\n📁 Available folders:")
    status, folder_list = imap.list()
    if status == "OK":
        for folder_data in folder_list[:10]:  # Show first 10
            print(f"  - {folder_data.decode('utf-8', errors='ignore')}")
    
    # Select INBOX
    print("\n📬 Selecting INBOX...")
    status, data = imap.select("INBOX")
    if status == "OK":
        print(f"✅ INBOX selected, {data[0].decode()} messages total")
    else:
        print(f"❌ Failed to select INBOX: {status}")
    
    # Search for recent emails
    since_days = 30
    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    print(f"\n🔍 Searching for emails since {since_date}...")
    
    status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
    if status == "OK":
        message_ids = message_numbers[0].split()
        print(f"✅ Found {len(message_ids)} emails in the last {since_days} days")
        
        if len(message_ids) > 0:
            # Try to fetch the first email
            print("\n📧 Fetching first email as test...")
            msg_id = message_ids[0]
            status, msg_data = imap.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status == "OK":
                print(f"✅ Successfully fetched email header:")
                print(msg_data[0][1].decode('utf-8', errors='ignore')[:500])
    else:
        print(f"❌ Search failed: {status}")
    
    # Try Sent folder
    print("\n📤 Looking for Sent folder...")
    sent_folders = ["Sent", "Sent Items", "Sent Mail", "[Gmail]/Sent Mail", "INBOX.Sent"]
    for sent_folder in sent_folders:
        status, _ = imap.select(sent_folder)
        if status == "OK":
            print(f"✅ Found sent folder: {sent_folder}")
            status, message_numbers = imap.search(None, f'(SINCE "{since_date}")')
            if status == "OK":
                message_ids = message_numbers[0].split()
                print(f"   {len(message_ids)} sent emails in the last {since_days} days")
            break
        else:
            print(f"   - '{sent_folder}' not found")
    
    imap.logout()
    print("\n✅ IMAP test completed successfully!")
    
except imaplib.IMAP4.error as e:
    print(f"\n❌ IMAP Error: {e}")
except Exception as e:
    print(f"\n❌ Error: {type(e).__name__}: {e}")
