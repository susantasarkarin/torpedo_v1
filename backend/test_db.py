import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI')
print('MONGO_URI=', MONGO_URI)
if not MONGO_URI:
    print('No MONGO_URI found in .env')
    raise SystemExit(1)

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    print('Attempting ping...')
    client.admin.command('ping')
    print('Mongo ping successful')
    
    # Check finance_db customers
    db = client['finance_db']
    count = db.customers.count_documents({})
    print(f'Customers in finance_db: {count}')
    for c in db.customers.find().limit(5):
        print(f"  - {c.get('name', 'NO NAME')}")
except Exception as e:
    print('Mongo connection failed:', repr(e))
    raise SystemExit(2)
