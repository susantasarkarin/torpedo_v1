"""
LOCAL SLM BENCHMARK — Qwen2.5-0.5B-Instruct on the cheap-role concurrency gate
================================================================================

Answers one question with actual measurements, not guesses: can this VM run
the local model for the cheap role without repeating the 2026-09-16 incident
(VM load average ~107, backend latency ~32ms -> ~1.6s)?

Two things are measured separately and deliberately:

  1. RAW single-request performance (bypasses the gate, talks to llama-server
     directly) -- used to compare llama-server flag combinations
     (--threads 1 vs 2, --ctx-size 1024 vs 2048). This is about the model
     server's own capability, independent of anything this codebase adds.

  2. GATED concurrency behavior (goes through the real
     leads.bedrock_client.converse(role="cheap") path, including the
     local_llm_gate concurrency limiter) -- this is what actually runs in
     production, so it's what needs to demonstrate predictable behaviour
     under 1/2/5/10 concurrent callers: exactly one inference at a time, the
     rest either wait within the queue timeout or fail fast, and the VM does
     not destabilize.

Uses a REAL cheap-role prompt shape (leads/bucket_classifier.py's own
SYSTEM_PROMPT/USER_PROMPT + a representative lead), not "hello world" --
context length and JSON-structure demands both affect latency and resource
use, and a toy prompt would under-measure both.

Run on the VM, from backend/:
    python scripts/benchmark_local_llm.py --mode raw
    python scripts/benchmark_local_llm.py --mode gated --concurrency 1
    python scripts/benchmark_local_llm.py --mode gated --concurrency 5
    python scripts/benchmark_local_llm.py --mode resources   # one-shot snapshot

The objective is NOT maximum throughput -- it's predictable behaviour under
overload. A high failure count at concurrency=10 with the VM still responsive
and no retry storm is a PASS for that purpose; a hang or VM destabilization is
not, regardless of how many requests "succeeded."
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A real, representative cheap-role lead -- same shape bucket_classifier.py
# actually builds and sends, not a synthetic minimal example.
_REAL_LEAD = {
    "name": "Priya Nair",
    "title": "VP of Market Research",
    "company": "Meridian Consumer Insights",
    "industry": "Consumer Packaged Goods",
    "country": "India",
    "seniority": "VP",
    "snippet": (
        "15+ years leading quantitative and qualitative research programs for "
        "FMCG brands across South Asia. Currently scoping a multi-market brand "
        "tracker and looking for panel partners with strong urban/rural India "
        "coverage. Previously ran insights at two regional agencies before "
        "moving client-side."
    ),
}


def _real_prompt():
    from leads.bucket_classifier import SYSTEM_PROMPT, build_prompt
    return SYSTEM_PROMPT, build_prompt(_REAL_LEAD)


@dataclass
class CallResult:
    ok: bool
    latency_s: float
    error: Optional[str] = None
    tokens: Optional[int] = None


def _resource_snapshot(label: str) -> dict:
    """One-shot capture of the numbers section 9/14 of the plan asks for.
    Best-effort -- missing tools (e.g. non-Linux) degrade gracefully."""
    snap = {"label": label, "ts": time.time()}
    try:
        with open("/proc/loadavg") as f:
            snap["loadavg"] = f.read().split()[:3]
    except Exception:
        snap["loadavg"] = None
    try:
        free_out = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5).stdout
        snap["free_m"] = free_out.strip().splitlines()
    except Exception:
        snap["free_m"] = None
    for name, grep in (("llama_server_rss_kb", "llama-server"),
                       ("mongod_rss_kb", "mongod"),
                       ("backend_rss_kb", "uvicorn")):
        try:
            out = subprocess.run(
                ["bash", "-c", f"ps -eo rss,comm | grep '{grep}' | awk '{{s+=$1}} END {{print s}}'"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            snap[name] = int(out) if out else 0
        except Exception:
            snap[name] = None
    return snap


def print_resource_snapshot(label: str) -> None:
    s = _resource_snapshot(label)
    print(f"\n--- resource snapshot: {label} ---")
    print(f"  loadavg (1/5/15m): {s['loadavg']}")
    if s["free_m"]:
        for line in s["free_m"]:
            print(f"  {line}")
    print(f"  llama-server RSS: {s['llama_server_rss_kb']} KB, "
          f"mongod RSS: {s['mongod_rss_kb']} KB, "
          f"backend RSS: {s['backend_rss_kb']} KB")


def _call_raw(base_url: str, api_key: str, model: str, timeout: float) -> CallResult:
    import requests
    system, user = _real_prompt()
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "max_tokens": 200, "temperature": 0.0},
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("completion_tokens")
        # Real success criterion for a cheap-role call: valid JSON in the
        # expected shape, not just "the HTTP call didn't error."
        parsed = json.loads(content)
        ok = "bucket" in parsed and "confidence" in parsed
        return CallResult(ok=ok, latency_s=elapsed, tokens=tokens,
                          error=None if ok else f"unexpected shape: {content[:200]}")
    except Exception as e:
        return CallResult(ok=False, latency_s=time.monotonic() - t0, error=str(e))


def _call_gated() -> CallResult:
    from leads.bedrock_client import converse_json_object
    system, user = _real_prompt()
    t0 = time.monotonic()
    try:
        data = converse_json_object(role="cheap", system=system, user=user,
                                    max_tokens=200, temperature=0.0)
        elapsed = time.monotonic() - t0
        ok = bool(data and "bucket" in data and "confidence" in data)
        return CallResult(ok=ok, latency_s=elapsed,
                          error=None if ok else f"unexpected shape: {data}")
    except Exception as e:
        return CallResult(ok=False, latency_s=time.monotonic() - t0, error=str(e))


def _report(results: List[CallResult], label: str) -> None:
    latencies = [r.latency_s for r in results]
    ok_count = sum(1 for r in results if r.ok)
    print(f"\n=== {label}: {len(results)} calls, {ok_count} ok, "
          f"{len(results) - ok_count} failed ===")
    if latencies:
        sorted_lat = sorted(latencies)
        p95_idx = min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))
        print(f"  latency: min={min(latencies):.2f}s "
              f"median={statistics.median(latencies):.2f}s "
              f"p95={sorted_lat[p95_idx]:.2f}s max={max(latencies):.2f}s")
    for r in results:
        if not r.ok:
            print(f"  FAIL ({r.latency_s:.2f}s): {r.error}")


def run_raw(base_url: str, api_key: str, model: str, n: int, timeout: float) -> List[CallResult]:
    return [_call_raw(base_url, api_key, model, timeout) for _ in range(n)]


def run_gated_concurrent(concurrency: int) -> List[CallResult]:
    print_resource_snapshot(f"before concurrency={concurrency}")
    results: List[CallResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_call_gated) for _ in range(concurrency)]
        for f in as_completed(futures):
            results.append(f.result())
    print_resource_snapshot(f"after concurrency={concurrency}")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["raw", "gated", "resources"], required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--sequential", type=int, default=1,
                        help="For --mode raw: number of sequential calls (test 1 vs test 2)")
    parser.add_argument("--base-url", default=os.getenv("SELF_HOSTED_BASE_URL", "http://127.0.0.1:8003/v1"))
    parser.add_argument("--api-key", default=os.getenv("SELF_HOSTED_API_KEY", ""))
    parser.add_argument("--model", default="qwen2.5-0.5b-instruct")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    if args.mode == "resources":
        print_resource_snapshot("manual snapshot")
        return

    if args.mode == "raw":
        if not args.api_key:
            print("ERROR: --api-key or SELF_HOSTED_API_KEY required for --mode raw", file=sys.stderr)
            sys.exit(1)
        print_resource_snapshot(f"before raw x{args.sequential}")
        results = run_raw(args.base_url, args.api_key, args.model, args.sequential, args.timeout)
        print_resource_snapshot(f"after raw x{args.sequential}")
        _report(results, f"raw sequential (n={args.sequential})")
        return

    if args.mode == "gated":
        results = run_gated_concurrent(args.concurrency)
        _report(results, f"gated concurrent (concurrency={args.concurrency})")
        return


if __name__ == "__main__":
    main()
