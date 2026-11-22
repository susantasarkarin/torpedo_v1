"""
Read-only audit of the Panel collections in campaign_platform. Prints counts
only (never emails). Run on the server:

    cd backend && venv/bin/python scripts/panel_data_audit.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _count(coll, query=None):
    return coll.count_documents(query or {})


def _group_counts(coll, field, match=None):
    pipeline = ([{"$match": match}] if match else []) + [{"$group": {"_id": f"${field}", "n": {"$sum": 1}}}]
    return {str(r["_id"]): r["n"] for r in coll.aggregate(pipeline, allowDiskUse=True)}


def _print_section(title, rows):
    print(f"\n== {title} ==")
    for label, value in rows:
        print(f"  {label}: {value}")


def run(db):
    now = datetime.utcnow()
    p, rw, ss = db["panelists"], db["panel_rewards"], db["panel_sessions"]
    inv, sup = db["panel_invitation_log"], db["panel_email_suppression"]

    no_email = {"$or": [{"email": {"$exists": False}}, {"email": None}, {"email": ""}]}
    dup_groups = list(p.aggregate([
        {"$match": {"email": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": {"$toLower": "$email"}, "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$group": {"_id": None, "groups": {"$sum": 1}, "extra": {"$sum": {"$subtract": ["$n", 1]}}}},
    ], allowDiskUse=True))
    dups = dup_groups[0] if dup_groups else {"groups": 0, "extra": 0}
    has_pw = {"password_hash": {"$exists": True, "$nin": [None, ""]}}
    _print_section("panelists", [
        ("total", _count(p)),
        ("duplicate emails (distinct lower(email) with >1 record)", dups["groups"]),
        ("surplus records from duplicates", dups["extra"]),
        ("missing email", _count(p, no_email)),
        ("member accounts (password_hash)", _count(p, has_pw)),
        ("invite-only (no password_hash)", _count(p, {"$nor": [has_pw]})),
        ("double_opt_in_completed = true", _count(p, {"double_opt_in_completed": True})),
        ("double_opt_in_completed not true", _count(p, {"double_opt_in_completed": {"$ne": True}})),
    ])

    by_status = _group_counts(rw, "status")
    members = list(rw.aggregate([{"$group": {"_id": "$panelist_id"}}, {"$count": "n"}], allowDiskUse=True))
    _print_section("panel_rewards", [("total", _count(rw))]
                   + [(f"status={k}", v) for k, v in sorted(by_status.items())]
                   + [("members with rewards", members[0]["n"] if members else 0)])

    _print_section("panel_sessions", [
        ("stored", _count(ss)),
        ("expired but still stored", _count(ss, {"expires_at": {"$lt": now}})),
    ])

    since = now - timedelta(days=30)
    by_inv = _group_counts(inv, "status", {"sent_at": {"$gte": since}})
    _print_section("panel_invitation_log (last 30 days)",
                   [(f"status={k}", v) for k, v in sorted(by_inv.items())] or [("rows", 0)])

    _print_section("panel_email_suppression", [("total", _count(sup))])


def main():
    from database import get_client
    run(get_client()["campaign_platform"])


if __name__ == "__main__":
    main()
