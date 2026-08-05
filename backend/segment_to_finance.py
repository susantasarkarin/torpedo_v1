"""
One-off pipeline: classified-email segments (vendor/client) -> finance_db
vendor/customer records with an AI-generated summary, deduped by email.

Usage on the VM (run from backend/ so relative imports resolve):
    python3 segment_to_finance.py --segment vendor --dry-run
    python3 segment_to_finance.py --segment vendor --apply
    python3 segment_to_finance.py --segment client --dry-run
    python3 segment_to_finance.py --segment client --apply
"""
import sys
import os
import re
import argparse
import asyncio
from collections import Counter
from datetime import datetime

sys.path.insert(0, '.')

from pymongo import MongoClient

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo = MongoClient(MONGO_URI)

gmail_db = mongo['torpedo_gmail']
email_metadata = gmail_db['email_metadata']

FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "mail.com", "protonmail.com",
    "zoho.com", "yandex.com", "gmx.com", "rediffmail.com", "googlemail.com",
}

OWN_DOMAINS = {"surveyfieldwork.com"}

SYSTEM_SENDER_PREFIXES = (
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@", "notification@",
    "alerts@", "alert@",
)


def is_system_sender(email: str) -> bool:
    e = email.lower()
    return any(e.startswith(p) for p in SYSTEM_SENDER_PREFIXES)


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def company_from_domain(domain: str) -> str:
    if not domain or domain in FREE_EMAIL_PROVIDERS:
        return ""
    return domain.split(".")[0].replace("-", " ").title()


def collect_contact_context(from_email: str, segment: str, limit: int = 15):
    """Pull recent emails for this contact for name/company inference + AI summary context."""
    docs = list(email_metadata.find(
        {"from_email": from_email, "ai_classification_status.segment": segment},
        {"subject": 1, "snippet": 1, "from_name": 1, "timestamp": 1, "direction": 1}
    ).sort("timestamp", -1).limit(limit))
    return docs


def best_name(docs, fallback_email: str) -> str:
    names = Counter((d.get("from_name") or "").strip() for d in docs if (d.get("from_name") or "").strip())
    if names:
        return names.most_common(1)[0][0]
    prefix = fallback_email.split("@")[0]
    return re.sub(r'[._]', ' ', prefix).title()


def sanitize_phone(raw: str) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw)
    if re.match(r'^\+?[0-9]{7,15}$', cleaned):
        return cleaned
    return ""


async def generate_ai_summary(gateway, contact_name: str, company: str, docs, segment: str) -> str:
    subjects = [d.get("subject") or "" for d in docs if d.get("subject")]
    subjects_block = "\n".join(f"- {s}" for s in subjects[:12])
    prompt = f"""You are summarizing a business {segment} relationship for a CRM record, based on real email subject lines with this contact.

Contact: {contact_name}{f' ({company})' if company else ''}
Recent email subjects with this contact:
{subjects_block or '(no subjects available)'}

Write a concise 2-3 sentence summary of what this {segment} relationship is about (what they do, what kind of work/requests are exchanged). Do not invent facts not supported by the subjects. No preamble, just the summary text."""
    try:
        return gateway.generate(prompt, max_tokens=200, task_type=f"{segment}_summary")
    except Exception as e:
        return f"(AI summary generation failed: {e})"


async def run(segment: str, dry_run: bool):
    assert segment in ("vendor", "client")

    from routers.finance import create_vendor, create_customer, vendors_collection, customers_collection
    from ai_governance.claude_gateway import get_claude_gateway

    target_collection = vendors_collection if segment == "vendor" else customers_collection
    create_fn = create_vendor if segment == "vendor" else create_customer

    unique_emails = [
        e for e in email_metadata.distinct("from_email", {"ai_classification_status.segment": segment})
        if e and domain_of(e) not in OWN_DOMAINS and not is_system_sender(e)
    ]
    print(f"=== segment={segment}  unique contacts (after filtering own-domain/system senders): {len(unique_emails)} ===")

    gateway = get_claude_gateway() if not dry_run else None

    created, skipped_existing, skipped_no_name = 0, 0, 0

    for email in sorted(unique_emails):
        existing = target_collection.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        if existing:
            skipped_existing += 1
            print(f"[skip-existing] {email} -> already a {segment} record ({existing['_id']})")
            continue

        docs = collect_contact_context(email, segment)
        name = best_name(docs, email)
        if not name:
            skipped_no_name += 1
            print(f"[skip-no-name] {email}")
            continue

        domain = domain_of(email)
        company = company_from_domain(domain)
        display_name = f"{name} ({company})" if company else name

        if dry_run:
            print(f"[would-create] {segment}: name={display_name!r} email={email} "
                  f"email_count_seen={len(docs)}")
            continue

        summary = await generate_ai_summary(gateway, name, company, docs, segment)

        payload = {
            "name": display_name,
            "email": email,
            "phone": "",
            "notes": f"Auto-created from {segment} email segregation on {datetime.utcnow().date().isoformat()}.",
            "ai_summary": summary,
            "gst_treatment": "unregistered",
            "status": "active",
            "source": "mail_segregation_auto_import",
        }

        result = await create_fn(payload)
        new_id = result.get("_id")
        created += 1
        print(f"[created] {segment} {new_id}: {display_name} <{email}> — summary: {summary[:100]}")

    print()
    print(f"=== DONE segment={segment} dry_run={dry_run} ===")
    print(f"created={created} skipped_existing={skipped_existing} skipped_no_name={skipped_no_name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", required=True, choices=["vendor", "client"])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    asyncio.run(run(args.segment, dry_run=args.dry_run))
