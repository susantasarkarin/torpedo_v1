"""
Migration: Normalize entryLink field in all project documents.

Old format (any variant):
  .../takesurvey?...&cc=<hardcoded_or_placeholder>&...&rid={RID}  (no panel param)

New format (fully dynamic):
  .../takesurvey?api=false&vid=<VID>&cc=[%CC%]&panel=[%PANEL%]&pid=<PID>&rid=[%RID%]

Rules applied:
  1. cc param → always replaced with [%CC%]
  2. panel param → added (or updated) to [%PANEL%]
  3. rid param → normalised to [%RID%] regardless of old token used
  4. Non-takesurvey entryLinks are left untouched.
"""

import os
import re
import sys
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    print("❌  MONGO_URI not set in .env – aborting")
    sys.exit(1)

DRY_RUN = "--apply" not in sys.argv   # safety: default is dry-run

# Dynamic placeholder tokens that should replace any per-session value
TARGET_CC    = "[%CC%]"
TARGET_PANEL = "[%PANEL%]"
TARGET_RID   = "[%RID%]"


def normalize_entry_link(url: str) -> str | None:
    """
    Return the normalised URL string, or None if no change is needed.
    """
    if not url or "takesurvey" not in url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    params = parse_qs(parsed.query, keep_blank_values=True)

    changed = False

    # 1. cc → [%CC%]
    if params.get("cc", [TARGET_CC])[0] != TARGET_CC:
        params["cc"] = [TARGET_CC]
        changed = True
    elif "cc" not in params:
        params["cc"] = [TARGET_CC]
        changed = True

    # 2. panel → [%PANEL%]
    if params.get("panel", [TARGET_PANEL])[0] != TARGET_PANEL:
        params["panel"] = [TARGET_PANEL]
        changed = True
    elif "panel" not in params:
        params["panel"] = [TARGET_PANEL]
        changed = True

    # 3. rid → [%RID%]
    if params.get("rid", [TARGET_RID])[0] != TARGET_RID:
        params["rid"] = [TARGET_RID]
        changed = True
    elif "rid" not in params:
        params["rid"] = [TARGET_RID]
        changed = True

    if not changed:
        return None

    # Rebuild in a stable order: api, vid, cc, panel, pid, rid, then any others
    key_order = ["api", "vid", "cc", "panel", "pid", "rid"]
    ordered = {}
    for k in key_order:
        if k in params:
            ordered[k] = params[k]
    for k, v in params.items():
        if k not in ordered:
            ordered[k] = v

    new_query = urlencode(ordered, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


def main():
    client = MongoClient(MONGO_URI)
    col = client["email_automation"]["projects"]

    total = col.count_documents({})
    print(f"📦  Total projects in collection: {total}")
    print(f"🔧  Mode: {'DRY RUN (pass --apply to write)' if DRY_RUN else 'LIVE WRITE'}\n")

    updated = 0
    skipped = 0
    no_link = 0
    errors  = 0

    cursor = col.find({}, {"_id": 1, "entryLink": 1, "surveyNo": 1, "vendorId": 1})

    for doc in cursor:
        raw_link = doc.get("entryLink", "")
        if not raw_link:
            no_link += 1
            continue

        new_link = normalize_entry_link(raw_link)

        if new_link is None:
            skipped += 1
            continue

        project_id = doc["_id"]
        survey_no  = doc.get("surveyNo", "?")
        print(f"  [{survey_no}] {raw_link}")
        print(f"       → {new_link}")

        if not DRY_RUN:
            try:
                col.update_one({"_id": project_id}, {"$set": {"entryLink": new_link}})
                updated += 1
            except Exception as e:
                print(f"       ❌ update failed: {e}")
                errors += 1
        else:
            updated += 1   # count as would-update in dry run

    print(f"\n{'=' * 60}")
    print(f"  Would update : {updated}" if DRY_RUN else f"  Updated      : {updated}")
    print(f"  Already clean: {skipped}")
    print(f"  No entryLink : {no_link}")
    if errors:
        print(f"  Errors       : {errors}")
    if DRY_RUN and updated > 0:
        print("\n  ⚠  DRY RUN – no changes written. Re-run with --apply to commit.")
    elif not DRY_RUN:
        print("\n  ✅  Migration complete.")

    client.close()


if __name__ == "__main__":
    main()
