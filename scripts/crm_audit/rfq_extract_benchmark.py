"""RFQ extraction benchmark (A8): accuracy per field against the 44-RFQ answer key.

Model = any OpenAI-compatible chat endpoint (BENCH_URL, BENCH_KEY, BENCH_MODEL).
On torpedo-prod each call takes a slot from the production LLM gate at "bulk"
priority (BENCH_USE_GATE=1), so it never exceeds the server's slots.
Text comes from Mongo (the RFQ's source mail), cleaned the same way for every model.

Scoring per item (only fields the answer key states are scored):
  countries  exact set match (items marked countries_ambiguous are skipped)
  n          extracted N equals the key, n_alt, or lies inside a [low, high] key
  loi / ir   extracted value equals the key or lies inside its range
Also reports: JSON parse rate, seconds per call, and how often the code checks
(rfq.extraction_checks) pass on correct vs wrong extractions.

Run from backend/: venv/bin/python /tmp/rfq_extract_benchmark.py gold.json > result.json
"""
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.getcwd())
import requests  # noqa: E402
from bson import ObjectId  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from rfq.extraction_checks import check  # noqa: E402

URL = os.environ["BENCH_URL"]
KEY = os.getenv("BENCH_KEY", "not-required")
MODEL = os.getenv("BENCH_MODEL", "qwen")
USE_GATE = os.getenv("BENCH_USE_GATE") == "1"

SYSTEM = (
    "You extract the specification of a market-research RFQ from an email. "
    "Return JSON only, no prose: {\"line_items\": [{\"country\": ISO-3166 alpha-2 code, \"n\": integer or null, "
    "\"loi_minutes\": number or null, \"ir_percent\": number or null}]}. "
    "One line item per country. If the mail gives one sample size per market, put it on every line. "
    "Use null for anything the mail does not state. Do not guess."
)


def clean(text):
    text = re.split(r"\n(?:From:|-{3,} ?Original Message|On .{5,80} wrote:|DISCLAIMER|Disclaimer:)", text or "")[0]
    text = re.sub(r"<https?://[^>]+>|\[(?:image|cid)[^\]]*\]", "", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:3000]


def ask(text):
    body = {"model": MODEL, "temperature": 0, "max_tokens": 900,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]}
    headers = {"Authorization": f"Bearer {KEY}"}
    t0 = time.time()
    if USE_GATE:
        from leads.local_llm_gate import acquire_local_llm_slot
        with acquire_local_llm_slot(priority="bulk", timeout=900):
            r = requests.post(URL, json=body, headers=headers, timeout=600).json()
    else:
        r = requests.post(URL, json=body, headers=headers, timeout=600).json()
    out = r["choices"][0]["message"]["content"].strip()
    out = re.sub(r"^```(?:json)?|```$", "", out).strip()
    return out, time.time() - t0


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
    lines = ext.get("line_items") or []
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
    c = MongoClient(os.environ["MONGO_URI"])
    rows, secs, parsed = [], [], 0
    for item in gold["items"]:
        opp = c.crm_db.opportunities.find_one({"_id": ObjectId(item["opp"])}, {"metadata.rfq.source_email_id": 1})
        mail = c.torpedo_gmail.email_metadata.find_one({"_id": ObjectId(opp["metadata"]["rfq"]["source_email_id"])},
                                                       {"subject": 1, "body_plain": 1})
        text = (mail.get("subject") or "") + "\n" + clean(mail.get("body_plain"))
        try:
            raw, s = ask(text)
            secs.append(s)
            ext = json.loads(raw)
            parsed += 1
        except Exception as e:
            rows.append({"id": item["id"], "error": str(e)[:200]})
            continue
        sc = score(item, ext)
        chk = check(ext, text)
        rows.append({"id": item["id"], "score": sc, "all_correct": all(sc.values()) if sc else None,
                     "check_pass": chk["pass"], "check_problems": chk["problems"][:4], "extraction": ext})
        print(item["id"], sc, "check", chk["pass"], f"{s:.1f}s", file=sys.stderr, flush=True)
    fields = ("countries", "n", "loi", "ir")
    acc = {}
    for f in fields:
        vals = [r["score"][f] for r in rows if "score" in r and f in r["score"]]
        acc[f] = {"scored": len(vals), "correct": sum(vals), "accuracy": round(sum(vals) / len(vals), 3) if vals else None}
    ok = [r for r in rows if r.get("all_correct") is True]
    bad = [r for r in rows if r.get("all_correct") is False]
    summary = {"model": MODEL, "items": len(gold["items"]), "parsed": parsed, "accuracy": acc,
               "all_fields_correct": f"{len(ok)}/{len(ok) + len(bad)}",
               "checks_pass_when_correct": f"{sum(r['check_pass'] for r in ok)}/{len(ok)}",
               "checks_pass_when_wrong": f"{sum(r['check_pass'] for r in bad)}/{len(bad)}",
               "sec_per_call_median": round(statistics.median(secs), 1) if secs else None,
               "sec_per_call_max": round(max(secs), 1) if secs else None}
    print(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str))


if __name__ == "__main__":
    main()
