import pymongo

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["torpedo"]

campaigns = list(db["outreach_campaigns_v2"].find({}, {
    "campaign_id": 1, "business": 1, "basket": 1, "is_active": 1, "status": 1
}))
for c in campaigns:
    print(f"  id={c.get('campaign_id','?')[:12]} business={c.get('business')} basket={c.get('basket')} is_active={c.get('is_active')} status={c.get('status')}")
