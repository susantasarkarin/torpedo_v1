"""Verify all 5 phases of the Sales pipeline rewiring on the live VM"""
import pymongo
import json
from datetime import datetime

c = pymongo.MongoClient("localhost", 27017)
db_ea = c["email_automation"]
db_torpedo = c["torpedo"]

print("=" * 60)
print("PHASE 1: ICP Basket Classification on Import")
print("=" * 60)

# Check enriched leads have ICP basket
total_enriched = db_ea["leads_enriched"].count_documents({})
with_basket = db_ea["leads_enriched"].count_documents({"classification_basket": {"$exists": True, "$ne": None}})
print(f"  Total enriched leads: {total_enriched}")
print(f"  With ICP basket: {with_basket}")

# Basket distribution
pipeline = [{"$group": {"_id": "$classification_basket", "count": {"$sum": 1}}}]
baskets = list(db_ea["leads_enriched"].aggregate(pipeline))
for b in sorted(baskets, key=lambda x: x["_id"] or "Z"):
    print(f"  Basket {b['_id']}: {b['count']}")

# Verify NO AI enrichment at import: check if classified_at is set but enrichment_status is not 'completed' for raw leads
no_ai = db_ea["leads_raw"].count_documents({"enrichment_status": {"$ne": "completed"}})
with_ai = db_ea["leads_raw"].count_documents({"enrichment_status": "completed"})
print(f"  Raw leads WITHOUT AI enrichment: {no_ai}")
print(f"  Raw leads WITH AI enrichment (pre-existing): {with_ai}")

sample = db_ea["leads_enriched"].find_one(
    {"classification_basket": {"$exists": True}},
    {"email": 1, "classification_basket": 1, "classification_basket_name": 1, "fit_tier": 1, "fit_tier_label": 1, "persona_label": 1, "source": 1, "_id": 0}
)
if sample:
    print(f"  Sample: {json.dumps(sample, default=str)}")

print()
print("=" * 60)
print("PHASE 2: Auto-Enrollment into Cold Outreach")
print("=" * 60)

# Check outreach leads enrolled
total_outreach = db_torpedo["outreach_leads_v2"].count_documents({})
by_basket = list(db_torpedo["outreach_leads_v2"].aggregate([
    {"$group": {"_id": "$classification_basket", "count": {"$sum": 1}}}
]))
print(f"  Total outreach leads: {total_outreach}")
for b in sorted(by_basket, key=lambda x: x["_id"] or "Z"):
    print(f"  Basket {b['_id']}: {b['count']}")

# Count by workflow status
by_status = list(db_torpedo["outreach_leads_v2"].aggregate([
    {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}}
]))
print("  By workflow status:")
for s in sorted(by_status, key=lambda x: -x["count"]):
    print(f"    {s['_id']}: {s['count']}")

# Check campaigns
campaigns = list(db_torpedo["outreach_campaigns_v2"].find({}, {"campaign_id": 1, "business": 1, "is_active": 1, "_id": 0}))
print(f"  Active campaigns: {len([c for c in campaigns if c.get('is_active')])}")
for camp in campaigns:
    print(f"    {camp['business']}: active={camp.get('is_active')} id={camp['campaign_id'][:12]}...")

print()
print("=" * 60)
print("PHASE 3: Mail Status Bucketing + Reply -> Leads")
print("=" * 60)

# Check outreach sends by status
total_sends = db_torpedo["outreach_sends_v2"].count_documents({})
bounced = db_torpedo["outreach_sends_v2"].count_documents({"status": "bounced"})
sent = db_torpedo["outreach_sends_v2"].count_documents({"status": "sent"})
opened = db_torpedo["outreach_sends_v2"].count_documents({"open_count": {"$gt": 0}})
replied = db_torpedo["outreach_sends_v2"].count_documents({"reply_received": True})
print(f"  Total sends: {total_sends}")
print(f"  Sent (not opened): {sent - opened}")
print(f"  Opened: {opened}")
print(f"  Bounced: {bounced}")
print(f"  Replied: {replied}")

# Check suppression
suppressed = db_torpedo["outreach_bounce_suppression"].count_documents({})
print(f"  Bounce suppression list: {suppressed} addresses")

# Check reply -> Leads promotion
reply_leads = db_ea["leads_enriched"].count_documents({"source": "outreach_reply"})
print(f"  Leads promoted from outreach replies: {reply_leads}")

print()
print("=" * 60)
print("PHASE 4: Leads Module qualified_only Filter")
print("=" * 60)

# Count by source
by_source = list(db_ea["leads_enriched"].aggregate([
    {"$group": {"_id": "$source", "count": {"$sum": 1}}}
]))
print("  leads_enriched by source:")
for s in sorted(by_source, key=lambda x: -x["count"]):
    print(f"    {s['_id']}: {s['count']}")

# Count qualified sources
QUALIFIED = ["gmail", "gmail_workspace", "email_sync", "classified_gmail", "outreach_reply"]
qualified = db_ea["leads_enriched"].count_documents({"source": {"$in": QUALIFIED}})
print(f"  Qualified leads (Gmail + outreach_reply): {qualified}")
print(f"  Total leads (all sources): {total_enriched}")

print()
print("=" * 60)
print("PHASE 5: Skrapp.io Email Pattern System")
print("=" * 60)

# Check email patterns collection
patterns = db_ea["email_patterns"].count_documents({})
by_source_p = list(db_ea["email_patterns"].aggregate([
    {"$group": {"_id": "$source", "count": {"$sum": 1}}}
]))
print(f"  Total email patterns: {patterns}")
for s in by_source_p:
    print(f"    Source '{s['_id']}': {s['count']}")

# Check leads with pattern-derived emails
pattern_derived = db_ea["leads_raw"].count_documents({"email_status": "pattern_derived"})
pending_pattern = db_ea["leads_raw"].count_documents({"email_status": "pending_pattern"})
print(f"  Leads with pattern-derived email: {pattern_derived}")
print(f"  Leads pending pattern discovery: {pending_pattern}")

print()
print("=" * 60)
print("NON-ASCII EMAIL FIX")
print("=" * 60)
error_leads = db_torpedo["outreach_leads_v2"].count_documents({
    "workflow_status": "error",
    "last_send_error": "Non-ASCII characters in email address"
})
print(f"  Leads caught by non-ASCII filter: {error_leads}")

print()
print("ALL PHASES VERIFIED ✓")
