"""
One-off pipeline extending segment_to_finance.py:

1. Any contact (vendor OR client segment, sent+received) who has a genuine
   two-way email thread (we sent, they replied) -> email_automation.leads_enriched
   record (the "AI Database" / Client > Leads view), AI-classified via the
   existing leads.ai_classifier pipeline, with an AI conversation summary.

2. Any contact who sent an RFQ (any status, not just won) -> full
   finance_db.customers record (a "Client"), linked back to their
   leads_enriched doc if one exists.

3. All vendor-segment contacts (regardless of engagement) -> finance_db.vendors
   (re-verifies/fills gaps on top of the earlier run).

4. Fills missing fields (title, phone, industry, company_size, etc.) on both
   new and previously-created vendor/customer records via signature-regex +
   AI company enrichment, reusing leads.ai_classifier helpers.

Usage (from backend/):
    python3 crm_promote.py --step leads --dry-run
    python3 crm_promote.py --step leads --apply
    python3 crm_promote.py --step rfq-clients --dry-run
    python3 crm_promote.py --step rfq-clients --apply
    python3 crm_promote.py --step vendors --dry-run
    python3 crm_promote.py --step vendors --apply
    python3 crm_promote.py --step fill-gaps --apply
"""
import sys
import os
import re
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, '.')

from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo = MongoClient(MONGO_URI)

gmail_db = mongo['torpedo_gmail']
email_metadata = gmail_db['email_metadata']
automation_db = mongo['email_automation']
leads_raw_coll = automation_db['leads_raw']
leads_enriched_coll = automation_db['leads_enriched']
rfqs_coll = automation_db['rfqs']

OWN_DOMAINS = {"surveyfieldwork.com"}
FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "mail.com", "protonmail.com",
    "zoho.com", "yandex.com", "gmx.com", "rediffmail.com", "googlemail.com",
}
SYSTEM_SENDER_PREFIXES = ("noreply@", "no-reply@", "donotreply@", "do-not-reply@", "notification@", "alerts@", "alert@")


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


def company_from_domain(domain: str) -> str:
    if not domain or domain in FREE_EMAIL_PROVIDERS:
        return ""
    return domain.split(".")[0].replace("-", " ").title()


def is_system_sender(email: str) -> bool:
    e = email.lower()
    return any(e.startswith(p) for p in SYSTEM_SENDER_PREFIXES)


def sanitize_phone(raw: str) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw)
    return cleaned if re.match(r'^\+?[0-9]{7,15}$', cleaned) else ""


# ============================================================
# STEP 1: reply-based leads_enriched promotion
# ============================================================

def find_repliers(segments=("vendor", "client")):
    """Contacts with a genuine two-way thread: we sent + they replied, same gmail_thread_id.
    Single aggregation pipeline instead of per-thread queries (was too slow at 354k docs)."""
    pipeline = [
        {"$match": {"gmail_thread_id": {"$ne": None, "$exists": True}}},
        {"$group": {
            "_id": "$gmail_thread_id",
            "directions": {"$addToSet": "$direction"},
            "inbound_senders": {"$addToSet": {
                "$cond": [
                    {"$and": [
                        {"$eq": ["$direction", "inbound"]},
                        {"$in": ["$ai_classification_status.segment", list(segments)]},
                    ]},
                    "$from_email", None
                ]
            }},
        }},
        {"$match": {"directions": {"$all": ["inbound", "outbound"]}}},
        {"$project": {"inbound_senders": {
            "$filter": {"input": "$inbound_senders", "cond": {"$ne": ["$$this", None]}}
        }}},
    ]
    contacts = set()
    for row in email_metadata.aggregate(pipeline, allowDiskUse=True):
        for fe in row.get("inbound_senders", []):
            fe = (fe or "").lower()
            if fe and domain_of(fe) not in OWN_DOMAINS and not is_system_sender(fe):
                contacts.add(fe)
    return contacts


async def promote_repliers_to_leads(dry_run: bool):
    from leads.ai_classifier import classify_lead
    from leads.models import LeadRaw
    from ai_governance.claude_gateway import get_claude_gateway

    contacts = find_repliers()
    print(f"=== repliers found (vendor+client, genuine two-way threads): {len(contacts)} ===")

    gateway = None if dry_run else get_claude_gateway()
    created, updated, skipped = 0, 0, 0

    for email in sorted(contacts):
        existing = leads_enriched_coll.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        if existing:
            skipped += 1
            print(f"[skip-existing-lead] {email}")
            continue

        docs = list(email_metadata.find(
            {"$or": [{"from_email": email}, {"to_emails": email}]},
        ).sort("timestamp", -1).limit(20))

        names = Counter((d.get("from_name") or "").strip() for d in docs
                         if (d.get("from_email") or "").lower() == email and (d.get("from_name") or "").strip())
        name = names.most_common(1)[0][0] if names else re.sub(r'[._]', ' ', email.split("@")[0]).title()
        parts = name.split(" ", 1)
        first_name, last_name = parts[0], (parts[1] if len(parts) > 1 else "")

        domain = domain_of(email)
        company = company_from_domain(domain)
        subjects = [d.get("subject") or "" for d in docs if d.get("subject")]
        snippet = " | ".join(subjects[:8])

        if dry_run:
            print(f"[would-create-lead] {name} <{email}> company={company!r} threads_seen={len(docs)}")
            continue

        placeholder_url = f"mailto:{email}"
        lead_raw_doc = {
            "name": name, "title": "", "linkedin_url": placeholder_url,
            "snippet": snippet, "source": "gmail_reply",
            "first_name": first_name, "last_name": last_name, "email": email,
            "company_name": company, "company_domain": domain,
            "created_at": datetime.utcnow(), "classification_status": "Pending",
            "classification_attempts": 0,
        }
        # A leads_raw doc may already exist for this contact (orphaned from an
        # earlier pipeline) — linkedin_url has a unique index, so upsert instead
        # of a blind insert.
        leads_raw_coll.update_one(
            {"linkedin_url": placeholder_url},
            {"$setOnInsert": lead_raw_doc},
            upsert=True,
        )
        raw_doc = leads_raw_coll.find_one({"linkedin_url": placeholder_url})
        raw_id = str(raw_doc["_id"])

        lead_for_classify = LeadRaw(
            name=name, title="", linkedin_url=f"mailto:{email}", snippet=snippet,
            source="gmail_reply", first_name=first_name, last_name=last_name,
            email=email, company_name=company, company_domain=domain,
        )
        classification, _log = classify_lead(lead_for_classify, source="crm_promote")

        conv_prompt = (f"Summarize this email relationship for a CRM lead record based on real subject lines.\n"
                        f"Contact: {name}{f' ({company})' if company else ''}\nSubjects:\n" +
                        "\n".join(f"- {s}" for s in subjects[:10]) +
                        "\n\nWrite 2-3 concise sentences. No preamble.")
        try:
            conv_summary = gateway.generate(conv_prompt, max_tokens=180, task_type="lead_conversation_summary")
        except Exception as e:
            conv_summary = f"(summary generation failed: {e})"

        email_threads = [{
            "message_id": str(d.get("gmail_message_id", d.get("_id"))),
            "thread_id": d.get("gmail_thread_id"),
            "subject": d.get("subject") or "",
            "body_preview": (d.get("snippet") or "")[:200],
            "direction": "sent" if d.get("direction") == "outbound" else "received",
            "from_email": d.get("from_email") or "",
            "to_emails": d.get("to_emails") or [],
            "date": d.get("timestamp") or datetime.utcnow(),
            "segment": (d.get("ai_classification_status") or {}).get("segment", "others"),
        } for d in docs]

        enriched_doc = {
            "raw_lead_id": raw_id,
            "name": name, "first_name": first_name, "last_name": last_name,
            "email": email, "email_status": "Delivered", "title": "",
            "location": None, "phone": None,
            "added_on": datetime.utcnow(), "source": "outreach_reply", "snippet": snippet,
            "seniority_level": "Unknown", "buying_role": "Unknown", "department": "Other",
            "persona": "Practitioner", "gender": "Unknown", "company_size": "SMB", "region": "Other",
            "confidence_score": 0.5,
            "company_name": company, "company_domain": domain,
            "linkedin_url": f"mailto:{email}",  # unique placeholder; leads_enriched.linkedin_url has a unique index
            "email_threads": email_threads,
            "seen_in_inboxes": list({d.get("mailbox_id") for d in docs if d.get("mailbox_id")}),
            "email_message_ids": [t["message_id"] for t in email_threads],
            "last_email_date": docs[0].get("timestamp") if docs else None,
            "conversation_summary": conv_summary,
            "rfq_ids": [],
            "engagement_score": 40.0, "engagement_status": "replied_neutral",
            "classification_version": 1, "classified_at": datetime.utcnow(),
            "campaign_ids": [], "enriched_at": datetime.utcnow(),
            "enrichment_source": "bedrock_auto_import",
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        }
        if classification:
            enriched_doc.update({
                "title": classification.company_industry and enriched_doc["title"] or enriched_doc["title"],
                "seniority_level": classification.seniority_level.value,
                "buying_role": classification.buying_role.value,
                "department": classification.department.value,
                "persona": classification.persona.value,
                "gender": classification.gender.value,
                "company_size": classification.company_size.value,
                "region": classification.region.value,
                "confidence_score": classification.confidence_score,
                "location": classification.inferred_location,
                "company_industry": classification.company_industry,
                "company_employee_count": classification.company_employee_count,
                "company_website": classification.company_website,
                "company_headquarters": classification.company_headquarters,
            })

        leads_raw_coll.update_one({"_id": raw_doc["_id"]}, {"$set": {
            "classification_status": "Classified" if classification else "Failed",
            "enriched_lead_id": None,
        }})
        result = leads_enriched_coll.insert_one(enriched_doc)
        leads_raw_coll.update_one({"_id": raw_doc["_id"]}, {"$set": {"enriched_lead_id": str(result.inserted_id)}})

        created += 1
        print(f"[created-lead] {result.inserted_id}: {name} <{email}> conf={enriched_doc['confidence_score']}")

    print(f"\n=== DONE leads dry_run={dry_run}: created={created} skipped_existing={skipped} ===")


# ============================================================
# STEP 2: RFQ senders -> finance_db.customers ("Client")
# ============================================================

async def promote_rfq_senders_to_clients(dry_run: bool):
    from routers.finance import create_customer, customers_collection
    from ai_governance.claude_gateway import get_claude_gateway

    rfq_by_email = defaultdict(list)
    for r in rfqs_coll.find({}, {"contact_email": 1, "title": 1, "description": 1, "status": 1}):
        ce = (r.get("contact_email") or "").lower()
        if ce:
            rfq_by_email[ce].append(r)

    print(f"=== unique RFQ senders (any status): {len(rfq_by_email)} ===")
    gateway = None if dry_run else get_claude_gateway()
    created, skipped_existing, updated_leads = 0, 0, 0

    for email, rfqs in sorted(rfq_by_email.items()):
        existing = customers_collection.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        if existing:
            skipped_existing += 1
            print(f"[skip-existing-customer] {email} -> {existing['_id']}")
            continue

        domain = domain_of(email)
        company = company_from_domain(domain)
        lead_doc = leads_enriched_coll.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        name = (lead_doc.get("name") if lead_doc else "") or re.sub(r'[._]', ' ', email.split("@")[0]).title()
        display_name = f"{name} ({company})" if company else name

        if dry_run:
            print(f"[would-create-client] {display_name} <{email}> rfq_count={len(rfqs)} "
                  f"statuses={Counter(r.get('status') for r in rfqs)}")
            continue

        titles = "\n".join(f"- [{r.get('status')}] {r.get('title') or r.get('description') or ''}" for r in rfqs[:10])
        prompt = (f"Summarize this client relationship for a CRM record based on their RFQs.\n"
                  f"Client: {display_name}\nRFQs:\n{titles}\n\n"
                  f"Write 2-3 concise sentences about what this client requests. No preamble.")
        try:
            summary = gateway.generate(prompt, max_tokens=180, task_type="rfq_client_summary")
        except Exception as e:
            summary = f"(summary generation failed: {e})"

        payload = {
            "name": display_name, "email": email, "phone": "",
            "notes": f"Auto-created from RFQ history ({len(rfqs)} RFQ(s)) on {datetime.utcnow().date().isoformat()}.",
            "ai_summary": summary, "gst_treatment": "unregistered", "status": "active",
            "source": "rfq_auto_import",
        }
        result = await create_customer(payload)
        new_id = result.get("_id")
        created += 1
        print(f"[created-client] {new_id}: {display_name} <{email}>")

        if lead_doc:
            leads_enriched_coll.update_one(
                {"_id": lead_doc["_id"]},
                {"$set": {"promoted_to_client": True, "finance_customer_id": new_id,
                          "rfq_ids": [str(r["_id"]) for r in rfqs], "updated_at": datetime.utcnow()}}
            )
            updated_leads += 1

    print(f"\n=== DONE rfq-clients dry_run={dry_run}: created={created} "
          f"skipped_existing={skipped_existing} linked_to_lead={updated_leads} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True, choices=["leads", "rfq-clients"])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.step == "leads":
        asyncio.run(promote_repliers_to_leads(dry_run=args.dry_run))
    elif args.step == "rfq-clients":
        asyncio.run(promote_rfq_senders_to_clients(dry_run=args.dry_run))
