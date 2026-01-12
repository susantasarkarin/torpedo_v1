from pymongo import MongoClient
c = MongoClient('mongodb://susanta:StrongPassDogfish!@127.0.0.1:27017/admin')
db = c['cint_research']
low_payout = list(db.cint_surveys.find({'payout': {'$lt': 1.0}}, {'survey_id': 1, 'payout': 1}).limit(10))
print(f'Surveys with payout < $1: {len(low_payout)}')
for s in low_payout:
    print(f'  ID: {s.get("survey_id")}, payout: ${s.get("payout", 0):.2f}')
total_low = db.cint_surveys.count_documents({'payout': {'$lt': 1.0}})
print(f'Total surveys with payout < $1: {total_low}')
total_all = db.cint_surveys.count_documents({})
print(f'Total surveys: {total_all}')
