from pymongo import MongoClient

client = MongoClient('mongodb://susanta:StrongPassDogfish!@127.0.0.1:27017/admin')
db = client['cint_research']
print('cint_surveys count:', db.cint_surveys.count_documents({}))
docs = list(db.cint_surveys.find().limit(3))
if docs:
    print('Sample doc keys:', list(docs[0].keys()))
else:
    print('No docs found')
