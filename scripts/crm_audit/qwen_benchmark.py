"""Qwen CPU benchmark for the CRM audit (Phase 1.4).

Two realistic tasks (reply classification, RFQ field extraction) on synthetic
mails, at 1 and 3 concurrent workers. Every call takes a slot from the
production Redis gate at "bulk" priority, so it never exceeds the server's
slot count and always yields to live work. Records wall time (incl. gate wait),
server-side prompt/generation ms, token counts, JSON validity and confidence.

Run on the VM from backend/:  venv/bin/python /tmp/qwen_benchmark.py
"""
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.getcwd())
from leads.local_llm_gate import acquire_local_llm_slot  # noqa: E402

URL = os.getenv("BENCH_URL", "http://127.0.0.1:8003/v1/chat/completions")
HEADERS = {"Authorization": f"Bearer {os.getenv('BENCH_KEY', 'not-required')}"}
CALLS = int(os.getenv("BENCH_CALLS", "6"))

CLASSIFY_SYS = (
    "You classify replies to B2B outreach for a market research data collection company. "
    "Categories: positive, negative, neutral, out_of_office, rfq, confirmation, redirect_request, other. "
    "Sender type is given. Return JSON only: "
    '{"category": str, "sub_reason": str, "return_date": str|null, "confidence": number 0-1}'
)
CLASSIFY_MAILS = [
    "Subject: Re: Online sample for India [L-10234]\nSender type: client\n\nHi, thanks for reaching out. "
    "We do run quant studies in India fairly often. Could you share your panel book and typical CPIs for gen pop? Regards, R.",
    "Subject: Re: Panel partnership [L-20871]\nSender type: client\n\nPlease remove me from your list. Not interested.",
    "Subject: Automatic reply: Fieldwork capacity [L-30112]\nSender type: client\n\nI am out of the office until 3 November "
    "with limited access to email. For urgent matters contact the team inbox.",
    "Subject: Re: Quick intro [L-40551]\nSender type: client\n\nI'm not the right person, please speak to our research "
    "operations lead, Priya, who handles vendor onboarding.",
]

RFQ_SYS = (
    "Extract RFQ fields from a client email for a market research data collection company. "
    "Return JSON only: {\"line_items\": [{\"country\": str|null, \"target_group\": str|null, \"n\": int|null, "
    "\"loi_minutes\": int|null, \"ir_percent\": number|null, \"methodology\": str|null, \"quotas\": str|null}], "
    "\"field_start\": str|null, \"field_end\": str|null, \"deliverables\": str|null, \"client_reference\": str|null, "
    "\"special_requirements\": str|null, \"confidence\": number 0-1}"
)
RFQ_MAILS = [
    "Subject: RFQ - FMCG usage & attitude study (Ref HX-2291)\nSender type: client\n\nHi team,\n\nPlease quote for an online "
    "survey: India n=800 and Indonesia n=500, adults 18-45 who bought packaged snacks in the last month. LOI 15 minutes, "
    "IR around 40%. Quotas: 50/50 gender, age 18-30 / 31-45 nat rep. Field to start 10 Nov, close by 24 Nov. "
    "Deliverables: raw data in SPSS + daily counts. Please include feasibility. Thanks, A.",
    "Subject: Costing needed - B2B IT decision makers\nSender type: client\n\nCould you send CPI and feasibility for "
    "US and UK, 150 completes each, IT decision makers at companies with 500+ employees, 20 min survey, incidence "
    "approx 12%. We need to be in field next week. Client ref: PRJ-5531. Thanks.",
]


def call(system, user, max_tokens):
    t0 = time.time()
    with acquire_local_llm_slot(priority="bulk", timeout=600):
        t1 = time.time()
        r = requests.post(URL, timeout=300, headers=HEADERS, json={
            "model": "qwen2.5-1.5b-instruct",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": max_tokens,
        })
    t2 = time.time()
    body = r.json()
    if "choices" not in body:
        raise RuntimeError(f"server error: {str(body)[:200]}")
    text = body["choices"][0]["message"]["content"]
    tm = body.get("timings", {})
    try:
        parsed = json.loads(text)
        valid, conf = True, parsed.get("confidence")
    except Exception:
        valid, conf = False, None
    return {"wall_s": round(t2 - t0, 2), "gate_wait_s": round(t1 - t0, 2), "infer_s": round(t2 - t1, 2),
            "prompt_tokens": tm.get("prompt_n"), "gen_tokens": tm.get("predicted_n"),
            "prompt_ms": tm.get("prompt_ms"), "gen_ms": tm.get("predicted_ms"),
            "json_valid": valid, "confidence": conf, "out": text[:300]}


def run(task, workers):
    system, mails, mt = (CLASSIFY_SYS, CLASSIFY_MAILS, 120) if task == "classify" else (RFQ_SYS, RFQ_MAILS, 450)
    jobs = [mails[i % len(mails)] for i in range(CALLS)]
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda m: call(system, m, mt), jobs))
    total = time.time() - t0
    inf = [r["infer_s"] for r in res]
    return {"task": task, "workers": workers, "calls": len(res), "batch_wall_s": round(total, 1),
            "throughput_calls_per_min": round(60 * len(res) / total, 2),
            "infer_median_s": round(statistics.median(inf), 1), "infer_max_s": max(inf),
            "gate_wait_median_s": round(statistics.median(r["gate_wait_s"] for r in res), 1),
            "json_valid": sum(r["json_valid"] for r in res), "results": res}


if __name__ == "__main__":
    out = []
    for task in ("classify", "rfq"):
        for w in (1, 3):
            r = run(task, w)
            print(json.dumps({k: v for k, v in r.items() if k != "results"}), file=sys.stderr, flush=True)
            out.append(r)
    json.dump(out, sys.stdout, indent=1)
