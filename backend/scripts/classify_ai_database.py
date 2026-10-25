"""Segregate the AI Database: potential clients / clients / vendors / shared mailboxes / not relevant.

    venv/bin/python scripts/classify_ai_database.py                 # dry run, rules only
    venv/bin/python scripts/classify_ai_database.py --with-model    # dry run, rules then the ladder
    venv/bin/python scripts/classify_ai_database.py --apply [--with-model] [--limit N]

Rules first (leads.party_type); --with-model sends what the rules leave open up
the ladder (Qwen in the 22:00-07:00 window, then Haiku/Sonnet when the account
has credit). --apply needs a mongodump < 3 h old and writes, per record:
  party_type / party_type_how / party_type_tier / party_type_at   (every record)
  vendor        -> copied to Vendor > Leads + transferred_to_vendor_leads (same as
                   scripts/move_vendor_leads.py; clearing the flag puts it back)
  role_mailbox  -> address added to the suppression list (never mailed)
Nothing is deleted. Re-running skips records that already have party_type
(use --redo to reconsider "unclear" ones).
"""
import argparse
import glob
import os
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def backup_age_hours(d="/var/www/campaign_platform/backups") -> float:
    dumps = sorted(glob.glob(os.path.join(d, "*", "full.archive.gz")))
    return (time.time() - os.path.getmtime(dumps[-1])) / 3600 if dumps else float("inf")


# For prospects, only companies whose product is sold to us count as vendors by
# domain: someone working at Google, Microsoft or a bank is a potential research
# buyer, even though mail FROM those domains is service mail (move_vendor_leads).
VENDOR_TOOL_DOMAINS = {
    "apollo.io", "zoominfo.com", "lusha.com", "snov.io", "hunter.io", "skrapp.io", "seamless.ai", "rocketreach.co",
    "clearbit.com", "uplead.com", "cognism.com", "mailchimp.com", "sendinblue.com", "brevo.com", "sendgrid.net",
    "mailgun.com", "lemlist.com", "instantly.ai", "smartlead.ai", "woodpecker.co", "reply.io",
}


def build_ctx(gd):
    ea, fin = gd("email_automation"), gd("finance_db")
    ctx = {"client_domains": set(), "vendor_domains": set(), "service_domains": set(VENDOR_TOOL_DOMAINS),
           "client_emails": set(), "vendor_emails": set()}
    for r in ea["party_relationships"].find({}, {"key": 1, "relationship": 1}):
        k = (r.get("key") or "").strip().lower()
        rel = (r.get("relationship") or "").lower()
        bucket = "client" if rel in ("client", "both") else "vendor" if rel == "vendor" else None
        if bucket and k:
            ctx[f"{bucket}_{'emails' if '@' in k else 'domains'}"].add(k)
    for v in fin["vendors"].find({}, {"email": 1}):
        e = (v.get("email") or "").lower()
        if "@" in e:
            ctx["vendor_domains"].add(e.rsplit("@", 1)[1])
    for v in ea["vendor_leads"].find({}, {"email": 1, "website": 1}):
        e = (v.get("email") or "").lower()
        if e:
            ctx["vendor_emails"].add(e)
    for c in fin["customers"].find({"is_deleted": {"$ne": True}, "email": {"$type": "string"}}, {"email": 1}):
        e = c["email"].lower()
        if "@" in e:
            ctx["client_domains"].add(e.rsplit("@", 1)[1])
    free = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "rediffmail.com"}
    for k in ("client_domains", "vendor_domains"):
        ctx[k] -= free
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--with-model", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    if a.apply and backup_age_hours() > 3:
        sys.exit("refusing to apply: newest mongodump is older than 3 h")
    from database import get_database as gd
    from leads import party_type
    from leads.service import lead_view_clause
    from scripts.move_vendor_leads import vendor_lead_doc
    model = None
    if a.with_model:
        from platform_core import ladder
        model = ladder.run
    ctx = build_ctx(gd)
    ea = gd("email_automation")
    le = ea["leads_enriched"]
    q = {"transferred_to_vendor_leads": {"$ne": True}, "superseded_by": {"$exists": False},
         "$and": [lead_view_clause("ai_database")]}
    if not a.redo:
        q["party_type"] = {"$exists": False}
    else:
        q["$or"] = [{"party_type": {"$exists": False}}, {"party_type": "unclear"}]
    now = datetime.utcnow()
    counts, how, tiers, samples = Counter(), Counter(), Counter(), {}
    cur = le.find(q, {"email": 1, "company_name": 1, "company": 1, "company_domain": 1, "company_industry": 1,
                      "company_website": 1, "company_description": 1, "title": 1, "outreach_bucket": 1, "first_name": 1,
                      "last_name": 1, "name": 1, "phone": 1, "linkedin_url": 1, "location": 1, "seniority_level": 1,
                      "department": 1, "mail_pool": 1})
    if a.limit:
        cur = cur.limit(a.limit)
    for rec in cur:
        r = party_type.classify(rec, ctx, model, ref={"collection": "email_automation.leads_enriched", "id": str(rec["_id"])})
        if r["label"] is None:
            counts["deferred"] += 1
            continue
        counts[r["label"]] += 1
        how[f"{r['label']}: {r['how'][:60]}"] += 1
        tiers[r.get("tier") or "-"] += 1
        samples.setdefault(r["label"], [])
        if len(samples[r["label"]]) < 8:
            samples[r["label"]].append(f"{(rec.get('company_name') or '-')[:35]:35} | {(rec.get('company_industry') or '-')[:30]:30} | {r['how'][:70]}")
        if not a.apply:
            continue
        upd = {"party_type": r["label"], "party_type_how": r["how"], "party_type_tier": r.get("tier"), "party_type_at": now}
        if r["label"] == "vendor":
            vid = ea["vendor_leads"].insert_one(vendor_lead_doc(rec, "party_type " + r["how"][:40], now)).inserted_id
            upd.update(transferred_to_vendor_leads=True, transferred_at=now, vendor_lead_id=str(vid),
                       vendor_move_reason="party_type: " + r["how"][:60])
        if r["label"] == "role_mailbox" and rec.get("email"):
            try:
                from messaging import suppression
                suppression.suppress(rec["email"], "role_mailbox", source="classify_ai_database")
            except Exception as e:
                upd["party_type_suppress_error"] = str(e)[:120]
        le.update_one({"_id": rec["_id"]}, {"$set": upd})
    print(f"{'APPLIED' if a.apply else 'DRY RUN'} ({'rules + ladder' if model else 'rules only'})")
    for k, v in counts.most_common():
        print(f"  {k:18} {v:,}")
    print("by tier:", dict(tiers))
    print("top reasons:")
    for k, v in how.most_common(14):
        print(f"  {v:6,}  {k}")
    for lab, ss in samples.items():
        print(f"-- {lab}")
        for s in ss:
            print("   ", s)
    if a.apply:
        ea["backfill_runs"].insert_one({"step": "classify_ai_database", "at": now, "counts": dict(counts), "tiers": dict(tiers)})


if __name__ == "__main__":
    main()
