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

# Find projects where entryLink has wrong pid (_id instead of surveyNo),
# or vendorId is missing, or entryLink is missing.
query = {
    "$or": [
        {"vendorId": {"$in": [None, ""]}},
        {"vendorId": {"$exists": False}},
        {"entryLink": {"$exists": False}},
        {"entryLink": {"$in": [None, ""]}},
        # Also catch entries where pid in entryLink is the 24-char hex _id (not 5-digit surveyNo)
        {"entryLink": {"$regex": r"pid=[0-9a-f]{24}"}},
    ]
}

projects = list(projects_col.find(query, {
    "_id": 1, "vendorName": 1, "vendorId": 1, "countryCode": 1, "entryLink": 1, "surveyNo": 1
}))
print(f"\nFound {len(projects)} projects to check\n")

updated = 0
skipped = 0

for p in projects:
    pid       = str(p["_id"])
    vendor_nm = (p.get("vendorName") or "").strip()
    vendor_id = (p.get("vendorId")   or "").strip()
    cc        = (p.get("countryCode") or "").strip()
    survey_no = (p.get("surveyNo")   or "").strip()

    # Resolve vendorId from vendor map if missing
    resolved_vid = vendor_id or vendor_map.get(vendor_nm, "")

    vid_param = resolved_vid or "{VID}"
    cc_param  = cc           or "{CC}"
    # pid must be surveyNo — the 5-digit number that /takesurvey resolves by
    pid_param = survey_no    or "{PID}"

    new_entry_link = (
        f"{BASE_URL}/takesurvey?api=false"
        f"&vid={vid_param}&cc={cc_param}&pid={pid_param}&rid={{RID}}"
    )

    set_fields = {
        "entryLink": new_entry_link,
        "updatedAt": datetime.utcnow(),
    }
    if resolved_vid and not vendor_id:
        set_fields["vendorId"] = resolved_vid

    projects_col.update_one({"_id": p["_id"]}, {"$set": set_fields})
    print(f"  [{pid}] {vendor_nm!r:20s} vid={resolved_vid!r:6s} cc={cc!r:4s} surveyNo={survey_no!r} → {new_entry_link}")
    updated += 1

print(f"\nDone. Updated {updated} projects, skipped {skipped}.")
