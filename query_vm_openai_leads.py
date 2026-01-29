"""Query VM for OpenAI-generated leads in the past 3 days"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "https://torpedo.cogentixresearch.com"

print("=" * 70)
print("OPENAI WEB SEARCH LEAD GENERATION - PAST 3 DAYS")
print("=" * 70)

# Get leads with pagination
try:
    # First, get leads list
    r = requests.get(f"{BASE_URL}/leads", timeout=30)
    if r.status_code == 200:
        data = r.json()
        leads = data.get('leads', [])
        total = len(leads)
        print(f"\n📊 Total leads returned: {total}")
        
        # Count leads by source
        source_counts = {}
        openai_leads = []
        three_days_ago = datetime.utcnow() - timedelta(days=3)
        recent_leads = 0
        recent_openai = 0
        
        for lead in leads:
            source = lead.get('source', 'unknown')
            source_counts[source] = source_counts.get(source, 0) + 1
            
            # Check if OpenAI source
            if 'openai' in str(source).lower() or 'websearch' in str(source).lower():
                openai_leads.append(lead)
            
            # Check if recent
            added_on = lead.get('added_on') or lead.get('created_at')
            if added_on:
                try:
                    if isinstance(added_on, str):
                        dt = datetime.fromisoformat(added_on.replace('Z', '+00:00').replace('+00:00', ''))
                    else:
                        dt = added_on
                    if dt.replace(tzinfo=None) >= three_days_ago:
                        recent_leads += 1
                        if 'openai' in str(source).lower():
                            recent_openai += 1
                except:
                    pass
        
        print(f"\n📈 SOURCE BREAKDOWN:")
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            marker = "⭐" if 'openai' in str(src).lower() else "  "
            print(f"   {marker} {src}: {count}")
        
        print(f"\n📅 PAST 3 DAYS:")
        print(f"   Recent leads: {recent_leads}")
        print(f"   Recent OpenAI leads: {recent_openai}")
        
        if openai_leads:
            print(f"\n🔍 OPENAI WEB SEARCH LEADS ({len(openai_leads)} total):")
            for lead in openai_leads[:10]:
                print(f"   - {lead.get('name', 'N/A')} | {lead.get('title', 'N/A')[:40]} | {lead.get('company_name', 'N/A')}")
        else:
            print("\n⚠️ No leads with 'openai' source found in this batch")
            
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# Try to get email leads from classified emails
print("\n" + "-" * 70)
print("CHECKING CLASSIFIED EMAILS FOR AI PROCESSING...")
try:
    r = requests.get(f"{BASE_URL}/classification/emails", timeout=30)
    if r.status_code == 200:
        data = r.json()
        emails = data.get('emails', data.get('items', []))
        print(f"   Classified emails: {len(emails)}")
except:
    pass

# Check email_leads endpoint
try:
    r = requests.get(f"{BASE_URL}/sales/email-leads", timeout=30)
    if r.status_code == 200:
        data = r.json()
        print(f"   Sales email leads: {data}")
except:
    pass

print("\n" + "=" * 70)
