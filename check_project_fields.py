import pymongo, os
from bson import ObjectId
client = pymongo.MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client["email_automation"]
p = db.projects.find_one({"_id": ObjectId("69a71b19c60c4838cd0d5f59")}, {"vendorName":1,"vendorId":1,"countryCode":1,"entryLink":1})
print("project:", p)
v = db.vendors.find_one({"vendorName": p.get("vendorName","")}, {"vid":1,"vendorName":1})
print("vendor:", v)
