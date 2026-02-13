#!/usr/bin/env python3
"""
Check lead counts by source (Google Search API + OpenAI backfill analysis)
"""

from pymongo import MongoClient

client = MongoClient()
db = client['email_automation']

print('='*60)
print('LEAD SOURCE ANALYSIS - GOOGLE SEARCH API + OPENAI BACKFILL')
print('='*60)

# Get all unique sources from leads_raw
raw_sources = list(db.leads_raw.aggregate([
    {'$group': {'_id': '$source', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}}
]))

# Get all unique sources from leads_enriched  
enriched_sources = list(db.leads_enriched.aggregate([
    {'$group': {'_id': '$source', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}}
]))

print('\n--- LEADS_RAW by Source ---')
total_raw = 0
for s in raw_sources:
    src = s['_id'] or 'unknown'
    cnt = s['count']
    print(f"  {src}: {cnt:,}")
    total_raw += cnt
print(f'  TOTAL: {total_raw:,}')

print('\n--- LEADS_ENRICHED by Source ---')
total_enriched = 0 
for s in enriched_sources:
    src = s['_id'] or 'unknown'
    cnt = s['count']
    print(f"  {src}: {cnt:,}")
    total_enriched += cnt
print(f'  TOTAL: {total_enriched:,}')

# Check for Google CSE specific tracking
print('\n--- Google CSE Usage Stats (last 7 days) ---')
cse_usage = list(db.google_cse_usage.find().sort('date', -1).limit(7))
if cse_usage:
    for u in cse_usage:
        print(f"  {u.get('date')}: {u.get('total_queries', 0)} queries")
else:
    print("  No Google CSE usage records found")

# Count leads from specific sources
print('\n--- Key Source Breakdown ---')
linkedin_raw = db.leads_raw.count_documents({'source': 'linkedin'})
linkedin_enriched = db.leads_enriched.count_documents({'source': 'linkedin'})
openai_search_raw = db.leads_raw.count_documents({'source': 'openai_search'})
openai_search_enriched = db.leads_enriched.count_documents({'source': 'openai_search'})
ai_database_raw = db.leads_raw.count_documents({'source': 'ai_database'})
ai_database_enriched = db.leads_enriched.count_documents({'source': 'ai_database'})
gmail_raw = db.leads_raw.count_documents({'source': 'gmail'})
gmail_enriched = db.leads_enriched.count_documents({'source': 'gmail'})

print(f'  LinkedIn (Google CSE): {linkedin_raw:,} raw / {linkedin_enriched:,} enriched')
print(f'  OpenAI Search: {openai_search_raw:,} raw / {openai_search_enriched:,} enriched')
print(f'  AI Database: {ai_database_raw:,} raw / {ai_database_enriched:,} enriched')
print(f'  Gmail: {gmail_raw:,} raw / {gmail_enriched:,} enriched')

# Check for leads with snippet (Google CSE results always have snippet)
leads_with_snippet = db.leads_raw.count_documents({'snippet': {'$exists': True, '$ne': ''}})
print(f'\n  Leads with Google CSE snippet: {leads_with_snippet:,}')

# Summary
print('\n--- Summary ---')
google_total = linkedin_raw + ai_database_raw + leads_with_snippet
openai_total = openai_search_raw
print(f'  Google Search API leads (estimated): {linkedin_raw:,} (LinkedIn source)')
print(f'  OpenAI backfill leads: {openai_search_raw:,}')
print(f'  Total raw leads: {total_raw:,}')
print(f'  Total enriched leads: {total_enriched:,}')
