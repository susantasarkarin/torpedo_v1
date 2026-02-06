from pymongo import MongoClient
from bson import ObjectId
import json
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["traffic_flow_db"]

class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, ObjectId)):
            return str(obj)
        return super().default(obj)

doc1 = db.url_parameters.find_one({"_id": ObjectId("698585c106f61e8d32dd34ab")})
print("=" * 60)
print("RESPONDENT 1: 698585c106f61e8d32dd34ab")
print(json.dumps(doc1, indent=2, cls=DateEncoder))

doc2 = db.url_parameters.find_one({"_id": ObjectId("698585b206f61e8d32dd34a7")})
print("=" * 60)
print("RESPONDENT 2: 698585b206f61e8d32dd34a7")
print(json.dumps(doc2, indent=2, cls=DateEncoder))
