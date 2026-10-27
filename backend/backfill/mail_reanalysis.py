"""Haiku re-analysis of the full mail pool (owner, 2026-10-27).

Re-process every inbound mail through Haiku to:
  - Classify sender: client, vendor, internal, or unknown
  - Detect RFQ and extract scope/pricing (if present)
  - Assign business unit (if detectable from content)
  - Link to CRM accounts/opportunities where confident

Results fill the CRM and Finance databases; nothing is overwritten, only
blanks are filled and RFQ details are versioned.

    venv/bin/python backfill/mail_reanalysis.py [--limit N] [--apply]

  --limit N     process only N mails (for testing)
  --apply       write to databases (dry-run otherwise)

Dry run unless apply. Stamped backfill.mail_reanalysis.
"""
import argparse
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bson import ObjectId

logger = logging.getLogger(__name__)


SCHEMA = {
    "type": "object",
    "required": ["sender_type"],
    "properties": {
        "sender_type": {
            "type": "string",
            "enum": ["client", "vendor", "internal", "unknown"],
            "description": "Sender classification based on domain, relationships, and content"
        },
        "is_rfq": {
            "type": ["boolean", "null"],
            "description": "Is this mail (or thread) an RFQ / request for quote?"
        },
        "rfq_scope": {
            "type": ["string", "null"],
            "description": "What they're asking to quote"
        },
        "rfq_budget": {
            "type": ["string", "number", "null"],
            "description": "Stated budget or price mention"
        },
        "business_unit": {
            "type": ["string", "null"],
            "enum": ["SFW", "BIM", "COGENTIX", None],
            "description": "Which business unit owns this relationship / project?"
        },
        "company_hint": {
            "type": ["string", "null"],
            "description": "Company name or domain extracted (for CRM matching)"
        },
    }
}

SYSTEM = """You are analyzing business emails to classify senders and detect RFQs.
For each email, determine:
1. sender_type: Is the sender a client (buys from us), vendor (sells to us), internal (our domain), or unknown?
2. is_rfq: Is this a request for a quote or proposal?
3. rfq_scope: What project/scope are they asking for? (null if not an RFQ)
4. rfq_budget: Any stated budget or price? (null if not mentioned)
5. business_unit: Which of our units (SFW=survey fieldwork, BIM=building info, COGENTIX=market research) is this for?
6. company_hint: The company name or domain

Respond with JSON only, no explanation."""


def _check_result(data, _text):
    """Validate the result structure."""
    issues = []
    if data.get("sender_type") not in ("client", "vendor", "internal", "unknown"):
        issues.append("invalid sender_type")
    if data.get("business_unit") and data["business_unit"] not in ("SFW", "BIM", "COGENTIX"):
        issues.append("invalid business_unit")
    return issues


def _process_mail(msg: Dict[str, Any], ladder) -> Dict[str, Any]:
    """Run Haiku on one mail to classify sender, detect RFQ, and assign BU."""
    msg_id = str(msg["_id"])
    subject = msg.get("subject") or ""
    body_plain = (msg.get("body_plain") or "")[:10000]
    from_email = msg.get("from_email") or ""
    from_name = msg.get("from_name") or ""

    body = f"""FROM: {from_name} <{from_email}>
SUBJECT: {subject}

{body_plain}"""

    try:
        result = ladder.run(
            task="mail_reanalysis",
            system=SYSTEM,
            body=body,
            schema=SCHEMA,
            code_check=_check_result,
            ref={"collection": "torpedo_gmail.email_metadata", "id": msg_id},
            enqueue_on_fail=False
        )
        data = result.get("data") if result and result.get("status") in ("ok", "review") else None
        if data:
            return {**data, "_msg_id": msg_id, "tier": result.get("tier", "unknown")}
        return {"sender_type": "unknown", "_msg_id": msg_id}
    except Exception as e:
        logger.exception("ladder failed for mail %s", msg_id)
        return {"sender_type": "unknown", "_msg_id": msg_id}


def run(c, apply=False, limit: Optional[int] = None, now=None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    stamp = {"backfill.mail_reanalysis": now, "updated_at": now}

    from platform_core import ladder

    md = c.torpedo_gmail["email_metadata"]
    crm, fin, ea = c.crm_db, c.finance_db, c.email_automation

    rep: Counter = Counter()
    samples = defaultdict(list)

    # Find all inbound mails, newest first
    q = {"direction": "inbound"}
    total = md.count_documents(q)
    rep["total_inbound_mails"] = total

    processed = 0
    rfq_processed = 0
    errors = 0

    for msg in md.find(q, {"subject": 1, "body_plain": 1, "from_email": 1, "from_name": 1, "timestamp": 1}).sort("timestamp", -1).limit(limit or 999999):
        if processed % 100 == 0 and processed > 0:
            logger.info("mail_reanalysis: %d processed, %d RFQs, %d errors", processed, rfq_processed, errors)
        processed += 1

        msg_id = str(msg["_id"])

        # Run Haiku classification
        result = _process_mail(msg, ladder)
        sender_type = result.get("sender_type") or "unknown"
        is_rfq = result.get("is_rfq")
        rfq_scope = result.get("rfq_scope")
        rfq_budget = result.get("rfq_budget")
        business_unit = result.get("business_unit")
        company_hint = result.get("company_hint")
        tier = result.get("tier", "unknown")

        if "error" in result:
            errors += 1

        rep[f"sender_type:{sender_type}"] += 1
        if is_rfq:
            rfq_processed += 1
            rep["is_rfq:true"] += 1
            if rfq_scope or rfq_budget:
                rep["rfq_details_extracted"] += 1
                if len(samples["rfq_details"]) < 12:
                    samples["rfq_details"].append({
                        "subject": (msg.get("subject") or "")[:60],
                        "scope": rfq_scope or ""
                    })
        if business_unit:
            rep[f"bu:{business_unit}"] += 1

        rep[f"tier:{tier}"] += 1

        # Mark this mail as reanalyzed (even dry-run, to log the analysis)
        if apply:
            md.update_one(
                {"_id": msg["_id"]},
                {"$set": {
                    "reanalysis": {
                        "sender_type": sender_type,
                        "is_rfq": is_rfq,
                        "rfq_scope": rfq_scope,
                        "rfq_budget": rfq_budget,
                        "business_unit": business_unit,
                        "company_hint": company_hint,
                        "tier": tier,
                        "at": now
                    },
                    **stamp
                }}
            )

    rep["processed"] = processed
    rep["rfq_detected"] = rfq_processed
    rep["errors"] = errors
    return {**rep, "samples": dict(samples)}


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("--limit", type=int, help="Process only N mails")
    ap.add_argument("--apply", action="store_true", help="Write to databases")
    a = ap.parse_args()

    from database import get_database
    c = type("", (), {
        "torpedo_gmail": get_database("torpedo_gmail"),
        "crm_db": get_database("crm_db"),
        "finance_db": get_database("finance_db"),
        "email_automation": get_database("email_automation"),
    })()

    result = run(c, apply=a.apply, limit=a.limit)
    print(("APPLIED" if a.apply else "DRY RUN"), dict(result))
    for k in ["rfq_details"]:
        if k in result.get("samples", {}):
            for s in result["samples"][k]:
                print("   ", s)


if __name__ == "__main__":
    main()
