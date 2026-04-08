"""
Migration: Set countryCode=IN for all projects missing it, regenerate entry links.
All existing traffic uses cc=IN, so IN is the correct default.
"""
import pymongo

BASE_URL = "https://torpedo.cogentixresearch.com"

def generate_entry_link(vid, cc, survey_no):
    vid_part = vid if vid else "{VID}"
    cc_part = cc if cc else "{CC}"
    pid_part = survey_no if survey_no else "{PID}"
    return f"{BASE_URL}/takesurvey?api=false&vid={vid_part}&cc={cc_part}&pid={pid_part}&rid={{RID}}"

client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["email_automation"]

projects = list(db.projects.find({}))
print(f"Total projects: {len(projects)}")

updated = 0
for p in projects:
    # Only update if countryCode is missing or empty
    if not p.get("countryCode"):
        vid = p.get("vendorId", "")
        survey_no = p.get("surveyNo", "")
        new_cc = "IN"
        new_entry_link = generate_entry_link(vid, new_cc, survey_no)

        db.projects.update_one(
            {"_id": p["_id"]},
            {"$set": {"countryCode": new_cc, "entryLink": new_entry_link}}
        )
        print(f"  Updated surveyNo={survey_no}: countryCode=IN, entryLink={new_entry_link}")
        updated += 1
    else:
        print(f"  Skipped surveyNo={p.get('surveyNo')}: already has countryCode={p['countryCode']}")

print(f"\nDone. Updated {updated} projects.")

# Verify
print("\nVerification:")
for p in db.projects.find({}, {"surveyNo": 1, "countryCode": 1, "entryLink": 1, "_id": 0}):
    print(f"  surveyNo={p.get('surveyNo')}  cc={p.get('countryCode')}  link={p.get('entryLink')}")
