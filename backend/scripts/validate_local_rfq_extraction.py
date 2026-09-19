"""
LOCAL RFQ EXTRACTION VALIDATION -- go/no-go check before enabling local Qwen
for sales/mail_pool_ai.py against live mail.
=============================================================================

Per the standing governance rule (docs/AI_MIGRATION_STATUS.md, adopted after
the bucket_classifier incident): "No local SLM workload may be promoted to
production merely because synthetic tests pass. Production acceptance
requires representative real-data validation, and for any workload capable
of changing CRM/business state, an independent correctness/sanity check
must exist outside the model's own self-reported confidence."

This script is that check for mail_pool_ai's RFQ extraction specifically.
It is READ-ONLY: it re-runs sales.mail_pool_ai.analyze_sender() (a pure
function -- no DB writes of its own) against real senders who already have
a real, human-relied-upon Opportunity on the CRM spine from the OLD
Bedrock-based extraction, and prints the new local-model proposal next to
the historical Bedrock-extracted fields for a human to judge.

It does NOT touch the review queue, does NOT call crm_service.create_rfq(),
and does NOT modify any email/sender/opportunity document. Nothing here
gates production on its own -- the review queue (sales/rfq_review_queue.py)
is the permanent per-item safety net; this is a one-time "is the model even
worth pointing at this task" sanity check.

Run on the VM (needs the real local model + real Mongo), from backend/:
    python scripts/validate_local_rfq_extraction.py --sample 20
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fetch_reference_opportunities(limit: int):
    from database import get_db_manager

    dbm = get_db_manager()
    opportunities = dbm.client["crm_db"]["opportunities"]
    return list(opportunities.find(
        {"metadata.source": "mail_pool_ai", "metadata.rfq": {"$exists": True}},
        {"metadata.rfq": 1, "contact_id": 1, "title": 1, "created_at": 1},
    ).sort("created_at", -1).limit(limit))


def _sender_email_for_contact(contact_id):
    if not contact_id:
        return None
    from app.services import crm_service
    contact = crm_service.get("contacts", contact_id)
    return (contact or {}).get("email")


def _fetch_sample_emails(from_email: str, limit: int):
    from sales.mail_pool_ai import MAIL_DB, MAIL_COLLECTION, MAX_SAMPLE_EMAILS_PER_SENDER, _get_db

    col = _get_db(MAIL_DB)[MAIL_COLLECTION]
    docs = list(col.find({"from_email": from_email})
                .sort("date", -1).limit(limit or MAX_SAMPLE_EMAILS_PER_SENDER))
    total = col.count_documents({"from_email": from_email})
    return docs, total


def _print_comparison(reference: dict, proposal: dict, from_email: str):
    ref_rfq = (reference.get("metadata") or {}).get("rfq") or {}
    fields = ["title", "budget", "currency", "description", "methodology",
             "loi", "ir", "sample_size", "country", "study_type",
             "target_audience", "timeline"]
    print(f"\n{'=' * 70}")
    print(f"Sender: {from_email}")
    print(f"Historical opportunity: {reference.get('title')} ({reference.get('_id')})")
    if proposal is None:
        print("  Local model proposal: NONE (analyze_sender returned no result "
              "-- treat as a failure for this sender, not a match)")
        return
    proposal_rfq = proposal.get("rfq") or {}
    print(f"  {'field':<18} {'historical (Bedrock)':<30} {'proposed (local Qwen)'}")
    for f in fields:
        print(f"  {f:<18} {str(ref_rfq.get(f))[:28]:<30} {str(proposal_rfq.get(f))[:40]}")
    print(f"  is_rfq detected: {proposal_rfq.get('is_rfq')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=20,
                       help="Number of historical RFQ opportunities to re-check")
    args = parser.parse_args()

    from sales.mail_pool_ai import analyze_sender

    references = _fetch_reference_opportunities(args.sample)
    print(f"Found {len(references)} historical mail_pool_ai RFQ opportunities to compare against.")

    checked = failed = 0
    for ref in references:
        contact_id = ref.get("contact_id")
        from_email = _sender_email_for_contact(contact_id)
        if not from_email:
            continue
        sample_docs, total_count = _fetch_sample_emails(from_email, limit=None)
        if not sample_docs:
            continue
        checked += 1
        newest = sample_docs[0]
        try:
            proposal = analyze_sender(from_email, newest.get("from_name") or "",
                                      total_count, sample_docs)
        except Exception as e:
            print(f"\n{'=' * 70}\nSender: {from_email}\n  ERROR calling local model: {e}")
            failed += 1
            continue
        if proposal is None:
            failed += 1
        _print_comparison(ref, proposal, from_email)

    print(f"\n{'=' * 70}")
    print(f"Checked {checked} senders, {failed} produced no usable proposal "
          f"(timeout, malformed JSON, or transport failure).")
    print("This is a manual go/no-go read, not an automated pass/fail -- "
          "eyeball the field-by-field comparisons above before enabling "
          "the pipeline against live mail.")


if __name__ == "__main__":
    main()
