"""Check email_metadata schema"""
import sys
import os
sys.path.insert(0, "/var/www/campaign_platform/backend")
os.chdir("/var/www/campaign_platform/backend")

from database import get_database
db = get_database("torpedo_gmail")

doc = db.email_metadata.find_one()
if doc:
    print("email_metadata schema:")
    for k, v in doc.items():
        val_type = type(v).__name__
        val_preview = str(v)[:60] if v else "None"
        print(f"  {k}: ({val_type}) {val_preview}")
