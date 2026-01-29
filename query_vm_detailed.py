"""Query VM for detailed lead stats including OpenAI web search"""
import requests
import json

BASE_URL = "https://torpedo.cogentixresearch.com"

print("=" * 70)
print("VM LEAD GENERATION STATS")
print("=" * 70)

# Get full sales dashboard
try:
    r = requests.get(f"{BASE_URL}/sales/dashboard", timeout=30)
    if r.status_code == 200:
        data = r.json()
        print("\n📊 SALES DASHBOARD SUMMARY:")
        print(f"   Generated at: {data.get('generated_at', 'N/A')}")
        print(f"   Date range: {data.get('date_range', {})}")
        
        # Funnel stages
        funnel = data.get('funnel', {}).get('stages', [])
        print("\n   📈 Funnel Stages:")
        for stage in funnel:
            print(f"      {stage.get('icon', '')} {stage.get('name', 'N/A')}: {stage.get('count', 0):,}")
        
        # Email leads
        email_leads = data.get('email_leads', {})
        if email_leads:
            print("\n   📧 Email Leads:")
            print(f"      Total: {email_leads.get('total', 0):,}")
            print(f"      AI Processed: {email_leads.get('ai_processed', 0):,}")
            print(f"      Pending: {email_leads.get('pending', 0):,}")
        
        # Discovery stats
        discovery = data.get('discovery', {})
        if discovery:
            print("\n   🔍 Discovery:")
            for key, val in discovery.items():
                print(f"      {key}: {val}")
        
        # Recent activity
        activity = data.get('recent_activity', [])
        if activity:
            print("\n   📝 Recent Activity:")
            for a in activity[:5]:
                print(f"      {a}")
                
except Exception as e:
    print(f"Error: {e}")

# Check vendor leads
try:
    r = requests.get(f"{BASE_URL}/vendor-leads/stats", timeout=10)
    if r.status_code == 200:
        data = r.json()
        print("\n📊 VENDOR LEADS:")
        for key, val in data.items():
            print(f"   {key}: {val}")
except Exception as e:
    print(f"Vendor leads error: {e}")

# Check agents status
try:
    r = requests.get(f"{BASE_URL}/agents/status", timeout=10)
    if r.status_code == 200:
        data = r.json()
        print("\n🤖 AGENTS STATUS:")
        agents = data.get('agents', {})
        for agent_id, info in agents.items():
            status = info.get('status', 'unknown')
            name = info.get('name', 'Unknown')
            last_run = info.get('last_run', 'Never')
            print(f"   Agent {agent_id}: {name} - {status} (last: {last_run})")
except Exception as e:
    print(f"Agents error: {e}")

# Try to get email leads specifically
try:
    print("\n📧 CHECKING EMAIL LEADS ENDPOINT...")
    r = requests.get(f"{BASE_URL}/gmail/leads", timeout=10)
    print(f"   /gmail/leads: {r.status_code}")
    
    r = requests.get(f"{BASE_URL}/leads/email-leads", timeout=10)
    print(f"   /leads/email-leads: {r.status_code}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 70)
print("SUMMARY: The VM has 12,724 leads captured in the funnel")
print("To see OpenAI web search specific leads, need to SSH to VM or")
print("add a specific /leads/openai-stats endpoint")
print("=" * 70)
