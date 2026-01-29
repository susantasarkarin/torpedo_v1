"""Query VM for OpenAI Search leads with proper pagination"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "https://torpedo.cogentixresearch.com"

print("=" * 70)
print("OPENAI WEB SEARCH LEADS - VM PRODUCTION DATA")
print("=" * 70)

three_days_ago = datetime.utcnow() - timedelta(days=3)

# Query OpenAI search leads
try:
    r = requests.get(f"{BASE_URL}/leads?source=openai_search&limit=500", timeout=30)
    if r.status_code == 200:
        data = r.json()
        total = data.get('total', 0)
        pages = data.get('pages', 1)
        leads = data.get('leads', [])
        
        print(f"\n📊 OPENAI SEARCH LEADS:")
        print(f"   Total in DB: {total}")
        print(f"   Pages: {pages}")
        print(f"   Returned: {len(leads)}")
        
        # Count recent leads
        recent_count = 0
        for lead in leads:
            added = lead.get('added_on') or lead.get('created_at')
            if added:
                try:
                    if isinstance(added, str):
                        dt = datetime.fromisoformat(added.replace('Z', '').split('+')[0])
                    if dt >= three_days_ago:
                        recent_count += 1
                except:
                    pass
        
        print(f"\n📅 PAST 3 DAYS:")
        print(f"   Recent OpenAI leads: {recent_count}")
        
        # Show sample
        if leads:
            print(f"\n🔍 SAMPLE LEADS (first 10):")
            for l in leads[:10]:
                name = l.get('name', 'N/A')
                title = l.get('title', 'N/A')[:35]
                company = l.get('company_name', 'N/A')
                added = l.get('added_on', l.get('created_at', 'N/A'))
                if isinstance(added, str) and len(added) > 10:
                    added = added[:10]
                print(f"   {added} | {name} | {title} | {company}")
        else:
            print("\n⚠️ No leads returned")
            
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# Also check for 'openai' source (without _search)
print("\n" + "-" * 70)
try:
    r = requests.get(f"{BASE_URL}/leads?source=openai&limit=100", timeout=30)
    if r.status_code == 200:
        data = r.json()
        print(f"Leads with source='openai': {data.get('total', 0)}")
except:
    pass

# Check enrichment source
try:
    r = requests.get(f"{BASE_URL}/leads?enrichment_source=openai_websearch&limit=100", timeout=30)
    if r.status_code == 200:
        data = r.json()
        print(f"Leads with enrichment_source='openai_websearch': {data.get('total', 0)}")
except:
    pass

print("\n" + "=" * 70)
