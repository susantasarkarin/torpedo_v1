"""
Migration: backfill vendorId and entryLink for projects that have vendorName but
missing vendorId / entryLink fields.
Safe to run multiple times (idempotent).
"""
import os
import pymongo
from bson import ObjectId
from datetime import datetime

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BASE_URL = "https://torpedo.cogentixresearch.com"

client = pymongo.MongoClient(MONGO_URI)
db = client["email_automation"]

projects_col = db["projects"]
vendors_col  = db["vendors"]

# Build vendorName -> vid lookup map
vendor_map = {}
for v in vendors_col.find({}, {"vendorName": 1, "vid": 1}):
    name = (v.get("vendorName") or "").strip()
    vid  = (v.get("vid") or "").strip()
    if name and vid:
        vendor_map[name] = vid

print(f"Loaded {len(vendor_map)} vendors: {vendor_map}")

# Find projects missing vendorId OR entryLink
query = {
    "$or": [
        {"vendorId": {"$in": [None, ""]}},
        {"vendorId": {"$exists": False}},
        {"entryLink": {"$exists": False}},
        {"entryLink": {"$in": [None, ""]}},
    ]
}

projects = list(projects_col.find(query, {
    "_id": 1, "vendorName": 1, "vendorId": 1, "countryCode": 1, "entryLink": 1
}))
print(f"\nFound {len(projects)} projects to check\n")

updated = 0
skipped = 0

for p in projects:
    pid       = str(p["_id"])
    vendor_nm = (p.get("vendorName") or "").strip()
    vendor_id = (p.get("vendorId")   or "").strip()
    cc        = (p.get("countryCode") or "").strip()

    # Resolve vendorId from vendor map if missing
    resolved_vid = vendor_id or vendor_map.get(vendor_nm, "")

    vid_param = resolved_vid or "{VID}"
    cc_param  = cc           or "{CC}"

    new_entry_link = (
        f"{BASE_URL}/takesurvey?api=false"
        f"&vid={vid_param}&cc={cc_param}&pid={pid}&rid={{RID}}"
    )

    set_fields = {
        "entryLink": new_entry_link,
        "updatedAt": datetime.utcnow(),
    }
    if resolved_vid and not vendor_id:
        set_fields["vendorId"] = resolved_vid

    projects_col.update_one({"_id": p["_id"]}, {"$set": set_fields})
    print(f"  [{pid}] {vendor_nm!r:20s} vid={resolved_vid!r:6s} cc={cc!r:4s} → {new_entry_link}")
    updated += 1

print(f"\nDone. Updated {updated} projects, skipped {skipped}.")
