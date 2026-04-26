#!/usr/bin/env python3
"""One-command smoke test for cold outreach sender + bounce feedback pipeline.

What it does:
1) Login and obtain session_id
2) GET /api/cold-outreach/sender-status
3) POST /api/cold-outreach/process-due
4) POST /api/cold-outreach/scan-bounces-replies
5) GET /api/cold-outreach/sender-status (again)
6) Optional Mongo checks for feedback-loop fields

Exit codes:
- 0: success (or success with warnings)
- 1: hard failure (login/API schema/HTTP failure)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _http_json(
    method: str,
    url: str,
    timeout: int,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"_raw": raw}
            return status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"_raw": raw}
        return e.code, parsed


def _login(base_url: str, username: str, password: str, timeout: int) -> str:
    status, data = _http_json(
        "POST",
        f"{base_url.rstrip('/')}/login/",
        timeout=timeout,
        body={"username": username, "password": password},
    )
    if status >= 400:
        raise RuntimeError(f"Login failed HTTP {status}: {data}")

    session_id = data.get("session_id")
    if not session_id:
        raise RuntimeError(f"Login succeeded but no session_id returned: {data}")
    return session_id


def _print_heading(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _sender_status_summary(data: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    campaigns = data.get("campaigns", []) or []
    active = [c for c in campaigns if c.get("is_active")]
    unresolved = [c for c in active if not c.get("sender_resolved")]
    notes: List[str] = []

    for c in unresolved:
        notes.append(
            f"{c.get('campaign_id')} | {c.get('business')} | diagnosis={c.get('diagnosis')}"
        )

    return len(active), len(unresolved), notes


def _check_mongo_feedback(uri: str, timeout_ms: int = 5000) -> Dict[str, Any]:
    try:
        from pymongo import MongoClient  # type: ignore
    except Exception as e:
        return {"enabled": False, "reason": f"pymongo unavailable: {e}"}

    client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    out: Dict[str, Any] = {"enabled": True}

    # email_automation.email_patterns
    ea = client["email_automation"]
    patterns = ea["email_patterns"]
    out["patterns_total"] = patterns.count_documents({})
    out["patterns_with_send_count"] = patterns.count_documents({"send_count": {"$gt": 0}})
    out["patterns_with_bounce_count"] = patterns.count_documents({"bounce_count": {"$gt": 0}})
    out["high_bounce_risk_domains"] = patterns.count_documents({"high_bounce_risk": True})
    out["blacklisted_domains"] = patterns.count_documents({"pattern_blacklisted": True})

    # torpedo.outreach_leads_v2
    torpedo = client["torpedo"]
    leads = torpedo["outreach_leads_v2"]
    out["leads_skipped_high_bounce_risk"] = leads.count_documents(
        {"workflow_status": "skipped_high_bounce_risk"}
    )

    # email_automation.leads_enriched
    enriched = ea["leads_enriched"]
    out["leads_enriched_delivered"] = enriched.count_documents({"email_status": "Delivered"})

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Cold outreach feedback-loop smoke test")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("SMOKE_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("SMOKE_PASSWORD", "password123"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("SMOKE_TIMEOUT", "30")))
    parser.add_argument(
        "--skip-mongo-check",
        action="store_true",
        help="Skip optional Mongo verification section",
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("MONGO_URI", os.getenv("MONGODB_URI", "mongodb://localhost:27017/")),
    )
    args = parser.parse_args()

    _print_heading("STEP 1: Login")
    try:
        session_id = _login(args.base_url, args.username, args.password, args.timeout)
        print(f"Login OK. Session prefix: {session_id[:20]}...")
    except Exception as e:
        print(f"FAIL: {e}")
        return 1

    auth_headers = {"Authorization": session_id}

    _print_heading("STEP 2: Sender Status (Pre)")
    code, sender_pre = _http_json(
        "GET",
        f"{args.base_url.rstrip('/')}/api/cold-outreach/sender-status",
        timeout=args.timeout,
        headers=auth_headers,
    )
    if code >= 400:
        print(f"FAIL: sender-status pre-check HTTP {code}: {sender_pre}")
        return 1

    active_count, unresolved_count, unresolved_notes = _sender_status_summary(sender_pre)
    print(f"Active campaigns: {active_count}")
    print(f"Unresolved senders: {unresolved_count}")
    for n in unresolved_notes:
        print(f"  - {n}")

    _print_heading("STEP 3: Trigger Send Cycle")
    code, due_result = _http_json(
        "POST",
        f"{args.base_url.rstrip('/')}/api/cold-outreach/process-due",
        timeout=args.timeout,
        headers=auth_headers,
        body={},
    )
    if code >= 400:
        print(f"FAIL: process-due HTTP {code}: {due_result}")
        return 1
    print(json.dumps(due_result, indent=2, default=str))

    _print_heading("STEP 4: Trigger Bounce/Reply Scan")
    code, scan_result = _http_json(
        "POST",
        f"{args.base_url.rstrip('/')}/api/cold-outreach/scan-bounces-replies",
        timeout=args.timeout,
        headers=auth_headers,
        body={},
    )
    if code >= 400:
        print(f"FAIL: scan-bounces-replies HTTP {code}: {scan_result}")
        return 1
    print(json.dumps(scan_result, indent=2, default=str))

    _print_heading("STEP 5: Sender Status (Post)")
    code, sender_post = _http_json(
        "GET",
        f"{args.base_url.rstrip('/')}/api/cold-outreach/sender-status",
        timeout=args.timeout,
        headers=auth_headers,
    )
    if code >= 400:
        print(f"FAIL: sender-status post-check HTTP {code}: {sender_post}")
        return 1

    active_count_post, unresolved_count_post, unresolved_notes_post = _sender_status_summary(sender_post)
    print(f"Active campaigns: {active_count_post}")
    print(f"Unresolved senders: {unresolved_count_post}")
    for n in unresolved_notes_post:
        print(f"  - {n}")

    if not args.skip_mongo_check:
        _print_heading("STEP 6: Mongo Feedback-Loop Checks (Optional)")
        try:
            mongo_result = _check_mongo_feedback(args.mongo_uri)
            print(json.dumps(mongo_result, indent=2, default=str))
        except Exception as e:
            print(f"WARN: Mongo checks failed: {e}")

    _print_heading("RESULT")
    if unresolved_count_post > 0:
        print("SMOKE PASS WITH WARNINGS: API flow works, but some campaign senders are unresolved.")
    else:
        print("SMOKE PASS: sender resolution + send cycle + bounce scan endpoints are healthy.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
