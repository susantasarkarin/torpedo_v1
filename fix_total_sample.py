import pymongo
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["qre_health_survey"]
res = db.studies.update_one({"_id": "6d4428ee"}, {"$set": {"quotas.total_sample": 1710}})
print("modified:", res.modified_count)
v = db.studies.find_one({"_id": "6d4428ee"}, {"quotas.total_sample": 1})
print("new total_sample:", v["quotas"]["total_sample"])
