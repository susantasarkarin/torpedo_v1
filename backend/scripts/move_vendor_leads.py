"""
MOVE VENDORS OUT OF SALES > LEADS
=================================
Gmail-sourced leads are everyone who ever mailed us, so the Leads page holds
the companies that sell TO us — data tools (Apollo, ZoomInfo), banks, SaaS
billing, and agencies pitching their panel — next to real prospects. This
copies those into Vendor > Leads (`email_automation.vendor_leads`) and flags
the sales lead `transferred_to_vendor_leads`, which takes it off the Leads
page and out of outreach enrollment. Nothing is deleted; clearing the flag
puts a lead back.

A lead moves when:
  - its domain is a known tool / service / bank (SERVICE_DOMAINS), or
  - the mail it sent us was tagged vendor / bank / newsletter / automated by
    the per-message AI analysis and none of it was tagged client or prospect.

It never moves when its domain or address is in party_relationships as
client or both (MR firms that buy from us as well as sell to us), when a
person set its status by hand, or when it has no mail of its own to judge.

    python -m scripts.move_vendor_leads            # dry run
    python -m scripts.move_vendor_leads --apply
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

QUALIFIED_SOURCES = ["gmail", "gmail_contact", "gmail_calendar", "outreach_reply"]

# Companies whose mail to us is always them selling or servicing: lead data
# tools, CRM/email/SaaS platforms, hosting, payments, banks, job boards.
SERVICE_DOMAINS = {
    "apollo.io", "zoominfo.com", "lusha.com", "snov.io", "hunter.io", "skrapp.io",
    "seamless.ai", "rocketreach.co", "clearbit.com", "uplead.com", "cognism.com",
    "hubspot.com", "salesforce.com", "zoho.com", "zohocorp.com", "zohoone.com",
    "zohoflow.com", "freshworks.com", "pipedrive.com", "mailchimp.com",
    "sendinblue.com", "brevo.com", "sendgrid.net", "mailgun.com", "lemlist.com",
    "instantly.ai", "smartlead.ai", "woodpecker.co", "reply.io",
    "linkedin.com", "google.com", "microsoft.com", "amazon.com", "amazonaws.com",
    "godaddy.com", "hostinger.com", "digitalocean.com", "cloudflare.com",
    "namecheap.com", "canva.com", "slack.com", "zoom.us", "atlassian.com",
    "notion.so", "cursor.com", "openai.com", "substack.com", "medium.com",
    "razorpay.com", "paypal.com", "stripe.com", "payoneer.com", "wise.com",
    "axisbank.com", "axisbankmail.com", "axis.bank.in", "hdfcbank.com",
    "hdfcbank.net", "icicibank.com", "sbi.co.in", "kotak.com",
    "indeed.com", "naukri.com", "upwork.com", "fiverr.com", "goindigo.in",
}

VENDOR_TYPES = {"vendor", "bank", "newsletter", "automated"}
BUYER_TYPES = {"client", "prospect"}


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in (email or "") else ""


def _matches(domain: str, names: Iterable[str]) -> Optional[str]:
    """The listed name this domain is, or is a subdomain of."""
    for name in names:
        if domain == name or domain.endswith("." + name):
            return name
    return None


def vendor_verdict(lead: Dict, sender_types: List[str],
                   protected: Dict[str, str]) -> Tuple[bool, str]:
    """(move?, reason). `sender_types` are the AI tags on mail the lead sent us."""
    email = (lead.get("email") or "").strip().lower()
    domain = _domain(email)
    if not domain:
        return False, "no_email"
    rel = protected.get(email) or protected.get(_matches(domain, protected) or "")
    if rel in ("client", "both"):
        return False, f"relationship_{rel}"
    if lead.get("lead_status_source") == "human":
        return False, "status_set_by_person"
    if _matches(domain, SERVICE_DOMAINS):
        return True, "service_domain"
    if rel == "vendor":
        return True, "relationship_vendor"
    tags = [t for t in sender_types if t]
    if not tags:
        return False, "no_mail_from_them"
    if any(t in BUYER_TYPES for t in tags):
        return False, "has_buyer_mail"
    if any(t in VENDOR_TYPES for t in tags):
        return True, "vendor_mail_only"
    return False, "unclear"


def vendor_lead_doc(lead: Dict, reason: str, now: datetime) -> Dict:
    """Same field mapping as POST /vendor-leads/transfer-from-ai-database."""
    s = lambda v: (v or "").strip() if isinstance(v, str) else ""
    return {
        "name": s(lead.get("name")) or f"{s(lead.get('first_name'))} {s(lead.get('last_name'))}".strip() or "Unknown",
        "first_name": s(lead.get("first_name")),
        "last_name": s(lead.get("last_name")),
        "email": s(lead.get("email")).lower(),
        "title": s(lead.get("title")),
        "company": s(lead.get("company_name")),
        "phone": s(lead.get("phone")),
        "linkedin_url": s(lead.get("linkedin_url")),
        "website": s(lead.get("company_website")) or s(lead.get("company_domain")),
        "industry": s(lead.get("company_industry")),
        "location": s(lead.get("location")),
        "seniority_level": lead.get("seniority_level"),
        "department": lead.get("department"),
        "status": "new",
        "notes": f"Moved from Sales > Leads on {now:%Y-%m-%d} ({reason.replace('_', ' ')})",
        "source": "sales_leads",
        "source_lead_id": str(lead["_id"]),
        "source_collection": "leads_enriched",
        "transferred_from_ai_database": True,
        "mail_pool": lead.get("mail_pool"),
        "created_at": now,
        "updated_at": now,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    client = MongoClient(MONGO_URI)
    ea = client["email_automation"]
    leads, vendors = ea["leads_enriched"], ea["vendor_leads"]
    mail = client["torpedo_gmail"]["email_metadata"]

    protected = {r["key"].strip().lower(): r.get("relationship")
                 for r in ea["party_relationships"].find({}, {"key": 1, "relationship": 1})
                 if r.get("key")}
    vendor_emails = {(v.get("email") or "").strip().lower(): v["_id"]
                     for v in vendors.find({}, {"email": 1})}

    query = {"$or": [{"source": {"$in": QUALIFIED_SOURCES}},
                     {"outreach_replied_at": {"$exists": True}}],
             "transferred_to_vendor_leads": {"$ne": True}}

    reasons, moved, samples = Counter(), 0, []
    now = datetime.utcnow()
    for lead in leads.find(query):
        email = (lead.get("email") or "").strip().lower()
        types = [((m.get("ai_analysis") or {}).get("sender_type") if isinstance(m.get("ai_analysis"), dict) else None)
                 for m in mail.find({"mail_counterparty": email}, {"from_email": 1, "ai_analysis.sender_type": 1}).limit(200)
                 if (m.get("from_email") or "").strip().lower() == email]
        move, reason = vendor_verdict(lead, types, protected)
        reasons[reason] += 1
        if not move:
            continue
        moved += 1
        if len(samples) < 25:
            samples.append(f"{email:45} {lead.get('company_name') or '-':25} {reason}  {Counter(t for t in types if t).most_common(3)}")
        if not args.apply:
            continue
        vendor_id = vendor_emails.get(email)
        if not vendor_id:
            vendor_id = vendors.insert_one(vendor_lead_doc(lead, reason, now)).inserted_id
            vendor_emails[email] = vendor_id
        leads.update_one({"_id": lead["_id"]}, {"$set": {
            "transferred_to_vendor_leads": True, "transferred_at": now,
            "vendor_lead_id": str(vendor_id), "vendor_move_reason": reason,
        }})

    for s in samples:
        print(s)
    print(f"\n{'MOVED' if args.apply else 'WOULD MOVE'} {moved:,} leads to Vendor > Leads")
    for r, n in reasons.most_common():
        print(f"  {r:24} {n:,}")
    if not args.apply:
        print("(dry run — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
