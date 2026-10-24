"""Read-only MongoDB inventory for the CRM audit (Phase 1.2).

Light on a loaded VM: estimated counts, a 300-doc random sample per collection
for field fill rates, _id/date min-max via indexed sorts only. Emails and phones
in samples are masked. Writes nothing to Mongo.

Usage: python mongo_inventory.py > inventory.json   (reads MONGO_URI from env)
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

from bson import ObjectId
from pymongo import MongoClient

SAMPLE = 300
SKIP_DBS = {"admin", "config", "local"}
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)")
PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,}\d")
DATE_FIELDS = ("created_at", "createdAt", "date", "received_at", "sent_at", "timestamp", "updated_at")


def mask(v):
    if isinstance(v, str):
        v = EMAIL_RE.sub(r"\1***@\2", v)
        v = PHONE_RE.sub("<phone>", v)
        return v[:120]
    if isinstance(v, dict):
        return {k: mask(x) for k, x in list(v.items())[:25]}
    if isinstance(v, list):
        return [mask(x) for x in v[:3]]
    if isinstance(v, (ObjectId, datetime)):
        return str(v)
    return v


def flatten(doc, prefix="", depth=0):
    for k, v in doc.items():
        key = f"{prefix}{k}"
        yield key, v
        if isinstance(v, dict) and depth < 1:
            yield from flatten(v, key + ".", depth + 1)


def ts(v):
    if isinstance(v, ObjectId):
        return v.generation_time.isoformat()[:10]
    if isinstance(v, datetime):
        return v.isoformat()[:10]
    if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v[:10]
    return None


def main():
    client = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=10000)
    out = {}
    for dbname in sorted(client.list_database_names()):
        if dbname in SKIP_DBS:
            continue
        db = client[dbname]
        out[dbname] = {}
        for cname in sorted(db.list_collection_names()):
            if cname.startswith("system."):
                continue
            c = db[cname]
            info = {"count": c.estimated_document_count()}
            if info["count"]:
                docs = list(c.aggregate([{"$sample": {"size": SAMPLE}}], allowDiskUse=False))
                fill = Counter()
                for d in docs:
                    for k, v in flatten(d):
                        if v not in (None, "", [], {}):
                            fill[k] += 1
                n = len(docs)
                info["fields"] = {k: round(fill[k] / n, 2) for k in sorted(fill)}
                info["sample"] = mask(docs[0])
                first = c.find_one(sort=[("_id", 1)], projection={"_id": 1})
                last = c.find_one(sort=[("_id", -1)], projection={"_id": 1})
                info["id_range"] = [ts(first["_id"]), ts(last["_id"])]
                indexed = {k for ix in c.index_information().values() for k, _ in ix["key"]}
                for f in DATE_FIELDS:
                    if f in indexed:
                        lo = c.find_one({f: {"$ne": None}}, sort=[(f, 1)], projection={f: 1})
                        hi = c.find_one({f: {"$ne": None}}, sort=[(f, -1)], projection={f: 1})
                        if lo and hi:
                            info["date_range"] = [f, ts(lo.get(f)), ts(hi.get(f))]
                        break
                else:
                    vals = [ts(d.get(f)) for d in docs for f in DATE_FIELDS if d.get(f)]
                    vals = [v for v in vals if v]
                    if vals:
                        info["date_range_sampled"] = [min(vals), max(vals)]
            out[dbname][cname] = info
            print(f"{dbname}.{cname} {info['count']}", file=sys.stderr)
    json.dump(out, sys.stdout, default=str, indent=1)


if __name__ == "__main__":
    main()
