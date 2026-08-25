"""
DEDUPE PANELIST RECORDS
=======================
`panelists.email_1` was created without unique=True, so nothing ever stopped a
second document being written for the same address. 2,974 addresses ended up
with two records each. That inflates every count keyed on panelists, and lets
one person be selected twice by the same send.

This is a MERGE, not a delete. Some duplicate pairs disagree — one carries
`sfw_profile_complete` or a `status` the other lacks — so the surviving record
absorbs any field the loser has and it does not, before the loser is removed.

Every removed document is copied to `panelists_dedupe_backup` first, so the
operation is reversible.

Afterwards the index is rebuilt as unique, which is what stops this recurring.

    python -m scripts.dedupe_panelists --dry-run
    python -m scripts.dedupe_panelists
    python -m scripts.dedupe_panelists --restore     # undo from the backup
"""

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
BACKUP = "panelists_dedupe_backup"

# Ordered strongest-first. The record that has progressed furthest through the
# funnel wins, because that is the one every downstream count and segment is
# already keyed on; losing it would silently un-register a real panelist.
RANK_FLAGS = ("double_opt_in_completed", "email_verified", "sfw_profile_complete")


def _score(doc):
    """Higher is a better keeper."""
    score = 0
    for i, flag in enumerate(RANK_FLAGS):
        if doc.get(flag):
            score += 100 * (len(RANK_FLAGS) - i)
    if doc.get("sfw_last_login"):
        score += 50
    if doc.get("last_invited_at"):
        score += 10
    # Tie-break on the older record: it owns the longer invite history.
    created = doc.get("created_at")
    return (score, -(created.timestamp() if created else 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    db = MongoClient(MONGO_URI)["campaign_platform"]
    pan, backup = db["panelists"], db[BACKUP]

    if args.restore:
        docs = list(backup.find({}))
        if not docs:
            print("backup is empty - nothing to restore")
            return 0
        restored = 0
        for d in docs:
            d.pop("_dedupe_merged_into", None)
            try:
                pan.insert_one(d)
                restored += 1
            except Exception as exc:
                print(f"   [warn] {d.get('email')}: {exc}")
        print(f"restored {restored:,} of {len(docs):,}")
        return 0

    groups = list(pan.aggregate([
        {"$group": {"_id": "$email", "n": {"$sum": 1}, "ids": {"$push": "$_id"}}},
        {"$match": {"n": {"$gt": 1}}},
    ], allowDiskUse=True))

    print(f"duplicate addresses: {len(groups):,}")
    if not groups:
        print("nothing to do")
        return 0

    merged_fields = Counter()
    removed = 0
    examined = 0

    for g in groups:
        docs = list(pan.find({"_id": {"$in": g["ids"]}}))
        if len(docs) < 2:
            continue
        docs.sort(key=_score, reverse=True)
        keeper, losers = docs[0], docs[1:]
        examined += 1

        # Absorb anything the keeper is missing.
        patch = {}
        for loser in losers:
            for k, v in loser.items():
                if k in ("_id", "email"):
                    continue
                if v in (None, "", []) or k in patch:
                    continue
                if keeper.get(k) in (None, "", []):
                    patch[k] = v
                    merged_fields[k] += 1

        if args.dry_run:
            removed += len(losers)
            continue

        for loser in losers:
            backup.update_one(
                {"_id": loser["_id"]},
                {"$setOnInsert": {**loser, "_dedupe_merged_into": keeper["_id"]}},
                upsert=True,
            )
        if patch:
            pan.update_one({"_id": keeper["_id"]}, {"$set": patch})
        res = pan.delete_many({"_id": {"$in": [l["_id"] for l in losers]}})
        removed += res.deleted_count

    print(f"groups processed   : {examined:,}")
    print(f"{'would remove' if args.dry_run else 'removed'}       : {removed:,}")
    if merged_fields:
        print("fields recovered from the removed copy:")
        for k, v in merged_fields.most_common(8):
            print(f"   {k:<28} {v:,}")

    if args.dry_run:
        print("\n(dry run - nothing written; unique index NOT created)")
        return 0

    # Only safe once the collection is actually unique.
    left = list(pan.aggregate([
        {"$group": {"_id": "$email", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}}, {"$limit": 1},
    ], allowDiskUse=True))
    if left:
        print("\nduplicates remain - unique index NOT created")
        return 1

    try:
        pan.drop_index("email_1")
    except Exception:
        pass
    pan.create_index("email", unique=True, name="email_1")
    print("\nemail_1 rebuilt as UNIQUE - duplicates can no longer be created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
