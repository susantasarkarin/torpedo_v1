"""
email_drafter.py — Task 4: Reactivation Email Drafting
=======================================================

Reads reactivation candidates, groups by company-country, and uses
Anthropic Batch API to generate personalised outreach drafts.

Output:
  - data/reactivation_drafts.jsonl

Usage:
  python -m backend.email_crm_pipeline.email_drafter
  python -m backend.email_crm_pipeline.email_drafter --input ./data/reactivation_candidates.jsonl
"""

import sys
import os
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from email_crm_pipeline.config import (
    ANTHROPIC_API_KEY,
    DRAFTER_MODEL,
    DRAFTER_MAX_TOKENS,
    BATCH_SIZE,
    BATCH_POLL_INTERVAL,
    REACTIVATION_FILE,
    DRAFTS_FILE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DRAFT_SYSTEM_PROMPT = """You write handcrafted B2B reactivation emails for a market research firm.
Return ONLY a valid JSON object with keys: subject, body.
Rules:
- Body <= 150 words
- Warm, professional, and specific
- Reference prior relationship context and project type if available
- Job changer: acknowledge new role and introduce services fresh
- Unanswered outbound: gentle follow-up on original topic
- Dormant: reconnect and ask for upcoming research needs
- Sign off exactly as: Susanta Banerjee, Survey Fieldwork
- Avoid generic template language
"""


def load_candidates(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Candidate file not found: {path}")
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def group_candidates(candidates: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for item in candidates:
        account = (item.get("company") or "Unknown Account").strip()
        country = (item.get("country") or "Unknown").strip()
        key = (account, country)

        if key not in grouped:
            grouped[key] = {
                "account": account,
                "country": country,
                "contacts": [],
                "bucket_types": set(),
                "contexts": [],
                "rfq_history": [],
            }

        email = (item.get("contact_email") or "").strip().lower()
        if email:
            grouped[key]["contacts"].append({
                "name": item.get("contact_name"),
                "email": email,
                "designation": item.get("designation"),
            })

        bucket = item.get("bucket") or "unknown"
        grouped[key]["bucket_types"].add(bucket)

        if item.get("relationship_context"):
            grouped[key]["contexts"].append(item["relationship_context"])
        for rfq in item.get("rfq_history") or []:
            if rfq:
                grouped[key]["rfq_history"].append(str(rfq))

    output = []
    for row in grouped.values():
        row["bucket_types"] = sorted(list(row["bucket_types"]))
        row["contacts"] = sorted(
            {c["email"]: c for c in row["contacts"] if c.get("email")}.values(),
            key=lambda x: x.get("email", ""),
        )
        row["contexts"] = row["contexts"][:5]
        row["rfq_history"] = row["rfq_history"][:5]
        output.append(row)
    return output


def build_requests(groups: list[dict]) -> list[dict]:
    requests = []
    for idx, group in enumerate(groups):
        payload = {
            "account": group["account"],
            "country": group["country"],
            "bucket_types": group["bucket_types"],
            "contacts": group["contacts"],
            "relationship_context": group["contexts"],
            "rfq_history": group["rfq_history"],
        }

        requests.append({
            "custom_id": f"draft-{idx+1}",
            "params": {
                "model": DRAFTER_MODEL,
                "max_tokens": DRAFTER_MAX_TOKENS,
                "system": [
                    {
                        "type": "text",
                        "text": DRAFT_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": "Draft a personalised reactivation email from this JSON context:\n" + json.dumps(payload, ensure_ascii=False),
                    }
                ],
            },
        })
    return requests


def _parse_json_from_text(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


def _poll_batch(client: anthropic.Anthropic, batch_id: str) -> None:
    while True:
        batch = client.beta.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        log.info("Draft batch %s status=%s", batch_id, status)
        if status != "in_progress":
            return
        time.sleep(BATCH_POLL_INTERVAL)


def run_drafting(input_path: Optional[Path] = None, output_path: Optional[Path] = None) -> dict:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set in the environment.")

    source = input_path or REACTIVATION_FILE
    out_path = output_path or DRAFTS_FILE

    candidates = load_candidates(source)
    groups = group_candidates(candidates)
    if not groups:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")
        return {"groups": 0, "drafts": 0, "output_file": str(out_path)}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    drafts: list[dict] = []

    for start in range(0, len(groups), BATCH_SIZE):
        chunk = groups[start:start + BATCH_SIZE]
        chunk_requests = build_requests(chunk)
        batch = client.beta.messages.batches.create(requests=chunk_requests)
        _poll_batch(client, batch.id)

        by_id = {f"draft-{i+1}": g for i, g in enumerate(chunk, start=0)}

        for result in client.beta.messages.batches.results(batch.id):
            cid = str(getattr(result, "custom_id", ""))
            group = by_id.get(cid)
            if not group:
                continue
            result_type = getattr(getattr(result, "result", None), "type", "")
            if result_type != "succeeded":
                log.warning("Draft failed for %s", cid)
                continue
            text = ""
            try:
                text = result.result.message.content[0].text
            except Exception:
                text = ""
            parsed = _parse_json_from_text(text)
            if not parsed:
                log.warning("Could not parse draft JSON for %s", cid)
                continue

            drafts.append({
                "account": group["account"],
                "country": group["country"],
                "contacts": group["contacts"],
                "subject": parsed.get("subject", ""),
                "body": parsed.get("body", ""),
                "bucket_type": ",".join(group["bucket_types"]),
                "draft_date": datetime.now(timezone.utc).isoformat(),
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in drafts:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    return {
        "groups": len(groups),
        "drafts": len(drafts),
        "output_file": str(out_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate reactivation draft emails")
    parser.add_argument("--input", metavar="PATH", help="Path to reactivation candidates JSONL")
    parser.add_argument("--output", metavar="PATH", help="Path to output drafts JSONL")
    args = parser.parse_args()

    result = run_drafting(
        input_path=Path(args.input) if args.input else None,
        output_path=Path(args.output) if args.output else None,
    )
    print(json.dumps(result, indent=2, default=str))
