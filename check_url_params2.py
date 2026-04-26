from pymongo import MongoClient
from datetime import datetime, timedelta
c = MongoClient()
db = c.traffic_flow_db
t = db.url_parameters.count_documents({})
s = datetime.utcnow() - timedelta(days=7)
r = db.url_parameters.count_documents({"createdAt": {"$gte": s}})
sa = db.url_parameters.find_one({}, {"createdAt": 1})
cr = sa.get("createdAt") if sa else None
print(f"Total: {t}")
print(f"Last 7d (datetime gte): {r}")
print(f"Sample createdAt: {cr!r} type: {type(cr).__name__}")
