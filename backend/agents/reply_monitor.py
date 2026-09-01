"""
REPLY MONITOR AGENT  (Phase 5 — cold-outreach reply monitoring)

Watches inbound outreach replies, drafts a suggested response, and routes it
through the AI decision engine as an APPROVAL-GATED review task. It never sends
email — the human reviews the draft (carried on the task) and sends it.

Flow (mirrors old_mail_classifier / follow_up_agent):
  reply source collection
    -> match/create canonical Contact (by email) [+ Account by company]
    -> draft a response (templated here; pluggable LLM hook)
    -> ai_engine.submit_decision(action_type="create_task", risk="medium")
       -> approve mode parks it pending; on approval a "review & send" task is
          created carrying the draft. risk="medium" so autopilot never
          auto-acts on a drafted reply.

Idempotent: replies already handled (tracked via logged ai_decisions
input_summary.reply_id) are skipped.

Usage:
    python -m backend.agents.reply_monitor --dry-run
    python -m backend.agents.reply_monitor --mode approve --execute --limit 100
"""

import argparse
from typing import Optional, Dict, Any

from app.services import crm_service, ai_engine
from database import get_database

AGENT_NAME = "reply_monitor"
DEFAULT_SOURCE_DB = "email_automation"
DEFAULT_REPLIES_COLLECTION = "outreach_replies"


def _already_handled() -> set:
    seen = set()
    for d in crm_service._col("ai_decisions").find(
        {"agent_name": AGENT_NAME}, {"input_summary.reply_id": 1}
    ):
        rid = (d.get("input_summary") or {}).get("reply_id")
        if rid:
            seen.add(rid)
    return seen


def _draft_reply(reply: Dict[str, Any], first_name: Optional[str]) -> str:
    """
    Produce a suggested response. Templated and deterministic for now; this is
    the single hook to swap in an LLM draft (e.g. Anthropic) later — keep the
    signature stable so the approval gate and tests are unaffected.
    """
    subject = reply.get("subject") or "your message"
    greeting = f"Hi {first_name}," if first_name else "Hi there,"
    return (
        f"{greeting}\n\n"
        f"Thanks for getting back to me regarding \"{subject}\". "
        f"I'd be glad to share more detail and find a time that works for you. "
        f"Are you available for a short call this week?\n\n"
        f"Best regards"
    )


def run(
    autonomy_mode: str = "approve",
    limit: Optional[int] = None,
    dry_run: bool = False,
    source_db: str = DEFAULT_SOURCE_DB,
    replies_collection: str = DEFAULT_REPLIES_COLLECTION,
) -> Dict[str, Any]:
    """Draft approval-gated responses for inbound replies. Returns stats."""
    src = get_database(source_db)[replies_collection]
    seen = _already_handled()

    stats = {
        "agent": AGENT_NAME,
        "mode": autonomy_mode,
        "dry_run": dry_run,
        "scanned": 0,
        "skipped_seen": 0,
        "skipped_no_sender": 0,
        "processed": 0,
        "queued": 0,
        "executed": 0,
        "contacts_created": 0,
        "errors": 0,
    }

    cursor = src.find({})
    if limit:
        cursor = cursor.limit(limit)

    for reply in cursor:
        stats["scanned"] += 1
        reply_id = str(reply.get("reply_id") or reply.get("_id"))
        if reply_id in seen:
            stats["skipped_seen"] += 1
            continue

        from_email = reply.get("from_email") or reply.get("from") or reply.get("email")
        if not from_email:
            stats["skipped_no_sender"] += 1
            seen.add(reply_id)
            continue

        if dry_run:
            stats["processed"] += 1
            seen.add(reply_id)
            continue

        try:
            company = reply.get("company") or reply.get("company_name")
            account_id = None
            if company:
                account, _created = crm_service.get_or_create_account(
                    company, defaults={"account_type": "client", "metadata": {"source": replies_collection}}
                )
                account_id = account["_id"]

            contact, created = crm_service.get_or_create_contact(
                from_email,
                defaults={
                    "firstName": (reply.get("from_name") or "").split(" ")[0] or None,
                    "company": company,
                    "account_id": account_id,
                    "metadata": {"source": replies_collection},
                },
            )
            if created:
                stats["contacts_created"] += 1

            draft = _draft_reply(reply, contact.get("firstName"))
            out = ai_engine.submit_decision(
                AGENT_NAME,
                decision=f"Draft reply to {from_email}",
                recommended_action=f"Review & send reply to {from_email}",
                action_type="create_task",
                action_payload={
                    "title": f"Review & send reply to {from_email}",
                    "status": "pending",
                    "priority": 2,
                    "linked_object_type": "contact",
                    "linked_object_id": contact["_id"],
                    "metadata": {
                        "agent": AGENT_NAME,
                        "source": "ai",
                        "reply_id": reply_id,
                        "subject": reply.get("subject"),
                        "draft": draft,
                    },
                },
                reason="Inbound reply awaiting a response",
                autonomy_mode=autonomy_mode,
                risk="medium",  # drafts are never auto-sent, even on autopilot
                linked_object_type="contact",
                linked_object_id=contact["_id"],
                input_summary={"reply_id": reply_id, "from_email": from_email},
            )
            stats["processed"] += 1
            if out.get("queued"):
                stats["queued"] += 1
            if out.get("executed"):
                stats["executed"] += 1
            seen.add(reply_id)
        except Exception as e:  # one bad reply shouldn't abort the run
            stats["errors"] += 1
            print(f"  ⚠️ error on reply_id={reply_id}: {e}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Draft approval-gated replies for inbound outreach replies.")
    parser.add_argument("--mode", default="approve", choices=["observe", "recommend", "approve", "autopilot"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Write changes (default is dry-run).")
    parser.add_argument("--source-db", default=DEFAULT_SOURCE_DB)
    parser.add_argument("--replies-collection", default=DEFAULT_REPLIES_COLLECTION)
    args = parser.parse_args()

    stats = run(
        autonomy_mode=args.mode,
        limit=args.limit,
        dry_run=not args.execute,
        source_db=args.source_db,
        replies_collection=args.replies_collection,
    )
    mode = "DRY RUN" if stats["dry_run"] else "EXECUTED"
    print(f"\n=== Reply monitor [{mode}] ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
