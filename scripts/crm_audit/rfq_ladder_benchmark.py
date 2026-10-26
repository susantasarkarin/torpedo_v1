"""RFQ extraction benchmark per ladder rung on the 44-RFQ answer key (read-only).

  venv/bin/python scripts/crm_audit/rfq_ladder_benchmark.py GOLD.json [--with-qwen]

rules only (default): which RFQs the rules rung answers on its own, and how
accurate those answers are. --with-qwen: RFQs the rules leave open go to the
local 1.5B through the ladder (cloud rungs off), giving rules+Qwen accuracy.
Scoring is the same as rfq_extract_benchmark.py. Writes nothing to MongoDB
except the Qwen job log when --with-qwen is used.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"))
from bson import ObjectId  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from rfq import flow, rules_extract  # noqa: E402


def _match(got, key, alt=()):
    if key is None:
        return None
    if got is None:
        return False
    g = float(got)
    if isinstance(key, list):
        return key[0] <= g <= key[1]
    return g == float(key) or g in [float(a) for a in alt]


def score(item, ext):
    lines = (ext or {}).get("line_items") or []
    sc = {}
    if item.get("countries") and not item.get("countries_ambiguous"):
        got = {(l.get("country") or "").upper().replace("UK", "GB") for l in lines if l.get("country")}
        sc["countries"] = got == set(item["countries"])
    first = lines[0] if lines else {}
    for field, k in (("n", "n"), ("loi", "loi_minutes"), ("ir", "ir_percent")):
        m = _match(first.get(k), item.get(field), item.get("n_alt", []) if field == "n" else ())
        if m is not None:
            sc[field] = m
    return sc


def main():
    gold = json.load(open(sys.argv[1], encoding="utf-8"))
    full = "--full" in sys.argv                    # rules -> Qwen -> Haiku -> Sonnet
    with_qwen = "--with-qwen" in sys.argv or full
    c = MongoClient(os.environ["MONGO_URI"])
    rows = []
    for item in gold["items"]:
        opp = c.crm_db.opportunities.find_one({"_id": ObjectId(item["opp"])}, {"metadata.rfq.source_email_id": 1})
        mail = c.torpedo_gmail.email_metadata.find_one({"_id": ObjectId(opp["metadata"]["rfq"]["source_email_id"])},
                                                       {"subject": 1, "body_plain": 1})
        text = (mail.get("subject") or "") + "\n" + (mail.get("body_plain") or "")
        r = rules_extract.extract(text)
        rung, ext = None, None
        if r is not None and rules_extract.complete(r) and not flow.code_check(r, text):
            rung, ext = "rules", r
        elif with_qwen:
            from platform_core import ladder
            out = ladder.run(task="rfq_extraction", system=flow.SYSTEM, body=text, schema=flow.SCHEMA,
                             code_check=flow.code_check, tiers=None if full else ["qwen"], enqueue_on_fail=False,
                             rules_result=r, rules_complete=rules_extract.complete(r))
            if out.get("data") is not None and not out.get("problems"):
                rung, ext = out.get("tier"), out["data"]
            else:
                rung, ext = "unresolved", out.get("data")
        else:
            rung, ext = "unresolved", r
        sc = score(item, ext)
        rows.append({"id": item["id"], "rung": rung, "score": sc, "all_correct": all(sc.values()) if sc else None})
        print(item["id"], rung, sc, file=sys.stderr, flush=True)
    out = {"items": len(rows), "by_rung": {}}
    for rung in sorted({r["rung"] for r in rows}):
        rs = [r for r in rows if r["rung"] == rung]
        acc = {}
        for f in ("countries", "n", "loi", "ir"):
            vals = [r["score"][f] for r in rs if f in r["score"]]
            acc[f] = f"{sum(vals)}/{len(vals)}" if vals else "-"
        out["by_rung"][rung] = {"rfqs": len(rs), "all_fields_correct": sum(1 for r in rs if r["all_correct"]),
                                "per_field": acc}
    answered = [r for r in rows if r["rung"] != "unresolved"]
    out["answered_without_person"] = len(answered)
    out["answered_and_fully_correct"] = sum(1 for r in answered if r["all_correct"])
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
