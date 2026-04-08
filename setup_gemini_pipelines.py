"""
setup_gemini_pipelines.py
=========================
One-time script: stores the Gemini pipeline key configuration AND account
names in MongoDB so the GeminiPipelineRotator can load them at runtime.

Run once (and again whenever you add a new key):
    python3 /tmp/sgp.py

Pipeline layout
---------------
Pipeline 1  outreach  → keys 1,2,3    (AI email drafting)
Pipeline 2  sfw_bim   → keys 4,5,6    (SFW + BIM enrichment + mail)
Pipeline 3  cogentix  → keys 7,8,9    (Cogentix enrichment + mail)
Pipeline 4  mail      → keys 10,11,12 (general mail / overflow)

Account names
-------------
Edit ACCOUNT_NAMES below to record which Google account owns each key slot.
Leave a slot as "" if a key hasn't been added yet.
"""
from pymongo import MongoClient

PIPELINE_CONFIG = {
    "outreach": [1, 2, 3],
    "sfw_bim":  [4, 5, 6],
    "cogentix": [7, 8, 9],
    "mail":     [10, 11, 12],
}

# ── Update these as you add / rotate keys ──────────────────────────────────
ACCOUNT_NAMES = {
    1:  "susantasarkar82@gmail.com",      # outreach key 1
    2:  "susanta.sarkar.1982@gmail.com",  # outreach key 2
    3:  "susanta.cogentix@gmail.com",     # outreach key 3
    4:  "",                               # sfw_bim key 1  ← add account name
    5:  "",                               # sfw_bim key 2
    6:  "",                               # sfw_bim key 3
    7:  "",                               # cogentix key 1
    8:  "",                               # cogentix key 2 — key not yet in DB
    9:  "",                               # cogentix key 3 — key not yet in DB
    10: "",                               # mail key 1    — key not yet in DB
    11: "",                               # mail key 2    — key not yet in DB
    12: "",                               # mail key 3    — key not yet in DB
}
# ───────────────────────────────────────────────────────────────────────────

c = MongoClient("mongodb://localhost:27017/")
settings_col = c["torpedo_settings"]["app_settings"]
doc = settings_col.find_one()

# Build the $set payload
update_fields = {"gemini_pipeline_config": PIPELINE_CONFIG}
for idx, name in ACCOUNT_NAMES.items():
    if name:  # only write non-empty names (don't overwrite with "")
        update_fields[f"gemini_account_{idx}"] = name

if doc:
    settings_col.update_one({"_id": doc["_id"]}, {"$set": update_fields})
    print("Updated app_settings with pipeline config + account names")
else:
    settings_col.insert_one(update_fields)
    print("Created app_settings with pipeline config + account names")

# ── Verification printout ──────────────────────────────────────────────────
doc = settings_col.find_one()
print(f"\nStored pipeline config: {doc.get('gemini_pipeline_config')}")
print()
print(f"{'Slot':>5}  {'Pipeline':10}  {'Account':35}  {'Key (first 20 chars)'}")
print("-" * 80)
for i in range(1, 13):
    pipeline = next(
        (name for name, indices in PIPELINE_CONFIG.items() if i in indices), "?"
    )
    key     = doc.get(f"gemini_api_key_{i}") or ""
    account = doc.get(f"gemini_account_{i}") or "— add account name —"
    key_str = (key[:20] + "...") if key else "NOT IN DB — add key"
    print(f"  {i:3d}  {pipeline:10}  {account:35}  {key_str}")
