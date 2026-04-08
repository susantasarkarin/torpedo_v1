import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017")
db = client["campaign_platform"]

projects = list(db.projects.find({}, {"surveyNo": 1, "projectName": 1, "countryCode": 1, "entryLink": 1, "_id": 0}))
for p in projects:
    print(p)
