from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017/")
db = client["cint_research"]
col = db["cint_surveys"]

print("=== is_active_in_pool status ===")
print(f"is_active_in_pool=True: {col.count_documents({'is_active_in_pool': True})}")
print(f"is_active_in_pool=False: {col.count_documents({'is_active_in_pool': False})}")
print(f"Missing field: {col.count_documents({'is_active_in_pool': {'$exists': False}})}")

# Check what the sample data shows
sample = col.find_one({}, {"survey_id": 1, "is_active": 1, "is_active_in_pool": 1, "is_live": 1, "message_reason": 1})
print(f"\nSample survey fields: {sample}")
