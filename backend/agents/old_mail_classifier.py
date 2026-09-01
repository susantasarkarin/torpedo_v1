"""
OLD MAIL CLASSIFIER AGENT  (Phase 5 — first AI agent)

Bridges the EXISTING email classification pipeline into the canonical CRM spine
through the AI decision engine + approval gate.

Pipeline context (already built, reused here):
    email_sync.emails
      -> email_crm_pipeline.email_classifier  (Anthropic) -> email_crm_extractions
      -> [THIS AGENT] match to canonical Contact/Account and attach an Activity,
         routed through ai_engine.submit_decision (logged + approval-gated).

It does NOT re-run the LLM and does NOT send email. For each extraction it:
  1. matches/creates a canonical Contact (by email) and Account (by company),
  2. builds an "email" Activity payload linked to those records,
  3. submits it via ai_engine as a `log_activity` action.

Autonomy (safe by default):
  - "approve"   (default): each attachment is parked PENDING for human approval.
  - "autopilot"          : attaching a historical email is low-risk, so it
                           executes immediately.
  - "recommend"/"observe": as per the engine (task / log-only).

Idempotent: extractions already seen by this agent (tracked via the logged
ai_decisions' input_summary.email_id) are skipped on re-run.

Usage:
    python -m backend.agents.old_mail_classifier --dry-run
    python -m backend.agents.old_mail_classifier --mode approve --limit 100
    python -m backend.agents.old_mail_classifier --mode autopilot --execute
"""

import argparse
from typing import Optional, Dict, Any

from app.services import crm_service, ai_engine
from database import get_database

AGENT_NAME = "old_mail_classifier"
DEFAULT_EXTRACTIONS_DB = "email_automation"
DEFAULT_EXTRACTIONS_COLLECTION = "email_crm_extractions"


def _already_seen() -> set:
    """email_ids this agent has already produced a decision for (idempotency)."""
    seen = set()
    for d in crm_service._col("ai_decisions").find(
        {"agent_name": AGENT_NAME}, {"input_summary.email_id": 1}
    ):
        eid = (d.get("input_summary") or {}).get("email_id")
        if eid:
            seen.add(eid)
    return seen


def _build_activity(extraction: Dict[str, Any], contact_id, account_id) -> Dict[str, Any]:
    contact = extraction.get("contact") or {}
    account = extraction.get("account") or {}
    rfq = extraction.get("rfq") or {}
    email_type = extraction.get("email_type", "unknown")
    subject = (
        extraction.get("subject")
        or rfq.get("rfq_summary")
        or f"{email_type} email"
    )
    return {
        "type": "email",
        "subject": subject,
        "description": f"[{email_type}] from {contact.get('email') or 'unknown'}"
        + (f" — {rfq.get('rfq_summary')}" if rfq.get("rfq_summary") else ""),
        "contact_id": contact_id,
        "account_id": account_id,
        "metadata": {
            "source": DEFAULT_EXTRACTIONS_COLLECTION,
            "source_id": str(extraction.get("email_id") or extraction.get("_id")),
            "email_type": email_type,
            "company": account.get("company_name"),
        },
    }


def run(
    autonomy_mode: str = "approve",
    limit: Optional[int] = None,
    dry_run: bool = False,
    extractions_db: str = DEFAULT_EXTRACTIONS_DB,
    extractions_collection: str = DEFAULT_EXTRACTIONS_COLLECTION,
) -> Dict[str, Any]:
    """Process classified-email extractions into the CRM spine. Returns stats."""
    src = get_database(extractions_db)[extractions_collection]
    seen = _already_seen()

    stats = {
        "agent": AGENT_NAME,
        "mode": autonomy_mode,
        "dry_run": dry_run,
        "scanned": 0,
        "skipped_seen": 0,
        "processed": 0,
        "queued": 0,
        "executed": 0,
        "contacts_created": 0,
        "accounts_created": 0,
        "errors": 0,
    }

    cursor = src.find({})
    if limit:
        cursor = cursor.limit(limit)

    for extraction in cursor:
        stats["scanned"] += 1
        email_id = str(extraction.get("email_id") or extraction.get("_id"))
        if email_id in seen:
            stats["skipped_seen"] += 1
            continue

        if dry_run:
            stats["processed"] += 1
            seen.add(email_id)
            continue

        try:
            contact = extraction.get("contact") or {}
            account = extraction.get("account") or {}
            contact_email = contact.get("email")
            company = account.get("company_name") or contact.get("company_name")

            account_id = None
            if company:
                acct, created = crm_service.get_or_create_account(
                    company,
                    defaults={
                        "account_type": "client",
                        "metadata": {
                            "source": extractions_collection,
                            "country": account.get("country"),
                        },
                    },
                )
                account_id = acct["_id"]
                if created:
                    stats["accounts_created"] += 1

            contact_id = None
            if contact_email:
                cont, created = crm_service.get_or_create_contact(
                    contact_email,
                    defaults={
                        "firstName": (contact.get("name") or "").split(" ")[0] or None,
                        "company": company,
                        "account_id": account_id,
                        "metadata": {"source": extractions_collection},
                    },
                )
                contact_id = cont["_id"]
                if created:
                    stats["contacts_created"] += 1

            if not contact_id and not account_id:
                # Nothing to attach to — skip rather than create an orphan activity.
                stats["skipped_seen"] += 1
                seen.add(email_id)
                continue

            link_type = "contact" if contact_id else "account"
            link_id = contact_id or account_id
            payload = _build_activity(extraction, contact_id, account_id)

            out = ai_engine.submit_decision(
                AGENT_NAME,
                decision=f"attach {extraction.get('email_type', 'email')} to {link_type}",
                recommended_action="Attach classified email to CRM record",
                action_type="log_activity",
                action_payload=payload,
                confidence=extraction.get("confidence"),
                reason=f"Classified as {extraction.get('email_type', 'unknown')}",
                autonomy_mode=autonomy_mode,
                risk="low",
                linked_object_type=link_type,
                linked_object_id=link_id,
                input_summary={"email_id": email_id, "email_type": extraction.get("email_type")},
            )
            stats["processed"] += 1
            if out.get("executed"):
                stats["executed"] += 1
            if out.get("queued"):
                stats["queued"] += 1
            seen.add(email_id)
        except Exception as e:  # one bad extraction shouldn't abort the run
            stats["errors"] += 1
            print(f"  ⚠️ error on email_id={email_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Attach classified old emails to the CRM spine.")
    parser.add_argument("--mode", default="approve", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--extractions-db", default=DEFAULT_EXTRACTIONS_DB)
    parser.add_argument("--extractions-collection", default=DEFAULT_EXTRACTIONS_COLLECTION)
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode,
        limit=args.limit,
        dry_run=not args.execute,
        extractions_db=args.extractions_db,
        extractions_collection=args.extractions_collection,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Old mail classifier [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
