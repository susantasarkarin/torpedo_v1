"""
Seed `roles` onto every user so RBAC_ENABLED=true is safe to switch on.

WHY THIS EXISTS
---------------
Enforcement is off today (rbac/flags.py). The reason it cannot simply be turned
on is that `app/security.py::_user_roles` falls back to `["user"]` for anyone
with no `roles` array — which happens to pass the coarse read/write gates — but
`rbac/decorators.py` resolves real permissions and refuses a user whose roles
grant nothing. Flipping the flag without seeding therefore locks people out of
every decorator-gated route while looking fine on the coarse ones.

This script gives every user an explicit `roles` list derived from the legacy
single `role` field, so both layers agree before the switch is thrown.

MAPPING
-------
The legacy field is a single string; `AVAILABLE_ROLES` in main.py has always
recognised admin / manager / user / viewer, and rbac/simple.py defines what
each may do. Anything unrecognised becomes "user" (read+write, no approve) —
never admin, because guessing upward is how an audit finding is born.

USAGE
-----
    python -m scripts.seed_rbac_roles --dry-run     # report only, no writes
    python -m scripts.seed_rbac_roles               # apply
    python -m scripts.seed_rbac_roles --force-admin alice,bob

Run from backend/ with the usual env (MONGO_URI). Idempotent: a user who
already has a non-empty `roles` array is left alone unless --overwrite.
"""

import argparse
import logging
import sys

from database import get_database
from rbac.simple import SIMPLE_ROLES

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_rbac_roles")

# Legacy single-role string -> canonical roles array.
_LEGACY_MAP = {
    "admin": ["admin"],
    "administrator": ["admin"],
    "superadmin": ["admin"],
    "manager": ["manager"],
    "user": ["user"],
    "member": ["user"],
    "staff": ["user"],
    "viewer": ["viewer"],
    "readonly": ["viewer"],
    "read-only": ["viewer"],
}
_DEFAULT_ROLES = ["user"]


def resolve_roles(user: dict) -> list:
    existing = user.get("roles")
    if isinstance(existing, list) and existing:
        return [r for r in existing if r in SIMPLE_ROLES] or _DEFAULT_ROLES
    legacy = (user.get("role") or "").strip().lower()
    return _LEGACY_MAP.get(legacy, _DEFAULT_ROLES)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change; write nothing")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-derive roles even for users that already have them")
    ap.add_argument("--force-admin", default="",
                    help="comma-separated usernames to force to ['admin']")
    args = ap.parse_args(argv)

    force_admin = {u.strip() for u in args.force_admin.split(",") if u.strip()}
    users = get_database("email_automation")["users"]

    total = changed = skipped = 0
    summary: dict = {}

    for user in users.find({}, {"username": 1, "role": 1, "roles": 1}):
        total += 1
        username = user.get("username")
        if not username:
            continue

        if username in force_admin:
            roles = ["admin"]
        else:
            roles = resolve_roles(user)

        already = user.get("roles")
        if already == roles and not args.overwrite:
            skipped += 1
            continue
        if isinstance(already, list) and already and not args.overwrite \
                and username not in force_admin:
            skipped += 1
            continue

        summary[username] = {"from": user.get("role"), "to": roles}
        changed += 1
        if not args.dry_run:
            users.update_one({"_id": user["_id"]}, {"$set": {"roles": roles}})

    for username, move in sorted(summary.items()):
        logger.info("  %-24s role=%-10s -> roles=%s",
                    username, move["from"], move["to"])

    verb = "would update" if args.dry_run else "updated"
    logger.info("%d users scanned; %s %d; %d already seeded",
                total, verb, changed, skipped)

    admins = users.count_documents({"roles": "admin"}) if not args.dry_run else \
        sum(1 for m in summary.values() if "admin" in m["to"])
    if admins == 0:
        logger.error(
            "NO USER HAS THE admin ROLE. Do not set RBAC_ENABLED=true — nobody "
            "would be able to administer the system. Re-run with --force-admin "
            "<username>."
        )
        return 1

    if args.dry_run:
        logger.info("dry run: nothing written")
    else:
        logger.info("Seeding complete. RBAC_ENABLED=true is now safe to set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
