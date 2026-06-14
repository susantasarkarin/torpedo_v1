"""
Reset / create an admin LOGIN account (username + hashed password).

The login endpoint (backend/routers/auth_handler.py) authenticates on a
`username` field and a bcrypt/PBKDF2 `password` hash. This script lists the
existing accounts and lets you set a known password using the project's own
hashing helper, so the credentials will pass verify_password().

Run this ON the machine that hosts Mongo (e.g. the prod VM), where the DB is
reachable at mongodb://localhost:27017/.

Examples:
    # 1) See what login accounts already exist
    python scripts/admin/reset_admin_login.py --list

    # 2) Set/reset a password for an existing or new username
    python scripts/admin/reset_admin_login.py --username admin --password 'ChangeMe123'
"""

import argparse
import os
import sys
from datetime import datetime

from pymongo import MongoClient

# Make backend/auth.py importable regardless of where this is run from.
_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

from auth import hash_password  # noqa: E402

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset/create an admin login account")
    parser.add_argument("--list", action="store_true", help="List existing accounts and exit")
    parser.add_argument("--username", help="Username to set/reset (login uses this field)")
    parser.add_argument("--password", help="New plaintext password (will be hashed)")
    parser.add_argument("--role", default="admin", help="Role to assign (default: admin)")
    args = parser.parse_args()

    db = MongoClient(MONGO_URI)["email_automation"]
    users = db["users"]

    if args.list or not (args.username and args.password):
        print(f"Accounts in email_automation.users  (uri={MONGO_URI})\n")
        found = False
        for u in users.find({}):
            found = True
            uname = u.get("username")
            pw = u.get("password", "")
            kind = "bcrypt" if pw.startswith("$2") else "pbkdf2" if pw.startswith("pbkdf2:") else ("MISSING" if not pw else "plaintext")
            print(f"  username={uname!r:30}  email={u.get('email')!r:30}  role={u.get('role')!r:10}  password={kind}")
        if not found:
            print("  (no users found)")
        if args.list:
            return 0
        print("\nProvide --username and --password to set credentials.")
        return 1

    hashed = hash_password(args.password)
    result = users.update_one(
        {"username": args.username},
        {
            "$set": {
                "username": args.username,
                "password": hashed,
                "role": args.role,
                "password_updated_at": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    action = "Created" if result.upserted_id else "Updated"
    print(f"OK: {action} login account username={args.username!r} role={args.role!r}.")
    print("You can now log in with that username and the password you supplied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
