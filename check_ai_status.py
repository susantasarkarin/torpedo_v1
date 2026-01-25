from pymongo import MongoClient
db = MongoClient('mongodb://localhost:27017').torpedo_gmail

total = db.email_metadata.count_documents({})
with_ai = db.email_metadata.count_documents({'ai_category': {'$exists': True}})
without_ai = db.email_metadata.count_documents({'ai_category': {'$exists': False}})

print(f'Total emails: {total}')
print(f'With ai_category: {with_ai}')
print(f'Without ai_category: {without_ai}')
print(f'Sum: {with_ai + without_ai}')

# Check empty ai_category
empty_ai = db.email_metadata.count_documents({'ai_category': ''})
none_ai = db.email_metadata.count_documents({'ai_category': None})
print(f'Empty string ai_category: {empty_ai}')
print(f'None ai_category: {none_ai}')

# Check a few samples
print()
print('Sample ai_category values:')
for doc in db.email_metadata.find({}, {'ai_category': 1, 'subject': 1}).limit(5):
    subj = doc.get('subject', 'NO SUBJECT')
    cat = doc.get('ai_category', 'MISSING')
    print(f"  {cat} - {subj[:40] if subj else 'No subject'}")
