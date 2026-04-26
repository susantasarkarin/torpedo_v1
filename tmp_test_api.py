"""Test API endpoints on the VM"""
import urllib.request
import json

BASE = "http://localhost:8000"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=10)
    return json.loads(r.read())

print("=== API Endpoint Tests ===")
print()

# 1. qualified_only=true
d = get("/leads?limit=1&qualified_only=true")
print(f"GET /leads?qualified_only=true => total={d['total']}")
if d['leads']:
    print(f"  First lead source: {d['leads'][0].get('source')}")

# 2. All leads (no filter)
d = get("/leads?limit=1")
print(f"GET /leads => total={d['total']}")
if d['leads']:
    print(f"  First lead source: {d['leads'][0].get('source')}")

# 3. Leads by status (campaign SFW)
d = get("/api/cold-outreach/campaigns/2a451219-3ce3-43fe-91d3-e1a3155f5363/leads-by-status?limit=2")
print(f"GET /leads-by-status (SFW) => total={d.get('total', '?')}, sends={len(d.get('sends',[]))}")
if d.get('sends'):
    s = d['sends'][0]
    print(f"  First send: {s['email']} status={s['status']} opens={s.get('open_count',0)}")

# 4. Leads by status - bounced filter
d = get("/api/cold-outreach/campaigns/2a451219-3ce3-43fe-91d3-e1a3155f5363/leads-by-status?status=bounced&limit=2")
print(f"GET /leads-by-status?status=bounced => total={d.get('total', '?')}")
if d.get('sends'):
    print(f"  First bounced: {d['sends'][0]['email']}")

# 5. Leads by status - replied filter
d = get("/api/cold-outreach/campaigns/2a451219-3ce3-43fe-91d3-e1a3155f5363/leads-by-status?status=replied&limit=2")
print(f"GET /leads-by-status?status=replied => total={d.get('total', '?')}")
if d.get('sends'):
    print(f"  First replied: {d['sends'][0]['email']} reply_received={d['sends'][0].get('reply_received')}")

# 6. Campaigns list
d = get("/api/cold-outreach/campaigns")
print(f"GET /campaigns => {len(d)} campaigns")
for c in d:
    print(f"  {c['business']}: active={c.get('is_active')} enrolled={c.get('total_enrolled',0)}")

print()
print("ALL API TESTS PASSED ✓")
