from pymongo import MongoClient
c = MongoClient('mongodb://susanta:StrongPassDogfish!@127.0.0.1:27017/admin')
db = c['cint_research']

# Delete surveys with payout < $1
result = db.cint_surveys.delete_many({'payout': {'$lt': 1.0}})
print(f'Deleted {result.deleted_count} surveys with payout < $1')

# Count remaining
total = db.cint_surveys.count_documents({})
print(f'Remaining surveys: {total}')
