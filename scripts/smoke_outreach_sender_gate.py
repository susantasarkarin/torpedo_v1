#!/usr/bin/env python3
"""Strict sender-resolution gate for cold outreach campaigns.

Purpose:
- Print per-campaign PASS/FAIL badges for sender resolution
- Exit non-zero when any active campaign cannot resolve a sender

Usage:
  python scripts/smoke_outreach_sender_gate.py
  python scripts/smoke_outreach_sender_gate.py --base-url http://localhost:8000
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict sender gate for cold outreach")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("SMOKE_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("SMOKE_PASSWORD", "password123"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("SMOKE_TIMEOUT", "30")))
    args = parser.parse_args()

    try:
        session_id = _login(args.base_url, args.username, args.password, args.timeout)
    except Exception as e:
        print(f"[FAIL] Login: {e}")
        return 2

    code, payload = _http_json(
        "GET",
        f"{args.base_url.rstrip('/')}/api/cold-outreach/sender-status",
        timeout=args.timeout,
        headers={"Authorization": session_id},
    )
    if code >= 400:
        print(f"[FAIL] sender-status endpoint HTTP {code}: {payload}")
        return 3

    campaigns: List[Dict[str, Any]] = payload.get("campaigns", []) or []
    active = [c for c in campaigns if c.get("is_active")]

    print("\nSender Gate Report")
    print("-" * 72)
    if not active:
        print("No active campaigns found.")
        return 0

    unresolved = 0
    for c in active:
        resolved = bool(c.get("sender_resolved"))
        badge = "PASS" if resolved else "FAIL"
        if not resolved:
            unresolved += 1

        cid = c.get("campaign_id", "")
        biz = c.get("business", "")
        sender = c.get("resolved_sender") or "(none)"
        due = c.get("due_leads", 0)
        err = c.get("error_leads", 0)

        print(f"[{badge}] {cid} | business={biz} | sender={sender} | due={due} | error={err}")
        if not resolved:
            print(f"       diagnosis: {c.get('diagnosis')}")

    print("-" * 72)
    print(f"Active campaigns: {len(active)}")
    print(f"Unresolved senders: {unresolved}")

    if unresolved > 0:
        print("\nGate result: FAIL")
        return 1

    print("\nGate result: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
