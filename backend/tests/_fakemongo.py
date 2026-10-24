"""Tiny in-memory stand-in for the pymongo calls the platform_core modules use.
Supports equality, $in, $ne, $gte, $nin, dotted keys, $set/$inc updates,
find().sort().limit(), count_documents and a $match/$group aggregate."""
import copy
from bson import ObjectId


def _get(doc, dotted):
    cur = doc
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _match(doc, q):
    for k, cond in (q or {}).items():
        v = _get(doc, k)
        if isinstance(cond, dict) and any(c.startswith("$") for c in cond):
            for op, arg in cond.items():
                if op == "$in" and v not in arg:
                    return False
                if op == "$nin" and v in arg:
                    return False
                if op == "$ne" and v == arg:
                    return False
                if op == "$gte" and (v is None or v < arg):
                    return False
                if op == "$exists" and (v is not None) != arg:
                    return False
        elif v != cond:
            return False
    return True


class _Cursor(list):
    def sort(self, key, direction=None):
        if isinstance(key, list):
            key, direction = key[0]
        return _Cursor(sorted(self, key=lambda d: (_get(d, key) is None, _get(d, key)), reverse=(direction == -1)))

    def limit(self, n):
        return _Cursor(self[:n])


class _Res:
    def __init__(self, i):
        self.inserted_id = i


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return _Res(doc["_id"])

    def find_one(self, q=None, projection=None, sort=None):
        for d in self.find(q):
            return d
        return None

    def find(self, q=None, projection=None):
        return _Cursor(copy.deepcopy(d) for d in self.docs if _match(d, q))

    def count_documents(self, q, **kw):
        return sum(1 for d in self.docs if _match(d, q))

    def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if _match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                for k, v in (upd.get("$inc") or {}).items():
                    d[k] = d.get(k, 0) + v
                return
        if upsert:
            base = {k: v for k, v in q.items() if not isinstance(v, dict)}
            base.update(upd.get("$set") or {})
            self.insert_one(base)

    def aggregate(self, pipeline):
        docs = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _match(d, stage["$match"])]
            elif "$group" in stage:
                g = stage["$group"]
                key_field = g["_id"].lstrip("$")
                groups = {}
                for d in docs:
                    k = _get(d, key_field)
                    row = groups.setdefault(k, {"_id": k})
                    for out, spec in g.items():
                        if out == "_id":
                            continue
                        if "$sum" in spec:
                            row[out] = row.get(out, 0) + (spec["$sum"] if isinstance(spec["$sum"], int) else 0)
                        if "$min" in spec:
                            v = _get(d, spec["$min"].lstrip("$"))
                            row[out] = v if out not in row else min(row[out], v)
                docs = list(groups.values())
        return docs


class FakeDB(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]
